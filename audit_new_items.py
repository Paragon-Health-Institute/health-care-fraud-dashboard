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


# ---------------------------------------------------------------------------
# Non-fraud crime demote list. Items matching these patterns get sent to AI
# review even when the HC keyword check passes — because the title is about a
# different category of crime that just happens to involve a doctor, hospital,
# pharmacy, or other healthcare-adjacent entity.
#
# Examples this catches:
#   - "Pediatrician Sentenced for Exchanging Prescriptions for Sex Acts"
#     (HC keyword "pediatrician" but case is sexual misconduct, not billing fraud)
#   - "Doctor Sentenced for Drug Trafficking Conspiracy"
#     (HC keyword "doctor" but case is street drug distribution, not Medicare fraud)
#   - "Hospital CEO Charged with Murder-for-Hire Plot"
#     (HC keyword "hospital" but case is violent crime)
#
# These items still go to AI review (not auto-rejected) so a borderline case
# with both a non-fraud crime and a real billing component can still get
# promoted by the AI.
# ---------------------------------------------------------------------------
NON_FRAUD_CRIME_PATTERNS = re.compile(
    # Note: each alternation must end at a word boundary on its own. Patterns
    # that match a partial word (e.g. "kidnap" in "kidnapping") use \w* to
    # consume the rest of the word so the regex engine reaches a true \b.
    r"\b("
    # Sex crimes / abuse
    r"sex\s+acts?|sexual\s+(abuse|assault|misconduct|exploitation|contact)|"
    r"lewd|indecent|child\s+(porn|exploit\w*|sex|abuse)|sextortion|"
    # Violence
    r"murder|homicide|manslaughter|kidnap\w*|abduction|"
    r"murder.?for.?hire|attempted?\s+murder|"
    r"shooting|shot\s+(to|and)|stabbed|stabbing|arson|"
    r"violent\s+crime|aggravated\s+assault|armed\s+robbery|"
    # Trafficking (people / drugs as commodity, not billing schemes)
    r"human\s+traffick\w*|sex\s+traffick\w*|forced\s+labor|"
    r"drug\s+traffick\w*|narcotic\s+traffick\w*|"
    r"smuggl\w*\s+(?:drugs?|narcotics?|cocaine|heroin|fentanyl|persons|child|migrant|alien)|"
    # Immigration & identity
    r"illegal\s+(?:re)?entry|illegal\s+alien|unaccompanied\s+(?:alien|minor)\s+child|"
    r"passport\s+fraud|visa\s+fraud|naturali[sz]ation\s+fraud|"
    r"citizenship\s+fraud|alien\s+smuggl\w*|"
    # Other federal benefit programs (not healthcare)
    r"snap\s+(fraud|benefit)|food\s+stamp|"
    r"social\s+security\s+(?:number|fraud|benefit)|ssn\s+fraud|"
    r"unemployment\s+(?:insurance\s+)?(?:fraud|benefit)|"
    r"housing\s+(?:stabilization|assistance|voucher)\s+fraud|hud\s+fraud|"
    r"child\s+care\s+(?:fraud|program)|child\s+daycare\s+fraud|"
    r"ppp\s+(?:loan\s+)?fraud|paycheck\s+protection|covid\s+relief\s+fraud|"
    r"economic\s+injury\s+disaster|eidl\s+fraud|"
    # Tax (unless explicitly tied to a healthcare crime)
    r"tax\s+evasion(?!.*health)|tax\s+fraud(?!.*health|.*medic|.*pharm)|"
    # Bank / mortgage (unless healthcare-tied)
    r"bank\s+fraud(?!.*health|.*medic|.*pharm|.*pat[iy]ent)|"
    r"mortgage\s+fraud(?!.*health|.*medic)|real\s+estate\s+fraud(?!.*health|.*medic)|"
    # Defense / non-HC contracting
    r"defense\s+contract(?:or|ing)|small\s+business\s+(?:government\s+)?contract|"
    # Cybercrime that's not HIPAA / EHR
    r"ransomware(?!.*hospital|.*medic|.*health)|"
    # Roundup / non-actionable bulletin posts
    r"icymi|highlights?\s+(?:a\s+)?(?:dozen|recent)|"
    r"government\s+shutdown(?!.*medicaid)|"
    r"new\s+(?:federal\s+)?prosecutor\s+(targets|named|appointed)|"
    r"u\.s\.\s+attorney\s+(?:announces|highlights)\s+(?:new|appointment|hire)|"
    # Generic / vague titles
    r"woman\s+sentenced\s+to\s+\d+\s+months\s+in\s+prison\s*$|"
    r"man\s+sentenced\s+to\s+\d+\s+months\s+in\s+prison\s*$"
    r")\b",
    re.IGNORECASE,
)


# Strong healthcare fraud phrases. If a title contains any of these, the
# demote list does NOT apply — the case is unambiguously a healthcare fraud
# matter that may also include side charges (tax, bank, unemployment, etc.).
STRONG_HC_FRAUD = re.compile(
    r"\b("
    # "Health Care Fraud" / "Healthcare Fraud" — direct phrase
    r"health\s*care\s+fraud|healthcare\s+fraud|"
    # "Health Care, ... Fraud" / "Health Care and Tax Fraud" — multi-charge headlines
    r"health\s*care[,\s]+(?:and\s+)?[\w\s]{0,20}\s+(?:fraud|schemes?)|"
    r"healthcare[,\s]+(?:and\s+)?[\w\s]{0,20}\s+(?:fraud|schemes?)|"
    # Programs
    r"medicare\s+(?:fraud|advantage)|medicaid\s+fraud|tricare\s+fraud|medi-?cal\s+fraud|"
    r"medical\s+(?:fraud|billing|claims)|"
    r"pharmacy\s+(?:fraud|kickback)|prescription\s+(?:fraud|drug\s+fraud)|"
    # Statutes
    r"false\s+claims\s+act|qui\s+tam|"
    r"anti.?kickback\s+statute|stark\s+law|stark\s+violation|"
    # Categories
    r"drug\s+diversion|"
    r"adult\s+day\s+care|"  # adult day care is on the allowlist; never demote
    r"prenatal\s+care|home\s+health|hospice\s+fraud|"
    r"nursing\s+home\s+fraud|skilled\s+nursing|long.term\s+care|"
    r"dme\s+fraud|durable\s+medical|"
    r"telehealth\s+fraud|telemedicine\s+fraud|"
    r"genetic\s+test|wound\s+care\s+fraud|behavioral\s+health\s+fraud|"
    r"opioid\s+(?:billing|prescribing)\s+(?:fraud|scheme)|pill\s+mill"
    r")\b",
    re.IGNORECASE,
)


def is_non_fraud_crime(item: dict) -> bool:
    """True if the title looks like a non-fraud crime that just happens to
    involve a healthcare-adjacent person/entity. These items get demoted to
    AI review even if the HC keyword check passes.

    Short-circuited by STRONG_HC_FRAUD: if the title explicitly mentions
    healthcare fraud / Medicare fraud / FCA / Stark Law / etc., we trust
    that the case is a real HC matter even if a side charge is mentioned.
    """
    title = item.get("title", "") or ""
    if STRONG_HC_FRAUD.search(title):
        return False
    return bool(NON_FRAUD_CRIME_PATTERNS.search(title))


def is_obviously_healthcare(item: dict) -> bool:
    """True if the item title or link slug clearly references healthcare AND
    does not match a non-fraud crime pattern. Items matching the demote list
    are sent to AI review regardless of HC keyword density.
    """
    if is_non_fraud_crime(item):
        return False
    title = item.get("title", "") or ""
    link = item.get("link", "") or ""
    text = f"{title} {link}"
    return bool(HC_KEYWORDS.search(text) or HC_ENTITIES.search(text))


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
        # Distinguish "no HC keyword" from "HC keyword but non-fraud crime"
        if is_non_fraud_crime(item):
            item["flag_reason"] = "title matches non-fraud crime pattern"
        else:
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


def cmd_promote(item_id: str) -> int:
    """Move an item from needs_review.json back to actions.json."""
    review = load_review()
    item = next((a for a in review["items"] if a.get("id") == item_id), None)
    if not item:
        print(f"promote: no item with id {item_id!r} in {REVIEW_FILE}", file=sys.stderr)
        return 1

    # Strip review-only metadata before re-adding
    item.pop("flagged_at", None)
    item.pop("flag_reason", None)
    item.pop("ai_decision", None)
    item.pop("ai_confidence", None)
    item.pop("ai_reason", None)

    data = load_json(DATA_FILE, {"actions": []})
    data.setdefault("actions", []).append(item)
    save_json(DATA_FILE, data)

    review["items"] = [a for a in review["items"] if a.get("id") != item_id]
    save_json(REVIEW_FILE, review)

    print(f"promoted {item_id} -> {os.path.basename(DATA_FILE)}")
    print(f"  title: {item.get('title', '')[:80]}")
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
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Audit newly-scraped items before publish.")
    parser.add_argument(
        "cmd",
        nargs="?",
        default="audit",
        choices=["audit", "list", "promote", "reject", "ai-review"],
    )
    parser.add_argument("item_id", nargs="?")
    args = parser.parse_args()

    if args.cmd == "audit":
        return cmd_audit()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "ai-review":
        return cmd_ai_review()
    if args.cmd in ("promote", "reject"):
        if not args.item_id:
            print(f"{args.cmd} requires an item ID", file=sys.stderr)
            return 2
        return cmd_promote(args.item_id) if args.cmd == "promote" else cmd_reject(args.item_id)
    return 1


if __name__ == "__main__":
    sys.exit(main())
