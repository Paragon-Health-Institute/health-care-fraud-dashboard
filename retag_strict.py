"""Strict re-tagging pass — literal-match evidence only, no AI inference.

Re-tags every item in data/actions.json using the new strict rules:

  1. Fetch the source page (or re-use existing body text if we have it).
  2. Combine title + body into a search text.
  3. Run the new strict regex patterns from tag_allowlist.auto_tags() —
     these require literal term matches or recognized synonyms, no
     inferential triggers.
  4. Optional second pass: run tag_extractor.extract_tags_with_evidence
     with the new strict prompt. Use the AI only for items where the
     regex found zero tags but the body has substantive text — catches
     synonym cases the regex didn't anticipate.
  5. Produce a diff report: (item_id, title, old_tags, new_tags).
  6. Apply with --apply.

Scope: items on the oversight/enforcement tabs (actions.json). Media items
have their own tagging flow.

Usage:
    python retag_strict.py                        # dry-run
    python retag_strict.py --limit 20             # dry-run subset
    python retag_strict.py --apply                # write changes
    python retag_strict.py --regex-only --apply   # skip AI second pass

The --regex-only mode is deterministic, free, and fast. The default mode
adds an AI second pass for items the regex missed entirely (~50 items
at ~$0.005/item = $0.25/run).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tag_allowlist import auto_tags, filter_tags, ALLOWED_TAGS, strip_boilerplate
from tag_extractor import extract_tags_with_evidence, make_client

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

ACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "actions.json")
REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "tmp_retag_strict_report.json")

# Tag co-apply rules. When a child tag is present, its parent must also
# appear. This preserves program-level tags on items whose body text
# may not explicitly say "Medicare" or "Medicaid" because the fraud
# is framed around a specific program (e.g., a Hospice case is
# inherently about Medicare because Hospice is a Medicare Part A
# benefit — even if the DOJ press release uses "federal health care
# programs" rather than literally saying "Medicare").
#
# Rules are directional: presence of the child implies presence of
# the parent.
_CO_APPLY = {
    # Subprogram -> parent program
    "Medicare Advantage":    "Medicare",
    "Medicaid Managed Care": "Medicaid",
    # Medicare-specific service/product categories. These exist almost
    # exclusively within Medicare (Medicaid doesn't cover hospice the
    # same way, and DMEPOS + Skin Substitutes are Medicare Part B).
    "Hospice":               "Medicare",
    "DME":                   "Medicare",
    "Skin Substitutes":      "Medicare",
}


def fetch_body(page, url: str) -> str:
    """Fetch page body via Playwright. Returns cleaned text.

    Strips "Related Press Releases" / "Related Content" sidebars BEFORE
    text extraction. DOJ pages and many news sites include sidebars
    listing other cases' titles and excerpts — when left in, those
    unrelated titles drive false-positive tag matches (e.g., a pure
    Medicare DME case gets tagged ACA because the sidebar links to an
    ACA-enrollment-fraud case under "Related Content").
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        html = page.content()
    except Exception:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # Check for Akamai access-denied + similar bot-block pages; skip.
    if "Access Denied" in html and len(html) < 2000:
        return ""
    main = (soup.find("main") or soup.find("article")
            or soup.find("div", class_="field-item")
            or soup.find("div", class_="entry-content")
            or soup.body)
    if not main:
        return ""
    for t in main.find_all(["nav", "footer", "aside", "script", "style"]):
        t.decompose()
    # Strip related-content sidebars (DOJ + common news patterns). Class
    # matching is done via regex because DOJ uses long compound class
    # names like "block-views-blockrelated-content--related-content-block".
    related_re = re.compile(
        r"(?:^|\s)(related-content|related-press|related-stor|"
        r"views-blockrelated|more-news|more-press|you-may-also-like|"
        r"further-reading|recommend)",
        re.I,
    )
    for t in main.find_all(class_=related_re):
        t.decompose()
    # Also strip common social/share widgets that can embed unrelated titles
    for t in main.find_all(class_=re.compile(r"social-share|share-links", re.I)):
        t.decompose()
    return re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:12000]


_PROGRAM_SET = {"Medicare", "Medicaid", "Medicare Advantage",
                "Medicaid Managed Care", "TRICARE", "ACA"}


def strict_tags_for(title: str, body: str, client=None,
                    use_ai: bool = True) -> tuple[list[str], str]:
    """Return (tags, source) for an item.

    Two-pass regex with different evidence thresholds:

      Pass A: title — any literal match counts.

      Pass B (full body): a tag is added from the body only if:
        - it's a PROGRAM tag and the keyword appears >=2 times after
          stripping boilerplate ("Centers for Medicare & Medicaid
          Services" doesn't count), OR
        - it's an AREA tag and the keyword appears >=1 time anywhere
          in the body (area tags are more specific, less likely to be
          boilerplate false-positives).

    This suppresses the failure mode where "Medicare" appears once in
    a press release's agency-attribution line but isn't the subject,
    while still capturing programs that are the actual subject (which
    virtually always appear multiple times).

    AI fallback only if both regex passes return zero tags AND the
    client is available AND the body is substantive.
    """
    # Pass A: title
    title_tags = set(filter_tags(auto_tags(title or "")))

    # Pass B: full body with boilerplate neutered. Two layers of stripping:
    #  1. strip_boilerplate() removes known DOJ Strike Force paragraphs,
    #     ACA enforcement-authority sentences, "including Medicare,
    #     Medicaid, and the Affordable Care Act" enumerations. This is
    #     the main Option-C fix — passing mentions in DOJ standard
    #     closing language no longer drive tag additions.
    #  2. "Centers for Medicare & Medicaid Services" (the agency phrase)
    #     gets collapsed to "cms" so literal Medicare/Medicaid mentions
    #     are counted only when they refer to programs, not the agency.
    body_clean = strip_boilerplate(body or "")
    body_clean = re.sub(
        r"centers\s+for\s+medicare\s+(&|and)\s+medicaid\s+services",
        "cms", body_clean, flags=re.I)

    # Count occurrences of each program keyword for threshold gating
    # (use simple word-boundary matches to count evidence strength)
    def count(pat):
        return len(re.findall(pat, body_clean, re.I))

    # Get all body matches, then filter PROGRAM tags by occurrence count
    # 1+ threshold for all tags. The 2+ threshold that used to guard
    # Medicare/Medicaid/TRICARE was belt-and-suspenders protection against
    # boilerplate false positives ("Centers for Medicare & Medicaid Services"
    # + "including Medicare, Medicaid, and the Affordable Care Act"
    # enumerations). We now have three stronger layers of protection:
    #   1. body_clean collapses "Centers for Medicare & Medicaid Services"
    #      to "cms" before counting (line above)
    #   2. strip_boilerplate() removes Strike Force paragraphs, ACA
    #      enforcement-authority sentences, boilerplate enumerations
    #   3. fetch_body() removes "Related Press Releases" / "Related Content"
    #      sidebars that embed unrelated case titles
    # With those in place, a single surviving "Medicare" mention in the
    # body is almost certainly substantive. The 2+ threshold had started
    # false-negatively dropping real Medicare cases (e.g., "Arizona
    # Cardiology $4.75M" where Medicare is only mentioned 1-2x).
    body_tags = set(filter_tags(auto_tags(body_clean)))

    all_tags = title_tags | body_tags

    # Co-apply rules (MA -> Medicare, MCO -> Medicaid)
    for child, parent in _CO_APPLY.items():
        if child in all_tags:
            all_tags.add(parent)

    if all_tags:
        # Preserve a sensible order: title-sourced first, then body-sourced
        ordered = [t for t in auto_tags(title or "") if t in all_tags]
        for t in all_tags:
            if t not in ordered:
                ordered.append(t)
        return filter_tags(ordered), "regex"

    # Regex found nothing; try AI if allowed + client present + body present
    if use_ai and client is not None and body and len(body) > 500:
        try:
            ai_tags = extract_tags_with_evidence(client, title, body)
        except Exception:
            return [], "regex_empty"
        ai_tags = filter_tags(ai_tags)
        # Apply co-apply rules to AI result too
        ai_set = set(ai_tags)
        for child, parent in _CO_APPLY.items():
            if child in ai_set:
                ai_set.add(parent)
        if ai_tags:
            ordered = list(ai_tags)
            for parent in ai_set - set(ai_tags):
                ordered.append(parent)
            return filter_tags(ordered), "ai"
        return [], "ai_empty"
    return [], "regex_empty"


def classify_diff(old: list, new: list) -> str:
    os_, ns_ = set(old), set(new)
    if os_ == ns_:
        return "unchanged"
    added = ns_ - os_
    removed = os_ - ns_
    if added and removed:
        return "changed"
    if added:
        return "added_only"
    if removed:
        return "removed_only"
    return "unchanged"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--regex-only", action="store_true",
                    help="Skip AI fallback (deterministic only)")
    ap.add_argument("--since", help="Only items dated >= YYYY-MM-DD")
    args = ap.parse_args()

    if not HAS_PLAYWRIGHT:
        print("playwright required"); sys.exit(1)

    ai_client = None if args.regex_only else make_client()
    if not args.regex_only and ai_client is None:
        print("NOTE: no ANTHROPIC_API_KEY — running regex-only")

    with io.open(ACTIONS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("actions", [])
    if args.since:
        items = [i for i in items if (i.get("date") or "") >= args.since]
    if args.limit:
        items = items[:args.limit]

    print(f"Processing {len(items)} items "
          f"(mode: {'regex-only' if args.regex_only else 'regex+ai'}, "
          f"{'APPLY' if args.apply else 'DRY-RUN'})")
    print()

    diffs = []
    sources_counter = {"regex": 0, "ai": 0, "regex_empty": 0, "ai_empty": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        for idx, item in enumerate(items, 1):
            link = item.get("link", "")
            title = item.get("title", "")
            old_tags = list(item.get("tags") or [])
            if not link or not title:
                continue
            if idx % 25 == 0:
                print(f"  [{idx}/{len(items)}] sources: {sources_counter}",
                      flush=True)

            body = fetch_body(page, link)
            new_tags, src = strict_tags_for(title, body, ai_client,
                                             use_ai=not args.regex_only)
            sources_counter[src] = sources_counter.get(src, 0) + 1

            verdict = classify_diff(old_tags, new_tags)
            diffs.append({
                "id": item.get("id"),
                "date": item.get("date"),
                "agency": item.get("agency"),
                "type": item.get("type"),
                "title": title,
                "link": link,
                "old_tags": old_tags,
                "new_tags": new_tags,
                "verdict": verdict,
                "source": src,
            })
            if args.apply and verdict != "unchanged":
                item["tags"] = new_tags
            time.sleep(0.1)

        browser.close()

    # Report
    changed = [d for d in diffs if d["verdict"] != "unchanged"]
    print()
    print(f"=== SUMMARY ===")
    print(f"Total processed: {len(diffs)}")
    print(f"  Unchanged: {sum(1 for d in diffs if d['verdict']=='unchanged')}")
    print(f"  Tags added only: {sum(1 for d in diffs if d['verdict']=='added_only')}")
    print(f"  Tags removed only: {sum(1 for d in diffs if d['verdict']=='removed_only')}")
    print(f"  Mixed add+remove: {sum(1 for d in diffs if d['verdict']=='changed')}")
    print(f"Sources: {sources_counter}")
    print()

    # Dump report
    with io.open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"total": len(diffs), "changed": len(changed),
                   "sources": sources_counter, "diffs": diffs},
                  f, indent=2, ensure_ascii=False)
    print(f"Full report: {REPORT_FILE}")

    # Print first 25 changed items as preview
    print()
    print("=== PREVIEW (first 25 changed items) ===")
    for d in changed[:25]:
        print(f"  [{d['verdict']}] {d['id'][:40]}")
        print(f"    title:   {d['title'][:90]}")
        print(f"    OLD:     {d['old_tags']}")
        print(f"    NEW:     {d['new_tags']}  ({d['source']})")

    if args.apply:
        from datetime import datetime
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        with io.open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE}: {len(changed)} items changed")
    else:
        print(f"\nDRY-RUN. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
