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
    _iso_to_local_date,
    HAS_PLAYWRIGHT,
)
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")


def fetch_body_and_date(url):
    """Fetch DOJ body + canonical date via Playwright.

    Returns (body_text, canonical_date_str_or_None).
    """
    try:
        soup = scrape_page_with_browser(url)
        if not soup:
            return "", None
        # Extract article:published_time meta and convert to local (ET) date
        canonical_date = None
        og = soup.find("meta", attrs={"property": "article:published_time"})
        if og and og.get("content"):
            canonical_date = _iso_to_local_date(og["content"], url)
        if not canonical_date:
            og2 = soup.find("meta", attrs={"property": "article:modified_time"})
            if og2 and og2.get("content"):
                canonical_date = _iso_to_local_date(og2["content"], url)
        # Body
        main = (soup.find("main") or soup.find("article")
                or soup.find("div", class_="field-item") or soup.body)
        if not main:
            return "", canonical_date
        for t in main.find_all(["nav", "footer", "aside", "script", "style"]):
            t.decompose()
        body = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:15000]
        return body, canonical_date
    except Exception as e:
        print(f"    ERROR fetching {url}: {e}", file=sys.stderr)
        return "", None


def _date_correction_allowed(old_date, new_date):
    """Only auto-correct when proposed date is exactly 1 day EARLIER than
    stored — the signature of the UTC-rollover bug. If the drift is
    more or in the other direction, the stored date was likely set
    manually with different intent (event vs publication, etc.) — don't
    override.
    """
    if not old_date or not new_date:
        return False
    try:
        o = datetime.strptime(old_date, "%Y-%m-%d")
        n = datetime.strptime(new_date, "%Y-%m-%d")
    except Exception:
        return False
    return (o - n).days == 1


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

    ra_diffs = []   # (item, old_ra, new_ra)
    date_diffs = [] # (item, old_date, new_date)
    date_skipped_manual = []  # proposed-but-not-applied date changes
    unchanged = 0
    fetch_failures = 0

    for i, x in enumerate(doj_items, 1):
        link = x["link"]
        old_ra = list(x.get("related_agencies") or [])
        old_date = x.get("date", "")
        body, canonical_date = fetch_body_and_date(link)
        if not body:
            fetch_failures += 1
            print(f"[{i}/{len(doj_items)}] FETCH FAIL: {x.get('title','')[:70]}")
            continue
        # related_agencies extraction
        new_ra = extract_investigator_agencies(body)
        ra_changed = (sorted(old_ra) != sorted(new_ra))
        # date correction — only when drift matches UTC-rollover signature
        date_changed = False
        if canonical_date and canonical_date != old_date:
            if _date_correction_allowed(old_date, canonical_date):
                date_diffs.append((x, old_date, canonical_date))
                date_changed = True
            else:
                date_skipped_manual.append((x, old_date, canonical_date))
        if ra_changed:
            ra_diffs.append((x, old_ra, new_ra))
        if ra_changed or date_changed:
            line = f"[{i}/{len(doj_items)}] CHANGE: {x.get('title','')[:60]}"
            print(line)
            if ra_changed:
                print(f"    ra:   {old_ra}  ->  {new_ra}")
            if date_changed:
                print(f"    date: {old_date}  ->  {canonical_date}")
        else:
            unchanged += 1
        if i % 10 == 0:
            time.sleep(0.5)

    print()
    print("=== Summary ===")
    print(f"Processed:             {len(doj_items)}")
    print(f"Unchanged:             {unchanged}")
    print(f"related_agencies diffs:{len(ra_diffs)}")
    print(f"  adds HHS-OIG:        {sum(1 for _, o, n in ra_diffs if 'HHS-OIG' in n and 'HHS-OIG' not in o)}")
    print(f"  removes HHS-OIG:     {sum(1 for _, o, n in ra_diffs if 'HHS-OIG' in o and 'HHS-OIG' not in n)}")
    print(f"Date corrections:      {len(date_diffs)} (UTC-rollover pattern only)")
    print(f"Date drifts skipped:   {len(date_skipped_manual)} (manual fixes protected)")
    print(f"Fetch failures:        {fetch_failures}")

    if date_skipped_manual:
        print("\nDate drifts NOT auto-corrected (likely manual fixes — review):")
        for x, o, n in date_skipped_manual:
            print(f"  stored {o}  proposed {n}  | {x.get('title','')[:65]}")

    if args.apply:
        for x, _, new_ra in ra_diffs:
            x["related_agencies"] = new_ra
        for x, _, new_date in date_diffs:
            x["date"] = new_date
        d["metadata"]["last_updated"] = datetime.now().isoformat()
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE} with {len(ra_diffs)} ra + {len(date_diffs)} date corrections.")
    else:
        print("\n[DRY-RUN — rerun with --apply to write changes]")


if __name__ == "__main__":
    main()
