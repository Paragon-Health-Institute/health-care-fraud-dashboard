"""Targeted scan: find items mentioning state-branded Medicaid programs
(TennCare, MassHealth, etc.) in body text that don't currently have the
Medicaid tag.

Dry-run by default. --apply writes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import fetch_detail_page, scrape_page_with_browser, HAS_PLAYWRIGHT

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIONS_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")

# State-branded Medicaid programs. Medi-Cal is already in the allowlist.
STATE_MEDICAID_RE = re.compile(
    r"\btenncare\b|"
    r"\bmasshealth\b|"
    r"\bmainecare\b|"
    r"\bsoonercare\b|"
    r"\bapple\s+health\b|"
    r"\bhusky\s+health\b|"
    r"\bahcccs\b|"
    r"\bhealthy\s+louisiana\b|"
    r"\bhoosier\s+healthwise\b|"
    r"\bhealthy\s+indiana\s+plan\b|"
    r"\bdenali\s+kidcare\b|"
    r"\bbadgercare\b|"          # WI
    r"\bmedi[-\s]cal\b|"        # CA (already covered; included for completeness)
    r"\bnj\s+familycare\b|"
    r"\bminnesotacare\b|"
    r"\bkancare\b|"             # KS
    r"\biowacare\b|"
    r"\bkidcare\b|"             # IL CHIP/Medicaid brand
    r"\bhealth\s+first\s+colorado\b|"
    r"\bdc\s+healthy\s+families\b",
    re.IGNORECASE,
)


def fetch_body(url, session):
    url_l = url.lower()
    if (url_l.endswith('.pdf') or url_l.endswith('/dl') or
            '/media/' in url_l or '/download' in url_l):
        return ""
    try:
        body, _, _, _ = fetch_detail_page(session, url)
        if body and len(body) > 200:
            return body
    except Exception:
        pass
    if HAS_PLAYWRIGHT:
        try:
            soup = scrape_page_with_browser(url)
            if not soup:
                return ""
            main = (soup.find("main") or soup.find("article") or soup.body)
            if not main:
                return ""
            for t in main.find_all(["nav", "footer", "aside", "script", "style"]):
                t.decompose()
            return re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:15000]
        except Exception:
            pass
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    d = json.load(open(ACTIONS_FILE, encoding="utf-8"))
    items = [x for x in d["actions"]
             if "Medicaid" not in (x.get("tags") or [])]
    print(f"Scanning {len(items)} items without Medicaid tag")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    })

    matches = []
    fetch_failures = 0
    for i, x in enumerate(items, 1):
        if i % 25 == 0 or i == 1:
            print(f"... [{i}/{len(items)}] scanning", flush=True)
        url = x.get("link", "") or ""
        if not url:
            continue
        title = x.get("title", "") or ""
        if STATE_MEDICAID_RE.search(title):
            m = STATE_MEDICAID_RE.search(title)
            matches.append((x, f"title:{m.group(0)}"))
            print(f"[{i}] MATCH(title:{m.group(0)}): {title[:70]}")
            continue
        body = fetch_body(url, session)
        if not body:
            fetch_failures += 1
            continue
        m = STATE_MEDICAID_RE.search(body)
        if m:
            matches.append((x, f"body:{m.group(0)}"))
            print(f"[{i}] MATCH(body:{m.group(0)}): {title[:70]}")
        if i % 10 == 0:
            time.sleep(0.3)

    print(f"\n=== Summary ===")
    print(f"Scanned:          {len(items)}")
    print(f"Matches:          {len(matches)}")
    print(f"Fetch failures:   {fetch_failures}")

    if args.apply:
        for x, src in matches:
            t = list(x.get("tags") or [])
            if "Medicaid" not in t:
                t.append("Medicaid")
                x["tags"] = t
        from datetime import datetime
        d["metadata"]["last_updated"] = datetime.now().isoformat()
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {ACTIONS_FILE}: tagged {len(matches)} items")
    else:
        print("\n[DRY-RUN — rerun with --apply to write]")


if __name__ == "__main__":
    main()
