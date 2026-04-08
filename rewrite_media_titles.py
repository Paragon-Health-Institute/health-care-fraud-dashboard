"""One-shot: rewrite media.json titles to match source headlines verbatim.

Parallel to rewrite_titles.py (which handles the enforcement tab). Walks
every story in data/media.json, fetches its linked URL with Playwright,
extracts the canonical <h1> / <meta og:title>, normalizes it (strips
site suffixes), and shows a diff.

Titles that successfully fetch get a proposed rewrite. Paywalled sites
(WSJ, NYT, Bloomberg) typically fail — those are listed separately so
the operator can supply the real headline via WebSearch.

Usage:
    python rewrite_media_titles.py                 # dry-run
    python rewrite_media_titles.py --apply         # actually write
    python rewrite_media_titles.py --only wsj      # filter by host substring
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_FILE = os.path.join(SCRIPT_DIR, "data", "media.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Site-specific suffixes to strip from <title> tags.
TITLE_SUFFIXES = [
    " | Reuters",
    " | CNN Business",
    " - CBS News",
    " | CBS News",
    " | Fox News",
    " - The Washington Post",
    " - The New York Times",
    " - WSJ",
    " | Bloomberg",
    " | The Guardian",
    " | NPR",
    " | ProPublica",
    " | KFF Health News",
    " | STAT",
    " | KARE11.com",
    " | WSMV 4",
    " | RealClearInvestigations",
    " | California Globe",
    " | New York Post",
]
BAD_TITLES = {"Access Denied", "Just a moment...", "Page Not Found", "", "NYTimes.com"}


def normalize(raw: str) -> str:
    if not raw:
        return ""
    t = raw.strip()
    for suf in sorted(TITLE_SUFFIXES, key=len, reverse=True):
        if t.endswith(suf):
            t = t[: -len(suf)].rstrip()
    # Some sites put the outlet as a prefix
    for prefix in ["The New York Times - ", "WSJ - ", "CNN - ", "Reuters - "]:
        if t.startswith(prefix):
            t = t[len(prefix):]
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("\u00a0", " ")
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "—")
    return t


def looks_bad(t: str) -> bool:
    if not t:
        return True
    s = t.strip()
    if s in BAD_TITLES:
        return True
    if len(s) < 10:
        return True
    for bad in ("Just a moment", "Access Denied", "Page Not Found",
                "403 Forbidden", "Subscribe", "Sign In", "You have been blocked"):
        if bad in s:
            return True
    return False


def fetch_title(page, url: str) -> tuple[str, str]:
    """Returns (raw_title, source_tag). source_tag is 'og'/'h1'/'title'/'fail'."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        html = page.content()
    except Exception as e:
        return f"ERROR: {e}", "fail"
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        cand = normalize(og["content"])
        if not looks_bad(cand):
            return cand, "og"
    h1 = soup.find("h1")
    if h1:
        cand = normalize(h1.get_text(strip=True))
        if not looks_bad(cand):
            return cand, "h1"
    t = soup.find("title")
    if t:
        cand = normalize(t.get_text(strip=True))
        if not looks_bad(cand):
            return cand, "title"
    return "COULD NOT EXTRACT", "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="Only process URLs containing this substring")
    args = ap.parse_args()

    if not HAS_PLAYWRIGHT:
        print("ERROR: playwright required")
        sys.exit(2)

    with open(MEDIA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    stories = data.get("stories", [])

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for i, s in enumerate(stories, 1):
            link = s.get("link", "")
            old = s.get("title", "")
            if args.only and args.only not in link:
                continue
            print(f"[{i}/{len(stories)}] {s['id'][:50]}")
            print(f"  URL: {link}")
            print(f"  OLD: {old}")
            raw, src = fetch_title(page, link)
            print(f"  NEW ({src}): {raw[:120]}")
            rows.append({
                "id": s["id"],
                "old": old,
                "new": raw,
                "source": src,
                "link": link,
            })
            print()
        browser.close()

    # Diff table
    print("\n===== SUMMARY =====\n")
    changed = [r for r in rows if r["source"] != "fail" and r["new"] != r["old"]]
    unchanged = [r for r in rows if r["source"] != "fail" and r["new"] == r["old"]]
    failed = [r for r in rows if r["source"] == "fail"]
    print(f"{len(changed)} to change, {len(unchanged)} already correct, {len(failed)} failed (paywalled/blocked)")
    if failed:
        print("\n----- FAILED (need manual/WebSearch recovery) -----")
        for r in failed:
            print(f"  {r['id']}")
            print(f"    {r['link']}")
            print(f"    current: {r['old']}")

    # Write a machine-readable proposal file for the apply pass
    proposal_path = os.path.join(SCRIPT_DIR, "data", "_media_title_proposal.json")
    with open(proposal_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"\nWrote proposal to {proposal_path}")

    if args.apply:
        # Apply only successful rewrites (failed ones untouched)
        by_id = {r["id"]: r for r in rows}
        applied = 0
        for s in stories:
            r = by_id.get(s["id"])
            if not r or r["source"] == "fail":
                continue
            if r["new"] == s["title"]:
                continue
            s["title"] = r["new"]
            applied += 1
        data["stories"] = stories
        with open(MEDIA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nAPPLIED {applied} title rewrites to {MEDIA_FILE}")
    else:
        print(f"\nDRY-RUN: re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
