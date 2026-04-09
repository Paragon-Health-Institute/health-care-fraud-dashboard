"""Weekly landing page monitor for healthcare fraud strategy documents.

Monitors a set of federal agency landing pages for NEW links (PDFs,
fact sheets, reports, strategy documents) that weren't there last time.
Designed to catch the kind of high-value documents that CMS/OIG/GAO
publish on static pages outside their newsrooms — annual reports,
strategic plans, hot-spot analyses, fact sheets, etc.

Runs weekly (not daily — these pages change slowly). Stores the set of
known links in data/_landing_page_state.json and diffs against it.

Usage:
    python monitor_landing_pages.py                    # check for new links
    python monitor_landing_pages.py --init             # first run: save current state
    python monitor_landing_pages.py --add-to-queue     # add new items to needs_review_oversight.json

The --init flag saves the current state without flagging anything as new
(useful for bootstrapping so the first real run doesn't flag everything).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "data", "_landing_page_state.json")
OVERSIGHT_QUEUE = os.path.join(SCRIPT_DIR, "data", "needs_review_oversight.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Pages to monitor. Each entry:
#   url:       the landing page URL
#   agency:    agency label for new items
#   label:     human-readable source label
#   link_re:   regex to filter which links to track (default: PDFs + /newsroom/ + /reports/)
MONITORED_PAGES = [
    {
        "url": "https://www.cms.gov/fraud",
        "agency": "CMS",
        "label": "CMS Anti-Fraud Landing Page",
        "link_re": r"\.(pdf)$|/files/document/|/newsroom/",
    },
    {
        "url": "https://oig.hhs.gov/fraud/",
        "agency": "HHS-OIG",
        "label": "HHS-OIG Fraud Hub",
        "link_re": r"\.(pdf)$|/reports/|/fraud/",
    },
    {
        "url": "https://oig.hhs.gov/about-oig/strategic-plan/",
        "agency": "HHS-OIG",
        "label": "HHS-OIG Strategic Plan",
        "link_re": r"\.(pdf)$|strategic",
    },
    {
        "url": "https://oig.hhs.gov/reports-and-publications/hcfac/",
        "agency": "HHS-OIG",
        "label": "HCFAC Annual Reports Archive",
        "link_re": r"\.(pdf)$|/reports/|hcfac",
    },
    {
        "url": "https://www.gao.gov/high-risk-list",
        "agency": "GAO",
        "label": "GAO High-Risk List",
        "link_re": r"/products/gao-|/assets/gao-|\.(pdf)$",
    },
    {
        "url": "https://oig.hhs.gov/compliance/",
        "agency": "HHS-OIG",
        "label": "HHS-OIG Compliance Guidance",
        "link_re": r"\.(pdf)$|/compliance/|icpg|gcpg",
    },
]

# Pre-filter: only track links whose anchor text mentions fraud/HC concepts
HC_SIGNAL = re.compile(
    r"fraud|integrity|improper|waste|abuse|medicare|medicaid|"
    r"hospice|dme|crush|fdoc|wiser|radv|strike force|"
    r"health care|healthcare|annual report|strategic plan|"
    r"high.risk|hot.spot|dual enrollment|skin substitute|"
    r"compliance program|icpg|gcpg",
    re.IGNORECASE,
)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"pages": {}, "last_checked": ""}


def save_state(state: dict) -> None:
    state["last_checked"] = datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def fetch_page(url: str) -> BeautifulSoup:
    """Fetch a page with Playwright (handles JS-rendered content)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()
    return BeautifulSoup(html, "lxml")


def extract_links(soup: BeautifulSoup, base_url: str, link_re: str) -> dict[str, str]:
    """Extract {url: anchor_text} for links matching the pattern."""
    pattern = re.compile(link_re, re.IGNORECASE) if link_re else None
    links = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        # Resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urlparse
            p = urlparse(base_url)
            href = f"{p.scheme}://{p.netloc}{href}"
        # Apply link pattern filter
        if pattern and not pattern.search(href):
            continue
        # Apply HC signal filter on anchor text
        if not HC_SIGNAL.search(text):
            continue
        links[href] = text
    return links


def main():
    ap = argparse.ArgumentParser(description="Monitor landing pages for new fraud documents")
    ap.add_argument("--init", action="store_true",
                    help="Save current state without flagging anything as new")
    ap.add_argument("--add-to-queue", action="store_true",
                    help="Add new items to needs_review_oversight.json")
    args = ap.parse_args()

    if not HAS_PLAYWRIGHT:
        print("ERROR: Playwright required. pip install playwright && playwright install chromium")
        sys.exit(2)

    state = load_state()
    all_new = []

    for page_def in MONITORED_PAGES:
        url = page_def["url"]
        agency = page_def["agency"]
        label = page_def["label"]
        link_re = page_def.get("link_re", "")

        print(f"\n{'='*60}")
        print(f"Checking: {label}")
        print(f"URL: {url}")

        try:
            soup = fetch_page(url)
        except Exception as e:
            print(f"  ERROR fetching: {e}")
            continue

        current_links = extract_links(soup, url, link_re)
        print(f"  Found {len(current_links)} tracked links")

        # Compare to previous state
        prev_links = set(state.get("pages", {}).get(url, {}).get("links", []))
        new_links = {href: text for href, text in current_links.items()
                     if href not in prev_links}

        if args.init:
            print(f"  INIT: saving {len(current_links)} links as baseline")
        elif new_links:
            print(f"  NEW: {len(new_links)} link(s) since last check:")
            for href, text in new_links.items():
                print(f"    {text[:60]}")
                print(f"      {href[:80]}")
                all_new.append({
                    "title": text,
                    "link": href,
                    "agency": agency,
                    "source_label": label,
                })
        else:
            print(f"  No new links since last check")

        # Update state
        state.setdefault("pages", {})[url] = {
            "links": list(current_links.keys()),
            "count": len(current_links),
            "last_checked": datetime.now().isoformat(),
        }

    save_state(state)

    if all_new and args.add_to_queue and not args.init:
        # Add new items to the oversight review queue
        with open(OVERSIGHT_QUEUE, encoding="utf-8") as f:
            queue = json.load(f)

        existing_links = set(a.get("link", "") for a in queue.get("items", []))
        added = 0
        for item in all_new:
            if item["link"] in existing_links:
                continue
            h = abs(int(hashlib.md5(item["link"].encode()).hexdigest()[:8], 16))
            date_str = datetime.now().strftime("%Y-%m-%d")
            queue["items"].append({
                "id": f"{item['agency'].lower()}-{date_str}-{h}",
                "date": date_str,
                "agency": item["agency"],
                "type": "Report",
                "title": item["title"],
                "amount": None,
                "amount_numeric": 0,
                "officials": [],
                "link": item["link"],
                "link_label": item["source_label"],
                "social_posts": [],
                "tags": [],
                "entities": [],
                "state": None,
                "source_type": "official",
                "auto_fetched": True,
                "related_agencies": [],
            })
            added += 1

        with open(OVERSIGHT_QUEUE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        print(f"\nAdded {added} new item(s) to oversight review queue")

    print(f"\nTotal new links found: {len(all_new)}")
    if all_new and not args.add_to_queue and not args.init:
        print("Run with --add-to-queue to push to the oversight pipeline")


if __name__ == "__main__":
    main()
