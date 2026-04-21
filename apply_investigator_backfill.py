"""Apply investigator + date corrections from backfill_dryrun.log.

Parses the existing dry-run output (no re-fetch, fast) and writes the
corrections to data/actions.json. Protects recently-manually-fixed
dates via --date-cutoff.

Usage:
    python apply_investigator_backfill.py --date-cutoff 2026-02-15
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "backfill_dryrun.log")


def parse_log():
    """Parse backfill_dryrun.log into (ra_changes, date_changes).

    Log format from backfill_investigators.py:
      [N/527] CHANGE: <title>
          ra:   ['HHS-OIG']  ->  []
          date: 2026-02-20  ->  2026-02-19
    """
    ra_changes = []    # list of (title_fragment, old_list, new_list)
    date_changes = []  # list of (title_fragment, old_date, new_date)
    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    current_title = None
    for i, line in enumerate(lines):
        m = re.match(r"\[(\d+)/\d+\]\s+CHANGE:\s+(.*)$", line)
        if m:
            current_title = m.group(2).strip()
            continue
        if current_title is None:
            continue
        ra_m = re.match(r"\s+ra:\s+(\[.*?\])\s+->\s+(\[.*?\])\s*$", line)
        if ra_m:
            try:
                old = eval(ra_m.group(1))
                new = eval(ra_m.group(2))
            except Exception:
                continue
            ra_changes.append((current_title, old, new))
            continue
        date_m = re.match(r"\s+date:\s+(\d{4}-\d{2}-\d{2})\s+->\s+(\d{4}-\d{2}-\d{2})\s*$", line)
        if date_m:
            date_changes.append((current_title, date_m.group(1), date_m.group(2)))
    return ra_changes, date_changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-cutoff", default="",
                    help="Skip date corrections on items with stored date "
                         ">= this YYYY-MM-DD (to protect manually-fixed dates)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would apply without writing")
    args = ap.parse_args()

    ra_changes, date_changes = parse_log()
    print(f"Parsed from log: {len(ra_changes)} ra changes, "
          f"{len(date_changes)} date changes")

    d = json.load(open(ACTIONS_FILE, encoding="utf-8"))
    # Build title -> item lookup (use truncated prefix since log shows 65 chars)
    by_title_prefix = {}
    for x in d["actions"]:
        key = (x.get("title", "") or "")[:60]
        by_title_prefix.setdefault(key, []).append(x)

    def find_item(title_frag):
        # Log truncates to ~65 chars. Match by first 50 chars.
        key = title_frag[:60]
        # exact match first
        if key in by_title_prefix and len(by_title_prefix[key]) == 1:
            return by_title_prefix[key][0]
        # prefix match fallback
        matches = []
        frag_trimmed = title_frag.rstrip().rstrip("�")[:50]
        for x in d["actions"]:
            if x.get("title", "").startswith(frag_trimmed):
                matches.append(x)
        return matches[0] if len(matches) == 1 else None

    ra_applied = 0
    ra_skipped = 0
    for title, old, new in ra_changes:
        item = find_item(title)
        if not item:
            ra_skipped += 1
            continue
        if not args.dry_run:
            item["related_agencies"] = new

        ra_applied += 1

    date_applied = 0
    date_protected = 0
    date_skipped = 0
    for title, old_date, new_date in date_changes:
        item = find_item(title)
        if not item:
            date_skipped += 1
            continue
        cur_date = item.get("date", "")
        if args.date_cutoff and cur_date >= args.date_cutoff:
            date_protected += 1
            continue
        if cur_date != old_date:
            # User may have already fixed; be conservative
            date_protected += 1
            continue
        if not args.dry_run:
            item["date"] = new_date
        date_applied += 1

    print(f"\nra: {ra_applied} applied, {ra_skipped} unmatched")
    print(f"date: {date_applied} applied, {date_protected} protected (cutoff/mismatch), "
          f"{date_skipped} unmatched")

    if not args.dry_run:
        d["metadata"]["last_updated"] = datetime.now().isoformat()
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE}")
    else:
        print("\n[DRY-RUN — rerun without --dry-run to write]")


if __name__ == "__main__":
    main()
