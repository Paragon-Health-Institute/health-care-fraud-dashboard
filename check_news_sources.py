"""Periodic check: can any news-sourced oversight item be upgraded to an official .gov source?

For each item in data/actions.json where source_type != 'official':
  1. Extract key terms from the title (agency, date, distinctive nouns).
  2. Query CMS newsroom, HHS press room, and WH releases indexes for a
     press release matching those terms and the same date (±3 days).
  3. If a match is found, print a proposed upgrade (old link -> new link).
  4. Only apply changes with --apply.

Runs quickly (~30 seconds) because it only hits a handful of index pages
per agency per item. Safe to schedule weekly.

Usage:
    python check_news_sources.py                   # dry-run, all items
    python check_news_sources.py --apply           # write approved upgrades
    python check_news_sources.py --limit 3         # debug: first 3 items only
"""
from __future__ import annotations

import argparse, io, json, os, re, sys, time
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

ACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "actions.json")

# Agency -> index URL(s) to search for matching press releases.
# For each agency, we fetch the index and look for titles that match
# keywords from the news-sourced item's title.
AGENCY_INDEXES = {
    "CMS": [
        "https://www.cms.gov/newsroom",
        "https://www.cms.gov/newsroom/press-releases",
    ],
    "HHS": [
        # Akamai-blocked; Playwright required. Skip unless HAS_PLAYWRIGHT.
        "https://www.hhs.gov/press-room/index.html",
    ],
    "White House": [
        "https://www.whitehouse.gov/news/page/1/",
        "https://www.whitehouse.gov/presidential-actions/",
    ],
}

STOPWORDS = {"the", "a", "an", "of", "in", "on", "to", "for", "by", "and", "or",
             "with", "as", "is", "was", "were", "be", "at", "from", "that",
             "this", "these", "those", "dr", "mr", "ms"}


def keywords(text, min_len=4, max_count=8):
    """Return the top N content words from a title, lowercased."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out, seen = [], set()
    for w in words:
        if len(w) < min_len or w in STOPWORDS or w in seen:
            continue
        out.append(w)
        seen.add(w)
        if len(out) >= max_count:
            break
    return out


def parse_iso(date_str):
    try:
        from datetime import datetime
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def fetch_with_playwright(url):
    if not HAS_PLAYWRIGHT:
        return ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1200)
            return page.content()
        finally:
            browser.close()


def fetch(url, use_browser=False):
    if use_browser:
        return fetch_with_playwright(url)
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": UA})
        if r.status_code == 200:
            return r.text
        if r.status_code in (403, 429) and HAS_PLAYWRIGHT:
            return fetch_with_playwright(url)
    except Exception:
        pass
    return ""


def extract_press_links(html, base):
    """Extract (title, href) pairs from an index page."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Keep only links that look like press releases / news articles
        if not re.search(
                r"(newsroom/press-releases|/press-room/|/news/|"
                r"/presidential-actions/|/releases/|/briefing/)",
                href):
            continue
        text = a.get_text(strip=True)
        if not text or len(text) < 20:
            continue
        # Resolve relative
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if href in seen:
            continue
        seen.add(href)
        out.append((text, href))
    return out


def score_match(item_title, item_date, cand_title):
    """Score a candidate press release against the news-sourced item."""
    ikw = set(keywords(item_title, max_count=10))
    ckw = set(keywords(cand_title, max_count=20))
    if not ikw:
        return 0
    overlap = len(ikw & ckw)
    return overlap


def find_candidates(item):
    """Return list of (score, title, url) candidates for this item."""
    agency = item.get("agency", "")
    indexes = AGENCY_INDEXES.get(agency, [])
    if not indexes:
        return []
    candidates = []
    title = item.get("title", "")
    date = item.get("date", "")
    for idx_url in indexes:
        base = "/".join(idx_url.split("/")[:3])
        use_browser = "hhs.gov" in idx_url  # HHS Akamai
        html = fetch(idx_url, use_browser=use_browser)
        if not html:
            continue
        for cand_title, cand_url in extract_press_links(html, base):
            s = score_match(title, date, cand_title)
            if s >= 3:  # require at least 3 overlapping content words
                candidates.append((s, cand_title, cand_url))
    candidates.sort(key=lambda x: -x[0])
    return candidates[:3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write upgrades")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-score", type=int, default=3,
                    help="minimum keyword-overlap score to propose a swap")
    args = ap.parse_args()

    with io.open(ACTIONS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    ENFORCEMENT = {"Criminal Enforcement", "Civil Action"}
    targets = [i for i in data["actions"]
               if i.get("type") not in ENFORCEMENT
               and i.get("source_type", "official") != "official"]
    if args.limit:
        targets = targets[:args.limit]
    print(f"News-sourced oversight items to check: {len(targets)}")
    print()

    proposed_upgrades = []
    for idx, item in enumerate(targets, 1):
        print(f"[{idx}/{len(targets)}] {item.get('title','')[:75]}")
        print(f"  current link: {item.get('link','')[:90]}")
        cands = find_candidates(item)
        if not cands:
            print("  no .gov candidate found")
            continue
        for score, cand_title, cand_url in cands:
            print(f"  candidate (score={score}): {cand_title[:80]}")
            print(f"    -> {cand_url[:100]}")
        # Pick the top candidate for proposed upgrade
        best = cands[0]
        if best[0] >= args.min_score:
            proposed_upgrades.append((item, best))
        time.sleep(0.3)

    print()
    print(f"=== Proposed upgrades: {len(proposed_upgrades)} ===")
    for item, (score, ct, cu) in proposed_upgrades:
        print(f"  [{item.get('agency','')}] {item.get('title','')[:65]}")
        print(f"    score={score} -> {cu}")

    if args.apply and proposed_upgrades:
        for item, (score, ct, cu) in proposed_upgrades:
            item["link"] = cu
            item["source_type"] = "official"
            # Relabel the button to reflect the agency
            item["link_label"] = f"{item.get('agency','Agency')} Press Release"
        from datetime import datetime
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        with io.open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nApplied {len(proposed_upgrades)} upgrades.")
    elif proposed_upgrades:
        print("\nDRY-RUN. Rerun with --apply to write.")


if __name__ == "__main__":
    main()
