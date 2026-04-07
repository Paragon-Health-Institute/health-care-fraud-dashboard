#!/usr/bin/env python3
"""Fetch investigative reports from major news outlets, updating media.json."""

import hashlib
import json
import os
import re
import sys
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from tag_allowlist import auto_tags as _auto_tags, filter_tags as _filter_tags

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_FILE = os.path.join(SCRIPT_DIR, "data", "media.json")

# ---------------------------------------------------------------------------
# News outlet RSS feeds
# ---------------------------------------------------------------------------
MEDIA_FEEDS = [
    # Tier 1 — regularly break health care fraud stories
    {"name": "KFF Health News",          "url": "https://kffhealthnews.org/feed/",                                    "label": "KFF Health News"},
    {"name": "ProPublica",               "url": "https://feeds.propublica.org/propublica/main",                        "label": "ProPublica"},
    {"name": "NPR",                      "url": "https://feeds.npr.org/1001/rss.xml",                                 "label": "NPR"},
    {"name": "CBS News",                 "url": "https://www.cbsnews.com/latest/rss/main",                             "label": "CBS News"},
    {"name": "WSJ",                      "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",         "label": "Wall Street Journal"},
    # Tier 2 — frequent but broader coverage
    {"name": "Washington Post",          "url": "https://feeds.washingtonpost.com/rss/national",                       "label": "Washington Post"},
    {"name": "Reuters",                  "url": "https://www.reutersagency.com/feed/",                                 "label": "Reuters"},
    {"name": "CNBC",                     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000108", "label": "CNBC"},
    {"name": "NY Times",                 "url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",             "label": "New York Times"},
    # Tier 3 — trade/niche but valuable
    {"name": "Fierce Healthcare",        "url": "https://www.fiercehealthcare.com/rss/xml",                            "label": "Fierce Healthcare"},
    {"name": "STAT News",               "url": "https://www.statnews.com/feed/",                                      "label": "STAT News"},
    {"name": "Reason",                   "url": "https://reason.com/feed/",                                            "label": "Reason"},
    {"name": "Modern Healthcare",        "url": "https://www.modernhealthcare.com/section/rss",                        "label": "Modern Healthcare"},
]

# ---------------------------------------------------------------------------
# Keyword filters — BOTH must match in the title
# ---------------------------------------------------------------------------
FRAUD_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    r'fraud', r'scheme', r'scam', r'overbilling', r'kickback',
    r'false claims', r'improper payment', r'billing scheme', r'whistleblower',
    r'phantom billing', r'upcoding', r'price.?gouging',
    r'indicted', r'charged', r'convicted', r'sentenced', r'settlement',
    r'takedown', r'crackdown', r'bust', r'sting',
    r'waste.{0,10}abuse', r'embezzl', r'misus', r'divert',
]]

HEALTHCARE_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    r'medicare', r'medicaid', r'tricare', r'health care', r'healthcare',
    r'hospital', r'hospice', r'home health', r'pharmacy', r'opioid',
    r'medical', r'insurance', r'\bcms\b', r'\bhhs\b', r'nursing home',
    r'physician', r'doctor', r'clinic', r'prescription', r'\bdme\b',
    r'telemedicine', r'behavioral health', r'substance abuse',
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

# Tag generation lives in tag_allowlist.py — this module imports auto_tags
# directly so all scrapers stay consistent. Do not redefine tag patterns here.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg):
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
    """Title must contain BOTH a fraud term AND a health care term."""
    has_fraud = any(p.search(title) for p in FRAUD_TERMS)
    has_health = any(p.search(title) for p in HEALTHCARE_TERMS)
    return has_fraud and has_health


def fetch_detail_page(session, url):
    """Fetch a detail page and extract main text content."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        main = (soup.find('main') or soup.find('article') or
                soup.find('div', class_='field-item') or
                soup.find('div', class_='entry-content'))
        if main:
            for tag in main.find_all(['nav', 'footer', 'aside', 'script', 'style']):
                tag.decompose()
            return re.sub(r'\s+', ' ', main.get_text(' ', strip=True))
        return ""
    except Exception as e:
        log(f"    Detail fetch failed for {url}: {e}")
        return ""


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


def extract_amount(text):
    m = re.search(r'\$[\d,]+(?:\.\d+)?\s*billion', text, re.IGNORECASE)
    if m:
        num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('billion', '')))
        return {"display": m.group(), "numeric": num * 1e9}
    m = re.search(r'\$[\d,]+(?:\.\d+)?\s*million', text, re.IGNORECASE)
    if m:
        num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('million', '')))
        return {"display": m.group(), "numeric": num * 1e6}
    # Shorthand: $350M, $10.6B
    m = re.search(r'\$([\d,]+(?:\.\d+)?)\s*B\b', text)
    if m:
        num = float(m.group(1).replace(',', ''))
        return {"display": m.group(), "numeric": num * 1e9}
    m = re.search(r'\$([\d,]+(?:\.\d+)?)\s*M\b', text)
    if m:
        num = float(m.group(1).replace(',', ''))
        return {"display": m.group(), "numeric": num * 1e6}
    return None


def generate_tags(text):
    """Generate tags restricted to the canonical allowlist."""
    return _auto_tags(text)


def get_state(text):
    for name, abbr in STATE_MAP.items():
        if re.search(r'\b' + re.escape(name) + r'\b', text):
            return abbr
    return None


def make_id(date_str, link):
    h = abs(int(hashlib.md5(link.encode()).hexdigest()[:8], 16))
    return f"media-{date_str}-{h}"


def guess_related_agency(text):
    """Guess the most relevant federal agency from the text."""
    lower = text.lower()
    if re.search(r'\bdoj\b|department of justice|u\.s\. attorney|justice department', lower):
        return 'DOJ'
    if re.search(r'\boig\b|inspector general|hhs-oig', lower):
        return 'HHS-OIG'
    if re.search(r'\bcms\b|centers for medicare', lower):
        return 'CMS'
    if re.search(r'\bfda\b|food and drug', lower):
        return 'FDA'
    if re.search(r'\bdea\b|drug enforcement', lower):
        return 'DEA'
    if re.search(r'\bgao\b|government accountability', lower):
        return 'GAO'
    return ''


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log("=== Media Investigations Scraper ===")

    # Load existing media data
    if os.path.exists(MEDIA_FILE):
        with open(MEDIA_FILE, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    else:
        data = {"metadata": {"last_updated": "", "version": "1.0"}, "stories": []}

    # Date cutoff: only add entries on or after the last run date
    last_run_raw = data["metadata"].get("last_updated", "")
    last_run_date = last_run_raw[:10] if last_run_raw else "2025-01-01"
    log(f"Last run date: {last_run_date} — skipping entries before this date")

    # Build dedup sets from existing entries
    existing_links = set()
    existing_titles = set()
    for s in data.get("stories", []):
        if s.get("link"):
            existing_links.add(s["link"])
        existing_titles.add(re.sub(r'[^a-z0-9 ]', '', s.get("title", "").lower()).strip())

    session = create_session()
    new_stories = []

    for feed in MEDIA_FEEDS:
        log(f"Fetching {feed['name']}...")
        try:
            resp = session.get(feed["url"], timeout=15)
            parsed = feedparser.parse(resp.content)
            if not parsed.entries:
                log(f"  {feed['name']}: 0 entries in feed.")
                continue

            count = 0
            for entry in parsed.entries[:30]:  # Check up to 30 recent entries
                title = entry.get('title', '').strip()
                if not title:
                    continue
                # Strip any HTML tags from title (some feeds wrap in <a> tags)
                # First extract link from <a> tag if present
                if '<a ' in title:
                    soup_title = BeautifulSoup(title, 'lxml')
                    a_tag = soup_title.find('a')
                    if a_tag and a_tag.get('href'):
                        title = a_tag.get_text(strip=True)
                    else:
                        title = clean_html(title)
                else:
                    title = clean_html(title)

                # Must match both fraud AND health care keywords in title
                if not title_matches(title):
                    continue

                link = entry.get('link', '')
                # Skip Google News redirects
                if link and 'news.google.com' in link:
                    continue

                # Dedup by link
                if link and link in existing_links:
                    continue

                # Dedup by normalized title
                norm_title = re.sub(r'[^a-z0-9 ]', '', title.lower()).strip()
                if norm_title in existing_titles:
                    continue

                # Parse date
                date_str = ''
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        date_str = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                    except Exception:
                        pass
                if not date_str:
                    date_str = parse_date(entry.get('published', ''))

                # Enforce Jan 2025 cutoff and last-run date cutoff
                if date_str < '2025-01-01':
                    continue
                if date_str < last_run_date:
                    continue

                # Get description from RSS summary
                desc_raw = entry.get('summary', '') or entry.get('description', '')
                desc_clean = clean_html(desc_raw)

                # If summary is short, try fetching detail page
                if len(desc_clean) < 100 and link:
                    detail_text = fetch_detail_page(session, link)
                    if detail_text:
                        desc_clean = detail_text[:600].strip()
                        if len(detail_text) > 600:
                            last_period = desc_clean.rfind('.')
                            if last_period > 200:
                                desc_clean = desc_clean[:last_period + 1]

                search_text = f"{title} {desc_clean}"
                # Media tab never shows dollar amounts — see project memory.
                amt_info = None
                state = get_state(search_text)
                tags = generate_tags(search_text)
                related = guess_related_agency(search_text)

                # NOTE: description field is intentionally NOT written.
                # See tag_allowlist.py and project memory for details.
                story = {
                    "id": make_id(date_str, link),
                    "date": date_str,
                    "agency": "Media",
                    "type": "Investigative Report",
                    "title": re.sub(r'\s+', ' ', title).strip(),
                    "amount": amt_info['display'] if amt_info else "",
                    "amount_numeric": amt_info['numeric'] if amt_info else 0,
                    "officials": [],
                    "link": link,
                    "link_label": f"{feed['label']} Report",
                    "social_posts": [],
                    "tags": _filter_tags(tags),
                    "state": state or "",
                    "source_type": "news",
                    "auto_fetched": True,
                    "entities": [],
                    "related_agencies": related,
                }

                new_stories.append(story)
                existing_links.add(link)
                existing_titles.add(norm_title)
                count += 1
                log(f"  + {title[:80]}")

            log(f"  {feed['name']}: {count} new stories found.")

        except Exception as e:
            log(f"  WARNING: {feed['name']} - {e}")

    if new_stories:
        # Insert new stories at the top, sorted by date descending
        new_stories.sort(key=lambda s: s['date'], reverse=True)
        data['stories'] = new_stories + data['stories']
        data['metadata']['last_updated'] = datetime.now().isoformat()

        with open(MEDIA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log(f"\n=== Added {len(new_stories)} new stories ===")
        for s in new_stories:
            log(f"  [{s['date']}] {s['title'][:80]}")
    else:
        # Still update timestamp
        data['metadata']['last_updated'] = datetime.now().isoformat()
        with open(MEDIA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log("\n=== No new stories found ===")

    return len(new_stories)


if __name__ == '__main__':
    added = main()
    sys.exit(0)
