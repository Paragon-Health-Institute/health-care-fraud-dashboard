#!/usr/bin/env python3
"""Fetch healthcare fraud RSS feeds and scrape enforcement pages, updating actions.json."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

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
DATA_FILE = os.path.join(SCRIPT_DIR, "data", "actions.json")
PENDING_FILE = os.path.join(SCRIPT_DIR, "data", "pending.json")

# ---------------------------------------------------------------------------
# Keywords & healthcare terms (compiled regexes)
# ---------------------------------------------------------------------------
KEYWORDS = [re.compile(p, re.IGNORECASE) for p in [
    r'health care fraud', r'healthcare fraud', r'medicare fraud', r'medicaid fraud',
    r'hospice fraud', r'home care fraud', r'home health fraud', r'prescription fraud',
    r'opioid fraud', r'health fraud', r'fraud takedown',
    r'false claims', r'false billing', r'improper billing', r'kickback', r'overbilling',
    r'upcoding', r'phantom billing', r'identity theft.*medicare', r'durable medical',
    r'program integrity',
]]

HEALTHCARE_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    r'medicare', r'medicaid', r'tricare', r'health care', r'healthcare', r'hospital',
    r'clinic', r'physician', r'medical', r'patient', r'prescription', r'pharmacist',
    r'pharmacy', r'hospice', r'home health', r'nursing home', r'assisted living',
    r'\bcms\b', r'\bhhs\b', r'\boig\b', r'health insurance', r'health plan',
    r'clinical', r'diagnosis', r'therapy', r'dental fraud', r'ambulance fraud',
    r'\bdme\b', r'durable medical', r'behavioral health', r'substance abuse',
    r'affordable care act', r'aca enrollment', r'chip program',
]]

# ---------------------------------------------------------------------------
# Feed definitions
# ---------------------------------------------------------------------------
FEEDS = [
    # --- Official agency feeds ---
    {"name": "DOJ",         "agency": "DOJ",          "url": "https://www.justice.gov/news/rss",                                          "enabled": True,  "source_type": "official", "browser_fallback": True},
    {"name": "HHS-OIG",     "agency": "HHS-OIG",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "oig"},
    {"name": "CMS",         "agency": "CMS",           "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "cms"},
    {"name": "HHS",         "agency": "HHS",           "url": "https://www.hhs.gov/rss/news.xml",                                         "enabled": False, "source_type": "official", "browser_fallback": True},
    {"name": "DOJ-USAO",    "agency": "DOJ",           "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "doj_usao"},
    {"name": "GAO",         "agency": "GAO",           "url": "https://www.gao.gov/rss/reports.xml",                                      "enabled": True,  "source_type": "official"},
    {"name": "H-Oversight", "agency": "Congress",      "url": "https://oversight.house.gov/feed/",                                        "enabled": True,  "source_type": "official"},
    {"name": "H-E&C",       "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "energy_commerce"},
    {"name": "S-Finance",   "agency": "Congress",      "url": "https://www.finance.senate.gov/rss/feeds/?type=press",                     "enabled": True,  "source_type": "official"},
    {"name": "S-HELP",      "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "help_committee"},
    {"name": "H-W&M",       "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "ways_means"},
    {"name": "HHS-OIG-RPT", "agency": "HHS-OIG",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "oig_reports"},
    {"name": "FDA",         "agency": "FDA",           "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "enabled": False, "source_type": "official"},
    {"name": "DEA",         "agency": "DEA",           "url": "https://www.dea.gov/press-releases/rss",                                   "enabled": True,  "source_type": "official", "browser_fallback": True},
    # --- Media feeds disabled — Fraud Landscape is manually curated (see data/media.json) ---
    # --- State AG feeds disabled — state actions removed from dashboard ---
]

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

def log(msg, color=None):
    if not silent:
        print(f"  {msg}", file=sys.stderr)

def test_any_keyword(text):
    for pat in KEYWORDS:
        if pat.search(text):
            return True
    return False

def test_healthcare_context(text):
    for pat in HEALTHCARE_TERMS:
        if pat.search(text):
            return True
    return False

def get_action_type(title, desc):
    text = f"{title} {desc}".lower()
    if re.search(r'signed into law|enacted|passes bill|bill signed|legislation|executive order|presidential memo|law.*(takes|went) effect', text):
        return 'Legislation'
    if re.search(r'hearing|committee\s+(hearing|held|examine|vote)|testimony|testif|subcommittee.*hearing|gao.*(report|finds|audit)|congressional.*report|senate.*report|house.*report', text):
        return 'Congressional Hearing'
    if re.search(r'plead|convict|indict|charg|guilty|arrest|prosecut', text):
        return 'Criminal Enforcement'
    if re.search(r'civil|settlement|civil.+action|false claims act', text):
        return 'Civil Action'
    if re.search(r'audit|review|report|oig', text):
        return 'Audit'
    if re.search(r'rule|regulation|final.+rule|proposed.+rule|loophole', text):
        return 'Rule/Regulation'
    if re.search(r'task force|division|unit|strike force|creat', text):
        return 'Structural/Organizational'
    if re.search(r'investigat|fact.?find|mission', text):
        return 'Investigation'
    if re.search(r'ai|artificial intelligence|machine learning', text):
        return 'Technology/Innovation'
    return 'Administrative Action'

def get_state(text):
    for name, abbr in STATE_MAP.items():
        if re.search(r'\b' + re.escape(name) + r'\b', text):
            return abbr
    return None

def extract_amount(text):
    m = re.search(r'\$[\d,]+(?:\.\d+)?\s*billion', text, re.IGNORECASE)
    if m:
        num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('billion', '')))
        return {"display": m.group(), "numeric": num * 1e9}
    m = re.search(r'\$[\d,]+(?:\.\d+)?\s*million', text, re.IGNORECASE)
    if m:
        num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('million', '')))
        return {"display": m.group(), "numeric": num * 1e6}
    return None

def generate_tags(text):
    """Generate relevant tags from text content.

    Tags are restricted to the canonical allowlist in tag_allowlist.py
    (programs + vulnerable fraud areas only). Anything else is filtered out.
    """
    return _auto_tags(text)

def fetch_detail_page(session, url):
    """Fetch a detail page and return (text, doj_link)."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        # Extract DOJ press release link if present
        doj_link = None
        for a_tag in soup.find_all('a', href=True):
            if 'justice.gov' in a_tag['href'] and '/pr/' in a_tag['href']:
                doj_link = a_tag['href']
                break
        # Try common content containers
        main = (soup.find('main') or soup.find('article') or
                soup.find('div', class_='field-item') or
                soup.find('div', class_='entry-content'))
        if main:
            for tag in main.find_all(['nav', 'footer', 'aside', 'script', 'style']):
                tag.decompose()
            return re.sub(r'\s+', ' ', main.get_text(' ', strip=True)), doj_link
        return "", doj_link
    except Exception as e:
        log(f"    Detail fetch failed for {url}: {e}")
        return "", None

def make_id(prefix, date_str, link, agency=""):
    hash_input = link or (date_str + agency)
    h = abs(int(hashlib.md5(hash_input.encode()).hexdigest()[:8], 16))
    return f"{prefix}-{date_str}-{h}"

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    return re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()

def parse_date(date_str):
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')
    # feedparser provides parsed time tuples
    for fmt in [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d',
        '%B %d, %Y',
        '%b %d, %Y',
        '%m/%d/%Y',
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue
    # Last resort: try dateutil if available, otherwise today
    try:
        from dateutil import parser as du_parser
        return du_parser.parse(date_str).strftime('%Y-%m-%d')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d')

def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def save_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# HTTP session with browser-like headers
# ---------------------------------------------------------------------------
def create_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, text/html, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    return s

# ---------------------------------------------------------------------------
# Playwright browser (lazy-initialized, shared across feeds)
# ---------------------------------------------------------------------------
_pw_instance = None
_browser = None

def get_browser():
    """Lazily start a headless Chromium browser. Returns (page_factory, cleanup)."""
    global _pw_instance, _browser
    if not HAS_PLAYWRIGHT:
        return None
    if _browser is None:
        _pw_instance = sync_playwright().start()
        _browser = _pw_instance.chromium.launch(headless=True)
        log("  Started headless browser.")
    return _browser

def close_browser():
    global _pw_instance, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _pw_instance:
        _pw_instance.stop()
        _pw_instance = None

def fetch_page_with_browser(url, wait_ms=3000):
    """Fetch a page using Playwright, returning the rendered HTML."""
    browser = get_browser()
    if not browser:
        raise RuntimeError("Playwright not available")
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 800},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        return html
    finally:
        context.close()

def fetch_rss_with_browser(url):
    """Fetch an RSS feed via Playwright (bypasses bot protection), then parse with feedparser."""
    html = fetch_page_with_browser(url, wait_ms=2000)
    # The page content may be raw XML served through the browser
    feed = feedparser.parse(html)
    items = []
    for entry in feed.entries:
        title = entry.get('title', '')
        desc = entry.get('summary', entry.get('description', ''))
        link = entry.get('link', '')
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            date_str = time.strftime('%Y-%m-%d', entry.published_parsed)
        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            date_str = time.strftime('%Y-%m-%d', entry.updated_parsed)
        else:
            date_str = entry.get('published', entry.get('updated', ''))
        items.append({'title': title, 'description': desc, 'link': link, 'pub_date': date_str})
    return items

def scrape_page_with_browser(url):
    """Scrape an HTML page via Playwright, returning BeautifulSoup object."""
    html = fetch_page_with_browser(url, wait_ms=3000)
    return BeautifulSoup(html, 'lxml')

# ---------------------------------------------------------------------------
# HTML scrapers for sites without RSS
# ---------------------------------------------------------------------------
def scrape_oig(session):
    """Scrape HHS-OIG enforcement actions page.

    Normal mode: pages 1-2 (enough for daily updates).
    Backfill mode: walks pages until all items on a page are older than
    BACKFILL_FLOOR, with a hard cap to avoid infinite loops.
    """
    base_url = "https://oig.hhs.gov/fraud/enforcement/?type=criminal-and-civil-actions"
    # Known OIG navigation/index paths that are not individual enforcement actions
    OIG_NAV_PATHS = {
        'https://oig.hhs.gov/fraud/enforcement/',
        'https://oig.hhs.gov/fraud/enforcement/about/',
        'https://oig.hhs.gov/fraud/enforcement/civil-monetary-penalty-authorities/',
    }
    DATE_RE = re.compile(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+\d{4}', re.I)
    items = []
    backfill = globals().get('BACKFILL_MODE', False)
    floor = globals().get('BACKFILL_FLOOR', '2025-01-01')
    max_pages = 60 if backfill else 2
    for page in range(1, max_pages + 1):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')
            # OIG lists actions as linked items with dates
            for a_tag in soup.select('a[href*="/fraud/enforcement/"]'):
                href = a_tag.get('href', '')
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                if href.startswith('/'):
                    href = 'https://oig.hhs.gov' + href
                # Skip navigation/index pages — only process individual action slugs
                href_norm = href.rstrip('/') + '/'
                if href_norm in OIG_NAV_PATHS or '?' in href:
                    continue
                # Date: try listing page parent element first
                parent = a_tag.find_parent(['li', 'div', 'article', 'tr'])
                date_str = ""
                if parent:
                    text = parent.get_text(' ', strip=True)
                    date_match = DATE_RE.search(text)
                    if date_match:
                        date_str = date_match.group()
                # Fetch OIG detail page — also extracts DOJ press release link if present
                detail_text, doj_link = fetch_detail_page(session, href)
                # If DOJ press release exists, use it as the canonical link.
                canonical_link = doj_link if doj_link else href
                # In normal mode we also fetch the DOJ press release text to
                # get better tag/amount extraction. In backfill mode we skip
                # that second fetch — justice.gov bot-blocks most of the time
                # and we don't store descriptions anyway, so the incremental
                # quality isn't worth the latency or failure rate.
                if doj_link and not backfill:
                    doj_text, _ = fetch_detail_page(session, doj_link)
                    if doj_text:
                        detail_text = doj_text  # use DOJ text for description/tags
                # Fallback: extract date from detail page text (e.g. "Action Details Date: March 27, 2026")
                if not date_str and detail_text:
                    date_match = DATE_RE.search(detail_text)
                    if date_match:
                        date_str = date_match.group()
                # Extract first meaningful paragraph as description (skip title echo)
                desc = ""
                if detail_text:
                    # Remove the title from the start if echoed
                    cleaned = detail_text
                    if title in cleaned:
                        cleaned = cleaned.split(title, 1)[-1].strip()
                    # Take first ~600 chars as description
                    desc = cleaned[:600].strip()
                    if len(cleaned) > 600:
                        # Cut at last sentence boundary
                        last_period = desc.rfind('.')
                        if last_period > 200:
                            desc = desc[:last_period + 1]

                items.append({
                    'title': title,
                    'description': desc,
                    'link': canonical_link,
                    'pub_date': date_str,
                    '_full_text': detail_text,  # carry for tag/amount extraction
                })

            # Backfill early-stop: if every item on this page has a parsed
            # date older than the floor, we've walked past the target range.
            if backfill and page >= 2:
                parsed_dates = []
                for it in items[-40:]:  # recent slice
                    try:
                        pd = parse_date(it.get('pub_date', ''))
                        if pd:
                            parsed_dates.append(pd)
                    except Exception:
                        pass
                if parsed_dates and max(parsed_dates) < floor:
                    log(f"  OIG backfill: page {page} all older than {floor}, stopping")
                    break
        except Exception as e:
            log(f"  WARNING: OIG scrape page {page} - {e}", "yellow")
    return items

def scrape_cms(session):
    """Scrape CMS newsroom press releases."""
    url = "https://www.cms.gov/about-cms/contact/newsroom"
    items = []
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for row in soup.select('.views-row, article, .node--type-press-release'):
            a_tag = row.find('a', href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag['href']
            if href.startswith('/'):
                href = 'https://www.cms.gov' + href
            date_str = ""
            date_el = row.find(string=re.compile(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}'))
            if date_el:
                date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}', date_el)
                if date_match:
                    date_str = date_match.group()
            # Fetch detail page for description
            detail_text, _ = fetch_detail_page(session, href)
            desc = ""
            if detail_text:
                cleaned = detail_text
                if title in cleaned:
                    cleaned = cleaned.split(title, 1)[-1].strip()
                desc = cleaned[:600].strip()
                if len(cleaned) > 600:
                    last_period = desc.rfind('.')
                    if last_period > 200:
                        desc = desc[:last_period + 1]

            items.append({
                'title': title,
                'description': desc,
                'link': href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: CMS scrape - {e}", "yellow")
    return items

def scrape_energy_commerce(session):
    """Scrape House Energy & Commerce press releases using Playwright."""
    if not HAS_PLAYWRIGHT:
        log("    Skipping H-E&C (requires Playwright)")
        return []
    url = "https://energycommerce.house.gov/news/press-release"
    items = []
    try:
        soup = scrape_page_with_browser(url)
        for a_tag in soup.find_all('a', href=re.compile(r'^/posts/')):
            href = 'https://energycommerce.house.gov' + a_tag['href']
            parent = a_tag.find_parent(['div', 'section', 'article', 'li'])
            if not parent:
                continue
            text = parent.get_text(' ', strip=True)
            dm = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}', text)
            date_str = dm.group() if dm else ""
            heading = parent.find(['h2', 'h3', 'h4', 'strong'])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 10:
                continue
            # Fetch detail page for description
            detail_text = ""
            try:
                detail_text, _ = fetch_detail_page(session, href)
            except Exception:
                pass
            desc = ""
            if detail_text:
                cleaned = detail_text
                if title in cleaned:
                    cleaned = cleaned.split(title, 1)[-1].strip()
                desc = cleaned[:600].strip()
                if len(cleaned) > 600:
                    last_period = desc.rfind('.')
                    if last_period > 200:
                        desc = desc[:last_period + 1]

            items.append({
                'title': title,
                'description': desc,
                'link': href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: H-E&C scrape - {e}")
    return items

def scrape_help_committee(session):
    """Scrape Senate HELP Committee press releases using Playwright."""
    if not HAS_PLAYWRIGHT:
        log("    Skipping S-HELP (requires Playwright)")
        return []
    url = "https://www.help.senate.gov/chair/newsroom"
    items = []
    try:
        soup = scrape_page_with_browser(url)
        for a_tag in soup.find_all('a', href=re.compile(r'/newsroom/press')):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = 'https://www.help.senate.gov' + href
            parent = a_tag.find_parent(['li', 'div', 'article', 'tr'])
            date_str = ""
            if parent:
                dm = re.search(r'\b(\d{2})\.(\d{2})\.(\d{4})\b', parent.get_text())
                if dm:
                    date_str = f"{dm.group(1)}/{dm.group(2)}/{dm.group(3)}"
                else:
                    dm2 = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}', parent.get_text())
                    if dm2:
                        date_str = dm2.group()
            # Fetch detail page for description
            detail_text = ""
            try:
                detail_text, _ = fetch_detail_page(session, href)
            except Exception:
                pass
            desc = ""
            if detail_text:
                cleaned = detail_text
                if title in cleaned:
                    cleaned = cleaned.split(title, 1)[-1].strip()
                desc = cleaned[:600].strip()
                if len(cleaned) > 600:
                    last_period = desc.rfind('.')
                    if last_period > 200:
                        desc = desc[:last_period + 1]

            items.append({
                'title': title,
                'description': desc,
                'link': href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: S-HELP scrape - {e}")
    return items

def scrape_ways_means(session):
    """Scrape House Ways & Means Committee news using Playwright."""
    if not HAS_PLAYWRIGHT:
        log("    Skipping H-W&M (requires Playwright)")
        return []
    url = "https://waysandmeans.house.gov/news/"
    items = []
    try:
        soup = scrape_page_with_browser(url)
        seen_hrefs = set()
        for a_tag in soup.find_all('a', href=re.compile(r'/\d{4}/\d{2}/\d{2}/')):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            # Skip "Read More" duplicate links
            if title.lower().startswith('read more'):
                continue
            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = 'https://waysandmeans.house.gov' + href
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            parent = a_tag.find_parent(['li', 'div', 'article', 'tr', 'section'])
            date_str = ""
            if parent:
                dm = re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    parent.get_text()
                )
                if dm:
                    date_str = dm.group()
            if not date_str:
                # Extract date from URL pattern /YYYY/MM/DD/
                dm = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', href)
                if dm:
                    date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
            # Fetch detail page for description
            detail_text = ""
            try:
                detail_text, _ = fetch_detail_page(session, href)
            except Exception:
                pass
            desc = ""
            if detail_text:
                cleaned = detail_text
                if title in cleaned:
                    cleaned = cleaned.split(title, 1)[-1].strip()
                desc = cleaned[:600].strip()
                if len(cleaned) > 600:
                    last_period = desc.rfind('.')
                    if last_period > 200:
                        desc = desc[:last_period + 1]

            items.append({
                'title': title,
                'description': desc,
                'link': href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: H-W&M scrape - {e}")
    return items

def scrape_doj_usao(session):
    """Scrape DOJ USAO press releases using Playwright (Akamai-blocked)."""
    if not HAS_PLAYWRIGHT:
        log("    Skipping DOJ-USAO (requires Playwright)")
        return []
    url = "https://www.justice.gov/usao/pressreleases"
    items = []
    try:
        soup = scrape_page_with_browser(url)
        for a_tag in soup.find_all('a', href=re.compile(r'/usao-.*/pr/')):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = 'https://www.justice.gov' + href
            parent = a_tag.find_parent(['li', 'div', 'article', 'tr'])
            date_str = ""
            if parent:
                dm = re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    parent.get_text()
                )
                if dm:
                    date_str = dm.group()
            # Fetch detail page for description
            detail_text = ""
            try:
                detail_text, _ = fetch_detail_page(session, href)
            except Exception:
                pass
            desc = ""
            if detail_text:
                cleaned = detail_text
                if title in cleaned:
                    cleaned = cleaned.split(title, 1)[-1].strip()
                desc = cleaned[:600].strip()
                if len(cleaned) > 600:
                    last_period = desc.rfind('.')
                    if last_period > 200:
                        desc = desc[:last_period + 1]

            items.append({
                'title': title,
                'description': desc,
                'link': href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: DOJ-USAO scrape - {e}")
    return items

# ---------------------------------------------------------------------------
# RSS fetch
# ---------------------------------------------------------------------------
def fetch_rss(session, url, use_browser_fallback=False):
    """Fetch and parse an RSS/Atom feed, returning normalized items."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        # Check for Akamai/bot blocks (HTML instead of XML)
        content_type = resp.headers.get('Content-Type', '')
        if 'html' in content_type and 'xml' not in content_type:
            if 'akamai' in resp.text.lower() or 'bm-verify' in resp.text:
                raise ConnectionError("Blocked by Akamai bot protection")
        feed = feedparser.parse(resp.content)
    except (requests.HTTPError, ConnectionError) as e:
        if use_browser_fallback and HAS_PLAYWRIGHT:
            log(f"    Requests failed ({e}), retrying with browser...")
            return fetch_rss_with_browser(url)
        raise
    items = []
    for entry in feed.entries:
        title = entry.get('title', '')
        desc = entry.get('summary', entry.get('description', ''))
        link = entry.get('link', '')
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            date_str = time.strftime('%Y-%m-%d', entry.published_parsed)
        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            date_str = time.strftime('%Y-%m-%d', entry.updated_parsed)
        else:
            date_str = entry.get('published', entry.get('updated', ''))

        # If RSS summary is short/empty, fetch the detail page
        desc_clean = clean_html(desc)
        detail_text = ""
        if link and len(desc_clean) < 100:
            try:
                detail_text, _ = fetch_detail_page(session, link)
                if detail_text:
                    cleaned = detail_text
                    if title in cleaned:
                        cleaned = cleaned.split(title, 1)[-1].strip()
                    desc = cleaned[:600].strip()
                    if len(cleaned) > 600:
                        last_period = desc.rfind('.')
                        if last_period > 200:
                            desc = desc[:last_period + 1]
            except Exception:
                pass

        items.append({
            'title': title,
            'description': desc,
            'link': link,
            'pub_date': date_str,
            '_full_text': detail_text,
        })
    return items

def scrape_oig_reports(session):
    """Scrape HHS-OIG audit/inspection reports (pages 1-2)."""
    base_url = "https://oig.hhs.gov/reports/all/"
    DATE_RE = re.compile(r'Issued\s+(\d{2}/\d{2}/\d{4})')
    items = []
    for page in range(1, 3):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')
            for card in soup.select('.usa-card__container'):
                body = card.select_one('.usa-card__body')
                if not body:
                    continue
                body_text = body.get_text(' ', strip=True)
                # Extract report type (Audit, Evaluation, etc.) and date
                date_str = ""
                date_match = DATE_RE.search(body_text)
                if date_match:
                    date_str = date_match.group(1)
                # Get title and link
                a_tag = card.find('a', href=True)
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                # Skip clean audits — "in accordance with" means no violations found
                if re.search(r'\bin accordance with\b', title, re.I):
                    continue
                href = a_tag['href']
                if href.startswith('/'):
                    href = 'https://oig.hhs.gov' + href
                # Determine report type from body text
                report_type = ""
                for rt in ['Audit', 'Evaluation', 'Inspection', 'Review', 'Investigation']:
                    if rt in body_text:
                        report_type = rt
                        break
                # Fetch detail page for description
                detail_text, _ = fetch_detail_page(session, href)
                desc = ""
                if detail_text:
                    cleaned = detail_text
                    if title in cleaned:
                        cleaned = cleaned.split(title, 1)[-1].strip()
                    desc = cleaned[:600].strip()
                    if len(cleaned) > 600:
                        last_period = desc.rfind('.')
                        if last_period > 200:
                            desc = desc[:last_period + 1]
                items.append({
                    'title': title,
                    'description': desc,
                    'link': href,
                    'pub_date': date_str,
                    '_full_text': detail_text,
                    '_report_type': report_type,
                })
        except Exception as e:
            log(f"  WARNING: OIG reports page {page} - {e}", "yellow")
    return items

# ---------------------------------------------------------------------------
# Fetch dispatcher
# ---------------------------------------------------------------------------
def fetch_feed(session, feed):
    """Fetch items from a feed via RSS, HTML scraper, or Playwright fallback."""
    scrape_mode = feed.get('scrape')
    if scrape_mode == 'oig':
        return scrape_oig(session)
    if scrape_mode == 'oig_reports':
        return scrape_oig_reports(session)
    if scrape_mode == 'cms':
        return scrape_cms(session)
    if scrape_mode == 'doj_usao':
        return scrape_doj_usao(session)
    if scrape_mode == 'energy_commerce':
        return scrape_energy_commerce(session)
    if scrape_mode == 'help_committee':
        return scrape_help_committee(session)
    if scrape_mode == 'ways_means':
        return scrape_ways_means(session)
    if not feed.get('url'):
        return []
    return fetch_rss(session, feed['url'], use_browser_fallback=feed.get('browser_fallback', False))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global silent, HAS_PLAYWRIGHT
    parser = argparse.ArgumentParser(description='Fetch healthcare fraud feeds')
    parser.add_argument('-s', '--silent', action='store_true')
    parser.add_argument('--no-browser', action='store_true', help='Disable Playwright browser fallback')
    parser.add_argument('--backfill-from', metavar='YYYY-MM-DD',
                        help='Backfill mode: scrape pages back to this date, '
                             'ignoring last_scraped cutoff. Also deepens '
                             'OIG pagination to walk the archive.')
    parser.add_argument('--opa-only', action='store_true',
                        help='Only accept items whose canonical link is a DOJ '
                             'Office of Public Affairs press release '
                             '(justice.gov/opa/pr/...). Skips USAO district '
                             'releases. Useful for high-signal backfills.')
    parser.add_argument('--enforcement-only', action='store_true',
                        help='Only accept items classified as Criminal '
                             'Enforcement or Civil Action. Drops oversight-'
                             'type items (Audit, Investigation, '
                             'Administrative Action, Rule/Regulation, '
                             'Hearing, Report, etc.). Used by the daily auto-'
                             'merge pipeline which only publishes to the '
                             'Federal Enforcement tab.')
    args = parser.parse_args()
    silent = args.silent
    if args.no_browser:
        HAS_PLAYWRIGHT = False

    log("Loading existing data...")
    data = load_json(DATA_FILE, {"metadata": {"last_updated": "", "version": "1.0"}, "actions": []})

    # Cutoff: backfill mode uses the explicit floor and ignores last_scraped.
    # Normal mode uses last_scraped to only pick up new items since last run.
    if args.backfill_from:
        last_scraped_date = args.backfill_from
        log(f"BACKFILL MODE: floor = {last_scraped_date} (ignoring last_scraped)")
    else:
        last_scraped_raw = data["metadata"].get("last_scraped") or data["metadata"].get("last_updated", "")
        last_scraped_date = last_scraped_raw[:10] if last_scraped_raw else "2025-01-01"
        log(f"Last scraped date: {last_scraped_date} — skipping entries before this date")

    # Thread backfill flag into scrapers via a module-level variable
    globals()['BACKFILL_MODE'] = bool(args.backfill_from)
    globals()['BACKFILL_FLOOR'] = last_scraped_date
    globals()['OPA_ONLY'] = bool(args.opa_only)
    globals()['ENFORCEMENT_ONLY'] = bool(args.enforcement_only)
    if args.opa_only:
        log("OPA-ONLY MODE: dropping items not linking to /opa/pr/")
    if args.enforcement_only:
        log("ENFORCEMENT-ONLY MODE: dropping items not typed Criminal Enforcement / Civil Action")

    # Dedup sets
    existing_links = set()
    existing_titles = set()
    for a in data.get("actions", []):
        if a.get("link"):
            existing_links.add(a["link"])
        # Normalize title for fuzzy dedup
        existing_titles.add(re.sub(r'[^a-z0-9 ]', '', a.get("title", "").lower()).strip())

    # Also dedup against needs_review.json so we don't re-scrape items that
    # are either pending review or have been permanently rejected.
    review_path = os.path.join(SCRIPT_DIR, "data", "needs_review.json")
    if os.path.exists(review_path):
        try:
            review = load_json(review_path, {"items": [], "rejected_links": []})
            for link in review.get("rejected_links", []) or []:
                if link:
                    existing_links.add(link)
            # Pending items: don't re-flag the same thing on the next run
            for pending in review.get("items", []) or []:
                if pending.get("link"):
                    existing_links.add(pending["link"])
        except Exception as e:
            log(f"  WARNING: could not load needs_review.json: {e}")

    session = create_session()
    added = 0
    new_actions = []

    for feed in FEEDS:
        if not feed.get("enabled"):
            continue
        log(f"Fetching {feed['name']}...")
        try:
            items = fetch_feed(session, feed)
            if not items:
                log(f"  {feed['name']}: 0 new items.")
                continue

            count = 0
            for item in items:
                title = item.get('title', '')
                if not title:
                    continue
                desc_raw = item.get('description', '')
                desc_clean = clean_html(desc_raw)
                link = item.get('link', '')

                search_text = f"{title} {desc_clean}"
                # Every item must pass the healthcare-context filter,
                # regardless of source. Previously we trusted the HHS-OIG
                # fraud/enforcement listing to be pre-filtered to healthcare,
                # but OIG surfaces SNAP, childcare, immigration, housing,
                # passport, and other non-HC cases. So require healthcare
                # context on every item.
                trusted_source = feed.get('agency') in ('HHS-OIG',)
                if not trusted_source:
                    # Non-trusted feeds need both a fraud keyword AND healthcare context
                    if not test_any_keyword(search_text):
                        continue
                if not test_healthcare_context(search_text):
                    continue
                # Media feeds: keyword must be in title
                is_media = feed['source_type'] == 'news'
                if is_media and not test_any_keyword(title):
                    continue
                # Reject Google News redirect URLs
                if link and 'news.google.com' in link:
                    continue
                # Dedup by link
                if link and link in existing_links:
                    continue
                # Dedup by normalized title
                norm_title = re.sub(r'[^a-z0-9 ]', '', title.lower()).strip()
                if norm_title in existing_titles:
                    continue

                date_str = item.get('pub_date', '')
                # If already YYYY-MM-DD, keep it; otherwise parse
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                    date_str = parse_date(date_str)

                # Enforce Jan 2025 floor and last-scraped cutoff
                if date_str < '2025-01-01':
                    continue
                if date_str < last_scraped_date:
                    continue

                # Federal Enforcement tab rule: items classified as Criminal
                # Enforcement or Civil Action MUST link to a .gov source.
                # Anything else (news/blog/law-firm site) gets dropped — even
                # if the underlying event is real, it doesn't belong on the
                # enforcement tab without an official source.
                if not is_media and link:
                    host = urlparse(link).netloc.lower().replace('www.', '')
                    is_gov_link = host.endswith('.gov') or host.endswith('.mil')
                    if not is_gov_link:
                        log(f"  skipping non-.gov link for enforcement candidate: {link}")
                        continue

                # OPA-only mode: only accept DOJ Office of Public Affairs press
                # releases. Drops all USAO district releases and OIG-hosted
                # pages. Used for high-signal backfills.
                if globals().get('OPA_ONLY') and '/opa/pr/' not in link:
                    continue

                # Use full detail text if available (from scrapers that fetch detail pages)
                full_text = item.get('_full_text', '')
                search_all = f"{title} {desc_clean} {full_text}"

                state = get_state(search_all)
                action_type = 'Investigative Report' if is_media else get_action_type(title, search_all)
                tags = generate_tags(search_all)

                # Enforcement-only filter: only add items classified as
                # Criminal Enforcement or Civil Action. Oversight items
                # (Audit, Investigation, Administrative Action,
                # Rule/Regulation, Hearing, Report, Structural/Organizational,
                # etc.) are dropped. Applied in backfill mode (historical
                # ingest) and when --enforcement-only is passed (daily
                # auto-merge pipeline for the Federal Enforcement tab).
                is_enforcement = action_type in ('Criminal Enforcement', 'Civil Action')
                if globals().get('BACKFILL_MODE') and not is_enforcement:
                    continue
                if globals().get('ENFORCEMENT_ONLY') and not is_enforcement:
                    continue

                # Dollar amounts are only kept on Criminal Enforcement /
                # Civil Action items. Oversight (Audit, Investigation,
                # Administrative Action, Rule/Regulation, Hearing, Report,
                # etc.) and Media items never get an amount. See project
                # memory: project_amounts_enforcement_only.
                if action_type in ('Criminal Enforcement', 'Civil Action'):
                    amt_info = extract_amount(search_all)
                else:
                    amt_info = None

                # HHS-OIG entries: recategorize by link domain and content
                actual_agency = feed['agency']
                if feed['agency'] == 'HHS-OIG' and link:
                    # DOJ press releases → categorize as DOJ
                    if 'justice.gov' in link:
                        actual_agency = 'DOJ'
                    # State AG sites → skip entirely (dashboard is federal-only)
                    elif any(d in link for d in ('attorneygeneral.', 'ag.gov', 'mass.gov', 'state.')):
                        continue
                    # Criminal/civil enforcement outcomes on oig.hhs.gov are DOJ prosecutions
                    elif re.search(r'sentenc|guilty plea|plead[s ]? guilty|convict|indict|charg|arrest|prison|ordered to pay|jury find|agrees to pay|consent judgment|settlement|resolve.*allegations', title.lower()):
                        actual_agency = 'DOJ'

                id_prefix = 'media' if is_media else re.sub(r'\W', '-', actual_agency.lower())
                link_label = f"{feed['name']} Report" if is_media else f"{actual_agency} Press Release"

                # NOTE: description field is intentionally NOT written.
                # The dashboard displays only title/link/date/tags. See
                # tag_allowlist.py and project memory for details.
                entry = {
                    "id": make_id(id_prefix, date_str, link, actual_agency),
                    "date": date_str,
                    "agency": actual_agency,
                    "type": action_type,
                    "title": re.sub(r'\s+', ' ', title).strip(),
                    "amount": amt_info['display'] if amt_info else None,
                    "amount_numeric": amt_info['numeric'] if amt_info else 0,
                    "officials": [],
                    "link": link,
                    "link_label": link_label,
                    "social_posts": [],
                    "tags": _filter_tags(tags),
                    "entities": [],
                    "state": state,
                    "source_type": feed['source_type'],
                    "auto_fetched": True,
                }

                new_actions.append(entry)
                added += 1
                if link:
                    existing_links.add(link)
                existing_titles.add(norm_title)
                count += 1

            log(f"  {feed['name']}: {count} new items.")
        except Exception as e:
            log(f"  WARNING: {feed['name']} - {e}")

    # Update metadata — last_scraped tracks when the scraper ran (used as cutoff next run)
    # last_updated is only bumped when new entries are actually added
    data["metadata"]["last_scraped"] = datetime.now().isoformat()
    if added > 0:
        data["metadata"]["last_updated"] = datetime.now().isoformat()

    if added > 0:
        data["actions"].extend(new_actions)
        log(f"Added {added} action(s).")
    else:
        log("No new actions found.")

    save_json(DATA_FILE, data)

    log("Saved.")
    close_browser()
    print(f"ADDED:{added}")

if __name__ == '__main__':
    main()
