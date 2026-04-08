"""One-shot: re-extract tags for existing items in actions.json / media.json
using the anchored AI tag extractor (tag_extractor.py).

For each item:
  1. Fetch the linked source page with Playwright (handles bot-protected sites).
  2. Extract the page's main text content + h1.
  3. Pass title + body to tag_extractor.extract_tags_with_evidence().
  4. Compare new tags to existing tags. Print a diff.
  5. Optionally apply the change (only if --apply is passed).

Usage:
    python retag_existing.py                       # all items in both files, dry-run
    python retag_existing.py --apply               # actually update files
    python retag_existing.py --file actions        # only actions.json
    python retag_existing.py --file media          # only media.json
    python retag_existing.py --limit 20            # process at most N items
    python retag_existing.py --since 2026-03-01    # only items dated >= this
    python retag_existing.py --type Audit          # only items of this type
    python retag_existing.py --agency HHS-OIG      # only items from this agency
    python retag_existing.py --sleep 0.5           # delay between items (rate limit)

The script preserves order, only writes changed items, and never touches
items where tag extraction failed (kept as-is).
"""
from __future__ import annotations

import argparse
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

from tag_allowlist import filter_tags as _filter_tags
from tag_extractor import extract_tags_with_evidence, make_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")
MEDIA_FILE = os.path.join(SCRIPT_DIR, "data", "media.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch_page_text(page, url: str) -> tuple[str, str]:
    """Return (h1, body_text). Empty strings on failure."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        html = page.content()
    except Exception as e:
        print(f"    fetch failed: {e}", file=sys.stderr)
        return "", ""
    soup = BeautifulSoup(html, "lxml")
    h1_el = soup.find("h1")
    h1 = h1_el.get_text(strip=True) if h1_el else ""
    main = (soup.find("main") or soup.find("article")
            or soup.find("div", class_="field-item")
            or soup.find("div", class_="entry-content")
            or soup.body)
    body_text = ""
    if main:
        for tag in main.find_all(["nav", "footer", "aside", "script", "style"]):
            tag.decompose()
        body_text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    return h1, body_text[:12000]


def process_items(items: list, label: str, page, ai_client, args) -> int:
    """Returns count of items where tags changed (or would have)."""
    if args.since:
        items = [it for it in items if (it.get("date") or "") >= args.since]
    if args.type:
        items = [it for it in items if it.get("type") == args.type]
    if args.agency:
        items = [it for it in items if it.get("agency") == args.agency]
    if args.limit:
        items = items[: args.limit]

    print(f"\n=== {label}: {len(items)} item(s) ===\n")
    changed_count = 0
    failed_count = 0

    for i, item in enumerate(items, 1):
        link = item.get("link", "")
        title = item.get("title", "")
        old_tags = list(item.get("tags", []))
        if not link or not title:
            continue
        print(f"[{i}/{len(items)}] {item.get('id', '?')[:50]}")
        print(f"        title: {title[:90]}")
        print(f"        old:   {old_tags}")

        h1, body = fetch_page_text(page, link)
        if not body:
            print(f"        SKIP — could not fetch source page")
            failed_count += 1
            continue

        # Use h1 as title if available (more reliable than the JSON title field)
        effective_title = h1 if h1 else title
        try:
            new_tags = extract_tags_with_evidence(ai_client, effective_title, body, debug=False)
        except Exception as e:
            print(f"        SKIP — extractor error: {e}")
            failed_count += 1
            continue
        new_tags = _filter_tags(new_tags)

        if set(new_tags) == set(old_tags):
            print(f"        no change")
        else:
            added = sorted(set(new_tags) - set(old_tags))
            removed = sorted(set(old_tags) - set(new_tags))
            change_str = []
            if added:
                change_str.append(f"+{added}")
            if removed:
                change_str.append(f"-{removed}")
            print(f"        new:   {new_tags}  ({' '.join(change_str)})")
            if args.apply:
                item["tags"] = new_tags
            changed_count += 1

        if args.sleep:
            time.sleep(args.sleep)

    print(f"\n{label}: {changed_count} changed, {failed_count} failed")
    return changed_count


def main():
    ap = argparse.ArgumentParser(description="Re-extract tags for existing items")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write the changes (default: dry-run)")
    ap.add_argument("--file", choices=["actions", "media", "both"], default="both",
                    help="Which file(s) to process")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since", help="Only items dated >= YYYY-MM-DD")
    ap.add_argument("--type", help="Only items with this type field")
    ap.add_argument("--agency", help="Only items from this agency")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="Seconds to sleep between items")
    args = ap.parse_args()

    if not HAS_PLAYWRIGHT:
        print("ERROR: Playwright is required. pip install playwright && playwright install chromium")
        sys.exit(2)

    ai_client = make_client()
    if ai_client is None:
        print("ERROR: ANTHROPIC_API_KEY not set or anthropic package missing")
        sys.exit(2)

    print(f"{'APPLY' if args.apply else 'DRY-RUN'} mode")
    print(f"AI client: enabled")
    print()

    actions_data = None
    media_data = None
    if args.file in ("actions", "both"):
        with open(ACTIONS_FILE, encoding="utf-8") as f:
            actions_data = json.load(f)
    if args.file in ("media", "both"):
        with open(MEDIA_FILE, encoding="utf-8") as f:
            media_data = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        total_changed = 0
        if actions_data is not None:
            total_changed += process_items(
                actions_data.get("actions", []), "actions.json", page, ai_client, args)
        if media_data is not None:
            total_changed += process_items(
                media_data.get("stories", []), "media.json", page, ai_client, args)

        browser.close()

    if args.apply and total_changed > 0:
        if actions_data is not None:
            with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(actions_data, f, indent=2, ensure_ascii=False)
            print(f"\nWrote {ACTIONS_FILE}")
        if media_data is not None:
            with open(MEDIA_FILE, "w", encoding="utf-8") as f:
                json.dump(media_data, f, indent=2, ensure_ascii=False)
            print(f"Wrote {MEDIA_FILE}")
    elif total_changed > 0:
        print(f"\nDRY-RUN: {total_changed} item(s) would have changed. Re-run with --apply to write.")
    else:
        print("\nNo changes.")


if __name__ == "__main__":
    main()
