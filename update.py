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
OVERSIGHT_KEYWORDS = [re.compile(p, re.IGNORECASE) for p in [
    # Congressional oversight verbs
    r'\bhearing\b', r'\btestimony\b', r'\btestif', r'\bsubcommittee\b',
    r'\bcommittee\s+(hearing|held|vote|investigat|markup)',
    r'\b(demand|demands|press(es)?\s+for|calls?\s+for)\s+(answers|action|hearings?|investigation|accountability)',
    r'\bopen(s|ed)?\s+(an?\s+)?investigation',
    r'\blaunch(es|ed)?\s+(an?\s+)?investigation',
    r'\bexpand(s|ed|ing)?\s+(an?\s+)?investigation',
    r'\bsubpoena',
    r'\bletter\s+(to|from|demanding|requesting)',
    r'\bchairman\b', r'\branking\s+member\b', r'\bsenator\b',
    # Reports + audits + program integrity
    r'\baudit\b', r'\bsemiannual\s+report\b', r'\bgao\s+report\b',
    r'\bpolicy\s+brief\b', r'\bissue\s+brief\b', r'\breport\s+to\s+congress',
    r'\bfindings\b', r'\bimproper\s+payment',
    r'\bprogram\s+integrity\b', r'\bfraud,?\s+waste,?\s+and\s+abuse\b',
    r'\b(top|major)\s+management\s+challenges',
    # Rules + advisories + corrective action
    r'\bfinal\s+rule\b', r'\bproposed\s+rule\b', r'\binterim\s+final\s+rule\b',
    r'\badvisory\b', r'\balert\b', r'\bbulletin\b', r'\bnotice\b', r'\bguidance\b',
    r'\bcorrective\s+action', r'\bmoratorium\b', r'\bsuspension\b',
    r'\b(withholding|deferral)\s+of\s+funds?',
    # Generic fraud language (shared with enforcement)
    r'\bfraud\b', r'\bscheme\b', r'\bkickback', r'\bfalse\s+claims?\b',
]]

KEYWORDS = [re.compile(p, re.IGNORECASE) for p in [
    # Generic fraud/scheme verbs — must also pass HEALTHCARE_TERMS for a
    # healthcare-context match, so 'fraud' alone is safe here.
    r'\bfraud\b', r'\bscheme\b',
    # False Claims Act and related civil-settlement language
    r'false claims', r'false billing', r'improper billing',
    r'\bfca\b', r'\bqui tam\b', r'stark law', r'anti-?kickback',
    r'\bkickback', r'overbilling', r'upcoding', r'unbundl',
    r'phantom billing', r'pill mill', r'drug diversion',
    # Charges / convictions
    r'plead[s ]? guilty', r'convict', r'sentenc',
    r'indict', r'charge[sd]? with', r'arrest',
    # Civil settlements
    r'agree.*(to )?pay', r'settlement', r'\bsettles?\b', r'consent (judgment|decree)',
    # Program integrity + enforcement language
    r'program integrity', r'health care fraud', r'healthcare fraud',
    r'\bfca\b', r'enrollment fraud', r'billing fraud',
    r'takedown', r'strike force',
    # Criminal drug distribution (controlled substance cases by licensed
    # providers — these are health care crimes when the defendant is
    # a doctor/pharmacist/pill mill operator)
    r'illegally distribut', r'unlawful distribut',
    # DME / durable medical (always fraud-adjacent in this context)
    r'durable medical', r'\bdme\b', r'dmepos',
]]

HEALTHCARE_TERMS = [re.compile(p, re.IGNORECASE) for p in [
    r'medicare', r'medicaid', r'tricare', r'health care', r'healthcare', r'hospital',
    r'clinic', r'physician', r'\bdoctor\b', r'\bnurse\b', r'medical', r'patient',
    r'prescription', r'pharmacist', r'pharmacy', r'hospice', r'home health',
    r'nursing home', r'assisted living',
    r'\bcms\b', r'\bhhs\b', r'\boig\b', r'health insurance', r'health plan',
    r'clinical', r'diagnosis', r'therapy', r'dental fraud', r'ambulance fraud',
    r'\bdme\b', r'durable medical', r'behavioral health', r'substance abuse',
    r'affordable care act', r'aca enrollment', r'chip program',
    # Opioid / pill mill language. NOTE: we intentionally do NOT include
    # 'fentanyl' / 'oxycodone' / 'hydrocodone' / 'controlled substance'
    # here — those terms dominate DOJ DEA street-level trafficking cases
    # which are NOT healthcare fraud. Keep 'pill mill' and 'opioid pills'
    # because those pattern-match provider-based prescription fraud.
    r'pill mill', r'opioid pills', r'opioid prescri',
    # Reimbursement / billing language
    r'reimbursement', r'medication', r'\bstark law\b',
]]

# ---------------------------------------------------------------------------
# Feed definitions
# ---------------------------------------------------------------------------
FEEDS = [
    # --- Official agency feeds ---
    # DOJ-OPA is the canonical source for /opa/pr/ items (topic-tag-gated).
    {"name": "DOJ-OPA",     "agency": "DOJ",          "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "doj_opa"},
    # DOJ "Justice News" RSS (justice.gov/news/rss) is DISABLED: the feed
    # is dominated by FOIA training events + unrelated USAO scraps, and
    # the occasional /opa/pr/ item it carries is already caught by
    # DOJ-OPA (with proper topic-tag provenance) or lands via HHS-OIG's
    # link extraction. Keeping it enabled only introduced a race where
    # OPA items landed in actions.json without doj_topics.
    {"name": "DOJ",         "agency": "DOJ",          "url": "https://www.justice.gov/news/rss",                                          "enabled": False, "source_type": "official", "browser_fallback": True},
    {"name": "HHS-OIG",     "agency": "HHS-OIG",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "oig"},
    {"name": "CMS",         "agency": "CMS",           "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "cms"},
    {"name": "HHS",         "agency": "HHS",           "url": "https://www.hhs.gov/rss/news.xml",                                         "enabled": False, "source_type": "official", "browser_fallback": True},
    {"name": "DOJ-USAO",    "agency": "DOJ",           "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "doj_usao"},
    {"name": "GAO",         "agency": "GAO",           "url": "https://www.gao.gov/rss/reports.xml",                                      "enabled": True,  "source_type": "official", "browser_fallback": True},
    {"name": "H-Oversight", "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "h_oversight"},
    {"name": "H-E&C",       "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "energy_commerce"},
    {"name": "S-Finance",   "agency": "Congress",      "url": "https://www.finance.senate.gov/rss/feeds/?type=press",                     "enabled": True,  "source_type": "official", "browser_fallback": True},
    {"name": "S-HELP",      "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "help_committee"},
    {"name": "H-W&M",       "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "ways_means"},
    {"name": "HHS-OIG-RPT", "agency": "HHS-OIG",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "oig_reports"},
    {"name": "HHS-OIG-PR",  "agency": "HHS-OIG",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "oig_press"},
    # --- Congressional Judiciary committees (HC fraud oversight of DOJ) ---
    {"name": "S-Judiciary",  "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "senate_judiciary"},
    {"name": "H-Judiciary",  "agency": "Congress",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "house_judiciary"},
    {"name": "FDA",         "agency": "FDA",           "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "enabled": False, "source_type": "official"},
    {"name": "DEA",         "agency": "DEA",           "url": "https://www.dea.gov/press-releases/rss",                                   "enabled": True,  "source_type": "official", "browser_fallback": True},
    # --- Commissions + Treasury anti-fraud (added Tier 2) ---
    {"name": "MedPAC",      "agency": "MedPAC",        "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "medpac"},
    {"name": "MACPAC",      "agency": "MACPAC",        "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "macpac"},
    {"name": "FinCEN",      "agency": "Treasury",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "fincen"},
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

def test_any_oversight_keyword(text):
    """Oversight-mode keyword check. Accepts oversight vocabulary
    (hearings, investigations, demand letters, audits, reports, rules,
    advisories, etc.) that the enforcement-oriented KEYWORDS list
    doesn't catch. In oversight mode the main loop uses this OR the
    enforcement KEYWORDS list to qualify items.
    """
    for pat in OVERSIGHT_KEYWORDS:
        if pat.search(text):
            return True
    return False

def test_healthcare_context(text):
    for pat in HEALTHCARE_TERMS:
        if pat.search(text):
            return True
    return False

def get_action_type(title, desc, agency=None, link=None):
    """Classify a scraped item into one of ~11 action types.

    Title-only checks run first, in priority order, so a criminal
    prosecution press release whose body text mentions "court hearing"
    or "testified" doesn't get mislabeled as a Congressional Hearing.
    Full text is only consulted as a fallback for ambiguous titles.

    If `agency` or `link` is provided, they're used as source hints:
      - MedPAC / MACPAC sources default to 'Report' unless the title
        clearly indicates otherwise
      - FinCEN sources default to 'Administrative Action' (advisories)
      - The fallback 'Audit' classification only fires when the source
        is HHS-OIG or GAO, avoiding the old bug where any release
        containing the word 'audit' in its body got labeled Audit
    """
    title_l = (title or '').lower()
    full_text = f"{title} {desc}".lower()
    agency_l = (agency or '').lower()
    link_l = (link or '').lower()

    # Source hints — used both early (for commission reports) and late
    # (for disambiguating the Audit fallback)
    is_oig = 'oig' in agency_l or 'oig.hhs.gov' in link_l
    is_gao = 'gao' in agency_l or 'gao.gov' in link_l
    is_medpac = 'medpac' in agency_l or 'medpac.gov' in link_l
    is_macpac = 'macpac' in agency_l or 'macpac.gov' in link_l
    is_fincen = 'fincen' in agency_l or 'fincen.gov' in link_l or 'treasury' in agency_l

    # ---- Title-only enforcement detection (highest priority) ----
    if re.search(r'\b(plead|pleads|pleaded|convict|convicted|indict|indicted|'
                 r'charg(ed|es|ing)|guilty|sentenc(e|ed|ing)|arrest(ed)?|'
                 r'prosecut(ed|ion)?)\b', title_l):
        return 'Criminal Enforcement'
    if re.search(r'\b(settlement|settles?|to pay|agree(s|d)? to pay|consent (judgment|decree)|'
                 r'civil action|false claims act|qui tam)\b', title_l):
        return 'Civil Action'

    # ---- Title-only legislation/hearing/report detection ----
    if re.search(r'signed into law|enacted|passes bill|bill signed|legislation|'
                 r'executive order|presidential memo|law.*(takes|went) effect',
                 title_l):
        return 'Legislation'
    if re.search(r'\b(hearing|testimony|testifies?|subcommittee hearing|'
                 r'committee (hearing|held|examines?|votes?))\b', title_l):
        return 'Congressional Hearing'
    if re.search(r'\b(audit|inspection|evaluation report)\b', title_l):
        return 'Audit'
    if re.search(r'\b(senate report|house report|congressional report|'
                 r'gao (report|finds)|report to the congress|report to congress)\b', title_l):
        return 'Report'
    # MedPAC/MACPAC publications default to Report (any publication from
    # these commissions is either a report to Congress, issue brief, or
    # comment letter — all "report"-like)
    if is_medpac or is_macpac:
        return 'Report'
    # FinCEN advisories/alerts default to Administrative Action
    if is_fincen and re.search(r'\b(advisor|alert|guidance|notice|bulletin)\b', title_l):
        return 'Administrative Action'
    if re.search(r'\b(rule|regulation|final rule|proposed rule|loophole)\b', title_l):
        return 'Rule/Regulation'
    if re.search(r'\b(task force|strike force|division|unit) (created|formed|launched|announced)\b', title_l):
        return 'Structural/Organizational'
    if re.search(r'\b(launches? (an? )?investigation|opens? (an? )?investigation|'
                 r'fact.?find(ing)?|sends?.*(letter|inquiry))\b', title_l):
        return 'Investigation'

    # ---- Fall back to full-text checks for ambiguous titles ----
    if re.search(r'plead|convict|indict|charg|guilty|arrest|prosecut', full_text):
        return 'Criminal Enforcement'
    if re.search(r'civil|settlement|false claims act', full_text):
        return 'Civil Action'
    # Tightened: only classify as Audit in the fallback tier if the source
    # is actually an audit agency (HHS-OIG or GAO). Previously any body
    # text containing the word "report" or "review" got mislabeled Audit.
    if (is_oig or is_gao) and re.search(r'audit|review|report|evaluation|inspection', full_text):
        return 'Audit'
    if re.search(r'rule|regulation|loophole', full_text):
        return 'Rule/Regulation'
    if re.search(r'task force|strike force', full_text):
        return 'Structural/Organizational'
    if re.search(r'investigat|fact.?find', full_text):
        return 'Investigation'
    if re.search(r'\bai\b|artificial intelligence|machine learning', full_text):
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

# Site-specific suffixes that pollute <title> tags. Stripped during
# canonical-title extraction so item titles match the actual headline.
TITLE_SUFFIX_PATTERNS = [
    " | United States Department of Justice",
    " | DEA.gov",
    " | U.S. Department of the Treasury",
    " | CMS",
    " | HHS.gov",
    " | Office of Inspector General | Government Oversight | U.S. Department of Health and Human Services",
    " | Office of Inspector General",
    " | U.S. GAO",
    " | U.S. Government Accountability Office (U.S. GAO)",
    " | The United States Senate Committee on Finance",
    " | Energy and Commerce Committee",
    " - United States Senate Committee on Health, Education, Labor and Pensions",
    " | House Committee on Ways and Means",
    " | Committee on Oversight and Accountability",
]
TITLE_PREFIX_RE = re.compile(
    r"^(?:Office of Public Affairs|Central District of California|"
    r"Eastern District of [A-Za-z ]+|Western District of [A-Za-z ]+|"
    r"Northern District of [A-Za-z ]+|Southern District of [A-Za-z ]+|"
    r"District of [A-Za-z ]+|Middle District of [A-Za-z ]+)\s*\|\s*"
)
BAD_TITLES = {"Access Denied", "Just a moment...", "Page Not Found", ""}

# Bare site-name patterns that some sites put in their og:title (FinCEN,
# Treasury, etc.) instead of the actual page title. If we see one of these
# we fall through to h1/title instead of using og:title.
BARE_SITE_NAME_RE = re.compile(
    r'^(fincen|treasury|hhs|cms|dea|gao|medpac|macpac|justice|doj)\.gov$',
    re.IGNORECASE,
)


def normalize_page_title(raw):
    """Strip boilerplate breadcrumb prefixes and site suffixes from a
    fetched <title>/<h1> string. Used to derive canonical item titles
    from press release detail pages.
    """
    if not raw:
        return ""
    t = raw.strip()
    for suf in sorted(TITLE_SUFFIX_PATTERNS, key=len, reverse=True):
        if t.endswith(suf):
            t = t[: -len(suf)].rstrip()
    t = TITLE_PREFIX_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("\u00a0", " ").strip()
    return t


def _looks_like_bad_title(t):
    if not t:
        return True
    s = t.strip()
    if s in BAD_TITLES:
        return True
    if len(s) < 10:
        return True
    if "Just a moment" in s or "Access Denied" in s or "Page Not Found" in s:
        return True
    # Reject bare site names (e.g. some FinCEN/Treasury pages put "FinCEN.gov"
    # in og:title instead of the real page title)
    if BARE_SITE_NAME_RE.match(s):
        return True
    return False


def fetch_detail_page(session, url):
    """Fetch a detail page and return (text, doj_link, canonical_title).

    The canonical_title is extracted from (in order of preference):
      1. <meta property="og:title">
      2. <h1> on the page
      3. <title> tag, stripped of site/breadcrumb boilerplate
    Returns "" for canonical_title if nothing usable was found — callers
    should fall back to the listing-page link text in that case.
    """
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
        # Extract canonical title — try og:title, h1, then <title>
        canonical_title = ""
        og = soup.find('meta', attrs={'property': 'og:title'})
        if og and og.get('content'):
            cand = normalize_page_title(og['content'])
            if not _looks_like_bad_title(cand):
                canonical_title = cand
        if not canonical_title:
            h1 = soup.find('h1')
            if h1:
                cand = normalize_page_title(h1.get_text(strip=True))
                if not _looks_like_bad_title(cand):
                    canonical_title = cand
        if not canonical_title:
            title_tag = soup.find('title')
            if title_tag:
                cand = normalize_page_title(title_tag.get_text(strip=True))
                if not _looks_like_bad_title(cand):
                    canonical_title = cand
        # Try common content containers
        main = (soup.find('main') or soup.find('article') or
                soup.find('div', class_='field-item') or
                soup.find('div', class_='entry-content'))
        if main:
            for tag in main.find_all(['nav', 'footer', 'aside', 'script', 'style']):
                tag.decompose()
            return re.sub(r'\s+', ' ', main.get_text(' ', strip=True)), doj_link, canonical_title
        return "", doj_link, canonical_title
    except Exception as e:
        log(f"    Detail fetch failed for {url}: {e}")
        return "", None, ""

def make_id(prefix, date_str, link, agency=""):
    hash_input = link or (date_str + agency)
    h = abs(int(hashlib.md5(hash_input.encode()).hexdigest()[:8], 16))
    return f"{prefix}-{date_str}-{h}"

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    return re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()


def normalize_link(url):
    """Canonicalize a URL for dedup purposes.

    - Lowercase scheme and host
    - Drop 'www.' prefix
    - Strip trailing slash from path
    - Drop URL fragments (#anchor)
    - Drop tracking query params (utm_*, fbclid, etc.)
    Returns an empty string for empty input.

    Used so that 'https://www.justice.gov/opa/pr/foo/',
    'https://justice.gov/opa/pr/foo', and
    'https://www.justice.gov/opa/pr/foo#section' all collapse to
    the same dedup key.
    """
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except Exception:
        return url.strip().lower()
    scheme = (p.scheme or 'https').lower()
    host = (p.netloc or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = p.path or ''
    # Strip trailing slash UNLESS it's the root path
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')
    # Drop tracking params
    query = ''
    if p.query:
        keep = []
        for kv in p.query.split('&'):
            if not kv:
                continue
            k = kv.split('=', 1)[0].lower()
            if k.startswith('utm_') or k in ('fbclid', 'gclid', 'mc_cid', 'mc_eid', 'bm-verify'):
                continue
            keep.append(kv)
        if keep:
            query = '?' + '&'.join(keep)
    return f"{scheme}://{host}{path}{query}"

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
                # Fetch OIG detail page — also extracts DOJ press release link
                # and canonical headline (h1/og:title)
                detail_text, doj_link, canonical_title = fetch_detail_page(session, href)
                # If DOJ press release exists, use it as the canonical link.
                canonical_link = doj_link if doj_link else href
                # In normal mode we also fetch the DOJ press release text to
                # get better tag/amount extraction. In backfill mode we skip
                # that second fetch — justice.gov bot-blocks most of the time
                # and we don't store descriptions anyway, so the incremental
                # quality isn't worth the latency or failure rate.
                if doj_link and not backfill:
                    doj_text, _, doj_canonical = fetch_detail_page(session, doj_link)
                    if doj_text:
                        detail_text = doj_text  # use DOJ text for description/tags
                    if doj_canonical:
                        canonical_title = doj_canonical  # prefer DOJ headline
                # Override listing-page title with the canonical headline
                if canonical_title:
                    title = canonical_title
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
            # Fetch detail page for description and canonical title
            detail_text, _, canonical_title = fetch_detail_page(session, href)
            if canonical_title:
                title = canonical_title
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

def scrape_h_oversight(session):
    """Scrape House Oversight Committee press releases using Playwright.

    The old RSS feed (/feed/) is stale — it returns 2020-era items from
    a legacy WordPress install that's no longer maintained. The current
    press release listing lives at /release/ and is rendered
    server-side with JS that the browser can read.
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping H-Oversight (requires Playwright)")
        return []
    url = "https://oversight.house.gov/release/"
    items = []
    try:
        soup = scrape_page_with_browser(url)
        for a_tag in soup.find_all('a', href=re.compile(r'oversight\.house\.gov/release/')):
            href = a_tag.get('href', '')
            txt = a_tag.get_text(' ', strip=True)
            if not txt or len(txt) < 30:
                continue
            # Anchor text format:  "Press ReleaseHeadline HereApril 1, 2026WASHINGTON..."
            # Extract headline by stripping the "Press Release" prefix and
            # finding the date anchor
            m = re.match(
                r'Press Release(.+?)(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                txt)
            if m:
                title = m.group(1).strip()
                date_str = txt[m.end(1):].strip()
                date_m = re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    date_str)
                date_str = date_m.group() if date_m else ""
            else:
                title = txt.replace('Press Release', '', 1).strip()
                date_str = ""
            if not title:
                continue
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
        log(f"  WARNING: H-Oversight scrape - {e}")
    return items


def scrape_oig_press(session):
    """Scrape HHS-OIG newsroom press releases.

    Separate from the enforcement listing (/fraud/enforcement/) and the
    reports listing (/reports/all/). The newsroom announces semiannual
    reports, enforcement results, policy statements, and data briefs
    that don't always appear on the other two pages.

    Source: oig.hhs.gov/newsroom/news-releases-articles/
    """
    url = "https://oig.hhs.gov/newsroom/news-releases-articles/"
    items = []
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for card in soup.select('li.usa-card'):
            a_tag = card.select_one('h2.usa-card__heading a')
            if not a_tag:
                a_tag = card.select_one('a[href]')
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = 'https://oig.hhs.gov' + href
            # Extract date from card metadata
            date_str = ""
            date_span = card.select_one('span.text-base-dark')
            if date_span:
                date_str = date_span.get_text(strip=True)
            if not date_str:
                dm = re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    card.get_text(' ', strip=True))
                if dm:
                    date_str = dm.group()
            # Fetch detail page for body text + canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
        log(f"  WARNING: OIG press scrape - {e}", "yellow")
    return items


# Pre-filter for congressional committee scrapers. Only return items
# whose title OR body text mentions a healthcare fraud concept. This
# prevents immigration, SCOTUS nomination, defense spending, and other
# non-HC Judiciary items from entering the pipeline.
_CONGRESS_HC_PREFILTER = re.compile(
    r'\b(medicare|medicaid|medi-?cal|tricare|health\s*care|healthcare|'
    r'hospital|hospice|home\s+health|nursing\s+(home|facility)|'
    r'pharmacy|pharmacist|prescription|opioid|fentanyl|pill\s+mill|'
    r'physician|doctor|clinic|medical|patient|'
    r'insurance\s+(fraud|ceo|compan|executive)|'
    r'false\s+claims?\s+act|anti-?kickback|stark\s+law|'
    r'program\s+integrity|improper\s+payment|'
    r'fraud.{0,15}(waste|abuse)|'
    r'dme|durable\s+medical|genetic\s+test|telehealth|'
    r'cms\b|hhs\b|oig\b|fda\b)\b',
    re.IGNORECASE,
)


def scrape_senate_judiciary(session):
    """Scrape Senate Judiciary Committee press releases.

    The Senate Judiciary Committee publishes mostly non-HC content
    (immigration, SCOTUS, defense). We pre-filter aggressively on HC
    keywords in the title, and if the title is ambiguous, we fetch the
    detail page and check the body text too. Only items that pass the
    HC pre-filter are returned to the main loop for normal processing.

    Source: judiciary.senate.gov/press/majority + /press/minority
    """
    items = []
    for path in ['/press/majority', '/press/minority']:
        url = f"https://www.judiciary.senate.gov{path}"
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200:
                log(f"    S-Judiciary {path}: HTTP {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, 'lxml')
            for h3 in soup.find_all('h3'):
                a_tag = h3.find('a', href=True)
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 15:
                    continue
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.judiciary.senate.gov' + href
                # Date — look for sibling p.Heading--time (format MM.DD.YYYY)
                date_str = ""
                parent = h3.find_parent(['div', 'li', 'article'])
                if parent:
                    date_el = parent.find('p', class_=re.compile(r'Heading--time'))
                    if date_el:
                        dm = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_el.get_text())
                        if dm:
                            date_str = f"{dm.group(3)}-{dm.group(1)}-{dm.group(2)}"
                # Pre-filter: title must mention HC.
                # If ambiguous, fetch body and check there.
                title_passes = bool(_CONGRESS_HC_PREFILTER.search(title))
                detail_text = ""
                _detail_title = ""
                if not title_passes:
                    # Fetch body for second-chance check
                    try:
                        detail_text, _, _detail_title = fetch_detail_page(session, href)
                    except Exception:
                        pass
                    if detail_text and _CONGRESS_HC_PREFILTER.search(detail_text):
                        title_passes = True
                if not title_passes:
                    continue
                # If we didn't fetch yet (title passed on first check), fetch now
                if not detail_text:
                    try:
                        detail_text, _, _detail_title = fetch_detail_page(session, href)
                    except Exception:
                        pass
                if _detail_title:
                    title = _detail_title
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
            log(f"  WARNING: S-Judiciary {path} scrape - {e}")
    return items


def scrape_house_judiciary(session):
    """Scrape House Judiciary Committee press releases using Playwright.

    The House Judiciary site is JS-rendered (Drupal with client-side
    listing). Playwright is required. Same aggressive HC pre-filter
    as Senate Judiciary.

    Source: judiciary.house.gov/news
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping H-Judiciary (requires Playwright)")
        return []
    items = []
    try:
        soup = scrape_page_with_browser("https://judiciary.house.gov/news")
        # Look for press release anchors — modern Drupal uses /media/press-releases/
        # or /news/documentsingle type patterns
        seen = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 20:
                continue
            if href in seen:
                continue
            # Only follow links that look like press releases
            if not re.search(r'judiciary\.house\.gov/.*(press|release|news)', href, re.I):
                if not href.startswith('/'):
                    continue
            seen.add(href)
            if href.startswith('/'):
                href = 'https://judiciary.house.gov' + href
            # Pre-filter on HC keywords in title
            if not _CONGRESS_HC_PREFILTER.search(title):
                continue
            # Extract date from parent if visible
            parent = a_tag.find_parent(['div', 'li', 'article', 'tr'])
            date_str = ""
            if parent:
                dm = re.search(
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}',
                    parent.get_text(' ', strip=True))
                if dm:
                    date_str = dm.group()
            # Fetch detail page
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
        log(f"  WARNING: H-Judiciary scrape - {e}")
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
            # Fetch detail page for description and canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
            # Fetch detail page for description and canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
            # Fetch detail page for description and canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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

def scrape_doj_opa(session):
    """Scrape DOJ Office of Public Affairs press releases using Playwright.

    This is THE canonical source for DOJ OPA releases (healthcare fraud
    takedowns, FCA settlements, major criminal cases). The DOJ 'Justice
    News' RSS feed (justice.gov/news/rss) does NOT include OPA releases
    — it's a mishmash of FOIA training events and USAO scraps — so for
    a long time OPA releases were only caught incidentally when HHS-OIG
    linked to them. This scraper closes that gap.

    INCLUSION RULE: Items are gated by the DOJ-assigned topic tag
    extracted from the detail page's .node-topics field. If DOJ tagged
    the release as 'Health Care Fraud' we include it unconditionally;
    otherwise we skip it. This matches the project rule
    (project_doj_topic_authoritative.md) — defer to DOJ's classification
    rather than second-guess it with regex keyword filters.

    Items returned by this scraper are marked with `_trust_source: True`
    so the main loop bypasses its regex HC-keyword filter (which was
    only needed because most sources don't provide topic tags). The
    DOJ topic list is stored on the item as `doj_topics` for provenance.

    The listing page is Akamai-protected; Playwright is required.
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping DOJ-OPA (requires Playwright)")
        return []
    url = "https://www.justice.gov/news/press-releases"
    items = []
    # Import topic helpers from audit_new_items so we share a single
    # source of truth for DOJ topic vocab + "Health Care Fraud" check.
    try:
        from audit_new_items import fetch_doj_topics, has_hc_topic
    except ImportError as e:
        log(f"  DOJ-OPA: cannot import topic helpers: {e}")
        return []
    try:
        soup = scrape_page_with_browser(url)
        candidates = []
        seen = set()
        for a_tag in soup.find_all('a', href=re.compile(r'^/opa/pr/')):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 20:
                continue
            href = a_tag.get('href', '')
            if href in seen:
                continue
            seen.add(href)
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
            candidates.append((title, href, date_str))

        log(f"    DOJ-OPA: {len(candidates)} candidates, checking topic tags...")
        # Get a reusable Playwright page for topic extraction
        browser = get_browser()
        page = None
        if browser is not None:
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
            )
            page = ctx.new_page()
        try:
            kept = 0
            for (title, href, date_str) in candidates:
                # Gate 1: DOJ topic tag check — authoritative
                topics = fetch_doj_topics(href, page=page)
                if not has_hc_topic(topics):
                    # Not tagged by DOJ as Health Care Fraud — skip entirely
                    continue
                # Gate 2: extract canonical title + body via a requests
                # fetch (justice.gov/opa/pr/* works fine with requests,
                # unlike the Akamai-protected listing page)
                detail_text, _, canonical_title = fetch_detail_page(session, href)
                if canonical_title:
                    title = canonical_title
                if not date_str and detail_text:
                    dm = re.search(
                        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                        detail_text)
                    if dm:
                        date_str = dm.group()
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
                    '_trust_source': True,  # bypass HC keyword filter
                    '_doj_topics': topics,  # store for provenance
                })
                kept += 1
            log(f"    DOJ-OPA: {kept} of {len(candidates)} candidates tagged 'Health Care Fraud'")
        finally:
            if page is not None:
                try:
                    page.context.close()
                except Exception:
                    pass
    except Exception as e:
        log(f"  WARNING: DOJ-OPA scrape - {e}")
    return items


def scrape_doj_usao(session):
    """Scrape DOJ USAO (district-level) press releases using Playwright.

    Uses the same topic-tag gate as scrape_doj_opa: each candidate's
    detail page is checked for a 'Health Care Fraud' tag in its
    .node-topics field, and items without that tag are skipped. This
    defers to DOJ's own classification (project_doj_topic_authoritative.md)
    instead of guessing from title keywords. Items that pass carry
    _trust_source + _doj_topics for provenance.

    The listing page is Akamai-protected; Playwright is required.
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping DOJ-USAO (requires Playwright)")
        return []
    url = "https://www.justice.gov/usao/pressreleases"
    items = []
    try:
        from audit_new_items import fetch_doj_topics, has_hc_topic
    except ImportError as e:
        log(f"  DOJ-USAO: cannot import topic helpers: {e}")
        return []
    try:
        soup = scrape_page_with_browser(url)
        candidates = []
        seen = set()
        for a_tag in soup.find_all('a', href=re.compile(r'/usao-.*/pr/')):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a_tag.get('href', '')
            if href in seen:
                continue
            seen.add(href)
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
            candidates.append((title, href, date_str))

        log(f"    DOJ-USAO: {len(candidates)} candidates, checking topic tags...")
        browser = get_browser()
        page = None
        if browser is not None:
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
            )
            page = ctx.new_page()
        try:
            kept = 0
            for (title, href, date_str) in candidates:
                # Topic tag gate
                topics = fetch_doj_topics(href, page=page)
                if not has_hc_topic(topics):
                    continue
                # Fetch detail page via requests for canonical title + body
                detail_text = ""
                _detail_title = ""
                try:
                    detail_text, _, _detail_title = fetch_detail_page(session, href)
                except Exception:
                    pass
                if _detail_title:
                    title = _detail_title
                if not date_str and detail_text:
                    dm = re.search(
                        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                        detail_text)
                    if dm:
                        date_str = dm.group()
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
                    '_trust_source': True,
                    '_doj_topics': topics,
                })
                kept += 1
            log(f"    DOJ-USAO: {kept} of {len(candidates)} candidates tagged 'Health Care Fraud'")
        finally:
            if page is not None:
                try:
                    page.context.close()
                except Exception:
                    pass
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

        # If RSS summary is short/empty, fetch the detail page (also captures
        # canonical title from h1/og:title to override RSS-provided title)
        desc_clean = clean_html(desc)
        detail_text = ""
        _detail_title = ""
        if link and len(desc_clean) < 100:
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, link)
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
        if _detail_title:
            title = _detail_title

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
                # Skip clean-bill-of-health audits. HHS-OIG uses three
                # stock phrases when an auditee passed compliance review:
                #   "in accordance with"
                #   "Generally Complied With"
                #   "Generally Ensured That"
                # None of these are fraud findings — auditee did the right
                # thing and the OIG is just documenting that. Skip them.
                if re.search(r'\b(in accordance with|generally complied with|'
                             r'generally ensured that)\b', title, re.I):
                    continue
                # Skip IT security / cybersecurity audits — these aren't
                # HC fraud oversight, they're information security reviews.
                if re.search(r'\b(information security program|cybersecurity|'
                             r'security controls to (enhance|prevent|detect))\b',
                             title, re.I):
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
                # Fetch detail page for description and canonical title
                detail_text, _, canonical_title = fetch_detail_page(session, href)
                if canonical_title:
                    title = canonical_title
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


def scrape_medpac(session):
    """Scrape MedPAC documents listing.

    MedPAC publishes Reports to Congress (Mar/Jun), Issue Briefs, Comment
    Letters, and Press Releases. We skip 'Chapters' (sub-documents of the
    Reports) to avoid duplicate coverage. The healthcare-context filter
    in the main loop further narrows these to fraud/program-integrity
    items (most MedPAC work is about payment policy, not fraud).
    """
    url = "https://www.medpac.gov/document/"
    items = []
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for art in soup.select('article.document-archive-item'):
            date_el = art.select_one('.document-archive-item-date')
            type_el = art.select_one('.document-archive-item-type')
            link_el = art.select_one('a.document-archive-item-link')
            if not link_el:
                continue
            date_str = date_el.get_text(strip=True) if date_el else ""
            doc_type = type_el.get_text(strip=True) if type_el else ""
            # Skip chapter sub-documents — the parent Report entry covers them
            if doc_type.lower() == 'chapters':
                continue
            title = link_el.get_text(strip=True)
            href = link_el.get('href', '')
            if not title or not href:
                continue
            # Fetch detail page for description + canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
        log(f"  WARNING: MedPAC scrape - {e}", "yellow")
    return items


def scrape_macpac(session):
    """Scrape MACPAC publications listing.

    MACPAC publishes Reports to Congress (Mar/Jun), Issue Briefs, Comment
    Letters, Chapters. The healthcare-context filter narrows these to
    Medicaid program-integrity items.
    """
    url = "https://www.macpac.gov/publication/"
    items = []
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for art in soup.select('article.publication'):
            header = art.select_one('header.article-header')
            if not header:
                continue
            byline = header.select_one('.byline')
            date_str = byline.get_text(strip=True) if byline else ""
            link_el = header.find('a', href=True)
            if not link_el:
                continue
            title = link_el.get('title') or link_el.get_text(strip=True)
            href = link_el['href']
            if not title or not href:
                continue
            # Skip chapter sub-documents
            class_str = " ".join(art.get('class', []))
            if 'publication-type-chapter' in class_str:
                continue
            # Fetch detail page
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
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
        log(f"  WARNING: MACPAC scrape - {e}", "yellow")
    return items


def scrape_fincen(session):
    """Scrape FinCEN press releases + advisories.

    FinCEN periodically issues healthcare-fraud advisories targeting SAR
    filers. The listing page on the Drupal site renders titles as anchors
    under /news/news-releases/. Dates aren't in the listing HTML (loaded
    dynamically) — we fetch each HC-candidate detail page for the date.
    """
    url = "https://www.fincen.gov/news/press-releases"
    items = []
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        seen_hrefs = set()
        for a in soup.select('a[href^="/news/news-releases/"]'):
            href = a.get('href', '')
            title = a.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            full_href = 'https://www.fincen.gov' + href
            # Pre-filter on title: only fetch detail pages for items that
            # look healthcare-related. FinCEN publishes a LOT of items
            # that aren't about healthcare fraud (Iran sanctions, real
            # estate money laundering, crypto enforcement, etc.).
            if not re.search(r'health\s*care|medicare|medicaid|prescription|'
                             r'hospital|hospice|pharmac|fraud\s+scheme',
                             title, re.I):
                continue
            # Fetch detail page for date + description + canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title = fetch_detail_page(session, full_href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            date_str = ""
            if detail_text:
                date_match = re.search(
                    r'(January|February|March|April|May|June|July|August|'
                    r'September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    detail_text)
                if date_match:
                    date_str = date_match.group()
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
                'link': full_href,
                'pub_date': date_str,
                '_full_text': detail_text,
            })
    except Exception as e:
        log(f"  WARNING: FinCEN scrape - {e}", "yellow")
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
    if scrape_mode == 'doj_opa':
        return scrape_doj_opa(session)
    if scrape_mode == 'h_oversight':
        return scrape_h_oversight(session)
    if scrape_mode == 'oig_press':
        return scrape_oig_press(session)
    if scrape_mode == 'senate_judiciary':
        return scrape_senate_judiciary(session)
    if scrape_mode == 'house_judiciary':
        return scrape_house_judiciary(session)
    if scrape_mode == 'energy_commerce':
        return scrape_energy_commerce(session)
    if scrape_mode == 'help_committee':
        return scrape_help_committee(session)
    if scrape_mode == 'ways_means':
        return scrape_ways_means(session)
    if scrape_mode == 'medpac':
        return scrape_medpac(session)
    if scrape_mode == 'macpac':
        return scrape_macpac(session)
    if scrape_mode == 'fincen':
        return scrape_fincen(session)
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
    parser.add_argument('--oversight-only', action='store_true',
                        help='Inverse of --enforcement-only. Only accept '
                             'items classified as oversight-type (Audit, '
                             'Investigation, Administrative Action, '
                             'Rule/Regulation, Hearing, Report, '
                             'Structural/Organizational, Legislation, '
                             'Congressional Hearing, Technology/Innovation). '
                             'Routes results to data/needs_review_oversight.json '
                             'instead of actions.json. Used by the daily '
                             'oversight pipeline which feeds the Oversight & '
                             'Accountability tab via human/AI review.')
    args = parser.parse_args()
    silent = args.silent
    if args.no_browser:
        HAS_PLAYWRIGHT = False

    log("Loading existing data...")
    data = load_json(DATA_FILE, {"metadata": {"last_updated": "", "version": "1.0"}, "actions": []})

    # Cutoff: backfill mode uses the explicit floor and ignores last_scraped.
    # Normal mode uses last_scraped to only pick up new items since last run.
    # Oversight mode uses its OWN last_scraped key so it doesn't share state
    # with the enforcement pipeline (they run on different schedules).
    if args.backfill_from:
        last_scraped_date = args.backfill_from
        log(f"BACKFILL MODE: floor = {last_scraped_date} (ignoring last_scraped)")
    elif args.oversight_only:
        ov_path_for_cutoff = os.path.join(SCRIPT_DIR, "data", "needs_review_oversight.json")
        if os.path.exists(ov_path_for_cutoff):
            try:
                ov_meta = load_json(ov_path_for_cutoff, {"metadata": {}}).get("metadata", {})
                last_scraped_raw = ov_meta.get("last_scraped", "")
            except Exception:
                last_scraped_raw = ""
        else:
            last_scraped_raw = ""
        last_scraped_date = last_scraped_raw[:10] if last_scraped_raw else "2025-01-01"
        log(f"Last oversight scrape: {last_scraped_date} — skipping older entries")
    else:
        last_scraped_raw = data["metadata"].get("last_scraped") or data["metadata"].get("last_updated", "")
        last_scraped_date = last_scraped_raw[:10] if last_scraped_raw else "2025-01-01"
        log(f"Last scraped date: {last_scraped_date} — skipping entries before this date")

    # Thread backfill flag into scrapers via a module-level variable
    globals()['BACKFILL_MODE'] = bool(args.backfill_from)
    globals()['BACKFILL_FLOOR'] = last_scraped_date
    globals()['OPA_ONLY'] = bool(args.opa_only)
    globals()['ENFORCEMENT_ONLY'] = bool(args.enforcement_only)
    globals()['OVERSIGHT_ONLY'] = bool(args.oversight_only)
    if args.opa_only:
        log("OPA-ONLY MODE: dropping items not linking to /opa/pr/")
    if args.enforcement_only:
        log("ENFORCEMENT-ONLY MODE: dropping items not typed Criminal Enforcement / Civil Action")
    if args.oversight_only:
        log("OVERSIGHT-ONLY MODE: dropping enforcement items, routing to needs_review_oversight.json")
    if args.enforcement_only and args.oversight_only:
        log("ERROR: --enforcement-only and --oversight-only are mutually exclusive", "red")
        sys.exit(2)

    # Dedup sets. Links are normalized (lowercase host, strip www,
    # strip trailing slash, drop tracking params) so minor URL variants
    # between scrapers don't break dedup. See normalize_link().
    existing_links = set()
    existing_titles = set()
    for a in data.get("actions", []):
        if a.get("link"):
            existing_links.add(normalize_link(a["link"]))
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
                    existing_links.add(normalize_link(link))
            # Pending items: don't re-flag the same thing on the next run
            for pending in review.get("items", []) or []:
                if pending.get("link"):
                    existing_links.add(normalize_link(pending["link"]))
        except Exception as e:
            log(f"  WARNING: could not load needs_review.json: {e}")

    # In oversight mode, also dedup against the oversight review queue so
    # the daily oversight pipeline doesn't re-flag items that already went
    # through review (promoted, pending, or rejected).
    oversight_review_path = os.path.join(SCRIPT_DIR, "data", "needs_review_oversight.json")
    if os.path.exists(oversight_review_path):
        try:
            ov_review = load_json(oversight_review_path, {"items": [], "rejected_links": []})
            for link in ov_review.get("rejected_links", []) or []:
                if link:
                    existing_links.add(normalize_link(link))
            for pending in ov_review.get("items", []) or []:
                if pending.get("link"):
                    existing_links.add(normalize_link(pending["link"]))
        except Exception as e:
            log(f"  WARNING: could not load needs_review_oversight.json: {e}")

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
                # Items marked with _trust_source=True have already been
                # gated by a higher-authority signal (e.g. scrape_doj_opa
                # only returns items DOJ itself tagged 'Health Care Fraud').
                # Bypass the regex HC keyword / context check for those,
                # per project_doj_topic_authoritative.md.
                trust_source = bool(item.get('_trust_source'))
                trusted_source = feed.get('agency') in ('HHS-OIG',) or trust_source
                if not trust_source:
                    if not trusted_source:
                        # Non-trusted feeds need both a fraud/oversight
                        # keyword AND healthcare context. Oversight mode
                        # accepts the broader OVERSIGHT_KEYWORDS list
                        # (hearings, investigations, audits, reports,
                        # rules, advisories) in addition to enforcement
                        # KEYWORDS; enforcement mode uses KEYWORDS only.
                        oversight_mode = bool(globals().get('OVERSIGHT_ONLY'))
                        keyword_ok = test_any_keyword(search_text)
                        if oversight_mode and not keyword_ok:
                            keyword_ok = test_any_oversight_keyword(search_text)
                        if not keyword_ok:
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
                # Dedup by link (normalized)
                link_key = normalize_link(link) if link else ""
                if link_key and link_key in existing_links:
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
                action_type = ('Investigative Report' if is_media
                               else get_action_type(title, search_all,
                                                    agency=feed.get('agency'),
                                                    link=link))
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
                # Oversight-only: drop enforcement items entirely. Oversight
                # items will be routed to needs_review_oversight.json at save
                # time, never directly into actions.json.
                if globals().get('OVERSIGHT_ONLY') and is_enforcement:
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
                related_agencies = []
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
                    # If we relabeled the primary agency away from HHS-OIG,
                    # preserve the OIG provenance as a related agency. OIG is
                    # the criminal investigative arm for Medicare/Medicaid
                    # fraud and is named as the investigating agency on
                    # virtually every healthcare fraud DOJ press release we
                    # source through this pipeline.
                    if actual_agency != 'HHS-OIG':
                        related_agencies.append('HHS-OIG')

                # Federal Enforcement tab = DOJ prosecutions ONLY.
                # If an item is classified as Criminal Enforcement or
                # Civil Action but the final agency isn't DOJ, it's a
                # classifier mistake (e.g. an OIG audit whose body text
                # contained "charged" in a billing context). Reclassify
                # as Audit so it goes to the Oversight tab instead.
                if is_enforcement and actual_agency != 'DOJ':
                    action_type = 'Audit'
                    is_enforcement = False
                    if globals().get('ENFORCEMENT_ONLY'):
                        continue  # skip entirely in enforcement mode
                    if globals().get('OVERSIGHT_ONLY'):
                        pass  # will be routed to oversight queue

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
                    "related_agencies": related_agencies,
                }
                # Persist DOJ topic tags when the scraper captured them —
                # useful provenance ("DOJ itself classified this as Health
                # Care Fraud") that survives into actions.json.
                doj_topics = item.get('_doj_topics')
                if doj_topics:
                    entry['doj_topics'] = doj_topics

                new_actions.append(entry)
                added += 1
                if link_key:
                    existing_links.add(link_key)
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

    if globals().get('OVERSIGHT_ONLY'):
        # Route oversight items to the oversight review queue, never directly
        # to actions.json. The oversight pipeline (audit-oversight,
        # ai-review-oversight) is responsible for promoting items to the
        # main actions.json.
        ov_path = os.path.join(SCRIPT_DIR, "data", "needs_review_oversight.json")
        ov_data = load_json(ov_path, {"items": [], "rejected_links": [], "metadata": {}})
        if "items" not in ov_data:
            ov_data["items"] = []
        if "rejected_links" not in ov_data:
            ov_data["rejected_links"] = []
        if "metadata" not in ov_data:
            ov_data["metadata"] = {}
        if added > 0:
            ov_data["items"].extend(new_actions)
            log(f"Added {added} oversight item(s) to review queue.")
        else:
            log("No new oversight items found.")
        ov_data["metadata"]["last_scraped"] = datetime.now().isoformat()
        save_json(ov_path, ov_data)
        # Do NOT touch actions.json metadata in oversight mode — the
        # enforcement pipeline owns that key.
    else:
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
