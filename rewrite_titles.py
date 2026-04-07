"""One-shot: rewrite enforcement-tab item titles to match source headlines.

Federal Enforcement tab items (Criminal Enforcement / Civil Action) must
have their `title` field exactly match the headline of the linked official
press release. This script fetches each item's link with Playwright (since
justice.gov is bot-protected), extracts the page title, normalizes it
(strips DOJ breadcrumb prefixes and site-name suffixes), and updates the
JSON.

Usage:
    python rewrite_titles.py            # all enforcement items
    python rewrite_titles.py --dry-run  # show changes without writing

After this runs, the in-pipeline guard in update.py / update_media.py
already preserves source titles verbatim, so this should be a one-time fix.
"""
import argparse
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

DATA_FILE = "data/actions.json"
ENFORCEMENT_TYPES = {"Criminal Enforcement", "Civil Action"}

# Site-specific suffixes to strip from <title> tags.
TITLE_SUFFIXES = [
    " | United States Department of Justice",
    " | DEA.gov",
    " | U.S. Department of the Treasury",
    " | CMS",
    " | HHS.gov",
    " | Office of Inspector General | Government Oversight | U.S. Department of Health and Human Services",
]

# Breadcrumb prefixes that DOJ pages put on the <title>.
TITLE_PREFIXES_RE = re.compile(
    r"^(?:Office of Public Affairs|Central District of California|Eastern District of [A-Za-z ]+|"
    r"Western District of [A-Za-z ]+|Northern District of [A-Za-z ]+|Southern District of [A-Za-z ]+|"
    r"District of [A-Za-z ]+|Middle District of [A-Za-z ]+)\s*\|\s*"
)


def normalize(title: str) -> str:
    """Strip DOJ breadcrumb prefixes / site-name suffixes / extra whitespace."""
    if not title:
        return ""
    t = title.strip()
    # Strip suffixes (longest first).
    for suf in sorted(TITLE_SUFFIXES, key=len, reverse=True):
        if t.endswith(suf):
            t = t[: -len(suf)].rstrip()
    # Strip DOJ breadcrumb prefix.
    t = TITLE_PREFIXES_RE.sub("", t)
    # Collapse whitespace.
    t = re.sub(r"\s+", " ", t).strip()
    # Replace common entity-encoded characters.
    t = t.replace("\u00a0", " ").strip()
    return t


BAD_TITLES = {"Access Denied", "Just a moment...", "Page Not Found", ""}


def _looks_bad(t: str) -> bool:
    if not t:
        return True
    s = t.strip()
    if s in BAD_TITLES:
        return True
    if len(s) < 10:
        return True
    if "Just a moment" in s or "Access Denied" in s:
        return True
    return False


def fetch_title(page, url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Some pages have a bot challenge that resolves automatically.
            page.wait_for_timeout(1200)
            # Prefer h1 on the press release; fall back to <title>.
            h1 = page.query_selector("h1")
            if h1:
                txt = (h1.inner_text() or "").strip()
                if not _looks_bad(txt):
                    return txt
            t = (page.title() or "").strip()
            if not _looks_bad(t):
                return t
        except Exception as e:
            print(f"    attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(1.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="process at most N items (0 = all)")
    args = ap.parse_args()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    enf = [a for a in data["actions"] if a.get("type") in ENFORCEMENT_TYPES]
    if args.limit:
        enf = enf[: args.limit]
    print(f"Processing {len(enf)} enforcement-tab items")

    changed = 0
    failed = 0
    no_change = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        for i, action in enumerate(enf, 1):
            link = action.get("link", "")
            old_title = action.get("title", "")
            if not link:
                continue
            print(f"[{i}/{len(enf)}] {action['id']}", file=sys.stderr)
            raw = fetch_title(page, link)
            if not raw:
                failed += 1
                print(f"    FAILED to fetch", file=sys.stderr)
                continue
            new_title = normalize(raw)
            if not new_title or _looks_bad(new_title):
                failed += 1
                print(f"    REJECTED: {raw}", file=sys.stderr)
                continue
            if new_title == old_title:
                no_change += 1
                continue
            print(f"    OLD: {old_title}", file=sys.stderr)
            print(f"    NEW: {new_title}", file=sys.stderr)
            if not args.dry_run:
                action["title"] = new_title
            changed += 1

        browser.close()

    print()
    print(f"Done. changed={changed} unchanged={no_change} failed={failed}")

    if not args.dry_run and changed:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
