"""One-shot backfill: re-extract related_agencies from DOJ body text.

Historically, every DOJ item got related_agencies=['HHS-OIG'] as a
default. This backfill re-fetches each DOJ item's body via Playwright
and applies extract_investigator_agencies() to determine whether HHS-OIG
was actually named as investigator. Items with no literal credit become
related_agencies=[].

Usage:
    python backfill_investigators.py                  # dry-run diff report
    python backfill_investigators.py --apply          # write corrections
    python backfill_investigators.py --limit 20       # test subset

Requires Playwright (DOJ bot-blocks plain requests).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import (
    extract_investigator_agencies,
    scrape_page_with_browser,
    HAS_PLAYWRIGHT,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")


def fetch_body(url):
    """Fetch DOJ body via Playwright. Returns text or empty string."""
    try:
        soup = scrape_page_with_browser(url)
        if not soup:
            return ""
        main = (soup.find("main") or soup.find("article")
                or soup.find("div", class_="field-item") or soup.body)
        if not main:
            return ""
        for t in main.find_all(["nav", "footer", "aside", "script", "style"]):
            t.decompose()
        return re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:15000]
    except Exception as e:
        print(f"    ERROR fetching {url}: {e}", file=sys.stderr)
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write corrections. Default: dry-run diff report.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process only N items (for testing).")
    args = ap.parse_args()

    if not HAS_PLAYWRIGHT:
        print("Playwright not available — cannot fetch DOJ bodies.", file=sys.stderr)
        sys.exit(1)

    d = json.load(open(ACTIONS_FILE, encoding="utf-8"))
    # Target: DOJ items with justice.gov links (we can actually re-fetch)
    doj_items = [
        x for x in d["actions"]
        if x.get("agency") == "DOJ" and "justice.gov" in x.get("link", "")
    ]
    if args.limit:
        doj_items = doj_items[: args.limit]

    print(f"Backfilling investigator agencies for {len(doj_items)} DOJ items")
    print(f"  (apply={args.apply})")
    print()

    diffs = []  # (item, old_related, new_related)
    unchanged = 0
    fetch_failures = 0

    for i, x in enumerate(doj_items, 1):
        link = x["link"]
        old_ra = list(x.get("related_agencies") or [])
        body = fetch_body(link)
        if not body:
            fetch_failures += 1
            print(f"[{i}/{len(doj_items)}] FETCH FAIL: {x.get('title','')[:70]}")
            continue
        new_ra = extract_investigator_agencies(body)
        if sorted(old_ra) != sorted(new_ra):
            diffs.append((x, old_ra, new_ra))
            print(f"[{i}/{len(doj_items)}] CHANGE: {x.get('title','')[:65]}")
            print(f"    old: {old_ra}  ->  new: {new_ra}")
        else:
            unchanged += 1
        # be polite
        if i % 10 == 0:
            time.sleep(0.5)

    print()
    print("=== Summary ===")
    print(f"Processed:          {len(doj_items)}")
    print(f"Unchanged:          {unchanged}")
    print(f"Would change:       {len(diffs)}")
    print(f"Fetch failures:     {fetch_failures}")

    # Break down the changes
    adds_oig = sum(
        1 for _, old, new in diffs if "HHS-OIG" in new and "HHS-OIG" not in old
    )
    removes_oig = sum(
        1 for _, old, new in diffs if "HHS-OIG" in old and "HHS-OIG" not in new
    )
    print(f"  adds HHS-OIG:      {adds_oig}")
    print(f"  removes HHS-OIG:   {removes_oig}")

    if args.apply:
        for x, _, new_ra in diffs:
            x["related_agencies"] = new_ra
        from datetime import datetime
        d["metadata"]["last_updated"] = datetime.now().isoformat()
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE} with {len(diffs)} corrections.")
    else:
        print("\n[DRY-RUN — rerun with --apply to write changes]")


if __name__ == "__main__":
    main()
