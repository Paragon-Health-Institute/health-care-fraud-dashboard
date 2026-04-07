#!/usr/bin/env python3
"""Fetch investigative healthcare-fraud reports from major news outlets.

Phase 1 of the media tab rebuild — borrows the architecture from the
enforcement scraper (``update.py``):

  - Scraped stories go into ``data/needs_review_media.json``, NOT directly
    into ``data/media.json``. A separate audit step (``audit_new_items.py
    audit-media`` + ``ai-review-media``) promotes verified stories into the
    live data file.
  - Playwright fallback for paywalled outlets (WSJ, NYT, WaPo) where plain
    requests returns Cloudflare challenge pages.
  - Expanded keyword lists (more fraud verbs, more healthcare specialties)
    so legitimate journalism with creative headlines gets caught.
  - Title prefix/suffix stripping per outlet (NPR's "Shots - Health News:",
    CBS's " - CBS News", etc.) so stored titles read clean.
  - CLI flags: --backfill-from, --no-browser, --dry-run, --silent,
    matching the enforcement scraper's interface.
  - Dedup against both media.json AND needs_review_media.json so the same
    URL never gets re-flagged on every run.

The scraper is intentionally permissive at this layer — false positives
get caught downstream by the AI relevance check. Better to over-scrape
and let the safety net filter than to miss a real story.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from tag_allowlist import auto_tags as _auto_tags, filter_tags as _filter_tags

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_FILE = os.path.join(SCRIPT_DIR, "data", "media.json")
REVIEW_FILE = os.path.join(SCRIPT_DIR, "data", "needs_review_media.json")

# ---------------------------------------------------------------------------
# News outlet RSS feeds
# ---------------------------------------------------------------------------
# browser_fallback=True flags outlets known to be Cloudflare/paywall protected.
# title_prefixes / title_suffixes are removed from feed titles before storage
# so titles read clean (e.g. NPR prepends "Shots - Health News:" to many items).
MEDIA_FEEDS = [
    # Tier 1 — regularly break healthcare fraud stories
    {"name": "KFF Health News",     "url": "https://kffhealthnews.org/feed/",                                "label": "KFF Health News"},
    {"name": "ProPublica",          "url": "https://feeds.propublica.org/propublica/main",                   "label": "ProPublica"},
    {"name": "NPR",                 "url": "https://feeds.npr.org/1001/rss.xml",                             "label": "NPR",
     "title_prefixes": ["Shots - Health News: ", "Shots: ", "Health News: "]},
    {"name": "CBS News",            "url": "https://www.cbsnews.com/latest/rss/main",                        "label": "CBS News",
     "title_suffixes": [" - CBS News"]},
    {"name": "WSJ",                 "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",    "label": "Wall Street Journal",
     "browser_fallback": True},
    # Tier 2 — frequent but broader coverage
    {"name": "Washington Post",     "url": "https://feeds.washingtonpost.com/rss/national",                  "label": "Washington Post",
     "browser_fallback": True},
    {"name": "Reuters",             "url": "https://www.reutersagency.com/feed/",                            "label": "Reuters"},
    {"name": "CNBC",                "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000108", "label": "CNBC"},
    {"name": "NY Times",            "url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",        "label": "New York Times",
     "browser_fallback": True},
    # Tier 3 — trade/niche but valuable
    {"name": "Fierce Healthcare",   "url": "https://www.fiercehealthcare.com/rss/xml",                       "label": "Fierce Healthcare"},
    {"name": "STAT News",           "url": "https://www.statnews.com/feed/",                                 "label": "STAT News"},
    {"name": "Reason",              "url": "https://reason.com/feed/",                                       "label": "Reason"},
    {"name": "Modern Healthcare",   "url": "https://www.modernhealthcare.com/section/rss",                   "label": "Modern Healthcare"},
]

# ---------------------------------------------------------------------------
# Keyword filters — title must hit BOTH a fraud term AND a healthcare term
# ---------------------------------------------------------------------------
FRAUD_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    # Direct fraud vocabulary
    r"\bfraud\b", r"\bscheme\b", r"\bscam\b", r"\bsting\b",
    # Billing / financial misconduct
    r"overbill", r"upcod", r"phantom\s+bill", r"double[- ]?bill",
    r"false\s+claim", r"improper\s+payment", r"billing\s+(?:scheme|fraud)",
    r"price[- ]?goug", r"price[- ]?fix", r"inflat(?:ed|ing)\s+(?:bill|claim|price)",
    r"overcharg", r"marked\s+up", r"hidden\s+fee",
    # Kickbacks / illegal payments
    r"\bkickback", r"anti[- ]?kickback", r"bribe", r"\bbribery\b",
    r"paid\s+(?:off|out)\s+(?:millions?|billions?)",
    # Verbs of stealing / cheating (broader)
    r"\bbilked", r"defraud\w*", r"swindl\w*", r"siphon\w*",
    r"embezzl\w*", r"steal\w*", r"divert\w*", r"misuse\w*",
    r"\bbogus\b", r"\bphony\b", r"\bsham\b",
    # Investigation / enforcement events
    r"indict\w*", r"\bcharged\b", r"convict\w*", r"sentenc\w*",
    r"plead(?:ed)?\s+guilty", r"guilty\s+plea", r"guilty\s+verdict",
    r"settle\w*", r"\bsettlement\b", r"agreed?\s+to\s+pay",
    r"resolv\w*\s+(?:allegations?|claims?)", r"\bjudgment\b",
    r"takedown", r"crackdown", r"\bbust\b", r"\bprobe\b",
    r"investig\w*", r"under\s+investigation", r"subpoena",
    r"\bquit?\s+tam\b", r"qui\s+tam", r"whistleblow\w*", r"class\s+action",
    # Loophole / exploit framing common in journalism
    r"loophole", r"exploit\w*", r"gam(?:ed|ing)\s+the\s+system",
    r"cost\s+taxpayers", r"taxpayer\s+(?:dollars?|money|funds?)",
    r"secretly\s+(?:billed|charged|profit)",
    # Waste/abuse
    r"waste.{0,10}abuse", r"wasteful\s+spending",
]]

HEALTHCARE_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    # Programs
    r"\bmedicare\b", r"\bmedicaid\b", r"\btricare\b", r"\bmedi-?cal\b",
    r"medicare\s+advantage", r"\baca\b", r"affordable\s+care\s+act",
    r"obamacare", r"chip\s+program",
    # Generic healthcare
    r"\bhealth\s*care\b", r"\bhealthcare\b",
    r"\bhospital\b", r"\bclinic\b",
    r"physician", r"\bdoctor\b", r"\bnurse\b", r"\bpatient",
    r"prescription", r"pharmac\w*", r"hospice", r"home\s+health",
    r"nursing\s+(?:home|facility)", r"skilled\s+nursing", r"long.term\s+care",
    r"assisted\s+living", r"adult\s+day\s+care",
    # Service categories / specialties
    r"\bdental\b", r"\bdentist\b", r"behavioral\s+health",
    r"substance\s+abuse", r"addiction", r"recovery\s+center",
    r"\bopioid", r"fentanyl", r"oxycodone", r"hydrocodone",
    r"controlled\s+substance",
    r"telemedic", r"telehealth", r"\bmedical\b",
    r"medical\s+(?:device|equipment|practice|center|group)",
    r"\bdme\b", r"dmepos", r"durable\s+medical",
    r"wound\s+care", r"skin\s+substitute", r"genetic\s+test\w*",
    r"genomic", r"\blab\b", r"laborator\w*", r"diagnostic",
    r"implant", r"prosthet\w*", r"orthot\w*",
    # Specialties
    r"cardiac", r"cardio\w*", r"oncolog\w*", r"radiolog\w*", r"podiatr\w*",
    r"dermatolog\w*", r"psychiatr\w*", r"pediatric", r"gynec\w*",
    r"ophthalmo\w*", r"urolog\w*", r"neurolog\w*", r"rheumat\w*",
    r"chiropract\w*", r"physiatr\w*",
    r"physical\s+therapy", r"occupational\s+therapy", r"speech\s+therapy",
    r"rehabilitation", r"\bambulance\b", r"\bambulatory\b",
    # Insurer / payer / system names
    r"health\s+(?:system|services|group|plan|insurance|net)",
    r"\bkaiser\b", r"\baetna\b", r"\bcentene\b", r"\bhumana\b", r"\bcigna\b",
    r"\bunitedhealth\w*", r"\belevance\b", r"\bmolina\b", r"\banthem\b",
    r"blue\s+(?:cross|shield)", r"\bcvs\b", r"\bwalgreens\b",
    r"\boptum\b", r"express\s+scripts",
    # Drug industry
    r"pharma\w*", r"drug\s+(?:company|manufacturer|maker)",
    r"biotech", r"biologic", r"vaccine", r"insulin", r"infusion",
    r"\bbotox\b",
    # Agencies (federal HC)
    r"\bcms\b", r"\bhhs\b", r"\boig\b", r"\bfda\b", r"\bdea\b",
    # HC-specific legal frameworks
    r"false\s+claims\s+act", r"anti.?kickback\s+statute", r"stark\s+law",
    r"qui\s+tam", r"hipaa",
]]

# ---------------------------------------------------------------------------
# State map
# ---------------------------------------------------------------------------
STATE_MAP = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
    'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
    'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
    'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
    'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
    'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
    'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
    'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV',
    'Wisconsin': 'WI', 'Wyoming': 'WY',
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
silent = False


def log(msg):
    if not silent:
        print(f"  {msg}", file=sys.stderr)


def create_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, text/html, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    return s


def title_matches(title):
    """Title must contain BOTH a fraud term AND a healthcare term."""
    has_fraud = any(p.search(title) for p in FRAUD_TERMS)
    has_health = any(p.search(title) for p in HEALTHCARE_TERMS)
    return has_fraud and has_health


def strip_title_decorations(title, feed):
    """Remove publisher-specific prefixes/suffixes from a feed title."""
    if not title:
        return title
    cleaned = title.strip()
    for prefix in feed.get("title_prefixes", []) or []:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip()
    for suffix in feed.get("title_suffixes", []) or []:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
    return cleaned


def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    return re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()


def parse_date(date_str):
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')
    for fmt in [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d',
        '%B %d, %Y',
        '%b %d, %Y',
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue
    try:
        from dateutil import parser as du_parser
        return du_parser.parse(date_str).strftime('%Y-%m-%d')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d')


def get_state(text):
    for name, abbr in STATE_MAP.items():
        if re.search(r'\b' + re.escape(name) + r'\b', text):
            return abbr
    return None


def make_id(date_str, link):
    h = abs(int(hashlib.md5(link.encode()).hexdigest()[:8], 16))
    return f"media-{date_str}-{h}"


# ---------------------------------------------------------------------------
# Playwright fallback (lazy-init, shared across feeds)
# ---------------------------------------------------------------------------
_pw_instance = None
_browser = None


def _get_browser():
    global _pw_instance, _browser
    if not HAS_PLAYWRIGHT:
        return None
    if _browser is None:
        _pw_instance = sync_playwright().start()
        _browser = _pw_instance.chromium.launch(headless=True)
        log("Started headless browser for Playwright fallback")
    return _browser


def _close_browser():
    global _pw_instance, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _pw_instance:
        _pw_instance.stop()
        _pw_instance = None


def fetch_feed_with_browser(url):
    """Fetch a feed via Playwright, returning the raw response text."""
    browser = _get_browser()
    if not browser:
        return ""
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 800},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1500)
        return page.content()
    except Exception as e:
        log(f"  Playwright fetch failed for {url}: {e}")
        return ""
    finally:
        context.close()


def fetch_feed(session, feed):
    """Fetch a feed via plain requests, with Playwright fallback if configured."""
    url = feed["url"]
    use_browser_fallback = bool(feed.get("browser_fallback")) and HAS_PLAYWRIGHT

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        # Akamai / Cloudflare bot challenges return HTML where we expect XML
        ct = resp.headers.get("Content-Type", "")
        text = resp.text
        looks_like_block = (
            ("html" in ct and "xml" not in ct)
            or "Just a moment" in text[:2000]
            or "challenge-platform" in text[:2000]
            or "Access Denied" in text[:2000]
        )
        if looks_like_block and use_browser_fallback:
            log(f"  {feed['name']}: plain fetch looks blocked, retrying with Playwright")
            text = fetch_feed_with_browser(url)
        return feedparser.parse(text)
    except (requests.HTTPError, requests.ConnectionError) as e:
        if use_browser_fallback:
            log(f"  {feed['name']}: requests failed ({e}), retrying with Playwright")
            text = fetch_feed_with_browser(url)
            return feedparser.parse(text)
        raise


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global silent, HAS_PLAYWRIGHT

    parser = argparse.ArgumentParser(description="Fetch healthcare-fraud media stories")
    parser.add_argument("-s", "--silent", action="store_true")
    parser.add_argument("--no-browser", action="store_true",
                        help="Disable Playwright browser fallback")
    parser.add_argument("--backfill-from", metavar="YYYY-MM-DD",
                        help="Backfill mode: scrape entries back to this date, "
                             "ignoring last-run cutoff")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the full pipeline but do NOT write to "
                             "needs_review_media.json. Print what would be added.")
    args = parser.parse_args()

    silent = args.silent
    if args.no_browser:
        HAS_PLAYWRIGHT = False

    log("=== Media Investigations Scraper ===")

    media_data = load_json(MEDIA_FILE, {"metadata": {"last_updated": "", "version": "1.0"}, "stories": []})
    review_data = load_json(REVIEW_FILE, {"items": [], "rejected_links": []})

    # Date cutoff
    if args.backfill_from:
        last_run_date = args.backfill_from
        log(f"BACKFILL MODE: floor = {last_run_date} (ignoring last_updated)")
    else:
        last_run_raw = media_data.get("metadata", {}).get("last_updated", "")
        last_run_date = last_run_raw[:10] if last_run_raw else "2025-01-01"
        log(f"Last run date: {last_run_date} — skipping entries before this date")

    # Build dedup set from media.json + needs_review_media.json (both items
    # and rejected_links). The same URL never gets re-flagged.
    existing_links = set()
    existing_titles = set()
    for s in media_data.get("stories", []):
        if s.get("link"):
            existing_links.add(s["link"])
        existing_titles.add(re.sub(r'[^a-z0-9 ]', '', s.get("title", "").lower()).strip())
    for pending in review_data.get("items", []):
        if pending.get("link"):
            existing_links.add(pending["link"])
    for rejected in review_data.get("rejected_links", []) or []:
        if rejected:
            existing_links.add(rejected)

    session = create_session()
    new_stories = []

    for feed in MEDIA_FEEDS:
        log(f"Fetching {feed['name']}...")
        try:
            parsed = fetch_feed(session, feed)
            if not parsed.entries:
                log(f"  {feed['name']}: 0 entries in feed.")
                continue

            count = 0
            for entry in parsed.entries[:30]:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                # Strip wrapping HTML / extract from <a> tags some feeds use
                if "<a " in title:
                    soup_title = BeautifulSoup(title, "lxml")
                    a_tag = soup_title.find("a")
                    if a_tag and a_tag.get("href"):
                        title = a_tag.get_text(strip=True)
                    else:
                        title = clean_html(title)
                else:
                    title = clean_html(title)

                # Strip publisher-specific decorations (prefix/suffix per feed)
                title = strip_title_decorations(title, feed)
                title = re.sub(r"\s+", " ", title).strip()

                # Title must hit both a fraud and a healthcare term
                if not title_matches(title):
                    continue

                link = entry.get("link", "")
                if link and "news.google.com" in link:
                    continue
                if link and link in existing_links:
                    continue

                norm_title = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
                if norm_title in existing_titles:
                    continue

                # Date
                date_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        date_str = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                if not date_str:
                    date_str = parse_date(entry.get("published", ""))
                if date_str < "2025-01-01" or date_str < last_run_date:
                    continue

                desc_raw = entry.get("summary", "") or entry.get("description", "")
                desc_clean = clean_html(desc_raw)
                search_text = f"{title} {desc_clean}"
                tags = _filter_tags(_auto_tags(search_text))
                state = get_state(search_text) or ""

                # NOTE: description, related_agencies, amount, officials, and
                # entities are intentionally NOT written on media items. See
                # project memory.
                story = {
                    "id": make_id(date_str, link),
                    "date": date_str,
                    "agency": "Media",
                    "type": "Investigative Report",
                    "title": title,
                    "amount": "",
                    "amount_numeric": 0,
                    "officials": [],
                    "link": link,
                    "link_label": f"{feed['label']} Report",
                    "social_posts": [],
                    "tags": tags,
                    "state": state,
                    "source_type": "news",
                    "auto_fetched": True,
                    "entities": [],
                }

                new_stories.append(story)
                existing_links.add(link)
                existing_titles.add(norm_title)
                count += 1
                log(f"  + {title[:80]}")

            log(f"  {feed['name']}: {count} new stories found.")

        except Exception as e:
            log(f"  WARNING: {feed['name']} - {e}")

    # Always close the browser if we started one
    _close_browser()

    if args.dry_run:
        log(f"\n=== DRY RUN: would add {len(new_stories)} new stories ===")
        for s in new_stories:
            log(f"  [{s['date']}] {s['title'][:90]}")
        return len(new_stories)

    if new_stories:
        # Append new stories to needs_review_media.json. The audit step then
        # promotes verified stories into media.json.
        now = datetime.now().isoformat()
        for s in new_stories:
            s["flagged_at"] = now
            s["flag_reason"] = "scraped from media feed, awaiting review"
        review_data["items"] = (review_data.get("items") or []) + new_stories
        save_json(REVIEW_FILE, review_data)

        # Touch media.json's last_updated so the next run picks up where we
        # left off, even though we didn't write any stories there directly.
        media_data["metadata"]["last_updated"] = datetime.now().isoformat()
        save_json(MEDIA_FILE, media_data)

        log(f"\n=== Added {len(new_stories)} stories to needs_review_media.json ===")
        for s in new_stories:
            log(f"  [{s['date']}] {s['title'][:80]}")
    else:
        media_data["metadata"]["last_updated"] = datetime.now().isoformat()
        save_json(MEDIA_FILE, media_data)
        log("\n=== No new media stories found ===")

    return len(new_stories)


if __name__ == "__main__":
    added = main()
    sys.exit(0)
