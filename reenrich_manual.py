"""Re-enrich manual items in data/actions.json through the current
scraper pipeline so their fields match auto-scraper standards.

Per user rule: "Manual additions need all of the same backfilling as
other items — make sure that happens."

Scope: items with auto_fetched=False. Re-fetches each source URL,
re-extracts all fields via the same helpers used by the scraper:
  - fetch_detail_page (title, canonical date, body)
  - generate_tags (strip_boilerplate + regex/AI + co-apply)
  - get_state (v3 rule)
  - derive_link_label (URL-based)
  - get_action_type (first-signal-wins for hybrids)
  - extract_amount (enforcement only)

Then diffs the fresh version against the stored version and reports.

Default: dry-run (report differences only).
--apply: write updated fields to data/actions.json.

Conservative rules:
  - Titles: only overwrite if current is empty or looks boilerplate
    (editorial cleanups preserved)
  - Tags: only overwrite if current is empty or if --force-tags
    (today's 8 editorial tag restorations are preserved by default)
  - Dates: always apply canonical if fresh beats current (user's rule:
    no guessing on dates)
  - State: apply if different (rule v3 is authoritative)
  - Link label: always apply (deterministic)
  - Type: apply if different (first-signal-wins is authoritative)
  - Amount: apply if enforcement type AND current is empty
  - source_type: apply if different
  - related_agencies: MERGE (add missing, don't remove existing)

Usage:
    python reenrich_manual.py                  # dry-run preview
    python reenrich_manual.py --apply          # write changes
    python reenrich_manual.py --limit 20       # subset
    python reenrich_manual.py --agency DOJ     # filter by agency
    python reenrich_manual.py --force-tags     # also overwrite tags
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

from update import (
    fetch_detail_page,
    generate_tags,
    get_state,
    derive_link_label,
    get_action_type,
    extract_amount,
    _looks_like_bad_title,
    scrape_page_with_browser,
    HAS_PLAYWRIGHT,
)
from tag_allowlist import filter_tags

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")

# Known news-outlet domains for source_type auto-detection
_NEWS_DOMAINS = {
    "cbsnews.com", "nytimes.com", "wsj.com", "washingtonpost.com",
    "npr.org", "foxnews.com", "bloomberg.com", "reuters.com",
    "axios.com", "propublica.org", "kffhealthnews.org", "statnews.com",
    "theguardian.com", "nypost.com", "latimes.com", "kare11.com",
    "azcir.org", "wsmv.com", "clickorlando.com", "townhall.com",
    "foxillinois.com", "foxla.com", "city-journal.org",
    "californiaglobe.com", "realclearinvestigations.com",
    "washingtontimes.com", "kstp.com", "deadlinedetroit.com",
    "clickondetroit.com", "fiercehealthcare.com", "fox9.com",
}


def fetch_and_enrich(item, session):
    """Re-fetch the item's source and return a fresh extraction."""
    url = item.get("link", "")
    if not url:
        return None

    host = urlparse(url).netloc.lower().replace("www.", "")

    try:
        body_text, doj_link, canonical_title, canonical_date = \
            fetch_detail_page(session, url)
    except Exception:
        body_text, doj_link, canonical_title, canonical_date = "", None, "", None

    # Playwright fallback for Akamai-blocked
    if not body_text and HAS_PLAYWRIGHT:
        try:
            soup = scrape_page_with_browser(url)
            if soup:
                main = (soup.find("main") or soup.find("article")
                        or soup.find("div", class_="field-item")
                        or soup.find("div", class_="entry-content")
                        or soup.body)
                if main:
                    for t in main.find_all(["nav", "footer", "aside",
                                            "script", "style"]):
                        t.decompose()
                    related_re = re.compile(
                        r"(?:^|\s)(related-content|related-press|related-stor|"
                        r"views-blockrelated|more-news|more-press|"
                        r"you-may-also-like|further-reading|recommend)", re.I)
                    for t in main.find_all(class_=related_re):
                        t.decompose()
                    body_text = re.sub(r"\s+", " ",
                                        main.get_text(" ", strip=True))[:12000]
                if not canonical_title:
                    og = soup.find("meta", attrs={"property": "og:title"})
                    if og and og.get("content"):
                        canonical_title = og["content"].strip()
                    elif soup.find("h1"):
                        canonical_title = soup.find("h1").get_text(strip=True)
        except Exception:
            pass

    agency = item.get("agency", "")
    is_media = False  # reenrich is for actions.json only for now

    # Tags
    fresh_tags = filter_tags(generate_tags(canonical_title or item.get("title", ""),
                                             body_text))
    # Type — computed before state so state extraction can skip body
    # fallback for policy items (state rule v3 update)
    fresh_type = get_action_type(canonical_title or item.get("title", ""),
                                  body_text[:500], agency=agency, link=url)
    # State (item-type-aware)
    fresh_state = get_state(body_text,
                              title=canonical_title or item.get("title", ""),
                              link=url, item_type=fresh_type)
    # Link label
    fresh_link_label = derive_link_label(agency, url, is_media=is_media)
    # Amount (enforcement only)
    is_enf = fresh_type in ("Criminal Enforcement", "Civil Action")
    fresh_amount = ""
    fresh_amount_numeric = 0
    if is_enf:
        amt = extract_amount(body_text,
                              title=canonical_title or item.get("title", ""))
        if amt:
            fresh_amount = amt.get("display", "")
            fresh_amount_numeric = int(amt.get("numeric", 0))
    # Source type
    host_clean = host
    fresh_source_type = "news" if any(n in host_clean for n in _NEWS_DOMAINS) \
                        else "official"

    return {
        "title": canonical_title,
        "date": canonical_date,
        "tags": fresh_tags,
        "state": fresh_state,
        "link_label": fresh_link_label,
        "type": fresh_type,
        "amount": fresh_amount,
        "amount_numeric": fresh_amount_numeric,
        "source_type": fresh_source_type,
        "_body_fetched": bool(body_text),
        "_title_is_bad": _looks_like_bad_title(canonical_title) if canonical_title else False,
    }


def compute_diff(current, fresh, force_tags=False, force_dates=False):
    """Return a dict of fields to change + their old/new values.

    FILL-BLANKS-ONLY philosophy. Editorial decisions are preserved.
    Rules:
      - Title: only fill if current is empty or boilerplate
      - Date: only fill if current is empty. Use --force-dates to
        overwrite (user's "no guessing on dates" rule). If current is
        YYYY-MM (already month-only) and fresh is a YYYY-MM-DD, prefer
        current (we don't re-expand month-only dates).
      - Tags: only fill if current is empty. Use --force-tags to
        overwrite (preserves today's editorial tag restorations).
      - State: only update if current is empty AND fresh is non-empty.
        Never regress a set state to None.
      - Link label: only update if source_type is "official" (preserve
        news outlet names like "Fox News", "KSTP News Report").
      - Type: NEVER overwrite. Editorial decisions should stick.
      - Amount: fill if enforcement type AND current is empty.
      - source_type: only fill if currently unset.
    """
    changes = {}

    # Title
    cur_title = current.get("title", "")
    fresh_title = fresh.get("title") or ""
    if fresh_title and not fresh.get("_title_is_bad"):
        if not cur_title or _looks_like_bad_title(cur_title):
            if fresh_title != cur_title:
                changes["title"] = (cur_title, fresh_title)

    # Date — fill-blanks-only unless --force-dates
    cur_date = (current.get("date") or "")
    fresh_date = fresh.get("date") or ""
    if fresh_date and fresh_date != cur_date:
        if not cur_date:
            changes["date"] = (cur_date, fresh_date)
        elif force_dates:
            # User's rule: no guessing on dates. If current date might
            # be wrong and canonical is available, overwrite.
            # BUT: don't re-expand YYYY-MM to YYYY-MM-DD (YYYY-MM is
            # a deliberate choice for month-only sources).
            cur_is_month_only = len(cur_date) == 7
            fresh_is_day = len(fresh_date) == 10
            if not (cur_is_month_only and fresh_is_day):
                changes["date"] = (cur_date, fresh_date)

    # Tags — fill-blanks-only unless --force-tags
    cur_tags = current.get("tags") or []
    fresh_tags = fresh.get("tags") or []
    if force_tags and sorted(cur_tags) != sorted(fresh_tags):
        changes["tags"] = (cur_tags, fresh_tags)
    elif not cur_tags and fresh_tags:
        changes["tags"] = (cur_tags, fresh_tags)

    # State — fill-blanks-only. Never regress non-empty to None.
    cur_state = current.get("state") or ""
    fresh_state = fresh.get("state") or ""
    if fresh_state and not cur_state:
        changes["state"] = (current.get("state"), fresh_state)

    # Link label — only for "official" source_type items (preserve
    # news outlet names)
    if (current.get("source_type", "official") == "official"):
        cur_label = current.get("link_label", "")
        fresh_label = fresh.get("link_label", "")
        if fresh_label and fresh_label != cur_label:
            changes["link_label"] = (cur_label, fresh_label)

    # Type — NEVER touch. Editorial decisions preserved.

    # Amount — fill if enforcement type AND current is empty
    cur_type = current.get("type", "")
    is_enf = cur_type in ("Criminal Enforcement", "Civil Action")
    if is_enf:
        cur_amount = (current.get("amount") or "").strip()
        fresh_amount = fresh.get("amount", "")
        if fresh_amount and not cur_amount:
            changes["amount"] = (cur_amount, fresh_amount)
            changes["amount_numeric"] = (
                current.get("amount_numeric", 0),
                fresh.get("amount_numeric", 0)
            )

    # source_type — only fill if currently unset
    cur_st = current.get("source_type", "")
    fresh_st = fresh.get("source_type", "")
    if not cur_st and fresh_st:
        changes["source_type"] = (cur_st, fresh_st)

    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write changes. Default: dry-run.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process only N items")
    ap.add_argument("--agency", default="",
                    help="Filter to items with this agency")
    ap.add_argument("--force-tags", action="store_true",
                    help="Also overwrite tags even when current has tags.")
    args = ap.parse_args()

    d = json.load(open(ACTIONS_FILE, encoding="utf-8"))
    manual = [x for x in d["actions"] if not x.get("auto_fetched", True)]
    if args.agency:
        manual = [x for x in manual if x.get("agency") == args.agency]
    if args.limit:
        manual = manual[:args.limit]

    print(f"Re-enriching {len(manual)} manual items "
          f"(apply={args.apply}, force_tags={args.force_tags})")
    print()

    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36")
    })

    total_changes = 0
    changed_items = 0
    fetch_fails = 0
    from collections import Counter
    field_counter = Counter()

    for i, item in enumerate(manual, 1):
        title_truncated = item.get("title", "")[:80]
        try:
            fresh = fetch_and_enrich(item, session)
        except Exception as e:
            print(f"[{i}/{len(manual)}] FETCH FAILED: {title_truncated}  ({e})")
            fetch_fails += 1
            continue
        if not fresh:
            continue
        if not fresh.get("_body_fetched"):
            # Body empty means we couldn't reliably extract — skip
            # unless the item currently has NO tags/state (in which case
            # don't overwrite with empty)
            print(f"[{i}/{len(manual)}] body empty (source unreachable): "
                  f"{title_truncated}")
            fetch_fails += 1
            continue

        changes = compute_diff(item, fresh, force_tags=args.force_tags)
        if not changes:
            continue

        changed_items += 1
        total_changes += len(changes)
        for field in changes:
            field_counter[field] += 1

        print(f"[{i}/{len(manual)}] {item.get('id','')}")
        print(f"   {title_truncated}")
        for field, (old, new) in changes.items():
            old_s = repr(old)[:80]
            new_s = repr(new)[:80]
            print(f"   {field:15s} {old_s}  ->  {new_s}")

        if args.apply:
            for field, (_, new) in changes.items():
                item[field] = new

    print()
    print(f"=== Summary ===")
    print(f"Processed:       {len(manual)}")
    print(f"Changed:         {changed_items}")
    print(f"Total field updates: {total_changes}")
    print(f"Fetch failures:  {fetch_fails}")
    print(f"Field breakdown:")
    for field, n in field_counter.most_common():
        print(f"  {n:4d}  {field}")

    if args.apply:
        d["metadata"]["last_updated"] = datetime.now().isoformat()
        json.dump(d, open(ACTIONS_FILE, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE}")
    else:
        print(f"\n[DRY-RUN — rerun with --apply to write]")


if __name__ == "__main__":
    main()
