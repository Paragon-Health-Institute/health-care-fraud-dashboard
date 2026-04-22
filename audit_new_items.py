#!/usr/bin/env python3
"""Pre-publish audit for newly-scraped enforcement actions.

Diffs ``data/actions.json`` against the version in ``git HEAD`` to find items
added since the last commit, runs each new title through a strict healthcare-
context check, and moves items that don't obviously match into
``data/needs_review.json``. Approved items stay in actions.json and ship on
the next dashboard publish; flagged items wait for human (or AI) review.

Subcommands:

    python audit_new_items.py            # default: run the diff + flag pass
    python audit_new_items.py audit      # same as above
    python audit_new_items.py list       # show pending review items
    python audit_new_items.py promote ID # move an item from needs_review back to actions
    python audit_new_items.py reject ID  # confirm rejection (link is permanently blocked)

The companion file ``data/needs_review.json`` has two sections:

    {
      "items":           [ ... full action objects awaiting review ... ],
      "rejected_links":  [ "https://www.justice.gov/...", ... ]
    }

``rejected_links`` is read by ``update.py`` during scraping so confirmed
rejections never get re-pulled.

This script is the foundation for an AI-assisted review layer (commit 2),
which will process items in needs_review.json automatically and either
auto-promote, auto-reject, or escalate based on Claude's confidence.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")
REVIEW_FILE = os.path.join(SCRIPT_DIR, "data", "needs_review.json")
SUMMARY_FILE = os.path.join(SCRIPT_DIR, "data", "_audit_summary.md")

# Media tab uses parallel files. media.json is a list of "stories" not
# "actions"; the audit/AI commands handle that key difference.
MEDIA_FILE = os.path.join(SCRIPT_DIR, "data", "media.json")
MEDIA_REVIEW_FILE = os.path.join(SCRIPT_DIR, "data", "needs_review_media.json")
MEDIA_SUMMARY_FILE = os.path.join(SCRIPT_DIR, "data", "_media_audit_summary.md")

# Oversight pipeline (parallel to enforcement). Items go to actions.json
# under oversight types (Audit, Investigation, Hearing, Report, etc.)
# after passing through needs_review_oversight.json + AI review.
OVERSIGHT_REVIEW_FILE = os.path.join(SCRIPT_DIR, "data", "needs_review_oversight.json")
OVERSIGHT_SUMMARY_FILE = os.path.join(SCRIPT_DIR, "data", "_oversight_audit_summary.md")

# ---------------------------------------------------------------------------
# Strict healthcare-context patterns. Anything matching these is auto-approved.
# Anything that doesn't match is flagged for review (NOT auto-rejected).
# ---------------------------------------------------------------------------
HC_KEYWORDS = re.compile(
    r"\b("
    # Programs
    r"medicare|medicaid|tricare|medi-?cal|chip\s+program|"
    r"affordable\s+care|\baca\b|obamacare|"
    # Generic healthcare
    r"health\s*care|healthcare|"
    r"hospital|clinic|physician|doctor|nurse|patient|"
    r"prescription|pharmac|hospice|home\s+health|"
    r"nursing\s+(home|facility)|skilled\s+nursing|long.term\s+care|"
    r"assisted\s+living|adult\s+day\s+care|"
    # Service types / specialties
    r"dental|dentist|behavioral\s+health|substance\s+abuse|addiction|"
    r"opioid|fentanyl|oxycodone|hydrocodone|controlled\s+substance|"
    r"telemedic|telehealth|"
    r"medical\s+(device|equipment|practice|center|group|provider|laborator|necessity)|"
    r"\bdme\b|dmepos|durable\s+medical|wound\s+care|skin\s+substitute|"
    r"genetic\s+test|genomic|"
    r"laborator|\blab\b|diagnostic|implant|prosthet|orthotic|"
    r"cardiac|cardio|oncolog|radiolog|podiatr|dermatolog|psychiatr|"
    r"pediatr|gyneco|ophthalmo|urolog|neurolog|rheumat|chiropract|"
    r"physiatr|physical\s+therapy|occupational\s+therapy|speech\s+therapy|"
    r"recovery\s+center|rehabilitation|ambulance|ambulatory|"
    r"health\s+(system|services|group|plan|insurance|net)|"
    r"pharma|drug\s+(company|manufacturer|distrib)|biotech|biologic|"
    r"vaccine|botox|insulin|infusion|"
    # Agencies
    r"\bcms\b|\bhhs\b|\boig\b|\bfda\b|\bdea\b|"
    # Healthcare-specific legal terms
    r"false\s+claims\s+act|anti.?kickback|stark\s+law|qui\s+tam|"
    r"whistleblower(?!.*tax)|"
    # Procedure / claim types
    r"upcod|unbundl|phantom\s+billing|prescription\s+(drug|fraud)|"
    r"compound\s+(drug|pharmacy)|drug\s+diversion|pill\s+mill|"
    r"\bnpi\b|provider\s+(enroll|number)"
    r")\b",
    re.IGNORECASE,
)

# Healthcare entity names that frequently appear without an HC keyword
HC_ENTITIES = re.compile(
    r"\b("
    r"kaiser|aetna|centene|humana|cigna|unitedhealth|elevance|molina|"
    r"anthem|blue\s+cross|blue\s+shield|"
    r"cvs|walgreens|rite\s+aid|express\s+scripts|optum|"
    r"amerisourcebergen|mckesson|cardinal\s+health|"
    r"pfizer|merck|abbvie|gilead|amgen|bristol[\s-]?myers|johnson\s*&\s*johnson|"
    r"novartis|sanofi|astrazeneca|eli\s+lilly|bayer|roche|"
    r"exactech|omnicare|dana[\s-]?farber|bioreference|opko|"
    r"atlantic\s+biologicals|semler|aesculap|magellan|"
    r"catholic\s+health|multicare|trinity\s+health|"
    r"hca|tenet\s+healthcare|community\s+health\s+systems|"
    r"davita|fresenius|encompass|brookdale|sunrise\s+senior"
    r")\b",
    re.IGNORECASE,
)


def is_obviously_healthcare(item: dict) -> bool:
    """True if the item title or link slug clearly references healthcare.

    Used as the first-stage regex pre-filter. Items matching here skip both
    the DOJ topic check and the AI review and go straight to actions.json.
    Items not matching here get the DOJ topic check next, then AI review.

    Editorial policy: we defer to DOJ's "Health Care Fraud" topic tag as
    the authoritative inclusion signal. We do NOT second-guess DOJ with a
    non-fraud crime demote list. If DOJ considers a case healthcare fraud,
    it belongs on the dashboard.
    """
    title = item.get("title", "") or ""
    link = item.get("link", "") or ""
    text = f"{title} {link}"
    return bool(HC_KEYWORDS.search(text) or HC_ENTITIES.search(text))


# Stricter HC gate for OVERSIGHT items. Unlike enforcement items (where
# "false claims", "kickback", or "fraud" alone is enough), oversight items
# come from HHS-OIG / GAO / Congressional committees that publish many
# NON-healthcare-fraud audits (LIHEAP, FISMA, ACF grants, NIH OT awards,
# cybersecurity, child welfare, foster care). So auto-promotion requires
# a signal that the audit/hearing/report is about Medicare, Medicaid, or
# a clearly-named healthcare program-integrity / fraud concept.
OVERSIGHT_FRAUD_GATE = re.compile(
    r"\b("
    # Programs defrauded
    r"medicare|medicaid|medi-?cal|chip\s+program|tricare|"
    r"affordable\s+care\s+act|\baca\s+(marketplace|exchange|enrollment)|"
    r"marketplace\s+(enrollment|fraud)|"
    # Core fraud / program integrity concepts
    r"fraud|kickback|false\s+claim|qui\s+tam|anti-?kickback|stark\s+law|"
    r"improper\s+payment|overpayment|unrecovered|unallowable\s+"
    r"(medicaid|medicare)|program\s+integrity|"
    r"semiannual\s+report|expected\s+recoveries|"
    # Provider / beneficiary schemes
    r"billing\s+scheme|upcod|unbundl|phantom\s+billing|pill\s+mill|"
    r"drug\s+diversion|"
    # Oversight language that implies a fraud concern
    r"fraud\s+(investigation|hearing|oversight|waste)|"
    r"waste.{0,10}abuse|anti-?fraud|"
    # HC-specific service areas where oversight items are always in scope
    r"hospice|durable\s+medical\s+equipment|\bdme\b|\bdmepos\b|"
    r"skin\s+substitute|home\s+health\s+agenc|nursing\s+home|"
    r"genetic\s+test|telehealth"
    r")\b",
    re.IGNORECASE,
)


def is_oversight_hc_fraud(item: dict) -> bool:
    """Stricter version of is_obviously_healthcare for OVERSIGHT items.

    Requires an explicit fraud/program-integrity signal OR a named
    federal healthcare program. Rejects generic mentions of "Health"
    (e.g. "Vibrent Health Claimed Unallowable Costs Under NIH Award" —
    Vibrent Health is a company name, NIH award is a grant, not fraud
    against Medicare/Medicaid).

    Used by cmd_audit_oversight instead of is_obviously_healthcare.
    """
    title = item.get("title", "") or ""
    link = item.get("link", "") or ""
    # Include link slug so e.g. "oig.hhs.gov/fraud/enforcement/..." counts
    text = f"{title} {link}"
    return bool(OVERSIGHT_FRAUD_GATE.search(text))


# ---------------------------------------------------------------------------
# DOJ topic extraction. Every justice.gov press release page carries a
# .node-topics field rendered by the Drupal template, containing DOJ's own
# topic classifications (e.g. "Health Care Fraud", "False Claims Act",
# "Financial Fraud", "Immigration"). Topics are concatenated with spaces,
# not delimited, so we greedy-match against a known vocabulary.
#
# This is the PRIMARY inclusion signal for the enforcement tab: if DOJ
# tags a release as "Health Care Fraud", we auto-promote regardless of
# what the title keywords suggest. We defer to DOJ's classification rather
# than impose our own narrower editorial filter.
# ---------------------------------------------------------------------------
DOJ_TOPIC_VOCAB = [
    "Health Care Fraud",
    "Healthcare Fraud",  # rare variant; keep as a safety net
    "Financial Fraud",
    "False Claims Act",
    "Identity Theft",
    "Prescription Drugs",
    "Consumer Protection",
    "Asset Forfeiture",
    "Drug Trafficking",
    "Violent Crime",
    "Civil Rights",
    "Immigration",
    "Public Corruption",
    "Tax",
    "Environment",
    "Cybercrime",
    "National Security",
    "Disability Rights",
    "Labor and Employment",
    "Human Trafficking",
    "Child Exploitation",
    "Firearms Offenses",
    "Antitrust",
    "Indian Country",
    "Project Safe Childhood",
    "Disaster Fraud",
    "Elder Justice",
]


def extract_topics_from_text(raw_text: str) -> list[str]:
    """Parse the contents of a .node-topics element into a list of DOJ topics.

    DOJ renders multi-topic pages as concatenated strings like
    "Health Care Fraud Financial Fraud Identity Theft". We greedy-match
    against DOJ_TOPIC_VOCAB, sorted longest-first so "Health Care Fraud"
    beats "Health" or "Fraud".
    """
    if not raw_text:
        return []
    # Strip leading "Topic" / "Topics" label
    text = re.sub(r"^\s*Topics?\s*", "", raw_text, flags=re.IGNORECASE).strip()
    if not text:
        return []
    found = []
    remaining = text
    for topic in sorted(DOJ_TOPIC_VOCAB, key=len, reverse=True):
        if topic in remaining:
            found.append(topic)
            remaining = remaining.replace(topic, " ")
    return found


def fetch_doj_topics(url: str, page=None) -> list[str] | None:
    """Fetch a justice.gov press release and extract its DOJ topic tags.

    Returns:
      - list of topic strings (possibly empty) if the page loaded AND had
        a .node-topics element
      - None if the page failed to load OR had no .node-topics element

    Accepts an optional Playwright ``page`` object so callers can reuse a
    browser session across many fetches. If not provided, a temporary
    browser is launched just for this call (expensive — prefer to batch).
    """
    if not url or "justice.gov" not in url:
        return None

    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print("fetch_doj_topics: playwright or bs4 not installed", file=sys.stderr)
        return None

    def _extract_from_html(html: str) -> list[str] | None:
        soup = BeautifulSoup(html, "lxml")
        node = soup.find(class_="node-topics")
        if not node:
            return None
        return extract_topics_from_text(node.get_text(" ", strip=True))

    if page is not None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1200)
            return _extract_from_html(page.content())
        except Exception as e:
            print(f"  fetch_doj_topics failed for {url}: {e}", file=sys.stderr)
            return None

    # Standalone fallback — launches a browser just for this call.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        )
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=25000)
            pg.wait_for_timeout(1200)
            return _extract_from_html(pg.content())
        except Exception as e:
            print(f"  fetch_doj_topics failed for {url}: {e}", file=sys.stderr)
            return None
        finally:
            browser.close()


def has_hc_topic(topics: list[str] | None) -> bool:
    """True if the DOJ topic list includes 'Health Care Fraud' (or variant)."""
    if not topics:
        return False
    return any("Health Care Fraud" in t or "Healthcare Fraud" in t for t in topics)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_review() -> dict:
    review = load_json(REVIEW_FILE, {"items": [], "rejected_links": []})
    review.setdefault("items", [])
    review.setdefault("rejected_links", [])
    return review


def get_committed_ids() -> set:
    """Return the set of action IDs in data/actions.json at git HEAD.

    Returns an empty set if HEAD has no actions.json (e.g. fresh repo).
    """
    try:
        out = subprocess.check_output(
            ["git", "show", "HEAD:data/actions.json"],
            cwd=SCRIPT_DIR,
            stderr=subprocess.DEVNULL,
        )
        committed = json.loads(out.decode("utf-8", errors="replace"))
        return {a["id"] for a in committed.get("actions", []) if "id" in a}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return set()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_audit() -> int:
    """Diff actions.json vs HEAD, move flagged items to needs_review.json."""
    committed_ids = get_committed_ids()
    data = load_json(DATA_FILE, {"actions": []})
    actions = data.get("actions", [])

    new_items = [a for a in actions if a.get("id") not in committed_ids]
    if not new_items:
        print("audit: no new items since last commit, nothing to do")
        # Clear summary file so a stale one doesn't confuse the workflow
        if os.path.exists(SUMMARY_FILE):
            os.remove(SUMMARY_FILE)
        return 0

    print(f"audit: {len(new_items)} new items since last commit")

    review = load_review()
    approved_new = []
    flagged = []
    for item in new_items:
        if is_obviously_healthcare(item):
            approved_new.append(item)
        else:
            flagged.append(item)

    if not flagged:
        print(f"audit: all {len(new_items)} new items passed the healthcare check")
        _write_summary(approved_new, [])
        return 0

    # Strip flagged items from actions.json, append to needs_review.json
    flagged_ids = {a["id"] for a in flagged}
    data["actions"] = [a for a in actions if a.get("id") not in flagged_ids]

    now = datetime.now().isoformat()
    for item in flagged:
        item["flagged_at"] = now
        item["flag_reason"] = "title lacks healthcare keyword"
        review["items"].append(item)

    save_json(DATA_FILE, data)
    save_json(REVIEW_FILE, review)

    print(f"audit: {len(approved_new)} auto-approved, {len(flagged)} flagged for review:")
    for item in flagged:
        print(f"  - {item['id']}: {item.get('title', '')[:80]}")
    print()
    print(f"  approved items kept in {os.path.basename(DATA_FILE)}")
    print(f"  flagged items moved to {os.path.basename(REVIEW_FILE)}")
    print(f"  promote a flagged item: python audit_new_items.py promote <id>")
    print(f"  permanently reject:     python audit_new_items.py reject <id>")

    _write_summary(approved_new, flagged)
    return 0


def cmd_list() -> int:
    """Show pending items in needs_review.json."""
    review = load_review()
    items = review.get("items", [])
    if not items:
        print("no items pending review")
        return 0
    print(f"{len(items)} item(s) pending review:")
    print()
    for item in items:
        print(f"  {item.get('id', '?')}")
        print(f"    title:    {item.get('title', '')[:90]}")
        print(f"    link:     {item.get('link', '')[:90]}")
        print(f"    type:     {item.get('type', '?')}")
        print(f"    flagged:  {item.get('flagged_at', '?')}")
        print(f"    reason:   {item.get('flag_reason', '?')}")
        print()
    print(f"To promote: python audit_new_items.py promote <id>")
    print(f"To reject:  python audit_new_items.py reject <id>")
    return 0


_REVIEW_METADATA_KEYS = (
    "flagged_at", "flag_reason",
    "ai_decision", "ai_confidence", "ai_reason", "ai_model",
    "topic_checked_at", "audit_decision",
    # doj_topics is kept — it's useful provenance even after promotion
)


def _strip_review_metadata(item: dict) -> dict:
    """Return a copy of item with review-only fields removed."""
    clean = {k: v for k, v in item.items() if k not in _REVIEW_METADATA_KEYS}
    return clean


def cmd_promote(item_id: str) -> int:
    """Move an item from needs_review.json back to actions.json."""
    review = load_review()
    item = next((a for a in review["items"] if a.get("id") == item_id), None)
    if not item:
        print(f"promote: no item with id {item_id!r} in {REVIEW_FILE}", file=sys.stderr)
        return 1

    clean = _strip_review_metadata(item)

    data = load_json(DATA_FILE, {"actions": []})
    data.setdefault("actions", []).append(clean)
    save_json(DATA_FILE, data)

    review["items"] = [a for a in review["items"] if a.get("id") != item_id]
    save_json(REVIEW_FILE, review)

    print(f"promoted {item_id} -> {os.path.basename(DATA_FILE)}")
    print(f"  title: {clean.get('title', '')[:80]}")
    return 0


def cmd_reject(item_id: str) -> int:
    """Permanently reject an item; its link is added to rejected_links."""
    review = load_review()
    item = next((a for a in review["items"] if a.get("id") == item_id), None)
    if not item:
        print(f"reject: no item with id {item_id!r} in {REVIEW_FILE}", file=sys.stderr)
        return 1

    link = item.get("link", "")
    if link and link not in review["rejected_links"]:
        review["rejected_links"].append(link)

    review["items"] = [a for a in review["items"] if a.get("id") != item_id]
    save_json(REVIEW_FILE, review)

    print(f"rejected {item_id}")
    print(f"  title: {item.get('title', '')[:80]}")
    if link:
        print(f"  link added to rejected_links — scraper will skip this URL going forward")
    return 0


def cmd_topic_check() -> int:
    """Fetch DOJ .node-topics for every unstamped item in needs_review.json.

    For each item in the queue that doesn't already have a `topic_checked_at`
    timestamp, fetch the justice.gov page via Playwright, extract the topic
    list, and store it as `doj_topics: [...]` plus the timestamp.

    Items where DOJ tagged "Health Care Fraud" are auto-promoted into
    actions.json. Items tagged with something else (False Claims Act,
    Drug Trafficking, etc.) stay in the queue for AI review. Items where
    the page has no .node-topics field also stay in the queue.

    This runs between cmd_audit and cmd_ai_review in the daily pipeline.
    Zero API cost; the only overhead is ~3s per Playwright fetch.
    """
    review = load_review()
    pending = [
        a for a in review.get("items", [])
        if "topic_checked_at" not in a and a.get("link", "").startswith("https://www.justice.gov")
    ]
    if not pending:
        print("topic-check: no un-checked justice.gov items in needs_review.json")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("topic-check: playwright not installed, skipping")
        return 0

    print(f"topic-check: checking {len(pending)} item(s) against DOJ .node-topics")

    data = load_json(DATA_FILE, {"actions": []})
    promoted = []
    tagged_non_hc = []
    no_topic = []
    now_iso = datetime.now().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        for item in pending:
            url = item.get("link", "")
            topics = fetch_doj_topics(url, page=page)
            item["topic_checked_at"] = now_iso

            if topics is None:
                item["doj_topics"] = None
                no_topic.append(item)
                print(f"  [NO TOPIC] {item['id']}: {item.get('title','')[:80]}")
            elif has_hc_topic(topics):
                item["doj_topics"] = topics
                clean = _strip_review_metadata(item)
                data.setdefault("actions", []).append(clean)
                promoted.append(item)
                print(f"  [PROMOTE]  {item['id']}: {topics}")
                print(f"             {item.get('title','')[:80]}")
            else:
                item["doj_topics"] = topics
                tagged_non_hc.append(item)
                print(f"  [KEEP]     {item['id']}: {topics}")
                print(f"             {item.get('title','')[:80]}")
        browser.close()

    # Remove promoted items from the review queue. Keep the rest (with
    # their newly-stamped doj_topics + topic_checked_at) in the queue so
    # they go through AI review next.
    promoted_ids = {a["id"] for a in promoted}
    review["items"] = [a for a in review["items"] if a.get("id") not in promoted_ids]

    save_json(DATA_FILE, data)
    save_json(REVIEW_FILE, review)

    print()
    print(f"topic-check: {len(promoted)} promoted (DOJ tagged HC), "
          f"{len(tagged_non_hc)} kept (tagged non-HC), "
          f"{len(no_topic)} kept (no topic field)")
    return 0


# ---------------------------------------------------------------------------
# Workflow integration
# ---------------------------------------------------------------------------
def _write_summary(approved: list, flagged: list) -> None:
    """Write a markdown summary the GHA workflow can paste into the PR body."""
    lines = []
    if approved:
        lines.append(f"### Auto-approved ({len(approved)} new items)")
        for item in approved:
            lines.append(f"- {item.get('title', '')[:120]}")
        lines.append("")
    if flagged:
        lines.append(f"### Needs review ({len(flagged)} item(s) — moved to needs_review.json)")
        lines.append("")
        lines.append("These items were scraped but did not match the healthcare keyword filter. ")
        lines.append("They are NOT live on the dashboard. Review and either promote or reject:")
        lines.append("")
        for item in flagged:
            lines.append(f"- **{item.get('title', '')}**")
            link = item.get("link", "")
            if link:
                lines.append(f"  [{link}]({link})")
            lines.append(f"  `python audit_new_items.py promote {item['id']}`  or  `reject {item['id']}`")
            lines.append("")
    save_json(SUMMARY_FILE.replace(".md", ".json"), {
        "approved": [{"id": a["id"], "title": a.get("title", "")} for a in approved],
        "flagged":  [{"id": a["id"], "title": a.get("title", ""), "link": a.get("link", "")} for a in flagged],
    })
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# AI review layer — Claude Haiku processes items in needs_review.json
# ---------------------------------------------------------------------------
AI_MODEL = "claude-haiku-4-5-20251001"

AI_SYSTEM_PROMPT = """You are a relevance classifier for a healthcare fraud enforcement dashboard.

The dashboard tracks federal enforcement actions against healthcare fraud in the United States: Medicare, Medicaid, TRICARE, ACA marketplace, and private health insurance fraud by providers, pharmacies, device makers, labs, and insurers.

You will be given a DOJ press release title and URL. Determine whether this press release belongs on the dashboard.

## IN SCOPE (answer healthcare_fraud=true)

- Medicare, Medicaid, TRICARE, ACA, or private health insurance fraud
- False Claims Act cases against healthcare providers, hospitals, clinics, labs, pharmacies, device makers, DME suppliers, hospice/home health, nursing facilities
- Anti-Kickback Statute or Stark Law violations in a healthcare context
- Drug diversion, pill mill, or opioid prescribing fraud by licensed medical professionals
- Genetic testing, telehealth, or wound care fraud schemes
- Healthcare-adjacent identity theft where stolen identities were used to submit false medical claims
- Pharmaceutical kickback, off-label marketing, or drug pricing fraud cases
- Healthcare cybersecurity violations leading to FCA liability (e.g. unsecured EHR systems)

## OUT OF SCOPE (answer healthcare_fraud=false)

- SNAP / food stamp fraud
- Unemployment insurance fraud
- Housing assistance fraud
- Child care / daycare program fraud
- PPP or COVID economic relief fraud (unless the fraud specifically involved medical services, medical test kits, or health insurance)
- Passport fraud, immigration fraud, unaccompanied alien minor sponsorship
- Social Security fraud (unless it's healthcare-related SSDI provider fraud)
- Street-level drug trafficking, gang prosecutions, murder-for-hire, or violent crime
- Bank fraud, mortgage fraud, real estate fraud (unless healthcare-specific)
- Defense contractor bribery
- Tax fraud (unless it's a side charge on a primary healthcare fraud case)
- Roundups, "ICYMI" posts, or district-wide prosecution highlights
- Press releases announcing new prosecutors, office changes, or organizational news

## OUTPUT

Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.

{
  "healthcare_fraud": true | false,
  "confidence": integer 0-100,
  "reason": "one sentence explaining the decision"
}

Confidence calibration:
- 95-100: title makes it unambiguous (mentions Medicare/Medicaid/pharmacy/doctor/hospital/etc. OR unambiguous non-HC term)
- 70-94: title clearly implies one direction but lacks a definitive keyword
- 30-69: title is genuinely ambiguous, could go either way
- 0-29: unable to judge from title alone
"""

AUTO_PROMOTE_THRESHOLD = 90  # confidence >= this AND healthcare_fraud=true -> auto-promote
AUTO_REJECT_THRESHOLD = 90   # confidence >= this AND healthcare_fraud=false -> auto-reject


def _call_claude(client, title: str, link: str) -> dict | None:
    """Call Claude Haiku with the classifier prompt. Returns decision dict or None."""
    user_msg = f"Title: {title}\nLink: {link}"
    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=200,
            system=AI_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # Strip possible markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        if "healthcare_fraud" not in result or "confidence" not in result:
            return None
        return result
    except Exception as e:
        print(f"    AI call failed: {e}", file=sys.stderr)
        return None


def cmd_ai_review() -> int:
    """Process items in needs_review.json with Claude Haiku.

    High-confidence healthcare items get auto-promoted back to actions.json.
    High-confidence non-healthcare items get auto-rejected. Borderline items
    stay in the review queue with an ai_decision/ai_confidence/ai_reason
    annotation so the human reviewer sees Claude's opinion in the PR.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ai-review: ANTHROPIC_API_KEY not set, skipping")
        return 0

    try:
        import anthropic
    except ImportError:
        print("ai-review: anthropic package not installed, skipping")
        return 0

    review = load_review()
    pending = [a for a in review.get("items", []) if "ai_decision" not in a]
    if not pending:
        print("ai-review: no un-reviewed items in needs_review.json")
        return 0

    print(f"ai-review: processing {len(pending)} item(s) with {AI_MODEL}")
    client = anthropic.Anthropic(api_key=api_key)

    data = load_json(DATA_FILE, {"actions": []})
    promoted_items = []
    rejected_items = []
    escalated_items = []

    for item in pending:
        title = item.get("title", "")
        link = item.get("link", "")
        print(f"  reviewing: {item['id']}")
        print(f"             {title[:80]}")

        decision = _call_claude(client, title, link)
        if decision is None:
            print("             SKIP (API error, left in queue)")
            continue

        is_hc = bool(decision.get("healthcare_fraud"))
        conf = int(decision.get("confidence", 0))
        reason = str(decision.get("reason", ""))[:200]

        item["ai_decision"] = "healthcare_fraud" if is_hc else "not_healthcare_fraud"
        item["ai_confidence"] = conf
        item["ai_reason"] = reason
        item["ai_model"] = AI_MODEL

        if is_hc and conf >= AUTO_PROMOTE_THRESHOLD:
            # Auto-promote: strip review metadata and add to actions
            clean = {k: v for k, v in item.items()
                     if not k.startswith("ai_") and k not in ("flagged_at", "flag_reason")}
            data.setdefault("actions", []).append(clean)
            promoted_items.append(item)
            print(f"             PROMOTE (confidence={conf}) — {reason[:80]}")
        elif (not is_hc) and conf >= AUTO_REJECT_THRESHOLD:
            if link and link not in review["rejected_links"]:
                review["rejected_links"].append(link)
            rejected_items.append(item)
            print(f"             REJECT  (confidence={conf}) — {reason[:80]}")
        else:
            # Borderline: leave in queue for human review
            escalated_items.append(item)
            label = "HC" if is_hc else "non-HC"
            print(f"             ESCALATE ({label}, confidence={conf}) — {reason[:80]}")

    # Remove promoted + rejected items from the review queue. Keep escalated.
    handled_ids = {a["id"] for a in promoted_items + rejected_items}
    review["items"] = [a for a in review["items"] if a.get("id") not in handled_ids]

    save_json(DATA_FILE, data)
    save_json(REVIEW_FILE, review)

    print()
    print(f"ai-review: {len(promoted_items)} promoted, "
          f"{len(rejected_items)} rejected, {len(escalated_items)} escalated")

    _append_ai_summary(promoted_items, rejected_items, escalated_items)
    return 0


def _append_ai_summary(promoted: list, rejected: list, escalated: list) -> None:
    """Append AI results to the markdown summary the workflow pastes into PRs."""
    lines = ["", "---", ""]
    if promoted:
        lines.append(f"### AI-promoted ({len(promoted)} item(s), added to actions.json)")
        lines.append("")
        lines.append("Claude classified these as healthcare fraud with high confidence:")
        lines.append("")
        for a in promoted:
            lines.append(f"- **{a.get('title', '')[:120]}**")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if rejected:
        lines.append(f"### AI-rejected ({len(rejected)} item(s), link blocked)")
        lines.append("")
        lines.append("Claude classified these as NOT healthcare fraud with high confidence:")
        lines.append("")
        for a in rejected:
            lines.append(f"- {a.get('title', '')[:120]}")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if escalated:
        lines.append(f"### AI-escalated ({len(escalated)} item(s), needs your call)")
        lines.append("")
        lines.append("Claude was unsure. Review and either promote or reject:")
        lines.append("")
        for a in escalated:
            lines.append(f"- **{a.get('title', '')}**")
            link = a.get("link", "")
            if link:
                lines.append(f"  [{link}]({link})")
            lines.append(f"  _Claude: {a.get('ai_decision', '?')} @ confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:200]}_")
            lines.append(f"  `python audit_new_items.py promote {a['id']}`  or  `reject {a['id']}`")
            lines.append("")

    # Append to existing summary, or create a new one
    existing = ""
    if os.path.exists(SUMMARY_FILE):
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            existing = f.read()
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(existing + "\n".join(lines))


# ---------------------------------------------------------------------------
# Media tab — parallel commands using needs_review_media.json + media.json
# ---------------------------------------------------------------------------
# The media tab works on a different cadence: items are scraped into
# needs_review_media.json by update_media.py and only get promoted into
# media.json after passing both regex (cmd_audit_media) and AI relevance
# checks (cmd_ai_review_media). Same safety net architecture as enforcement,
# adapted for the "stories" key and the looser editorial scope of journalism.
#
# Key differences from the enforcement audit:
#   - Stories live under "stories" not "actions"
#   - Items start in needs_review_media.json (already separated by the
#     scraper); cmd_audit_media diffs the review file against itself + the
#     committed media.json to find newly-scraped items, runs the regex
#     gate, and auto-promotes obvious items into media.json
#   - The AI prompt asks "is this an investigative-journalism piece about
#     healthcare fraud?" — slightly different scope than enforcement
#     (e.g. opinion pieces, broad industry coverage, and roundups all
#     get rejected even if they mention healthcare fraud)


_MEDIA_AI_PROMPT_TEMPLATE = """You are a relevance classifier for the Media Investigations tab of a healthcare fraud dashboard.

The tab tracks third-party investigative journalism that exposes specific healthcare fraud schemes, providers, insurers, or programs in the United States. You will be given a news article title and URL. Decide whether this story belongs on the dashboard.

## IN SCOPE (answer healthcare_fraud_journalism=true)

- Investigative reporting on a specific Medicare, Medicaid, TRICARE, or ACA fraud scheme
- Coverage of a False Claims Act case, qui tam suit, kickback case, or similar
- Reporting on a healthcare provider (hospital, clinic, doctor, lab, DME supplier, pharmacy, hospice, home health, nursing home) accused of billing fraud
- Coverage of pharmaceutical/device company fraud (off-label, kickbacks, FCA, drug pricing)
- Coverage of healthcare insurer fraud (UnitedHealth, Aetna, Humana, Centene, Kaiser, etc.)
- Reporting on telehealth or genetic testing fraud schemes
- Coverage of opioid/controlled substance billing fraud or pill mills
- Coverage of an HHS-OIG or DOJ investigation INTO healthcare fraud (the journalism is about the underlying fraud, not the agency action itself — for the latter, the item belongs on the Oversight tab not the Media tab)
- Reporting on systemic fraud loopholes (NPI loophole, DMEPOS supplier abuse, etc.)

## OUT OF SCOPE (answer healthcare_fraud_journalism=false)

- General healthcare policy debates (Medicare for All, premium increases, hospital consolidation) without a specific fraud angle
- Opinion pieces, editorials, or op-eds (even if they mention fraud)
- Industry analyst coverage (Q1 earnings, M&A, drug approval news)
- Hospital or insurer PR / press release rewrites
- Sex crimes or violent crimes by doctors (these are criminal cases, not healthcare fraud)
- Drug trafficking by physicians outside a billing-fraud context
- Medical malpractice without a fraud allegation
- Drug recall coverage / FDA approval coverage
- Class action lawsuits without a specific fraud allegation
- Public health stories (outbreaks, vaccine policy, epidemiology)
- Generic "healthcare costs are rising" pieces
- Roundups, "year in review" pieces, or summary articles unless they detail a specific scheme
- AGENCY-LED stories: if the article is primarily about a federal agency (DOJ, CMS, HHS-OIG) announcing or taking an action, that item belongs on the Oversight tab, not the Media tab. Reject from media in that case.
- SINGLE-CASE PRESS-RELEASE REWRITES: if the article is a short news-wire rewrite of one DOJ/USAO press release — the defendant, amount, charges, and prosecutor quotes all come from a single case, with no original reporting, no other examples, and no broader scheme context — reject. Those cases already live in Federal Enforcement (via the underlying DOJ press release). Titles like "Surgeon Gets X Years for $Y Fraud" or "Company Agrees to $Z FCA Settlement" from local TV / small wires are usually this pattern. REJECT only when it's purely a single-case rewrite. It is FINE (accept) if the article cites a specific DOJ case as one example in a broader story — trend pieces, multi-case pattern analysis, systemic fraud exposes, regional fraud coverage with multiple defendants — even if one DOJ case is referenced or summarized within the article. The test: does the article add context the DOJ press release doesn't (other cases, patient interviews, prior warnings, data analysis, policy framing)? If yes, accept. If no, reject.
- HEARING / TESTIMONY REWRITES: if the article's news peg is a Congressional hearing, committee testimony, or similar legislative event — the article summarizes what witnesses said, quotes lawmakers' questions, or reports on hearing announcements — REJECT. Titles like "Hearing exposes fraud in X", "Lawmakers demand answers", "Senator warns of X", "Witness tells Congress", or URLs containing "hearing" / "testimony" / "capitol-hill" are typical. These are news-wire coverage of a hearing event, not original investigative journalism. The hearings themselves belong on the Oversight tab. Only accept if the article is clearly multi-source original reporting that uses the hearing as ONE of several anchors (e.g., a deep investigation that ALSO cites a hearing).

## OUTPUT

Return ONLY valid JSON. No markdown fences, no prose.

{{
  "healthcare_fraud_journalism": true | false,
  "confidence": integer 0-100,
  "reason": "one sentence explaining the decision"
}}

Confidence calibration:
- 95-100: title makes the call unambiguous
- 70-94: title clearly implies one direction
- 30-69: genuinely ambiguous
- 0-29: unable to judge from title alone
"""


def _build_media_ai_prompt() -> str:
    return _MEDIA_AI_PROMPT_TEMPLATE


def load_media_review() -> dict:
    review = load_json(MEDIA_REVIEW_FILE, {"items": [], "rejected_links": []})
    review.setdefault("items", [])
    review.setdefault("rejected_links", [])
    return review


def cmd_audit_media() -> int:
    """Run the regex healthcare check on items in needs_review_media.json.

    Items that pass the HC keyword check AND don't match the non-fraud
    crime demote list get promoted into media.json. Anything else stays
    in the review queue for AI review or human triage.
    """
    review = load_media_review()
    pending = [a for a in review.get("items", []) if not a.get("ai_decision")
               and not a.get("audit_decision")]

    if not pending:
        print("audit-media: no un-audited items in needs_review_media.json")
        if os.path.exists(MEDIA_SUMMARY_FILE):
            os.remove(MEDIA_SUMMARY_FILE)
        return 0

    print(f"audit-media: {len(pending)} pending items to check")

    media = load_json(MEDIA_FILE, {"metadata": {"version": "1.0", "last_updated": ""},
                                    "stories": []})

    # Media two-tier gate (mirrors oversight approach):
    #   Tier 1: Strong fraud-investigation signal → auto-promote
    #   Tier 2: HC keyword but no fraud signal → AI review
    #   Neither → auto-reject
    MEDIA_FRAUD_SIGNAL = re.compile(
        r"\b("
        r"fraud|scam|scheme|kickback|false claim|improper payment|"
        r"overbill|upcod|billing scheme|phantom billing|"
        r"investigation|investigat|expos|uncover|reveal|probe|"
        r"indict|convict|sentenc|plead|guilty|arrest|"
        r"settlement|agrees? to pay|ordered to pay|"
        r"whistleblower|qui tam|"
        r"billion.{0,10}(fraud|scheme|loss)|"
        r"million.{0,10}(fraud|scheme|loss)"
        r")\b",
        re.IGNORECASE,
    )

    auto_promoted = []
    still_pending = []
    auto_rejected = []
    for item in pending:
        title = item.get("title", "") or ""
        # Tier 1: strong fraud/investigation signal → auto-promote
        if MEDIA_FRAUD_SIGNAL.search(title) and is_obviously_healthcare(item):
            auto_promoted.append(item)
            item["audit_decision"] = "auto_approved"
        # Tier 2: HC keyword but no fraud signal → AI review
        elif is_obviously_healthcare(item):
            still_pending.append(item)
            item["flag_reason"] = "HC keyword but no fraud/investigation signal — needs AI review"
        # Neither → auto-reject
        else:
            auto_rejected.append(item)
            item["audit_decision"] = "auto_rejected"
            item["flag_reason"] = "no HC keyword"

    # Block auto-rejected links
    for item in auto_rejected:
        link = item.get("link", "")
        if link and link not in review["rejected_links"]:
            review["rejected_links"].append(link)

    if auto_promoted:
        # Strip review-only metadata before adding to media.json
        for item in auto_promoted:
            for k in ("flagged_at", "flag_reason", "audit_decision"):
                item.pop(k, None)
        # New stories go at the top, sorted by date desc
        new_stories = sorted(auto_promoted, key=lambda s: s.get("date", ""), reverse=True)
        media["stories"] = new_stories + media.get("stories", [])
        media["metadata"]["last_updated"] = datetime.now().isoformat()
        save_json(MEDIA_FILE, media)

    # Remove auto-promoted + auto-rejected from the review queue
    handled_ids = {a["id"] for a in auto_promoted + auto_rejected}
    review["items"] = [a for a in review["items"] if a.get("id") not in handled_ids]
    save_json(MEDIA_REVIEW_FILE, review)

    ai_pending = len(still_pending)
    print(f"audit-media: {len(auto_promoted)} auto-promoted, "
          f"{len(auto_rejected)} auto-rejected, "
          f"{ai_pending} flagged for AI review")

    _write_media_audit_summary(auto_promoted, still_pending)
    return 0


def cmd_ai_review_media() -> int:
    """Process items in needs_review_media.json with Claude Haiku.

    Same three-tier logic as cmd_ai_review for enforcement: auto-promote
    high-confidence yes, auto-reject high-confidence no, escalate the rest.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ai-review-media: ANTHROPIC_API_KEY not set, skipping")
        return 0

    try:
        import anthropic
    except ImportError:
        print("ai-review-media: anthropic package not installed, skipping")
        return 0

    review = load_media_review()
    pending = [a for a in review.get("items", []) if "ai_decision" not in a]
    if not pending:
        print("ai-review-media: no un-reviewed items in needs_review_media.json")
        return 0

    print(f"ai-review-media: processing {len(pending)} item(s) with {AI_MODEL}")
    client = anthropic.Anthropic(api_key=api_key)

    media = load_json(MEDIA_FILE, {"metadata": {"version": "1.0", "last_updated": ""}, "stories": []})

    promoted = []
    rejected = []
    escalated = []

    for item in pending:
        title = item.get("title", "")
        link = item.get("link", "")
        print(f"  reviewing: {item['id']}")
        print(f"             {title[:80]}")

        decision = _call_claude_media(client, title, link)
        if decision is None:
            print("             SKIP (API error, left in queue)")
            continue

        is_journalism = bool(decision.get("healthcare_fraud_journalism"))
        conf = int(decision.get("confidence", 0))
        reason = str(decision.get("reason", ""))[:200]

        item["ai_decision"] = "healthcare_fraud_journalism" if is_journalism else "not_journalism"
        item["ai_confidence"] = conf
        item["ai_reason"] = reason
        item["ai_model"] = AI_MODEL

        if is_journalism and conf >= AUTO_PROMOTE_THRESHOLD:
            clean = {k: v for k, v in item.items()
                     if not k.startswith("ai_")
                     and k not in ("flagged_at", "flag_reason", "audit_decision")}
            media.setdefault("stories", []).insert(0, clean)
            promoted.append(item)
            print(f"             PROMOTE (confidence={conf}) — {reason[:80]}")
        elif (not is_journalism) and conf >= AUTO_REJECT_THRESHOLD:
            if link and link not in review["rejected_links"]:
                review["rejected_links"].append(link)
            rejected.append(item)
            print(f"             REJECT  (confidence={conf}) — {reason[:80]}")
        else:
            escalated.append(item)
            label = "journalism" if is_journalism else "not journalism"
            print(f"             ESCALATE ({label}, confidence={conf}) — {reason[:80]}")

    handled_ids = {a["id"] for a in promoted + rejected}
    review["items"] = [a for a in review["items"] if a.get("id") not in handled_ids]

    if promoted:
        # Re-sort stories by date desc since we inserted new ones
        media["stories"] = sorted(media.get("stories", []),
                                   key=lambda s: s.get("date", ""), reverse=True)
        media["metadata"]["last_updated"] = datetime.now().isoformat()

    save_json(MEDIA_FILE, media)
    save_json(MEDIA_REVIEW_FILE, review)

    print()
    print(f"ai-review-media: {len(promoted)} promoted, {len(rejected)} rejected, "
          f"{len(escalated)} escalated")

    _append_media_ai_summary(promoted, rejected, escalated)
    return 0


def _call_claude_media(client, title: str, link: str) -> dict | None:
    """Call Claude Haiku with the media-specific classifier prompt."""
    user_msg = f"Title: {title}\nLink: {link}"
    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=300,
            system=_build_media_ai_prompt(),
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        if "healthcare_fraud_journalism" not in result or "confidence" not in result:
            return None
        return result
    except Exception as e:
        print(f"    AI call failed: {e}", file=sys.stderr)
        return None


def cmd_media_promote(item_id: str) -> int:
    """Move a media story from needs_review_media.json into media.json."""
    review = load_media_review()
    item = next((a for a in review["items"] if a.get("id") == item_id), None)
    if not item:
        print(f"media-promote: no item {item_id!r} in {MEDIA_REVIEW_FILE}", file=sys.stderr)
        return 1

    for k in ("flagged_at", "flag_reason", "audit_decision",
              "ai_decision", "ai_confidence", "ai_reason", "ai_model"):
        item.pop(k, None)

    media = load_json(MEDIA_FILE, {"metadata": {"version": "1.0", "last_updated": ""}, "stories": []})
    media.setdefault("stories", []).insert(0, item)
    media["stories"] = sorted(media["stories"], key=lambda s: s.get("date", ""), reverse=True)
    media["metadata"]["last_updated"] = datetime.now().isoformat()
    save_json(MEDIA_FILE, media)

    review["items"] = [a for a in review["items"] if a.get("id") != item_id]
    save_json(MEDIA_REVIEW_FILE, review)

    print(f"media-promoted {item_id} -> {os.path.basename(MEDIA_FILE)}")
    print(f"  title: {item.get('title', '')[:80]}")
    return 0


def cmd_media_reject(item_id: str) -> int:
    """Permanently reject a media story; its link is added to rejected_links."""
    review = load_media_review()
    item = next((a for a in review["items"] if a.get("id") == item_id), None)
    if not item:
        print(f"media-reject: no item {item_id!r} in {MEDIA_REVIEW_FILE}", file=sys.stderr)
        return 1

    link = item.get("link", "")
    if link and link not in review["rejected_links"]:
        review["rejected_links"].append(link)

    review["items"] = [a for a in review["items"] if a.get("id") != item_id]
    save_json(MEDIA_REVIEW_FILE, review)

    print(f"media-rejected {item_id}")
    print(f"  title: {item.get('title', '')[:80]}")
    if link:
        print(f"  link added to media rejected_links — scraper will skip it")
    return 0


def cmd_media_list() -> int:
    """Show pending items in needs_review_media.json."""
    review = load_media_review()
    items = review.get("items", [])
    if not items:
        print("no media items pending review")
        return 0
    print(f"{len(items)} media item(s) pending review:")
    print()
    for item in items:
        print(f"  {item.get('id', '?')}")
        print(f"    title:    {item.get('title', '')[:90]}")
        print(f"    link:     {item.get('link', '')[:90]}")
        print(f"    flagged:  {item.get('flagged_at', '?')}")
        print(f"    reason:   {item.get('flag_reason', '?')}")
        if item.get("ai_decision"):
            print(f"    ai:       {item['ai_decision']} @ confidence {item.get('ai_confidence')}")
            print(f"    ai_reason: {item.get('ai_reason', '')[:120]}")
        print()
    print("To promote: python audit_new_items.py media-promote <id>")
    print("To reject:  python audit_new_items.py media-reject  <id>")
    return 0


def _write_media_audit_summary(approved: list, flagged: list) -> None:
    """Write a markdown summary of the media audit pass."""
    lines = []
    if approved:
        lines.append(f"### Auto-promoted media stories ({len(approved)})")
        for item in approved:
            lines.append(f"- {item.get('title', '')[:120]}")
        lines.append("")
    if flagged:
        lines.append(f"### Flagged media stories ({len(flagged)} pending review)")
        lines.append("")
        for item in flagged:
            lines.append(f"- **{item.get('title', '')}**")
            link = item.get("link", "")
            if link:
                lines.append(f"  [{link}]({link})")
            lines.append(f"  _reason: {item.get('flag_reason', '?')}_")
            lines.append(f"  `python audit_new_items.py media-promote {item['id']}`  or  `media-reject {item['id']}`")
            lines.append("")
    save_json(MEDIA_SUMMARY_FILE.replace(".md", ".json"), {
        "approved": [{"id": a["id"], "title": a.get("title", "")} for a in approved],
        "flagged":  [{"id": a["id"], "title": a.get("title", ""), "link": a.get("link", "")} for a in flagged],
    })
    with open(MEDIA_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _append_media_ai_summary(promoted: list, rejected: list, escalated: list) -> None:
    """Append media AI results to the markdown summary."""
    lines = ["", "---", ""]
    if promoted:
        lines.append(f"### Media AI-promoted ({len(promoted)} story/stories)")
        lines.append("")
        lines.append("Claude classified these as healthcare fraud journalism with high confidence:")
        lines.append("")
        for a in promoted:
            lines.append(f"- **{a.get('title', '')[:120]}**")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if rejected:
        lines.append(f"### Media AI-rejected ({len(rejected)} story/stories, link blocked)")
        lines.append("")
        for a in rejected:
            lines.append(f"- {a.get('title', '')[:120]}")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if escalated:
        lines.append(f"### Media AI-escalated ({len(escalated)} story/stories, needs your call)")
        lines.append("")
        for a in escalated:
            lines.append(f"- **{a.get('title', '')}**")
            link = a.get("link", "")
            if link:
                lines.append(f"  [{link}]({link})")
            lines.append(f"  _Claude: {a.get('ai_decision', '?')} @ confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:200]}_")
            lines.append(f"  `python audit_new_items.py media-promote {a['id']}`  or  `media-reject {a['id']}`")
            lines.append("")

    existing = ""
    if os.path.exists(MEDIA_SUMMARY_FILE):
        with open(MEDIA_SUMMARY_FILE, encoding="utf-8") as f:
            existing = f.read()
    with open(MEDIA_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(existing + "\n".join(lines))


# ---------------------------------------------------------------------------
# Oversight pipeline — parallel to media/enforcement, routes oversight-type
# items (Audit, Investigation, Hearing, Report, Administrative Action,
# Rule/Regulation, Legislation, Structural/Organizational) into actions.json
# after passing both regex and AI relevance checks.
# ---------------------------------------------------------------------------
OVERSIGHT_AI_PROMPT = """You are a relevance classifier for the Oversight & Accountability tab of a healthcare fraud dashboard.

The Oversight tab tracks federal *oversight* actions about healthcare fraud — distinct from criminal/civil enforcement. In scope:

## IN SCOPE (answer healthcare_fraud_oversight=true)

- HHS-OIG audits, evaluations, inspections, semiannual reports about Medicare/Medicaid/CHIP/program-integrity findings
- GAO reports on healthcare fraud, improper payments, program-integrity gaps in Medicare/Medicaid/TRICARE/ACA
- Congressional hearings (House E&C, House Oversight, House Ways & Means, Senate Finance, Senate HELP) about healthcare fraud, improper payments, or program integrity
- Congressional committee investigations or letters demanding info about healthcare fraud
- CMS administrative anti-fraud actions: corrective action plans, program suspensions, moratoria, payment hold-ups, NPI revocations, deferral notices
- Treasury/FinCEN advisories specifically about healthcare-fraud SARs or money-laundering typologies
- White House / DOJ healthcare-fraud task force formation or org changes
- Healthcare-fraud-relevant rules / regulations / policy changes (CMS Final Rule on DMEPOS screening, etc.)
- Senate or House reports on healthcare fraud findings
- DOJ FY recovery announcements that summarize healthcare-fraud results (the DOJ False Claims Act annual report etc.)

## OUT OF SCOPE (answer healthcare_fraud_oversight=false)

- DOJ/USAO criminal prosecutions or civil settlements (those go on the Federal Enforcement tab, not Oversight)
- General congressional hearings unrelated to healthcare fraud (immigration, tax, defense, foreign aid, etc.)
- HHS-OIG audits NOT about healthcare fraud or program integrity (e.g. SNAP, Head Start, OCR)
- GAO reports unrelated to healthcare fraud (defense procurement, NASA, IRS service, etc.)
- DEA drug seizures, gang takedowns, fentanyl trafficking arrests
- General agency newsroom announcements (new staff, organizational announcements, awards)
- News coverage of an oversight action (that goes on the Media tab)
- Roundup posts, "ICYMI", press release indices

## Borderline notes

- A hearing titled "Examining Medicaid Improper Payments" → IN scope, high confidence
- A hearing titled "Oversight of Federal Spending" → OUT, too broad
- A report titled "DOJ Recovers $X Billion in False Claims Act Settlements in FY2025" → IN if it breaks out healthcare; the FCA report is annually a primary HC fraud doc
- A CMS press release announcing a new CMS Administrator → OUT
- A CMS press release announcing a new program integrity initiative → IN

## OUTPUT

Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.

{
  "healthcare_fraud_oversight": true | false,
  "confidence": integer 0-100,
  "reason": "one sentence explaining the decision"
}

Confidence calibration:
- 95-100: title makes it unambiguous
- 70-94: title clearly implies one direction
- 30-69: title is genuinely ambiguous
- 0-29: unable to judge from title alone
"""


def load_oversight_review() -> dict:
    review = load_json(OVERSIGHT_REVIEW_FILE, {"items": [], "rejected_links": []})
    review.setdefault("items", [])
    review.setdefault("rejected_links", [])
    return review


def cmd_audit_oversight() -> int:
    """Run the regex healthcare check on items in needs_review_oversight.json.

    Items that pass the HC keyword check get auto-promoted into actions.json.
    Anything else stays in the review queue for AI review.
    """
    review = load_oversight_review()
    pending = [a for a in review.get("items", [])
               if not a.get("ai_decision") and not a.get("audit_decision")]

    if not pending:
        print("audit-oversight: no un-audited items in needs_review_oversight.json")
        if os.path.exists(OVERSIGHT_SUMMARY_FILE):
            os.remove(OVERSIGHT_SUMMARY_FILE)
        return 0

    print(f"audit-oversight: {len(pending)} pending items to check")

    actions = load_json(DATA_FILE, {"metadata": {"version": "1.0", "last_updated": ""},
                                     "actions": []})

    # Mixed-content sources (CMS, GAO, Congress, MedPAC, MACPAC) publish
    # both fraud-relevant and non-fraud content. For these we use a
    # TWO-TIER gate:
    #   Tier 1: Strong fraud signal in title → auto-promote (no API call)
    #   Tier 2: HC program name but no fraud signal → AI review
    #   Neither → reject outright
    #
    # This makes the pipeline self-sustaining: ~80% of items get decided
    # by regex alone (auto-promote or reject), and only the genuinely
    # ambiguous ~20% go to Claude for a binary yes/no.
    MIXED_CONTENT_AGENCIES = {'CMS', 'GAO', 'Congress', 'MedPAC', 'MACPAC'}
    # Commentary/messaging blocklist. These are press statements, op-eds,
    # floor remarks, and "chairman's news" pieces that use the word "fraud"
    # but aren't actions — they're political messaging about existing
    # policy. Auto-reject before the fraud-signal check so "Working Families
    # Tax Cuts Fight Medicaid Fraud" (Crapo op-ed) doesn't slip through.
    # Only paths that are unambiguously political messaging. Avoid /blog/
    # and /newsletter/ — CMS (and others) use those for real action
    # announcements, not commentary.
    COMMENTARY_URL_PATHS = re.compile(
        r"/chairmans?-news/|/ranking-members?-news/|/minority-news/|"
        r"/op-?ed/|/opinion/|/floor-remarks/|/dear-colleague/",
        re.IGNORECASE,
    )
    COMMENTARY_TITLE = re.compile(
        r"^(chairman|ranking\s+member|senator|representative|rep\.|sen\.)\s+\S+\s+"
        r"(statement|op-?ed|opening\s+(statement|remarks)|closing\s+(statement|remarks)|"
        r"floor\s+remarks|speech)\b|"
        r"^(opening|closing)\s+(statement|remarks)\b|"
        r"^op-?ed:\s|"
        r"^my\s+statement\b",
        re.IGNORECASE,
    )
    STRONG_FRAUD_SIGNAL = re.compile(
        r"\b("
        r"fraud|kickback|false\s+claim|qui\s+tam|anti-?kickback|"
        r"improper\s+payment|overpayment|program\s+integrity|"
        r"anti-?fraud|fraud.{0,10}(waste|abuse)|waste.{0,10}abuse|"
        r"moratorium|suspension|corrective\s+action|deferral\s+of\s+funds?|"
        r"enforcement|takedown|strike\s+force|"
        r"whistleblower|criminal\s+referral|"
        r"upcod|unbundl|billing\s+scheme|phantom\s+billing|"
        r"pill\s+mill|drug\s+diversion|"
        r"excluded?\s+provider|revok|debarment"
        r")\b",
        re.IGNORECASE,
    )
    # Minimum HC context for borderline items that go to AI review —
    # items without even a basic HC-program mention get rejected outright
    # since AI review would reject them anyway.
    HC_PROGRAM_MENTION = re.compile(
        r"\b(medicare|medicaid|medi-?cal|chip|tricare|"
        r"affordable\s+care|health\s+care|healthcare|"
        r"hospice|home\s+health|nursing\s+home|dme|"
        r"prescription|pharmacy|opioid)\b",
        re.IGNORECASE,
    )

    auto_promoted = []
    still_pending = []
    for item in pending:
        agency = item.get("agency", "")
        title = item.get("title", "") or ""
        link = item.get("link", "") or ""

        # Commentary blocklist: op-eds, chairman's statements, floor remarks.
        # URL-path match (e.g. /chairmans-news/) is an unambiguous
        # messaging-section signal — auto-reject. Title-only match is
        # softer: "Chairman X Statement" COULD describe a real action,
        # so route to AI review instead of rejecting outright.
        if COMMENTARY_URL_PATHS.search(link):
            still_pending.append(item)
            item["flag_reason"] = "URL in commentary/press-statement section — not an action"
            item["audit_decision"] = "auto_rejected"
            continue
        if COMMENTARY_TITLE.search(title):
            still_pending.append(item)
            item["flag_reason"] = "title looks like a statement/op-ed — needs AI review to confirm action vs messaging"
            continue

        if agency in MIXED_CONTENT_AGENCIES:
            # Tier 1: strong fraud signal → auto-promote
            if STRONG_FRAUD_SIGNAL.search(title):
                auto_promoted.append(item)
                item["audit_decision"] = "auto_approved"
            # Tier 2: HC program mention but no fraud signal → AI review
            elif HC_PROGRAM_MENTION.search(title):
                still_pending.append(item)
                item["flag_reason"] = "HC program mentioned but no fraud signal — needs AI review"
            # Neither → reject outright
            else:
                still_pending.append(item)
                item["flag_reason"] = "no HC fraud signal and no HC program mention — auto-reject"
                item["audit_decision"] = "auto_rejected"
        # Trusted fraud-specific sources (HHS-OIG, Treasury, etc.)
        elif is_oversight_hc_fraud(item):
            auto_promoted.append(item)
            item["audit_decision"] = "auto_approved"
        else:
            still_pending.append(item)
            item["flag_reason"] = "title lacks HC fraud / program integrity signal"

    # Handle auto-rejected items (no HC fraud signal AND no HC program name)
    auto_rejected = [a for a in still_pending if a.get("audit_decision") == "auto_rejected"]
    for item in auto_rejected:
        link = item.get("link", "")
        if link and link not in review["rejected_links"]:
            review["rejected_links"].append(link)

    if auto_promoted:
        for item in auto_promoted:
            for k in ("flagged_at", "flag_reason", "audit_decision"):
                item.pop(k, None)
        actions.setdefault("actions", []).extend(auto_promoted)
        actions["metadata"]["last_updated"] = datetime.now().isoformat()
        save_json(DATA_FILE, actions)

    # Remove promoted + auto-rejected from the review queue.
    # Only items flagged for AI review (Tier 2) remain.
    handled_ids = {a["id"] for a in auto_promoted + auto_rejected}
    review["items"] = [a for a in review["items"] if a.get("id") not in handled_ids]
    save_json(OVERSIGHT_REVIEW_FILE, review)

    ai_pending = len(still_pending) - len(auto_rejected)
    print(f"audit-oversight: {len(auto_promoted)} auto-promoted, "
          f"{len(auto_rejected)} auto-rejected, "
          f"{ai_pending} flagged for AI review")

    _write_oversight_audit_summary(auto_promoted, still_pending)
    return 0


def _call_claude_oversight(client, title: str, link: str, agency: str, item_type: str) -> dict | None:
    """Call Claude Haiku with the oversight classifier prompt."""
    user_msg = f"Title: {title}\nAgency: {agency}\nType: {item_type}\nLink: {link}"
    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=300,
            system=OVERSIGHT_AI_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        if "healthcare_fraud_oversight" not in result or "confidence" not in result:
            return None
        return result
    except Exception as e:
        print(f"    AI call failed: {e}", file=sys.stderr)
        return None


def cmd_ai_review_oversight() -> int:
    """Process items in needs_review_oversight.json with Claude Haiku.

    Same three-tier logic: auto-promote high-confidence yes,
    auto-reject high-confidence no, escalate the rest.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ai-review-oversight: ANTHROPIC_API_KEY not set, skipping")
        return 0

    try:
        import anthropic
    except ImportError:
        print("ai-review-oversight: anthropic package not installed, skipping")
        return 0

    review = load_oversight_review()
    pending = [a for a in review.get("items", []) if "ai_decision" not in a]
    if not pending:
        print("ai-review-oversight: no un-reviewed items in needs_review_oversight.json")
        return 0

    print(f"ai-review-oversight: processing {len(pending)} item(s) with {AI_MODEL}")
    client = anthropic.Anthropic(api_key=api_key)

    actions = load_json(DATA_FILE, {"metadata": {"version": "1.0", "last_updated": ""},
                                     "actions": []})

    promoted = []
    rejected = []
    escalated = []

    for item in pending:
        title = item.get("title", "")
        link = item.get("link", "")
        agency = item.get("agency", "")
        item_type = item.get("type", "")
        print(f"  reviewing: {item['id']}")
        print(f"             {title[:80]}")

        decision = _call_claude_oversight(client, title, link, agency, item_type)
        if decision is None:
            print("             SKIP (API error, left in queue)")
            continue

        is_oversight = bool(decision.get("healthcare_fraud_oversight"))
        conf = int(decision.get("confidence", 0))
        reason = str(decision.get("reason", ""))[:200]

        item["ai_decision"] = "healthcare_fraud_oversight" if is_oversight else "not_oversight"
        item["ai_confidence"] = conf
        item["ai_reason"] = reason
        item["ai_model"] = AI_MODEL

        if is_oversight and conf >= AUTO_PROMOTE_THRESHOLD:
            clean = {k: v for k, v in item.items()
                     if not k.startswith("ai_")
                     and k not in ("flagged_at", "flag_reason", "audit_decision")}
            actions.setdefault("actions", []).append(clean)
            promoted.append(item)
            print(f"             PROMOTE (confidence={conf}) — {reason[:80]}")
        elif (not is_oversight) and conf >= AUTO_REJECT_THRESHOLD:
            if link and link not in review["rejected_links"]:
                review["rejected_links"].append(link)
            rejected.append(item)
            print(f"             REJECT  (confidence={conf}) — {reason[:80]}")
        else:
            escalated.append(item)
            label = "oversight" if is_oversight else "not oversight"
            print(f"             ESCALATE ({label}, confidence={conf}) — {reason[:80]}")

    handled_ids = {a["id"] for a in promoted + rejected}
    review["items"] = [a for a in review["items"] if a.get("id") not in handled_ids]

    if promoted:
        actions["metadata"]["last_updated"] = datetime.now().isoformat()

    save_json(DATA_FILE, actions)
    save_json(OVERSIGHT_REVIEW_FILE, review)

    print()
    print(f"ai-review-oversight: {len(promoted)} promoted, {len(rejected)} rejected, "
          f"{len(escalated)} escalated")

    _append_oversight_ai_summary(promoted, rejected, escalated)
    return 0


def cmd_oversight_promote(item_id: str) -> int:
    review = load_oversight_review()
    items = review.get("items", [])
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            it = items.pop(i)
            for k in ("ai_decision", "ai_confidence", "ai_reason", "ai_model",
                      "flagged_at", "flag_reason", "audit_decision"):
                it.pop(k, None)
            actions = load_json(DATA_FILE, {"metadata": {"version": "1.0",
                                                          "last_updated": ""},
                                              "actions": []})
            actions.setdefault("actions", []).append(it)
            actions["metadata"]["last_updated"] = datetime.now().isoformat()
            save_json(DATA_FILE, actions)
            save_json(OVERSIGHT_REVIEW_FILE, review)
            print(f"oversight-promote: moved {item_id} to actions.json")
            return 0
    print(f"oversight-promote: no item with id {item_id}", file=sys.stderr)
    return 1


def cmd_oversight_reject(item_id: str) -> int:
    review = load_oversight_review()
    items = review.get("items", [])
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            link = it.get("link", "")
            items.pop(i)
            if link and link not in review["rejected_links"]:
                review["rejected_links"].append(link)
            save_json(OVERSIGHT_REVIEW_FILE, review)
            print(f"oversight-reject: removed {item_id}, link blocked")
            return 0
    print(f"oversight-reject: no item with id {item_id}", file=sys.stderr)
    return 1


def cmd_oversight_list() -> int:
    review = load_oversight_review()
    items = review.get("items", [])
    if not items:
        print("(no items in needs_review_oversight.json)")
        return 0
    for it in items:
        ai = it.get("ai_decision", "")
        ai_str = f" [AI:{ai} c={it.get('ai_confidence', '?')}]" if ai else ""
        print(f"  {it.get('id', '?'):40} {it.get('agency', '?'):10} {it.get('type', '?'):20} {it.get('date', '?'):10}{ai_str}")
        print(f"    {it.get('title', '')[:120]}")
    return 0


def _write_oversight_audit_summary(approved: list, flagged: list) -> None:
    lines = ["# Oversight Audit Summary", ""]
    lines.append(f"_Generated: {datetime.now().isoformat()}_")
    lines.append("")
    if approved:
        lines.append(f"## Auto-promoted ({len(approved)})")
        for a in approved:
            lines.append(f"- **{a.get('title', '')[:120]}** ({a.get('agency', '?')} / {a.get('type', '?')})")
        lines.append("")
    if flagged:
        lines.append(f"## Flagged for AI/human review ({len(flagged)})")
        for a in flagged:
            lines.append(f"- {a.get('title', '')[:120]} ({a.get('agency', '?')} / {a.get('type', '?')})")
        lines.append("")
    with open(OVERSIGHT_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _append_oversight_ai_summary(promoted: list, rejected: list, escalated: list) -> None:
    lines = ["", "---", ""]
    if promoted:
        lines.append(f"### Oversight AI-promoted ({len(promoted)})")
        for a in promoted:
            lines.append(f"- **{a.get('title', '')[:120]}**")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if rejected:
        lines.append(f"### Oversight AI-rejected ({len(rejected)}, link blocked)")
        for a in rejected:
            lines.append(f"- {a.get('title', '')[:120]}")
            lines.append(f"  _confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:150]}_")
        lines.append("")
    if escalated:
        lines.append(f"### Oversight AI-escalated ({len(escalated)}, needs your call)")
        for a in escalated:
            lines.append(f"- **{a.get('title', '')}**")
            link = a.get("link", "")
            if link:
                lines.append(f"  [{link}]({link})")
            lines.append(f"  _Claude: {a.get('ai_decision', '?')} @ confidence {a.get('ai_confidence')} — {a.get('ai_reason', '')[:200]}_")
            lines.append(f"  `python audit_new_items.py oversight-promote {a['id']}`  or  `oversight-reject {a['id']}`")
            lines.append("")
    existing = ""
    if os.path.exists(OVERSIGHT_SUMMARY_FILE):
        with open(OVERSIGHT_SUMMARY_FILE, encoding="utf-8") as f:
            existing = f.read()
    with open(OVERSIGHT_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(existing + "\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Audit newly-scraped items before publish.")
    parser.add_argument(
        "cmd",
        nargs="?",
        default="audit",
        choices=[
            # Enforcement commands
            "audit", "list", "promote", "reject", "ai-review", "topic-check",
            # Media commands
            "audit-media", "list-media", "media-promote", "media-reject", "ai-review-media",
            # Oversight commands
            "audit-oversight", "list-oversight", "oversight-promote", "oversight-reject",
            "ai-review-oversight",
        ],
    )
    parser.add_argument("item_id", nargs="?")
    args = parser.parse_args()

    if args.cmd == "audit":
        return cmd_audit()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "topic-check":
        return cmd_topic_check()
    if args.cmd == "ai-review":
        return cmd_ai_review()
    if args.cmd in ("promote", "reject"):
        if not args.item_id:
            print(f"{args.cmd} requires an item ID", file=sys.stderr)
            return 2
        return cmd_promote(args.item_id) if args.cmd == "promote" else cmd_reject(args.item_id)

    # Media tab parallel commands
    if args.cmd == "audit-media":
        return cmd_audit_media()
    if args.cmd == "list-media":
        return cmd_media_list()
    if args.cmd == "ai-review-media":
        return cmd_ai_review_media()
    if args.cmd in ("media-promote", "media-reject"):
        if not args.item_id:
            print(f"{args.cmd} requires an item ID", file=sys.stderr)
            return 2
        return cmd_media_promote(args.item_id) if args.cmd == "media-promote" else cmd_media_reject(args.item_id)

    # Oversight tab parallel commands
    if args.cmd == "audit-oversight":
        return cmd_audit_oversight()
    if args.cmd == "list-oversight":
        return cmd_oversight_list()
    if args.cmd == "ai-review-oversight":
        return cmd_ai_review_oversight()
    if args.cmd in ("oversight-promote", "oversight-reject"):
        if not args.item_id:
            print(f"{args.cmd} requires an item ID", file=sys.stderr)
            return 2
        return cmd_oversight_promote(args.item_id) if args.cmd == "oversight-promote" else cmd_oversight_reject(args.item_id)
    return 1


if __name__ == "__main__":
    sys.exit(main())
