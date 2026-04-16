"""Scrape congressional hearings via the Congress.gov API.

Uses a layered filter to identify healthcare-fraud-relevant hearings:

  1. Enumerate every committee meeting in the date range (both chambers).
  2. Fetch detail for each meeting.
  3. Drop non-hearings (markups, votes, recorded amendments).
  4. Classify remaining hearings by signal strength:
       strong   - title keyword match OR witness list signal -> auto-include
       medium   - healthcare-adjacent committee routing       -> AI review
       none                                                   -> skip
  5. Produce a dry-run report; --apply writes new items to actions.json
     with type=Hearing.

The script does NOT fetch press releases, follow-up releases, or committee
pages. Link resolution to committee URLs is a TODO on the apply path.

Usage:
    export CONGRESS_GOV_API_KEY=...
    python scrape_congress_hearings.py --from 2026-03-01 --to 2026-03-31
    python scrape_congress_hearings.py --from 2025-01-03 --to 2026-04-16
    python scrape_congress_hearings.py --from 2026-03-01 --to 2026-03-31 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

API_KEY = os.environ.get("CONGRESS_GOV_API_KEY", "")
BASE = "https://api.congress.gov/v3"

# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------

# TIER 1 — unambiguous fraud-in-healthcare phrases. Auto-include always.
HC_FRAUD_PHRASE = re.compile(
    r"\b("
    # Explicit combinations
    r"(medicare|medicaid|tricare|health\s*care|medical|hospice|"
    r"pharmacy|rx|drug|dme|dmepos|prescription|opioid|telehealth)"
    r"\s+(fraud|scheme|kickback|integrity|upcoding|abuse|audit)|"
    r"(fraud|kickback|scheme)\s+(in\s+)?"
    r"(medicare|medicaid|tricare|health\s*care|hospice|nursing|pharmacy|dme)|"
    # Specific fraud-scheme phrases
    r"pill\s+mill|program\s+integrity|improper\s+payment|"
    r"anti-?kickback|false\s+claim|qui\s+tam|strike\s+force|"
    r"risk\s+adjustment\s+(fraud|upcoding)|"
    r"skin\s+substitute|genetic\s+test.*(fraud|scheme)"
    r")\b",
    re.I,
)

# TIER 2 — healthcare context (any mention) in title.
# Auto only if paired with another healthcare signal like HC committee or witness;
# otherwise routes to review (lots of non-fraud healthcare policy here).
HC_CONTEXT_TITLE = re.compile(
    r"\b("
    r"medicare|medicaid|tricare|medi-?cal|"
    r"health\s*care|healthcare|affordable\s+care|"
    r"medical\s+(device|billing|practice|necessity)|"
    r"hospital|clinic|physician|hospice|nursing\s+home|skilled\s+nursing|"
    r"prescription|pharmac|opioid|fentanyl|"
    r"telehealth|telemedic|dmepos|\bdme\b|durable\s+medical|"
    r"\bhhs\b|\bhhs\-oig\b|\bcms\b|"
    r"behavioral\s+health|substance\s+abuse|addiction|"
    r"home\s+health|assisted\s+living|adult\s+day\s+care"
    r")\b",
    re.I,
)

# TIER 3 — generic fraud vocabulary. Needs HC committee to auto-include.
HC_WEAK_TITLE = re.compile(
    r"\b(fraud|kickback|false\s+claim|waste.{0,15}abuse|improper\s+payment)\b",
    re.I,
)

# Committee system-code PREFIXES that match HC-relevant committees
# (full committees + all their subcommittees). A code like "hsgo24"
# (Oversight Government Operations subcomm) matches the "hsgo" prefix.
HC_COMMITTEE_PREFIXES = (
    # Senate
    "ssfi",  # Finance
    "sshe",  # HELP
    "ssga",  # HSGAC (houses many fraud investigations)
    "ssju",  # Judiciary
    # House
    "hsif",  # Energy & Commerce
    "hswm",  # Ways & Means
    "hsgo",  # Oversight
    "hsju",  # Judiciary
)
# Specific Appropriations subcommittee codes that cover HHS/Labor-HHS.
# Full Appropriations (hsap00, ssap00) is too broad — we add the specific
# LHHS subcommittees here instead.
HC_APPROPRIATIONS_CODES = {
    "hsap08",  # House Appropriations Subcomm on Departments of Labor, HHS, Education
    "ssap08",  # Senate LHHS equivalent (verify at runtime)
    "hsap02",  # alternate numbering some Congresses
    "ssap02",
}


def committee_is_hc(code):
    """True if committee code belongs to a healthcare-fraud-relevant committee
    or any of its subcommittees (including specific LHHS Appropriations subs)."""
    if not code:
        return False
    if code in HC_APPROPRIATIONS_CODES:
        return True
    return any(code.startswith(p) for p in HC_COMMITTEE_PREFIXES)

# Witness patterns that suggest healthcare-fraud context even if title is vague.
WITNESS_SIGNALS = re.compile(
    r"health\s+(and\s+)?human\s+services|hhs\-?oig|"
    r"inspector\s+general.*(health|human\s+services)|"
    r"centers?\s+for\s+medicare|\bcms\b|"
    r"medicare\s+(administrator|director|commissioner)|"
    r"medicaid\s+(administrator|director|commissioner)|"
    r"health\s+care\s+fraud\s+(strike\s+force|unit|section)|"
    r"government\s+accountability\s+office\s+.*(health|medicare|medicaid)|"
    r"unitedhealth|centene|humana|elevance|cigna|aetna|molina|anthem|"
    r"blue\s+cross\s+blue\s+shield|"
    r"food\s+and\s+drug|\bfda\b|"
    r"drug\s+enforcement|\bdea\b|"
    r"pharmaceutical\s+research\s+and\s+manufacturers",
    re.I,
)

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(url_or_path, **params):
    if url_or_path.startswith("http"):
        url = url_or_path
    else:
        url = f"{BASE}{url_or_path}"
    params.setdefault("api_key", API_KEY)
    params.setdefault("format", "json")
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429:
                wait = 2 ** attempt
                print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1)
    return None


def fetch_meeting_listing(chamber, congress=119):
    """Yield meeting summary dicts for a chamber/congress, all pages."""
    offset = 0
    limit = 250
    while True:
        data = api_get(
            f"/committee-meeting/{congress}/{chamber}",
            limit=limit, offset=offset,
        )
        meetings = data.get("committeeMeetings", [])
        if not meetings:
            break
        for m in meetings:
            yield m
        pagination = data.get("pagination", {})
        next_url = pagination.get("next")
        if not next_url:
            break
        offset += limit


def fetch_meeting_detail(detail_url):
    data = api_get(detail_url)
    return data.get("committeeMeeting", {})


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def is_hearing(meeting):
    """True if the meeting is a hearing (vs markup, vote, business meeting).

    Priority order:
      1. The `type` field is the authoritative signal. Values like "Markup",
         "Business Meeting", "Hearing" etc. Reject anything that isn't a
         hearing type. (Previously we fell through to documentType and title
         checks which produced false positives on markups that happen to have
         a "Hearing: Member Roster" document — every committee meeting does.)
      2. If the type field is absent or vague ("Meeting" on Senate items),
         fall back to title-based detection: "Hearings to examine ..." is
         the Senate convention.
      3. Finally, documentType fallback — but only accept strong hearing-
         specific documents (witness statements/testimony), not the generic
         "Hearing: Member Roster" that appears on markups.
    """
    mtype = (meeting.get("type") or "").strip().lower()
    if mtype:
        # Explicit non-hearing types → not a hearing
        if mtype in {"markup", "business meeting", "conference", "briefing",
                     "field hearing", "bill signing", "organizational meeting"}:
            # "field hearing" IS a hearing — correct below
            if "hearing" in mtype:
                return True
            return False
        if "hearing" in mtype:
            return True
        # For "Meeting" (Senate default), fall through to title check
    # Title-based: "Hearings to examine ..." Senate pattern
    title = (meeting.get("title") or "").lower()
    if re.match(r"\s*hearings?\s+to\s+(examine|consider|receive|review)\b", title):
        return True
    # Strong document-type signals (not generic Member Roster)
    for doc in (meeting.get("meetingDocuments") or []):
        dt = (doc.get("documentType") or "").lower()
        if dt in ("hearing: witness statement", "hearing transcript",
                  "hearing: witness biography", "hearing: witness truth in testimony"):
            return True
    return False


def witness_blob(meeting):
    """Flatten witnesses for pattern matching."""
    parts = []
    for w in meeting.get("witnesses", []) or []:
        parts.append(f"{w.get('name','')} {w.get('position','')} {w.get('organization','')}")
    # Witness documents sometimes have witness info
    for wd in meeting.get("witnessDocuments", []) or []:
        parts.append(wd.get("description", ""))
    return " ".join(parts)


def classify(meeting):
    """Return (verdict, reason) for a meeting.

    verdict is one of:
      'include_auto'   - strong signal, should be on dashboard
      'include_review' - borderline, needs AI/human review
      'skip_nonhearing'
      'skip_no_signal'
    """
    if not is_hearing(meeting):
        return "skip_nonhearing", "not a hearing (markup/vote/amendment)"

    title = meeting.get("title") or ""
    committee_codes = [c.get("systemCode", "") for c in meeting.get("committees", [])]
    committee_names = [c.get("name", "") for c in meeting.get("committees", [])]
    witnesses = witness_blob(meeting)
    has_hc_committee = any(committee_is_hc(c) for c in committee_codes)
    first_committee = committee_names[0] if committee_names else "?"

    # TIER 1: unambiguous fraud-in-healthcare phrase in title → always auto
    if HC_FRAUD_PHRASE.search(title):
        return "include_auto", "explicit HC-fraud phrase in title"

    # TIER 2: generic fraud vocabulary + HC committee → auto
    # (without HC committee, this would catch e.g. Foreign Assistance fraud)
    if HC_WEAK_TITLE.search(title):
        if has_hc_committee:
            return "include_auto", f"fraud keyword + HC committee ({first_committee})"
        else:
            return "skip_no_signal", f"fraud keyword but non-HC committee ({first_committee})"

    # TIER 3: witness-only signal (HHS/CMS/DOJ testifying) → review, not auto.
    # Witness presence alone is too broad — HHS officials testify on policy,
    # nominations, budget, etc. Only auto if paired with fraud-signal in title.
    if witnesses and WITNESS_SIGNALS.search(witnesses):
        return "include_review", "witness signal (HHS/CMS/DOJ healthcare-adjacent)"

    # TIER 4: healthcare context in title (policy/program but no fraud word) + HC committee → review
    # Examples: "Modernizing American Health Care", "Public Health Workforce". Healthcare but
    # not necessarily about fraud. Send to review rather than auto.
    if HC_CONTEXT_TITLE.search(title) and has_hc_committee:
        return "include_review", f"HC title context on HC committee ({first_committee}), no explicit fraud signal"

    # TIER 5: HC committee with any title, no HC title signal → review
    if has_hc_committee and title:
        return "include_review", f"HC committee ({first_committee}), title not explicit"

    return "skip_no_signal", "no HC signal"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def format_date(d):
    if isinstance(d, list) and d:
        return d[0].get("date", "")[:10] if isinstance(d[0], dict) else str(d[0])[:10]
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, dict):
        return d.get("date", "")[:10]
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD floor (inclusive)")
    ap.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD ceiling (inclusive)")
    ap.add_argument("--congress", type=int, default=119)
    ap.add_argument("--chambers", default="house,senate", help="comma-separated")
    ap.add_argument("--limit", type=int, default=0, help="max meetings to fetch (debug)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent detail fetchers (default 8; be polite at 5000/hr rate limit)")
    ap.add_argument("--apply", action="store_true", help="write new items to actions.json")
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: set CONGRESS_GOV_API_KEY env var", file=sys.stderr)
        sys.exit(2)

    chambers = [c.strip() for c in args.chambers.split(",")]
    date_from, date_to = args.date_from, args.date_to

    print(f"Date range: {date_from} to {date_to}")
    print(f"Chambers: {chambers}  Congress: {args.congress}")
    print()

    # Step 1: enumerate listing. The listing is sorted by updateDate desc.
    # updateDate usually lags a meeting's actual date by 0-7 days (when
    # documents are posted), so we filter by updateDate >= (date_from - 90d).
    # 90-day buffer is generous to avoid missing anything; meetings outside
    # the true date range still get dropped after the detail fetch.
    from datetime import datetime, timedelta
    floor_d = (datetime.strptime(date_from, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    ceil_d = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
    print(f"Step 1: enumerate meetings (updateDate window: {floor_d} to {ceil_d})...", flush=True)
    candidates = []
    for chamber in chambers:
        count = 0
        kept = 0
        stopped_early = False
        for m in fetch_meeting_listing(chamber, args.congress):
            count += 1
            upd = m.get("updateDate", "")[:10]
            if upd and upd > ceil_d:
                continue  # updated in the future
            if upd and upd < floor_d:
                # Since listing is sorted by updateDate desc, once we drop
                # below the floor we can stop.
                stopped_early = True
                break
            candidates.append((chamber, m))
            kept += 1
            if args.limit and kept >= args.limit:
                break
        status = f"stopped early at page {count//250+1}" if stopped_early else "full listing"
        print(f"  {chamber}: {count} scanned, {kept} kept for detail fetch ({status})", flush=True)

    print(f"Total candidates: {len(candidates)}", flush=True)
    print()

    # Step 2+3+4: fetch detail, filter, classify (concurrent)
    print(f"Step 2: fetch detail + classify (workers={args.workers})...", flush=True)
    verdict_counts = {"include_auto": 0, "include_review": 0,
                      "skip_nonhearing": 0, "skip_no_signal": 0,
                      "skip_out_of_range": 0, "error": 0}
    results = []

    def process(candidate):
        chamber, m = candidate
        try:
            detail = fetch_meeting_detail(m["url"])
        except Exception as e:
            return ("error", None, f"detail fetch failed: {e}", chamber, m)
        mdate = format_date(detail.get("date"))
        if mdate and (mdate < date_from or mdate > date_to):
            return ("skip_out_of_range", None, "", chamber, m)
        verdict, reason = classify(detail)
        row = None
        if verdict.startswith("include"):
            row = {
                "chamber": chamber,
                "eventId": m.get("eventId"),
                "date": mdate,
                "title": detail.get("title") or "(no title)",
                "committees": [c.get("name", "") for c in detail.get("committees", [])],
                "committee_codes": [c.get("systemCode", "") for c in detail.get("committees", [])],
                "witnesses_count": len(detail.get("witnesses", []) or []),
                "verdict": verdict,
                "reason": reason,
                "api_url": m["url"].split("?")[0],
                "congress_url": f"https://www.congress.gov/event/{args.congress}-congress/{chamber}-event/{m['eventId']}",
            }
        return (verdict, row, reason, chamber, m)

    processed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(process, c) for c in candidates]
        for fut in as_completed(futures):
            verdict, row, reason, chamber, m = fut.result()
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            if row is not None:
                results.append(row)
            processed += 1
            if processed % 50 == 0:
                print(f"  [{processed}/{len(candidates)}] verdict totals: {verdict_counts}", flush=True)

    print()
    print(f"Final verdicts: {verdict_counts}")
    print()

    # Step 5: report
    results.sort(key=lambda r: (r["date"], r["chamber"]))
    print("=== CAPTURED HEARINGS ===")
    for r in results:
        mark = "[AUTO]   " if r["verdict"] == "include_auto" else "[REVIEW] "
        comm = r["committees"][0] if r["committees"] else "(?)"
        print(f"{mark}{r['date']:10s} {r['chamber']:6s} {comm[:35]:35s} {r['title'][:70]}")
        print(f"           reason: {r['reason']}  witnesses: {r['witnesses_count']}")
        print(f"           {r['congress_url']}")

    # Dump to JSON for inspection
    out_path = "tmp_congress_hearings_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "from": date_from, "to": date_to,
            "counts": verdict_counts,
            "results": results,
        }, f, indent=2)
    print(f"\nFull report written to {out_path}")

    if args.apply:
        apply_to_actions(results)


# ---------------------------------------------------------------------------
# --apply: dedup + write new hearings to actions.json
# ---------------------------------------------------------------------------

ACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "actions.json")
REVIEW_QUEUE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "data", "tmp_hearings_review_queue.json")


def _slugify(s):
    """Lowercase, collapse non-alnum to dashes, strip trailing dashes."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


# Committee-specific URL patterns for /hearing/ pages. Keyed by committee
# systemCode prefix (matches main committee + any subcommittee via prefix).
# Format: (base_url, slug_format). slug_format is a Python format string
# that takes {slug} (the slugified title).
COMMITTEE_URL_PATTERNS = {
    # House
    "hsgo": "https://oversight.house.gov/hearing/{slug}/",
    "hsif": "https://energycommerce.house.gov/events/{slug}",
    "hswm": "https://waysandmeans.house.gov/event/{slug}",
    "hsju": "https://judiciary.house.gov/committee-activity/hearings/{slug}",
    # Senate
    "ssfi": "https://www.finance.senate.gov/hearings/{slug}",
    "sshe": "https://www.help.senate.gov/hearings/{slug}",
    "ssju": "https://www.judiciary.senate.gov/committee-activity/hearings/{slug}",
    "ssga": "https://www.hsgac.senate.gov/hearings/{slug}",
}


def resolve_committee_url(title, committee_code, session=None):
    """Try to resolve a hearing to its committee's own page URL.

    Slugifies the title, builds the expected committee URL, and does a
    HEAD request to verify it exists. Returns the committee URL if reachable,
    otherwise None (caller should fall back to the congress.gov URL).
    """
    if not title or not committee_code:
        return None
    # Find matching URL pattern by committee prefix
    pattern = None
    for prefix, url_fmt in COMMITTEE_URL_PATTERNS.items():
        if committee_code.startswith(prefix):
            pattern = url_fmt
            break
    if not pattern:
        return None
    # Slugify title (strip leading quotes, limit length)
    clean_title = re.sub(r"[\"\u201c\u201d\u2018\u2019]", "", title).strip()
    slug = _slugify(clean_title)
    # Some committee sites trim long slugs; try the first 100 chars
    if len(slug) > 110:
        slug = slug[:110].rsplit("-", 1)[0]
    candidate = pattern.format(slug=slug)
    try:
        import requests as _req
        # Do NOT follow redirects: some sites (senate.gov) redirect
        # missing pages to a custom 404 page that returns 200. We need
        # to see the raw status of the candidate URL.
        r = _req.head(candidate, timeout=6, allow_redirects=False,
                      headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return candidate
        # HEAD sometimes blocked (405/403) — try GET no-redirect
        if r.status_code in (405, 403):
            r = _req.get(candidate, timeout=10, allow_redirects=False,
                         headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return candidate
        # 301 (permanent redirect) to a non-404 target is fine — but
        # we need to verify the redirect target isn't a 404 page.
        if r.status_code == 301:
            loc = r.headers.get("Location", "")
            if loc and "404" not in loc.lower() and "notfound" not in loc.lower():
                # Accept the candidate (redirect target is some canonical URL)
                return candidate
    except Exception:
        pass
    return None


_DEDUP_STOPWORDS = {"the", "a", "an", "of", "in", "on", "to", "for", "at", "by",
                    "and", "or", "with", "as", "is", "are", "was", "were", "be",
                    "from", "that", "this"}


def _content_words(title):
    """Return the set of content (non-stopword) words in a title."""
    return {w for w in _slugify(title).split("-")
            if w and w not in _DEDUP_STOPWORDS and len(w) > 1}


def _matches_existing_hearing(new_row, existing_items):
    """True if a new hearing looks like an existing Hearing-type item.

    Dedup rules:
      - Same congress.gov event URL
      - Same date AND title content-word overlap is high (>=60% of the
        shorter title's content words appear in the longer one, with a
        minimum of 3 shared words). Uses stopword-filtered tokens so
        "Fighting Obamacare Subsidy Fraud" matches "Fighting Obamacare
        Subsidy Fraud: Is the Administrative Procedure Act Working".
      - Date within 1 day AND high content overlap (hearings sometimes
        get rescheduled by a day; press release dates can differ from
        the actual hearing date).
    """
    new_date = new_row["date"]
    new_words = _content_words(new_row["title"])
    for ex in existing_items:
        if ex.get("type") != "Hearing":
            continue
        link = ex.get("link", "")
        # Event URL match
        if f"-event/{new_row['eventId']}" in link:
            return True
        # Date + content word overlap
        ex_date = ex.get("date", "")
        ex_words = _content_words(ex.get("title", ""))
        if not ex_words or not new_words:
            continue
        shared = new_words & ex_words
        shorter = min(len(new_words), len(ex_words))
        # Allow 1-day slack (hearing vs announcement dates)
        date_close = (ex_date == new_date
                      or _date_within_days(ex_date, new_date, 1))
        if date_close and len(shared) >= max(3, int(shorter * 0.6)):
            return True
    return False


def _date_within_days(a, b, days):
    try:
        from datetime import datetime
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
        return abs((da - db).days) <= days
    except Exception:
        return False


def apply_to_actions(results):
    """Write new auto-include hearings to actions.json; review queue to tmp file."""
    with open(ACTIONS_FILE, encoding="utf-8") as f:
        actions = json.load(f)
    existing = actions.get("actions", [])

    auto = [r for r in results if r["verdict"] == "include_auto"]
    review = [r for r in results if r["verdict"] == "include_review"]

    # Dedup AUTO against existing
    new_items = []
    skipped_dup = 0
    resolved_committee = 0
    for r in auto:
        if _matches_existing_hearing(r, existing):
            skipped_dup += 1
            continue
        # Try to resolve to committee's own page URL — nicer than congress.gov
        # URL (committee pages have video, witness docs, etc.)
        primary_cc = r["committee_codes"][0] if r.get("committee_codes") else ""
        committee_url = resolve_committee_url(r["title"], primary_cc)
        if committee_url:
            link = committee_url
            link_label = f"{r['committees'][0] if r['committees'] else 'Committee'} Hearing"
            resolved_committee += 1
        else:
            link = r["congress_url"]
            link_label = "Congress.gov Event"
        new_items.append({
            "id": f"congress-{r['chamber']}-{r['eventId']}",
            "date": r["date"],
            "agency": "Congress",
            "type": "Hearing",
            "title": r["title"],
            "amount": "",
            "amount_numeric": 0,
            "officials": [],
            "link": link,
            "link_label": link_label,
            "tags": [],  # will be filled by retag_existing or next run
            "state": "",
            "source_type": "official",
            "auto_fetched": True,
            "entities": [],
            "_source": f"congress.gov committee-meeting {r['eventId']}",
            "_committees": r["committees"],
            "_filter_reason": r["reason"],
        })

    if new_items:
        actions.setdefault("actions", []).extend(new_items)
        actions.setdefault("metadata", {})["last_updated"] = datetime.now().isoformat()
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(actions, f, indent=2, ensure_ascii=False)

    # Write review queue separately (not into actions.json)
    with open(REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "count": len(review),
            "note": "Hearings needing human review before auto-include. "
                   "Promote with: move entries into actions.json with type=Hearing.",
            "items": review,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nAPPLY:")
    print(f"  AUTO new items added to actions.json: {len(new_items)}")
    print(f"  AUTO duplicates skipped: {skipped_dup}")
    print(f"  AUTO with resolved committee URL: {resolved_committee}")
    print(f"  REVIEW items queued to {REVIEW_QUEUE_FILE}: {len(review)}")


if __name__ == "__main__":
    main()
