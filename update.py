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

from tag_allowlist import (
    auto_tags as _auto_tags,
    filter_tags as _filter_tags,
    strip_boilerplate as _strip_boilerplate,
    apply_co_apply as _apply_co_apply,
)

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
    # Program integrity language (catches CMS oversight items)
    r'\bintegrity\b', r'\bloophole\b', r'skin substitute',
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
    {"name": "CMS-Fraud",   "agency": "CMS",           "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "cms_fraud"},
    # HHS press room is Akamai Bot Manager-blocked (403 even with Playwright).
    # Scraper scaffolding is in place; requires stealth tooling to enable.
    # Items from hhs.gov/press-room/ are added manually (~1-2/month).
    {"name": "HHS",         "agency": "HHS",           "url": None,                                                                       "enabled": False, "source_type": "official", "scrape": "hhs_press"},
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
    # FDA + DEA feeds disabled 2026-04-21: dashboard tracks federal HC fraud
    # enforcement + policy; DEA/FDA cases are captured via Opioids and
    # Medical Devices area tags on DOJ prosecutions, and we don't separately
    # track these agencies in primary or related_agencies anymore.
    {"name": "FDA",         "agency": "FDA",           "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "enabled": False, "source_type": "official"},
    {"name": "DEA",         "agency": "DEA",           "url": "https://www.dea.gov/press-releases/rss",                                   "enabled": False, "source_type": "official", "browser_fallback": True},
    # --- Commissions + Treasury anti-fraud (added Tier 2) ---
    {"name": "MedPAC",      "agency": "MedPAC",        "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "medpac"},
    {"name": "MACPAC",      "agency": "MACPAC",        "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "macpac"},
    {"name": "FinCEN",      "agency": "Treasury",      "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "fincen"},
    {"name": "WhiteHouse",  "agency": "White House",   "url": None,                                                                       "enabled": True,  "source_type": "official", "scrape": "whitehouse"},
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
    # Federal district + territories
    'District of Columbia': 'DC', 'Puerto Rico': 'PR', 'Guam': 'GU',
    'U.S. Virgin Islands': 'VI', 'American Samoa': 'AS',
}

_VALID_STATE_ABBR = set(STATE_MAP.values())

# DOJ USAO district URL -> state code. For DOJ items, the prosecuting district
# is the authoritative state (defendant's home state is noise). Audited at
# 95% agreement with existing stored states; every disagreement in the audit
# favored the USAO code over the stored state.
_USAO_LINK_RE = re.compile(r'/usao-([a-z]+)/', re.I)


def extract_usao_state(link):
    """Extract prosecuting-state code from a justice.gov USAO URL, or None.

    Handles both single-district (`/usao-ct/` -> CT, `/usao-ri/` -> RI) and
    multi-district (`/usao-sdny/` -> NY, `/usao-edmi/` -> MI) patterns.
    """
    if not link:
        return None
    m = _USAO_LINK_RE.search(link.lower())
    if not m:
        return None
    code = m.group(1)
    if len(code) == 2 and code.upper() in _VALID_STATE_ABBR:
        return code.upper()
    # Multi-district: [emwnsc]d + 2-letter state, e.g. sdny, edmi, ndga, cdca
    if len(code) == 4 and code[1] == 'd' and code[0] in 'emwnsc':
        st = code[2:].upper()
        if st in _VALID_STATE_ABBR:
            return st
    return None


# Top US cities -> state. Used as a fallback for items whose title names a
# city but not a state. Covers top-50 metros, state capitals, and cities that
# appear frequently in federal healthcare-fraud press releases. Intentionally
# small — cities not in this dict just fall through (state stays empty).
# When a city name is ambiguous (e.g., "Springfield" in multiple states),
# it's OMITTED entirely rather than guessed.
_CITY_TO_STATE = {
    'birmingham': 'AL', 'montgomery': 'AL', 'huntsville': 'AL',
    'anchorage': 'AK',
    'phoenix': 'AZ', 'tucson': 'AZ', 'mesa': 'AZ', 'scottsdale': 'AZ', 'tempe': 'AZ', 'chandler': 'AZ',
    'little rock': 'AR', 'fayetteville': 'AR',
    'los angeles': 'CA', 'san diego': 'CA', 'san jose': 'CA', 'san francisco': 'CA',
    'fresno': 'CA', 'sacramento': 'CA', 'long beach': 'CA',
    'bakersfield': 'CA', 'anaheim': 'CA', 'santa ana': 'CA', 'riverside': 'CA',
    'stockton': 'CA', 'irvine': 'CA', 'modesto': 'CA', 'huntington beach': 'CA',
    'santa rosa': 'CA', 'rancho cucamonga': 'CA', 'santa clarita': 'CA',
    'garden grove': 'CA', 'oceanside': 'CA', 'elk grove': 'CA',
    'palmdale': 'CA', 'pasadena': 'CA',
    'fullerton': 'CA', 'thousand oaks': 'CA', 'visalia': 'CA', 'berkeley': 'CA',
    'simi valley': 'CA', 'torrance': 'CA', 'sunnyvale': 'CA', 'hayward': 'CA',
    'concord': 'CA', 'roseville': 'CA', 'salinas': 'CA', 'escondido': 'CA',
    'san bernardino': 'CA',
    'denver': 'CO', 'colorado springs': 'CO', 'aurora': 'CO', 'fort collins': 'CO',
    'lakewood': 'CO', 'boulder': 'CO', 'thornton': 'CO',
    'bridgeport': 'CT', 'new haven': 'CT', 'hartford': 'CT', 'stamford': 'CT',
    'waterbury': 'CT', 'norwalk': 'CT', 'danbury': 'CT', 'bloomfield': 'CT',
    'north haven': 'CT',
    'wilmington': 'DE', 'dover': 'DE',
    'jacksonville': 'FL', 'miami': 'FL', 'tampa': 'FL', 'orlando': 'FL',
    'st petersburg': 'FL', 'saint petersburg': 'FL', 'hialeah': 'FL', 'tallahassee': 'FL',
    'port st lucie': 'FL', 'cape coral': 'FL', 'fort lauderdale': 'FL',
    'pembroke pines': 'FL', 'hollywood': 'FL', 'miramar': 'FL', 'gainesville': 'FL',
    'coral springs': 'FL', 'lehigh acres': 'FL', 'miami gardens': 'FL',
    'clearwater': 'FL', 'palm bay': 'FL', 'pompano beach': 'FL', 'west palm beach': 'FL',
    'lakeland': 'FL', 'sarasota': 'FL', 'naples': 'FL', 'fort myers': 'FL',
    'boca raton': 'FL', 'daytona beach': 'FL', 'key west': 'FL', 'pensacola': 'FL',
    'atlanta': 'GA', 'augusta': 'GA', 'macon': 'GA', 'savannah': 'GA',
    'athens': 'GA', 'sandy springs': 'GA', 'roswell': 'GA',
    'honolulu': 'HI', 'hilo': 'HI',
    'boise': 'ID',
    'chicago': 'IL', 'rockford': 'IL', 'joliet': 'IL', 'naperville': 'IL',
    'peoria': 'IL',
    'indianapolis': 'IN', 'fort wayne': 'IN', 'evansville': 'IN', 'south bend': 'IN',
    'des moines': 'IA', 'cedar rapids': 'IA', 'davenport': 'IA', 'marshalltown': 'IA',
    'dubuque': 'IA',
    'wichita': 'KS', 'overland park': 'KS', 'topeka': 'KS',
    'louisville': 'KY', 'lexington': 'KY', 'bowling green': 'KY', 'frankfort': 'KY',
    'new orleans': 'LA', 'baton rouge': 'LA', 'shreveport': 'LA', 'lafayette': 'LA',
    'lake charles': 'LA',
    'bangor': 'ME', 'lewiston': 'ME',
    'baltimore': 'MD', 'annapolis': 'MD', 'rockville': 'MD', 'frederick': 'MD',
    'boston': 'MA', 'worcester': 'MA', 'cambridge': 'MA', 'lowell': 'MA',
    'brockton': 'MA', 'new bedford': 'MA', 'quincy': 'MA',
    'detroit': 'MI', 'grand rapids': 'MI', 'warren': 'MI', 'sterling heights': 'MI',
    'ann arbor': 'MI', 'lansing': 'MI', 'flint': 'MI', 'dearborn': 'MI',
    'southfield': 'MI',
    'minneapolis': 'MN', 'st paul': 'MN', 'saint paul': 'MN', 'duluth': 'MN',
    'jackson': 'MS', 'gulfport': 'MS',
    'kansas city mo': 'MO', 'st louis': 'MO', 'saint louis': 'MO',
    'independence': 'MO', 'jefferson city': 'MO',
    'helena': 'MT',
    'omaha': 'NE', 'lincoln': 'NE',
    'las vegas': 'NV', 'henderson': 'NV', 'reno': 'NV', 'north las vegas': 'NV',
    'carson city': 'NV',
    'manchester nh': 'NH', 'nashua': 'NH',
    'newark': 'NJ', 'jersey city': 'NJ', 'paterson': 'NJ', 'trenton': 'NJ',
    'elizabeth nj': 'NJ', 'edison': 'NJ', 'hoboken': 'NJ',
    'albuquerque': 'NM', 'las cruces': 'NM', 'santa fe': 'NM',
    'new york city': 'NY', 'buffalo': 'NY', 'yonkers': 'NY', 'syracuse': 'NY',
    'albany': 'NY', 'new rochelle': 'NY', 'brooklyn': 'NY', 'bronx': 'NY',
    'manhattan': 'NY', 'staten island': 'NY', 'harlem': 'NY',
    'long island': 'NY',
    'charlotte': 'NC', 'raleigh': 'NC', 'greensboro': 'NC', 'durham': 'NC',
    'winston-salem': 'NC', 'cary': 'NC', 'kinston': 'NC',
    'fargo': 'ND', 'bismarck': 'ND',
    'cleveland': 'OH', 'cincinnati': 'OH', 'toledo': 'OH', 'akron': 'OH',
    'dayton': 'OH', 'youngstown': 'OH',
    'oklahoma city': 'OK', 'tulsa': 'OK', 'norman': 'OK',
    'eugene': 'OR', 'gresham': 'OR',
    'philadelphia': 'PA', 'pittsburgh': 'PA', 'allentown': 'PA', 'erie': 'PA',
    'reading': 'PA', 'scranton': 'PA', 'bethlehem': 'PA', 'harrisburg': 'PA',
    'york pa': 'PA',
    'providence': 'RI', 'warwick': 'RI', 'cranston': 'RI',
    'myrtle beach': 'SC',
    'sioux falls': 'SD', 'rapid city': 'SD', 'pierre': 'SD',
    'nashville': 'TN', 'memphis': 'TN', 'knoxville': 'TN', 'chattanooga': 'TN',
    'clarksville': 'TN', 'murfreesboro': 'TN', 'hendersonville': 'TN',
    'houston': 'TX', 'san antonio': 'TX', 'dallas': 'TX', 'austin': 'TX',
    'fort worth': 'TX', 'el paso': 'TX', 'corpus christi': 'TX', 'plano': 'TX',
    'laredo': 'TX', 'lubbock': 'TX', 'garland': 'TX', 'irving': 'TX',
    'amarillo': 'TX', 'grand prairie': 'TX', 'brownsville': 'TX', 'mckinney': 'TX',
    'mesquite': 'TX', 'killeen': 'TX', 'waco': 'TX', 'beaumont': 'TX',
    'midland': 'TX', 'carrollton': 'TX', 'collin county': 'TX',
    'salt lake city': 'UT', 'provo': 'UT', 'west valley city': 'UT',
    'burlington vt': 'VT', 'montpelier': 'VT',
    'virginia beach': 'VA', 'richmond': 'VA', 'norfolk': 'VA', 'chesapeake': 'VA',
    'newport news': 'VA', 'roanoke': 'VA', 'north chesterfield': 'VA',
    'seattle': 'WA', 'spokane': 'WA', 'tacoma': 'WA', 'vancouver wa': 'WA',
    'bellevue': 'WA', 'kent': 'WA', 'olympia': 'WA',
    'morgantown': 'WV', 'huntington wv': 'WV', 'wheeling': 'WV',
    'milwaukee': 'WI', 'madison': 'WI', 'green bay': 'WI', 'kenosha': 'WI',
    'racine': 'WI', 'waukesha': 'WI',
    'cheyenne': 'WY', 'casper': 'WY',
    'san juan': 'PR',
}

# Intentionally AMBIGUOUS cities (omitted from _CITY_TO_STATE):
# - "Springfield" (MO, MA, IL, OH, VA, and many more)
# - "Columbia" (SC, MO, MD)
# - "Washington" (DC, WA, county in PA, etc.)
# - "Portland" (OR, ME)
# - "Columbus" (OH, GA, IN)
# - "Aurora" (CO, IL)
# - "Charleston" (SC, WV)
# - "Kansas City" (MO or KS — we only map "kansas city mo")
# - "Glendale" (CA or AZ)
# - "Arlington" (VA, TX)
# - "Oakland" (CA, but Oakland COUNTY in MI is extremely common)
# - "Lancaster" (CA, PA, SC, TX, OH — widely ambiguous)
# - "Larchmont" (NY village, but also Larchmont neighborhood in LA/CA)
# - "Orange" (CA, NJ, CT — plus the word itself)
# - "Ontario" (CA — also Canadian province, heavily ambiguous)
# - "Mobile" (AL — but also a common adjective/noun)
# - "Reading" (PA — but also the verb)
# - "Billings" (MT — but also verb form of "billing", e.g. "false billings")
# - "Queens" (NY borough — but "queens" is also a common noun)
# - "Corona" (CA — word means "crown" and is a virus name post-2020)

# Regex matching any city name as a whole word, longest-first.
_CITY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(_CITY_TO_STATE.keys(), key=lambda x: -len(x))) + r')\b',
    re.IGNORECASE,
)


def extract_city_states(text):
    """Return a list of state codes implied by city names found in text.
    Handles multi-state when multiple cities appear.

    Skips matches immediately followed by "County" — "Raleigh County"
    (WV) shouldn't resolve to Raleigh, NC; "Oakland County" (MI)
    shouldn't resolve to Oakland, CA. When a city name precedes
    "County", the phrase is a county reference, not a city reference,
    and the state can't be inferred from the city dict alone.
    """
    if not text:
        return []
    found = []
    for m in _CITY_RE.finditer(text):
        # Skip if followed by "County" — it's a county ref, not a city
        after = text[m.end():m.end() + 10]
        if re.match(r'\s+County\b', after, re.IGNORECASE):
            continue
        code = _CITY_TO_STATE.get(m.group(0).lower())
        if code and code not in found:
            found.append(code)
    return found


def extract_all_state_names(text):
    """Return a list of state codes matched by state names in text.

    Iterates state names longest-first and masks out matched spans so a
    shorter substring (e.g., "Virginia" inside "West Virginia") doesn't
    also match. Returns list in the order matches appear in the original
    text, deduplicated.
    """
    if not text:
        return []
    # Work on a mutable copy we can blank out as we match longer names
    scratch = text
    # Collect (start_pos, abbr) so we can sort by textual order at the end
    matches = []
    for name, abbr in sorted(STATE_MAP.items(), key=lambda x: -len(x[0])):
        pat = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
        for m in pat.finditer(scratch):
            matches.append((m.start(), abbr))
        # Mask every occurrence so subsequent shorter-name iterations don't
        # re-match inside the same span. Replace with same-length space.
        scratch = pat.sub(lambda m: ' ' * len(m.group()), scratch)
    # Sort by occurrence order in original text, dedup preserving order
    matches.sort()
    out = []
    for _, abbr in matches:
        if abbr not in out:
            out.append(abbr)
    return out

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
    or "testified" doesn't get mislabeled as a Hearing.
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

    # URL-path guard: if the link is on an audit/report path, the item
    # is oversight (Audit/Report/Evaluation) — never enforcement. Title
    # keywords like "$9.4 million" or "Medicare fraud" on OIG audit pages
    # used to misroute these to Civil Action; this guard prevents that.
    # Applies to oig.hhs.gov/reports/all/, gao.gov/products/, and
    # analogous audit-doc paths.
    is_audit_path = (
        'oig.hhs.gov/reports/' in link_l or
        'gao.gov/products/' in link_l or
        'macpac.gov/publication/' in link_l or
        'medpac.gov/document' in link_l
    )
    if is_audit_path:
        # Skip straight to the oversight classifier — bypass enforcement
        # signal matching. The title still distinguishes Audit vs Report
        # vs Evaluation downstream.
        t = title_l
        if 'annual report' in t or 'semiannual report' in t:
            return 'Report'
        if 'evaluation' in t or 'inspection' in t:
            return 'Audit'  # Evaluations/inspections live under Audit type
        # Default oversight-path classification: Audit
        return 'Audit'

    # ---- Title-only enforcement detection (highest priority) ----
    #
    # Hybrid cases (title mentions BOTH criminal and civil signals, e.g.,
    # "Pleads Guilty and Agrees to Pay $X Settlement") use a "first
    # signal in title wins" rule. This mirrors DOJ press-release
    # convention: the more-primary action is named first. So:
    #   - "Pleads Guilty and Agrees to Pay ..." -> Criminal
    #   - "Agrees to Pay ... and Pleads Guilty" -> Civil (rare)
    #   - "Agrees to Pay ... to Resolve FCA Allegations Related to NPA" -> Civil
    # DPA/NPA are criminal signals but usually appear later in titles
    # where the civil component is named first (e.g., Aesculap case).
    # If DPA/NPA is in the title and NO other criminal verbs, Criminal
    # still wins; otherwise first-signal applies.
    _crim_re = re.compile(
        r'\b(plead|pleads|pleaded|convict|convicted|indict|indicted|'
        r'charg(ed|es|ing)|guilty|sentenc(e|ed|ing)|arrest(ed)?|'
        r'prosecut(ed|ion)?|deferred\s+prosecution|non-?prosecution\s+agreement|'
        r'criminal\s+resolution)\b', re.I)
    _civ_re = re.compile(
        r'\b(settlement|settles?|to\s+pay|agree(s|d)?\s+to\s+pay|'
        r'consent\s+(judgment|decree)|civil\s+action|false\s+claims\s+act|'
        r'qui\s+tam|to\s+resolve\s+(false\s+claims|allegations)|'
        r'to\s+settle\s+allegations)\b', re.I)
    crim_m = _crim_re.search(title_l)
    civ_m = _civ_re.search(title_l)
    if crim_m and civ_m:
        # Both present — first signal wins
        return 'Criminal Enforcement' if crim_m.start() <= civ_m.start() else 'Civil Action'
    if crim_m:
        return 'Criminal Enforcement'
    if civ_m:
        return 'Civil Action'

    # ---- Title-only legislation/hearing/report detection ----
    if re.search(r'signed into law|enacted|passes bill|bill signed|legislation|'
                 r'executive order|presidential memo|law.*(takes|went) effect',
                 title_l):
        return 'Legislation'
    if re.search(r'\b(hearing|testimony|testifies?|subcommittee hearing|'
                 r'committee (hearing|held|examines?|votes?))\b', title_l):
        return 'Hearing'
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

# Titles that describe inherently national actions shouldn't be tagged with
# a single state just because a USAO office published them. Nationwide
# takedowns, multi-district lawsuits, and agency-level announcements apply
# across the country.
_NATIONAL_TITLE_RE = re.compile(
    r"^national\s+(health|healthcare|health\s*care)\s+fraud\s+takedown|"
    r"\bnationwide\b|"
    r"\b\d+\s+(additional\s+)?states\b|"
    r"\bmulti-?state\b|"
    r"\bfederal\s+benefit\s+programs?\b|"
    r"\btaxpayer-funded\s+programs?\b|"
    r"\bgovernment-wide\b|"
    r"\bnational\s+strategy\b|"
    r"\bcross-agency\b",
    re.IGNORECASE,
)

# Body text that indicates a case spans the country. When triggered, the
# item is too nationwide for a single-state tag — return None rather than
# picking a defendant-origin demonym.
_NATIONAL_BODY_RE = re.compile(
    r"\b(nationwide|across\s+the\s+country|multi-?state\s+scheme|"
    r"nationally|throughout\s+the\s+United\s+States|"
    r"in\s+multiple\s+states|government-wide|cross-agency)\b",
    re.IGNORECASE,
)

# Item types where body-text state fallback is unreliable and should be
# skipped. These are policy/hearing/report/org items where incidental
# state mentions (senator home states, witness testimony, example
# jurisdictions) get wrongly assigned as the item's geographic scope.
# Enforcement + Investigation items keep the body fallback because
# they're usually state-specific.
_STATE_BODY_FALLBACK_SKIP_TYPES = {
    'Hearing', 'Report', 'Audit', 'Rule/Regulation',
    'Administrative Action', 'Structural/Organizational',
    'Presidential Action', 'Legislation',
}

# Role nouns that turn a state name into a demonym ("Florida Man",
# "Illinois Doctor"). When a state appears ONLY in this pattern, it's a
# defendant-origin signal, not a fraud-location signal — needs body
# corroboration to count.
_DEMONYM_ROLE_WORDS = (
    r"Man|Woman|Men|Women|Resident|Native|Citizen|Duo|Pair|Couple|Trio|"
    r"Brothers?|Sisters?|Doctor|Physician|Nurse|Nursing\s+Assistant|"
    r"Chiropractor|Podiatrist|Pharmacist|Dentist|Psychologist|Therapist|"
    r"Pastor|Attorney|Lawyer|Defendant|Official|Representative|"
    r"Businessman|Businesswoman|Businessperson|Business\s+Owner|"
    r"Clinic\s+Operator|Pharmacy\s+Owner|CEO|Executive|Owner|Manager|"
    r"Company|Pharmacy|Clinic"
)

# "State of X" / "the States of X, Y, and Z" / "X ex rel" — explicit
# state-as-party signal, much stronger than a demonym.
_STATE_AS_PARTY_RE = re.compile(
    r"(?:the\s+)?States?\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?"
    r"(?:,\s*(?:and\s+)?[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)*)",
    re.IGNORECASE,
)


def extract_state_party_mentions(text):
    """Find 'State of X' / 'States of X, Y, and Z' / 'X ex rel' patterns.

    Returns state abbrs in the order they appear. Captures only the
    explicit-party framing — ignores incidental state name mentions.
    """
    if not text:
        return []
    out = []
    for m in _STATE_AS_PARTY_RE.finditer(text):
        blob = m.group(1)
        # Split on commas and "and" to handle "Georgia, Colorado, and South Carolina"
        for part in re.split(r",\s*|\s+and\s+", blob):
            part = part.strip()
            # Try longest first (handle "South Carolina" before "Carolina")
            for name, abbr in sorted(STATE_MAP.items(), key=lambda x: -len(x[0])):
                if part.lower() == name.lower():
                    if abbr not in out:
                        out.append(abbr)
                    break
    # Also capture "X ex rel" qui tam pattern (one state per match)
    for m in re.finditer(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+ex\s+rel\b", text):
        name = m.group(1).strip()
        for sname, abbr in STATE_MAP.items():
            if name.lower() == sname.lower():
                if abbr not in out:
                    out.append(abbr)
                break
    return out


def _title_demonym_states(title):
    """Return state abbrs that appear in title ONLY as weak signals —
    i.e. demonyms OR residence-context mentions (defendant residence,
    not fraud location).

    Weak signals:
      - Demonym: state-name followed by role noun (Man, Doctor, etc.)
      - Residence context: "residing in STATE", "resident of STATE",
        "based in STATE", "living in STATE", "from STATE", "of STATE"
        when preceded by a person-describing phrase

    If a state appears in title AND at least one occurrence is a real
    signal (e.g., "Fraud in Illinois", "Illinois Doctor indicted in
    Illinois Medicaid scheme"), the state is NOT flagged here.

    Called by get_state() to defer these weak-signal states to Path 5
    (requires body corroboration to apply).
    """
    if not title:
        return []
    weak_only = []
    for name, abbr in sorted(STATE_MAP.items(), key=lambda x: -len(x[0])):
        # Find all occurrences of this state name in title
        matches = list(re.finditer(r"\b" + re.escape(name) + r"\b", title, re.IGNORECASE))
        if not matches:
            continue
        all_weak = True
        for m in matches:
            after = title[m.end():m.end() + 60]
            before = title[max(0, m.start() - 60):m.start()]
            is_demonym = bool(re.match(
                r"\s+(?:" + _DEMONYM_ROLE_WORDS + r")\b", after, re.IGNORECASE,
            ))
            is_residence = bool(re.search(
                r"(?:residing|resident|based|living|located|headquartered)"
                r"\s+(?:of|in|at)\s*(?:Southern|Northern|Eastern|Western|"
                r"Central)?\s*$",
                before, re.IGNORECASE,
            ))
            if not (is_demonym or is_residence):
                all_weak = False
                break
        if all_weak:
            weak_only.append(abbr)
    return weak_only


def _demonym_corroborated(body_text, state_name):
    """True if state_name appears in body_text outside demonym patterns.

    "Florida Man" in title corroborated only if body mentions Florida in
    a non-demonym context: "Florida pharmacy", "in Florida", "Florida-based",
    etc. If every body occurrence is also a demonym, it's NOT corroborated.
    """
    if not body_text:
        return False
    matches = list(re.finditer(r"\b" + re.escape(state_name) + r"\b", body_text, re.IGNORECASE))
    if not matches:
        return False
    for m in matches:
        after = body_text[m.end():m.end() + 60]
        if not re.match(r"\s+(?:" + _DEMONYM_ROLE_WORDS + r")\b", after, re.IGNORECASE):
            return True
    return False


def get_state(text, title=None, link=None, item_type=None):
    """Return a state code (or comma-separated list) from available signals.

    **Rule (2026-04-20, revised):** prosecution venue + explicit party
    mentions win. Demonyms ("Florida Man", "Illinois Doctor") are weak
    signals and only count when corroborated by the body text. For
    non-enforcement items, body-text fallback is skipped (policy/
    hearing items shouldn't get state from incidental mentions like
    senator home states or witness testimony).

    Priority order:
      0. National-scope guard: title OR body matches nationwide/multi-state
         pattern -> None.
      1. USAO district from LINK (DOJ items) -> primary state.
      2. State-as-party patterns ("State of X", "States of X, Y, Z",
         "X ex rel") in title+body -> append.
      3. Non-demonym state names in title (e.g., "Fraud in Illinois" —
         Illinois appears not as a demonym) -> append.
      4. City in title via `_CITY_TO_STATE` -> append, but ONLY when no
         USAO (to avoid noise from incidental city names in /usao-xx/ items).
      5. Title demonyms ("Florida Man") -> append ONLY if corroborated
         by a non-demonym mention of that state in body text.
      6. Body-text fallback (longest state-name match) -> use only if
         nothing above produced a result AND `item_type` is NOT a
         policy/hearing/report type (see _STATE_BODY_FALLBACK_SKIP_TYPES).
         Body fallback is reliable for enforcement items (state = the
         venue) but not for policy items where incidental state mentions
         (senator home states, witness affiliations) leak through.

    `item_type` is the action type classification (Criminal Enforcement,
    Hearing, Report, etc.). When omitted, body fallback runs unconditionally
    (backward-compatible with older callers; auto-scraper always passes it).

    See `state_tag_meaning_tbd.md` for the design discussion.
    """
    # Path 0: national-scope short-circuit (title OR body)
    if title and _NATIONAL_TITLE_RE.search(title):
        return None
    if text and _NATIONAL_BODY_RE.search(text):
        return None

    states = []  # ordered, deduped

    # Path 1: USAO district (primary)
    usao = extract_usao_state(link) if link else None
    if usao:
        states.append(usao)

    # Path 2: state-as-party ("State of X", "States of X, Y, Z")
    combined_text = (title or "") + "\n" + (text or "")
    for s in extract_state_party_mentions(combined_text):
        if s not in states:
            states.append(s)

    # Path 3: non-demonym state names in title (real signals)
    if title:
        demonym_states = set(_title_demonym_states(title))
        for s in extract_all_state_names(title):
            if s in demonym_states:
                continue  # defer to path 5 (needs corroboration)
            if s not in states:
                states.append(s)

    # Path 4: city in title — ONLY if USAO absent. USAO is authoritative
    # for DOJ-district items; appending city to USAO can add noise (a
    # random city name in a title doesn't necessarily mean fraud happened
    # there). City is a fallback for /opa/ (Main DOJ) and non-DOJ items
    # where USAO isn't available.
    if title and not usao:
        for s in extract_city_states(title):
            if s not in states:
                states.append(s)

    # Path 5: title demonyms — only if corroborated by body text
    if title and text:
        for name, abbr in sorted(STATE_MAP.items(), key=lambda x: -len(x[0])):
            if abbr in states:
                continue
            # Only consider if present as a demonym in title
            if abbr not in _title_demonym_states(title):
                continue
            if _demonym_corroborated(text, name):
                states.append(abbr)

    # Path 5b: multi-state operator patterns. Body text like "operates in
    # Michigan, Illinois, Indiana, Wisconsin, and Georgia" / "clinics in
    # [states]" / "conducted business in [states]" indicates a multi-state
    # provider/scheme. Append all states from such lists regardless of
    # whether path 1 (USAO) already set a primary state. This is an
    # enforcement-only signal — skipped for policy/report item types so
    # "examples include California, Texas, Florida" in a general policy
    # report doesn't wrongly assign states.
    enf_only = not item_type or item_type in (
        "Criminal Enforcement", "Civil Action", "Investigation",
    )
    if text and enf_only:
        # Pattern: "(operat|clinic|facilit|office|location|patient|busines|
        # provider|bill|serv)... in STATE, STATE(, STATE)*(, and|and) STATE"
        # Require at least 2 states in the list to gate on clear multi-state
        # intent.
        ctx_re = re.compile(
            r"\b(operat\w*|(?:clinic|facilit|office|location|patient|"
            r"provider|fraud|scheme|business|billing|served?)s?)"
            r"\s+(?:\w+\s+){0,6}in\s+"
            r"((?:"
            + r"|".join(sorted(STATE_MAP.keys(), key=lambda s: -len(s)))
            + r")(?:\s*,\s*(?:and\s+)?(?:"
            + r"|".join(sorted(STATE_MAP.keys(), key=lambda s: -len(s)))
            + r")){1,20})",
            re.IGNORECASE,
        )
        for m in ctx_re.finditer(text):
            state_list = m.group(2)
            for name in re.findall(
                r"\b("
                + r"|".join(sorted(STATE_MAP.keys(), key=lambda s: -len(s)))
                + r")\b",
                state_list,
                re.IGNORECASE,
            ):
                abbr = STATE_MAP.get(name.title())
                if abbr and abbr not in states:
                    states.append(abbr)

    if states:
        return ", ".join(states)

    # Path 6: body-text fallback (longest name wins). SKIPPED for
    # policy/hearing/report item types because these get false-positive
    # state assignments from incidental body mentions (senator home
    # states, witness testimony, example jurisdictions).
    if item_type and item_type in _STATE_BODY_FALLBACK_SKIP_TYPES:
        return None
    if text:
        for name, abbr in sorted(STATE_MAP.items(), key=lambda x: -len(x[0])):
            if re.search(r"\b" + re.escape(name) + r"\b", text):
                return abbr
    return None

def extract_amount(text, title=""):
    """Extract a dollar amount from text, preferring the title.

    The title always contains the case-specific amount (e.g. "$135 Million"
    for a specific settlement). The body text often contains DOJ boilerplate
    like "Since January 2009, the Justice Department has recovered over
    $45 billion through False Claims Act cases..." — that aggregate figure
    is NOT the case-specific amount.

    Strategy: check the title first. If no amount in the title, fall back
    to body text but SKIP known boilerplate patterns.
    """
    def _parse(t):
        # Try "$X Billion" first
        m = re.search(r'\$[\d,]+(?:\.\d+)?\s*billion', t, re.IGNORECASE)
        if m:
            num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('billion', '')))
            return {"display": m.group(), "numeric": num * 1e9}
        # Then "$X Million"
        m = re.search(r'\$[\d,]+(?:\.\d+)?\s*million', t, re.IGNORECASE)
        if m:
            num = float(re.sub(r'[\$,\s]', '', m.group().lower().replace('million', '')))
            return {"display": m.group(), "numeric": num * 1e6}
        # Then "$X,XXX" shorthand (e.g. "$850,000", "$4.75M")
        m = re.search(r'\$([\d,]+(?:\.\d+)?)\s*[MmBb]\b', t)
        if m:
            raw = m.group(1).replace(',', '')
            val = float(raw)
            unit = t[m.end()-1].lower()
            if unit == 'b':
                return {"display": f"${m.group(1)} Billion", "numeric": val * 1e9}
            else:
                return {"display": f"${m.group(1)} Million", "numeric": val * 1e6}
        # Finally raw dollar amounts >= $10,000 (e.g. "$850,000", "$704,349")
        m = re.search(r'\$([\d,]+(?:\.\d+)?)\b', t)
        if m:
            raw = m.group(1).replace(',', '')
            val = float(raw)
            if val >= 10_000:  # skip trivially small amounts
                return {"display": m.group(), "numeric": val}
        return None

    # 1. Try the title first — always case-specific
    if title:
        result = _parse(title)
        if result:
            return result

    # 2. Fall back to body text, but strip DOJ boilerplate
    if text:
        # Remove the common DOJ boilerplate paragraph about total FCA recoveries
        cleaned = re.sub(
            r'since (january|fiscal year).*?(justice department|department of justice).*?'
            r'recover\w*.*?\$[\d,.]+\s*(billion|million)[^.]*\.',
            '', text, flags=re.IGNORECASE | re.DOTALL)
        # Also remove "the largest health care fraud takedown" aggregate paragraphs
        cleaned = re.sub(
            r'(this|the)\s+(national|largest|record).*?takedown.*?\$[\d,.]+\s*(billion|million)[^.]*\.',
            '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        # Remove statutory fine/penalty-cap phrasing. DOJ releases routinely
        # describe the maximum sentence as "a fine of up to $250,000" or
        # "maximum penalty of $500,000 per count" — these are not case
        # amounts. Strip them before amount extraction so we don't end up
        # storing the statutory cap as the fraud amount.
        cleaned = re.sub(
            r'(?:a\s+)?(?:maximum\s+)?(?:statutory\s+)?(?:fine|penalty)\s+of\s+'
            r'(?:up\s+to\s+|not\s+(?:more\s+than|to\s+exceed)\s+)?'
            r'\$[\d,.]+(?:\s*million|\s*billion|\s*per\s+count)?',
            '', cleaned, flags=re.IGNORECASE)
        # Also strip "fine of $X or twice the gross gain" pattern
        cleaned = re.sub(
            r'fine\s+of\s+(?:up\s+to\s+)?\$[\d,.]+\s+or\s+twice[^.]*',
            '', cleaned, flags=re.IGNORECASE)
        result = _parse(cleaned)
        if result:
            return result

    return None

_AI_CLIENT = None
_AI_CLIENT_CHECKED = False

def _get_ai_client():
    """Lazy-init Anthropic client. Returns None if no API key or SDK unavailable."""
    global _AI_CLIENT, _AI_CLIENT_CHECKED
    if _AI_CLIENT_CHECKED:
        return _AI_CLIENT
    _AI_CLIENT_CHECKED = True
    try:
        from tag_extractor import make_client
        _AI_CLIENT = make_client()
    except Exception:
        _AI_CLIENT = None
    return _AI_CLIENT


# Canonical link_label map for congressional committee URLs. Used by
# derive_link_label() so the "View Source" button on each card is
# consistently labeled across items from the same committee (previously
# the same committee would produce "House Oversight", "House Oversight
# Press Release", "House Oversight Release", "House Oversight Committee",
# and "Committee Hearing Page" depending on which scraper and path).
#
# Convention: "{Committee Name} {Release|Hearing}" — no "Committee"
# suffix (redundant), "Release" for press releases, "Hearing" for
# hearing pages.
_COMMITTEE_URL_LABELS = [
    ('oversight.house.gov/hearing/', 'House Oversight Hearing'),
    ('oversight.house.gov/release/', 'House Oversight Release'),
    ('oversight.house.gov/',         'House Oversight Release'),
    ('energycommerce.house.gov/',    'House E&C Release'),
    ('waysandmeans.house.gov/event/', 'House Ways & Means Hearing'),
    ('waysandmeans.house.gov/',      'House Ways & Means Release'),
    ('help.senate.gov/',             'Senate HELP Release'),
    ('finance.senate.gov/',          'Senate Finance Release'),
    ('judiciary.senate.gov/',        'Senate Judiciary Release'),
    ('judiciary.house.gov/hearings/', 'House Judiciary Hearing'),
    ('judiciary.house.gov/',         'House Judiciary Release'),
    ('hsgac.senate.gov/hearings/',   'Senate HSGAC Hearing'),
    ('hsgac.senate.gov/',            'Senate HSGAC Release'),
    ('congress.gov/committee-meeting/', 'Congress.gov Hearing'),
    ('congress.gov/event/',          'Congress.gov Hearing'),
]

# URL pattern -> label for non-Congress agencies where doc type matters
# (a /fact-sheets/ URL should say "Fact Sheet", not "Press Release").
_AGENCY_URL_LABELS = [
    ('cms.gov/newsroom/fact-sheets/', 'CMS Fact Sheet'),
    ('cms.gov/newsroom/press-releases/', 'CMS Press Release'),
    ('cms.gov/blog/',                 'CMS Blog Post'),
    ('cms.gov/files/',                'CMS Report'),
    ('cms.gov/training-education/',   'CMS Report'),
    ('whitehouse.gov/fact-sheets/',   'White House Fact Sheet'),
    ('whitehouse.gov/presidential-actions/', 'White House Release'),
    ('whitehouse.gov/releases/',      'White House Release'),
    ('oig.hhs.gov/reports/',          'HHS-OIG Report'),
    ('oig.hhs.gov/documents/',        'HHS-OIG Report'),
    ('oig.hhs.gov/fraud/strike-force/', 'HHS-OIG Report'),
    ('oig.hhs.gov/newsroom/',         'HHS-OIG Press Release'),
    ('oig.hhs.gov/fraud/enforcement/', 'HHS-OIG Press Release'),
    ('gao.gov/products/',             'GAO Report'),
    ('macpac.gov/publication/',       'MACPAC Report'),
    ('macpac.gov/',                   'MACPAC Report'),
    ('medpac.gov/document/',          'MedPAC Report'),
    ('medpac.gov/',                   'MedPAC Report'),
    ('federalregister.gov/',          'Federal Register'),
    # DOJ non-/pr/ doc paths (annual reports, case summaries, policy memos)
    ('justice.gov/archives/opa/documents/', 'DOJ Report'),
    ('justice.gov/opa/documents/',    'DOJ Report'),
    ('justice.gov/criminal/file/',    'DOJ Report'),
    ('justice.gov/criminal/criminal-fraud/', 'DOJ Report'),
    # Senate Grassley / other senator websites (not committee)
    ('grassley.senate.gov/',          'Senate Grassley Release'),
]


def derive_link_label(agency, link, feed_name=None, is_media=False):
    """Produce a consistent link_label for a scraped item.

    Resolution order:
      1. Media items: "{feed_name} Report" (e.g., "KARE 11 Report")
      2. Congress items: committee-specific label from URL pattern
      3. Non-Congress agency items: URL-based doc-type refinement
         (e.g., CMS fact-sheet URLs get "CMS Fact Sheet", not "CMS
         Press Release")
      4. Fallback: "{agency} Press Release"
    """
    if is_media:
        return f"{feed_name} Report" if feed_name else "Media Report"
    link_l = (link or "").lower()
    # Congress items: use committee-specific label
    if agency == 'Congress':
        # First pass: detect hearings by "/hearing" anywhere in the path
        # (handles URLs like hsgac.senate.gov/subcommittees/dmdcc/
        # hearings/... where a simple prefix match misses). This runs
        # BEFORE the prefix map so that e.g. "hsgac.senate.gov/" → Release
        # doesn't win over an actual hearing URL.
        if '/hearing' in link_l or '/event/' in link_l or '/committee-meeting/' in link_l:
            import re as _re_local
            m = _re_local.search(r'//([\w.]+)/', link_l)
            host = m.group(1) if m else ''
            host_map = {
                'www.hsgac.senate.gov':     'Senate HSGAC',
                'hsgac.senate.gov':         'Senate HSGAC',
                'www.finance.senate.gov':   'Senate Finance',
                'finance.senate.gov':       'Senate Finance',
                'www.help.senate.gov':      'Senate HELP',
                'help.senate.gov':          'Senate HELP',
                'www.judiciary.senate.gov': 'Senate Judiciary',
                'judiciary.senate.gov':     'Senate Judiciary',
                'oversight.house.gov':      'House Oversight',
                'judiciary.house.gov':      'House Judiciary',
                'energycommerce.house.gov': 'House E&C',
                'waysandmeans.house.gov':   'House Ways & Means',
            }
            if host in host_map:
                return f"{host_map[host]} Hearing"
            if 'congress.gov' in host:
                return "Congress.gov Hearing"
        # Second pass: committee URL prefix map (press releases etc.)
        for pat, lbl in _COMMITTEE_URL_LABELS:
            if pat in link_l:
                return lbl
        return "Congress Release"  # generic fallback
    # Non-Congress agencies: URL-based doc-type refinement
    for pat, lbl in _AGENCY_URL_LABELS:
        if pat in link_l:
            return lbl
    # Fallback: agency-named press release
    return f"{agency} Press Release"


def generate_tags(title, full_text=""):
    """Generate allowlist tags from title + body text.

    If ANTHROPIC_API_KEY is set, uses the anchored AI extractor
    (tag_extractor.extract_tags_with_evidence) which cites verbatim
    phrases from the source — much more accurate than regex on body
    content. Otherwise falls back to the regex matcher from
    tag_allowlist.auto_tags.

    Both paths return only canonical tags from ALLOWED_TAGS.
    """
    client = _get_ai_client()
    if client is not None and full_text:
        try:
            from tag_extractor import extract_tags_with_evidence
            return _apply_co_apply(extract_tags_with_evidence(client, title, full_text))
        except Exception as e:
            log(f"  tag_extractor failed, falling back to regex: {e}", "yellow")
    # Regex fallback: strip DOJ boilerplate from body (Strike Force
    # paragraph, ACA enforcement-authority sentences, etc.) so passing
    # mentions in standard closing language don't trip false-positive
    # ACA/Medicare/Medicaid tags. Title always counts as-is. Co-apply
    # rules (Hospice -> Medicare, DME -> Medicare, etc.) ensure that
    # Medicare-specific service categories preserve their parent program.
    clean_body = _strip_boilerplate(full_text) if full_text else ""
    return _apply_co_apply(_auto_tags(f"{title} {clean_body}"))

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


# Host -> IANA timezone map for converting UTC publication timestamps
# into the publisher's local date. Without this, a news article
# published at 7:47 PM CST shows up as the next UTC day in its
# article:published_time meta tag, causing our stored date to be
# off by one. Default for anything not listed is ET (most US media
# HQ in ET).
_HOST_TIMEZONES = {
    # Central Time
    'wsmv.com': 'America/Chicago',
    'kstp.com': 'America/Chicago',
    'kare11.com': 'America/Chicago',
    'fox9.com': 'America/Chicago',
    'foxillinois.com': 'America/Chicago',
    'deadlinedetroit.com': 'America/Detroit',  # Michigan = ET but close to CT border
    'clickondetroit.com': 'America/Detroit',
    # Pacific Time
    'latimes.com': 'America/Los_Angeles',
    'californiaglobe.com': 'America/Los_Angeles',
    'foxla.com': 'America/Los_Angeles',
    # Mountain / Arizona (no DST)
    'azcir.org': 'America/Phoenix',
    # Florida
    'clickorlando.com': 'America/New_York',
}


def _iso_to_local_date(iso_str, url):
    """Convert an ISO datetime string to the publisher's local date.

    If the ISO string has a UTC 'Z' suffix or an explicit offset, we
    parse it and convert to the host's local timezone. If the string
    is a bare date ('2026-02-19') or bare datetime with no TZ, we
    treat it as already-local and return the date portion.

    Falls back to ET for hosts not in _HOST_TIMEZONES (US media default).
    Returns 'YYYY-MM-DD' or None on parse failure.
    """
    if not iso_str:
        return None
    # Bare date — no conversion needed
    if re.match(r'^\d{4}-\d{2}-\d{2}$', iso_str):
        return iso_str
    try:
        from datetime import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            # Python <3.9 fallback: no conversion, return date portion
            return iso_str[:10] if len(iso_str) >= 10 else None
        # Parse ISO datetime (handles 'Z' suffix and +hh:mm offsets)
        s = iso_str.replace('Z', '+00:00')
        dt = _dt.fromisoformat(s)
        # If TZ-naive, assume UTC (safer than assuming local)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        host = urlparse(url).netloc.lower().replace('www.', '')
        tz_name = _HOST_TIMEZONES.get(host, 'America/New_York')
        local_dt = dt.astimezone(ZoneInfo(tz_name))
        return local_dt.strftime('%Y-%m-%d')
    except Exception:
        # Parse failed — fall back to raw first 10 chars
        return iso_str[:10] if len(iso_str) >= 10 else None


def _extract_canonical_date(soup, url, response_headers=None):
    """Extract a publication date from structured markup.

    Priority order (most authoritative first):
      1. <meta property="article:published_time"> — OpenGraph standard
      2. JSON-LD datePublished — schema.org standard
      3. <time datetime="..."> — HTML5 standard
      4. URL path date pattern /YYYY/MM/DD/
      5. HTTP Last-Modified header (if response_headers provided)

    Returns an ISO date string 'YYYY-MM-DD' or None if nothing was found.
    Visual body-text scraping is intentionally NOT done here — callers
    keep their existing regex fallback for that case.

    Timestamps are converted from UTC to the publisher's local timezone
    before extracting the date, so a 7:47 PM CST article isn't stored
    as the next UTC day. See _iso_to_local_date().
    """
    # 1. OpenGraph
    og = soup.find('meta', attrs={'property': 'article:published_time'})
    if og and og.get('content'):
        iso = _iso_to_local_date(og['content'], url)
        if iso and re.match(r'^\d{4}-\d{2}-\d{2}$', iso):
            return iso
    # 2. JSON-LD datePublished (may be array of scripts; take first valid)
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        # JSON-LD can be a single object, an array, or a @graph wrapper
        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if '@graph' in data and isinstance(data['@graph'], list):
                candidates = data['@graph']
            else:
                candidates = [data]
        for obj in candidates:
            if isinstance(obj, dict) and obj.get('datePublished'):
                iso = _iso_to_local_date(str(obj['datePublished']), url)
                if iso and re.match(r'^\d{4}-\d{2}-\d{2}$', iso):
                    return iso
    # 3. <time datetime="..."> — prefer elements marked as publication
    for time_el in soup.find_all('time', attrs={'datetime': True}):
        dt = time_el['datetime']
        iso = _iso_to_local_date(dt, url)
        if iso and re.match(r'^\d{4}-\d{2}-\d{2}$', iso):
            return iso
    # 4. URL path /YYYY/MM/DD/
    m = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})(?:/|$)', url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    # 5. HTTP Last-Modified header (weak — reflects server caching, not pub)
    if response_headers:
        lm = response_headers.get('Last-Modified')
        if lm:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(lm).strftime('%Y-%m-%d')
            except Exception:
                pass
    return None


def fetch_detail_page(session, url):
    """Fetch a detail page and return (text, doj_link, canonical_title, canonical_date).

    The canonical_title is extracted from (in order of preference):
      1. <meta property="og:title">
      2. <h1> on the page
      3. <title> tag, stripped of site/breadcrumb boilerplate
    Returns "" for canonical_title if nothing usable was found — callers
    should fall back to the listing-page link text in that case.

    The canonical_date is extracted from structured markup via
    _extract_canonical_date(). Returns None if no structured date was
    found — callers should fall back to listing-page date / body-text
    regex in that case.
    """
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()

        # PDF branch: if the URL or Content-Type indicates PDF, extract
        # text with pypdf. CMS Fast Facts, annual reports, and many
        # federal agency publications are PDF-only — HTML parsing skips
        # them entirely. This lets the strict tagger see PDF body
        # content instead of only the title.
        ct = resp.headers.get('content-type', '').lower()
        if url.lower().endswith('.pdf') or 'application/pdf' in ct:
            try:
                import io
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(resp.content))
                # Use first 12k chars so we don't overfetch giant reports
                parts = []
                for page in reader.pages:
                    try:
                        parts.append(page.extract_text() or '')
                    except Exception:
                        continue
                text = re.sub(r'\s+', ' ', ' '.join(parts))[:12000]
                # PDFs don't have og:title / h1. Use PDF document title
                # if present; otherwise return empty (caller will use
                # listing-page title).
                doc_title = ''
                try:
                    if reader.metadata and reader.metadata.title:
                        doc_title = reader.metadata.title.strip()
                except Exception:
                    pass
                # PDFs usually don't have a proper canonical date; rely
                # on caller's date fallback.
                return (text, None, doc_title, None)
            except Exception as e:
                log(f"    PDF parse failed for {url}: {e}")
                return "", None, "", None

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
        # Extract canonical date from structured markup (None if not found)
        canonical_date = _extract_canonical_date(soup, url, resp.headers)
        # Try common content containers
        main = (soup.find('main') or soup.find('article') or
                soup.find('div', class_='field-item') or
                soup.find('div', class_='entry-content'))
        if main:
            for tag in main.find_all(['nav', 'footer', 'aside', 'script', 'style']):
                tag.decompose()
            # Strip "Related Press Releases" / "Related Content" sidebars
            # that embed unrelated case titles (which drive tag-extraction
            # false positives like ACA being tagged on a Medicare DME
            # case because the sidebar links to an ACA case).
            related_re = re.compile(
                r"(?:^|\s)(related-content|related-press|related-stor|"
                r"views-blockrelated|more-news|more-press|"
                r"you-may-also-like|further-reading|recommend)",
                re.I,
            )
            for tag in main.find_all(class_=related_re):
                tag.decompose()
            for tag in main.find_all(class_=re.compile(
                    r"social-share|share-links", re.I)):
                tag.decompose()
            # Heading-text-based related-sidebar strip: CMS and some other
            # agencies render "Related Releases" / "Related Press Releases"
            # as a heading rather than via a class hook. Decompose the
            # heading and every sibling after it so the sidebar's
            # unrelated press-release titles can't leak into tag extraction.
            _related_heading_re = re.compile(
                r"^\s*(related\s+(releases|press\s+releases|content|"
                r"stor(y|ies)|articles?)|more\s+(news|press|from))\b",
                re.I,
            )
            for h in main.find_all(["h2", "h3", "h4"]):
                if _related_heading_re.match(h.get_text(" ", strip=True) or ""):
                    # remove this heading and all following siblings
                    sib = h.find_next_sibling()
                    h.decompose()
                    while sib is not None:
                        nxt = sib.find_next_sibling()
                        try: sib.decompose()
                        except Exception: pass
                        sib = nxt
                    break
            return (re.sub(r'\s+', ' ', main.get_text(' ', strip=True)),
                    doj_link, canonical_title, canonical_date)
        return "", doj_link, canonical_title, canonical_date
    except Exception as e:
        log(f"    Detail fetch failed for {url}: {e}")
        return "", None, "", None

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

def parse_date(date_str, *, strict=False):
    """Parse a date string into 'YYYY-MM-DD'.

    Returns today's date for empty input (convenience for callers that
    don't care). For non-empty strings that can't be parsed:
      - strict=True returns None (caller is expected to handle the
        missing date — flag for review, skip, etc.)
      - strict=False falls back to today's date and logs a WARNING
        with the raw string, so the parser gap becomes visible.

    New callers should pass strict=True. The non-strict default stays
    for backward compatibility, but those call sites should be migrated
    over time.
    """
    if not date_str:
        return None if strict else datetime.now().strftime('%Y-%m-%d')
    for fmt in [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d',
        '%B %d, %Y',
        '%b %d, %Y',
        '%b. %d, %Y',
        '%m/%d/%Y',
        '%d %B %Y',
        '%d %b %Y',
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue
    # Last-resort dateutil fallback
    try:
        from dateutil import parser as du_parser
        return du_parser.parse(date_str).strftime('%Y-%m-%d')
    except Exception:
        pass
    # All parsers failed
    if strict:
        return None
    log(f"  WARNING: could not parse date '{date_str}' — defaulting to today. "
        f"Add a format string to parse_date() to fix.", "yellow")
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
                detail_text, doj_link, canonical_title, canonical_date = fetch_detail_page(session, href)
                # If DOJ press release exists, use it as the canonical link.
                canonical_link = doj_link if doj_link else href
                # In normal mode we also fetch the DOJ press release text to
                # get better tag/amount extraction. In backfill mode we skip
                # that second fetch — justice.gov bot-blocks most of the time
                # and we don't store descriptions anyway, so the incremental
                # quality isn't worth the latency or failure rate.
                if doj_link and not backfill:
                    doj_text, _, doj_canonical, _doj_date = fetch_detail_page(session, doj_link)
                    if doj_text:
                        detail_text = doj_text  # use DOJ text for description/tags
                    if doj_canonical:
                        canonical_title = doj_canonical  # prefer DOJ headline
                    # DOJ press release date is the authoritative prosecution date
                    if _doj_date:
                        canonical_date = _doj_date
                # Override listing-page title with the canonical headline
                if canonical_title:
                    title = canonical_title
                # Date priority: structured canonical > listing-page regex > body-text regex
                if canonical_date:
                    date_str = canonical_date
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
    """Scrape CMS newsroom press releases with pagination.

    CMS's newsroom shows only 7 items per page, and fraud-relevant
    items (CRUSH, hospice suspensions, corrective actions) scroll off
    within days as rate-setting announcements take over. Walking
    pages 0-9 (up to 70 items) catches fraud items from the past
    ~2-3 months.

    Normal mode: pages 0-4 (35 items, ~1 month of CMS output).
    Backfill mode: pages 0-14 (105 items, ~3-4 months).

    Requires Playwright because the CMS newsroom is JS-rendered —
    requests returns the same 7 items regardless of page param.
    Falls back to the old requests approach (page 0 only) if
    Playwright is unavailable.
    """
    items = []
    seen_hrefs = set()
    backfill = globals().get('BACKFILL_MODE', False)
    floor = globals().get('BACKFILL_FLOOR', '2025-01-01')
    # Backfill walks up to 40 pages; early-stops on a page fully below floor.
    max_pages = 40 if backfill else 5

    if HAS_PLAYWRIGHT:
        try:
            prev_len = 0
            for page_n in range(max_pages):
                url = f"https://www.cms.gov/newsroom?page={page_n}"
                soup = scrape_page_with_browser(url)
                page_items = 0
                for a_tag in soup.find_all('a', href=True):
                    txt = a_tag.get_text(strip=True)
                    if not txt.startswith('Read moreabout '):
                        continue
                    title = txt.replace('Read moreabout ', '').strip()
                    if not title or len(title) < 15:
                        continue
                    href = a_tag.get('href', '')
                    if href.startswith('/'):
                        href = 'https://www.cms.gov' + href
                    if href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)
                    # Fetch detail page for canonical title + body + date
                    detail_text = ""
                    _detail_title = ""
                    try:
                        detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
                    except Exception:
                        pass
                    if _detail_title:
                        title = _detail_title
                    # Date priority: structured markup (canonical) > body-text regex
                    date_str = _detail_date or ""
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
                    })
                    page_items += 1
                if page_items == 0:
                    break  # empty page = end of listing
                # Backfill early-stop: all new items this page below floor.
                if backfill and page_n >= 1:
                    new_this_page = items[prev_len:]
                    parsed_dates = []
                    for it in new_this_page:
                        pd = it.get('pub_date', '')
                        if pd:
                            try:
                                parsed_dates.append(parse_date(pd))
                            except Exception:
                                pass
                    if parsed_dates and max(parsed_dates) < floor:
                        log(f"  CMS backfill: page {page_n} all older than {floor}, stopping")
                        break
                prev_len = len(items)
        except Exception as e:
            log(f"  WARNING: CMS Playwright scrape - {e}", "yellow")
    else:
        # Fallback: old requests-based scrape (page 0 only)
        url = "https://www.cms.gov/about-cms/contact/newsroom"
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
                detail_text, _, canonical_title, canonical_date = fetch_detail_page(session, href)
                if canonical_title:
                    title = canonical_title
                # Structured date first, body-text regex as fallback
                date_str = canonical_date or ""
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

def scrape_cms_fraud_page(session):
    """Scrape cms.gov/fraud — CMS's dedicated anti-fraud landing page.

    This page carries PDF fact sheets, annual reports, data dashboards,
    and hot-spot analyses that CMS publishes OUTSIDE of the newsroom.
    The FDOC, CRUSH, WISeR, hospice fraud, RADV, and DMEPOS fraud
    content all live here. Updates ~quarterly (not daily), so this is
    a low-volume but high-value source.

    Requires Playwright because the page is JS-rendered.
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping CMS-Fraud (requires Playwright)")
        return []
    items = []
    try:
        soup = scrape_page_with_browser("https://www.cms.gov/fraud")
        seen = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            if href in seen:
                continue
            seen.add(href)
            # Only CMS PDF fact sheets + reports — the real content
            if not re.search(r'\.pdf$|/files/document/', href, re.I):
                continue
            if href.startswith('/'):
                href = 'https://www.cms.gov' + href
            # Pre-filter: must be fraud-related content
            if not re.search(r'fraud|crush|fdoc|wiser|hospice|moratorium|'
                             r'integrity|improper|radv|dmepos|hot.spot|'
                             r'dual.enrollment|annual.report',
                             f"{title} {href}", re.I):
                continue
            items.append({
                'title': title,
                'description': '',
                'link': href,
                'pub_date': '',  # PDFs don't have inline dates
                '_full_text': '',
            })
    except Exception as e:
        log(f"  WARNING: CMS fraud page scrape - {e}", "yellow")
    return items


# Pattern for press releases that describe/announce/recap a hearing
# (but aren't the hearing itself). These get rejected by committee
# scrapers because the hearing-proper is already captured via
# scrape_congress_hearings.py (Congress.gov API). Keeping both on the
# dashboard creates duplicate coverage of the same event.
#
# Examples:
#   "Chairmen Guthrie and Joyce Announce ... Hearing on ..."
#   "Chairman Comer Opening Statement at Hearing on ..."
#   "Hearing Wrap-Up: ..."
#   "Press Release: Committee Holds Hearing on ..."
#   "Chair Smith's Opening Statement: Hearing with ..."
_HEARING_ABOUT_PATTERN = re.compile(
    r"("
    # "Announce(s/d) ... Hearing" with up to 60 chars between
    r"\bannounc\w*\s[\w\s,.&'-]{0,60}?\bhearing\b|"
    # "Opens / Opened ... Hearing"
    r"\bopen(s|ed|ing)?\s[\w\s,.&'-]{0,30}?\bhearing\b|"
    # "Opening Statement ... Hearing" or "Opening Statement: Hearing"
    r"\bopening\s+(statement|remarks)[\s\S]{0,30}?\bhearing\b|"
    # Wrap-up phrasing
    r"\bhearing\s+wrap[-\s]?up\b|"
    r"\bwrap[-\s]?up[\s\S]{0,20}?\bhearing\b|"
    # "Committee to hold/convene hearing"
    r"\bcommittee\s+(to\s+)?(hold|holds|holding|convene|convenes|will\s+hold)\s+(an?\s+|the\s+)?hearing\b|"
    r"\b(will\s+)?(hold|convene)\s+(an?\s+|the\s+|upcoming\s+)?hearing\b|"
    # Closing statements
    r"\bclosing\s+(statement|remarks)[\s\S]{0,20}?\bhearing\b|"
    # Recap/readout about a hearing
    r"\b(recap|readout|summary)\s[\w\s,.&'-]{0,20}?\bhearing\b"
    r")",
    re.IGNORECASE,
)


def _is_hearing_about(title):
    """True if the title describes a hearing event (announcement/wrap-up/
    opening statement) rather than being the hearing's own page.
    Used by committee press-release scrapers to reject hearing-about items;
    the hearing itself is captured via Congress.gov API."""
    if not title:
        return False
    return bool(_HEARING_ABOUT_PATTERN.search(title))


# Pattern for "Member X introduces / files / proposes bill / legislation"
# press releases. Dashboard doesn't systematically track bill introductions,
# so including these leads to arbitrary/inconsistent coverage.
_BILL_INTRO_PATTERN = re.compile(
    r"\b("
    r"introduce(s|d)?\s+(a?\s+)?(new\s+)?(bipartisan\s+)?(bill|legislation|act)\b|"
    r"(introduces|reintroduces|unveils|releases)\s+.{0,40}?\b(bill|legislation|act|proposal)\b|"
    r"bill\s+(to\s+fight|to\s+combat|to\s+address|to\s+prevent)|"
    r"legislative\s+proposal\s+to\s+(fight|combat|address|prevent)|"
    r"file(s|d)?\s+.{0,30}?\blegislation\b"
    r")",
    re.IGNORECASE,
)


def _is_bill_intro(title):
    """True if the title is a 'Member X introduces bill' press release."""
    if not title:
        return False
    return bool(_BILL_INTRO_PATTERN.search(title))


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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Reject press releases that describe a hearing (announcement,
            # opening statement, wrap-up) — the hearing itself is captured
            # via scrape_congress_hearings.py (Congress.gov API). Avoids
            # duplicate coverage of the same event.
            if _is_hearing_about(title):
                continue
            # Reject "Member X introduces bill" press releases — the
            # dashboard doesn't track bill introductions consistently, so
            # these get arbitrary inclusion. Actual legislation that
            # passes + affects fraud enforcement should appear via its
            # implementing agency's press release instead.
            if _is_bill_intro(title):
                continue
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

    Normal mode: pages 1-3 (60 items, ~2-3 years of press releases).
    Backfill mode: pages 1-8 (all ~160 items in the archive).

    Source: oig.hhs.gov/newsroom/news-releases-articles/
    """
    base_url = "https://oig.hhs.gov/newsroom/news-releases-articles/"
    backfill = globals().get('BACKFILL_MODE', False)
    floor = globals().get('BACKFILL_FLOOR', '2025-01-01')
    # Backfill walks up to 40 pages; early-stops on a page fully below floor.
    max_pages = 40 if backfill else 3
    items = []
    prev_len = 0
    for page_n in range(max_pages):
        url = base_url if page_n == 0 else f"{base_url}?page={page_n}"
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
                # Skip "At a Glance" summary press releases — these are
                # 2-page digests of the biannual semiannual Reports to
                # Congress. The full report is captured elsewhere; we don't
                # need both.
                if re.match(r'^at\s+a\s+glance\b', title, re.I):
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
                    detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
                except Exception:
                    pass
                if _detail_title:
                    title = _detail_title
                # Prefer structured canonical date over the listing-card span
                if _detail_date:
                    date_str = _detail_date
                # Dedup-against-report: many OIG news releases are summaries
                # of audit reports. If the press-release body links to a
                # report at /reports/all/, prefer the report as the canonical
                # item and skip this news release. (The report is typically
                # already on the dashboard via scrape_oig_reports.)
                if detail_text:
                    linked_report = re.search(
                        r'https?://oig\.hhs\.gov/reports/all/[^\s<>"]+',
                        detail_text)
                    if linked_report:
                        # Stash the linked report URL so downstream dedup
                        # (audit_new_items + actions.json comparison) can
                        # use it to detect the duplicate.
                        pass  # handled as _report_ref below
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
                item = {
                    'title': title,
                    'description': desc,
                    'link': href,
                    'pub_date': date_str,
                    '_full_text': detail_text,
                }
                # If body links to an OIG report, record the report URL.
                # The main dedup pass (in update.py's promote-to-actions
                # logic) treats items with _report_ref as candidates to
                # drop when a matching report is already present.
                if detail_text:
                    rlink = re.search(
                        r'https?://oig\.hhs\.gov/reports/all/[^\s<>"]+',
                        detail_text)
                    if rlink:
                        item['_report_ref'] = rlink.group().rstrip('.,)"\'')
                items.append(item)
            # Backfill early-stop: all new items on this page below floor.
            if backfill and page_n >= 1:
                page_items = items[prev_len:]
                parsed_dates = []
                for it in page_items:
                    pd = it.get('pub_date', '')
                    if pd:
                        try:
                            parsed_dates.append(parse_date(pd))
                        except Exception:
                            pass
                if parsed_dates and max(parsed_dates) < floor:
                    log(f"  OIG press backfill: page {page_n} all older than {floor}, stopping")
                    break
            prev_len = len(items)
        except Exception as e:
            log(f"  WARNING: OIG press scrape page {page_n} - {e}", "yellow")
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
                        detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
                    except Exception:
                        pass
                    if detail_text and _CONGRESS_HC_PREFILTER.search(detail_text):
                        title_passes = True
                if not title_passes:
                    continue
                # If we didn't fetch yet (title passed on first check), fetch now
                if not detail_text:
                    try:
                        detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
                    except Exception:
                        pass
                if _detail_title:
                    title = _detail_title
                # Reject hearing-about press releases (announcement, opening
                # statement, wrap-up). Hearing itself is captured via
                # scrape_congress_hearings.py (Congress.gov API).
                if _is_hearing_about(title):
                    continue
                # Reject "Member X introduces bill" press releases — not
                # tracked consistently across dashboard.
                if _is_bill_intro(title):
                    continue
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Reject press releases that describe a hearing (announcement,
            # opening statement, wrap-up) — the hearing itself is captured
            # via scrape_congress_hearings.py (Congress.gov API). Avoids
            # duplicate coverage of the same event.
            if _is_hearing_about(title):
                continue
            # Reject "Member X introduces bill" press releases — the
            # dashboard doesn't track bill introductions consistently, so
            # these get arbitrary inclusion. Actual legislation that
            # passes + affects fraud enforcement should appear via its
            # implementing agency's press release instead.
            if _is_bill_intro(title):
                continue
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Reject press releases that describe a hearing (announcement,
            # opening statement, wrap-up) — the hearing itself is captured
            # via scrape_congress_hearings.py (Congress.gov API). Avoids
            # duplicate coverage of the same event.
            if _is_hearing_about(title):
                continue
            # Reject "Member X introduces bill" press releases — the
            # dashboard doesn't track bill introductions consistently, so
            # these get arbitrary inclusion. Actual legislation that
            # passes + affects fraud enforcement should appear via its
            # implementing agency's press release instead.
            if _is_bill_intro(title):
                continue
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Reject press releases that describe a hearing (announcement,
            # opening statement, wrap-up) — the hearing itself is captured
            # via scrape_congress_hearings.py (Congress.gov API). Avoids
            # duplicate coverage of the same event.
            if _is_hearing_about(title):
                continue
            # Reject "Member X introduces bill" press releases — the
            # dashboard doesn't track bill introductions consistently, so
            # these get arbitrary inclusion. Actual legislation that
            # passes + affects fraud enforcement should appear via its
            # implementing agency's press release instead.
            if _is_bill_intro(title):
                continue
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Reject press releases that describe a hearing (announcement,
            # opening statement, wrap-up) — the hearing itself is captured
            # via scrape_congress_hearings.py (Congress.gov API). Avoids
            # duplicate coverage of the same event.
            if _is_hearing_about(title):
                continue
            # Reject "Member X introduces bill" press releases — the
            # dashboard doesn't track bill introductions consistently, so
            # these get arbitrary inclusion. Actual legislation that
            # passes + affects fraud enforcement should appear via its
            # implementing agency's press release instead.
            if _is_bill_intro(title):
                continue
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

def extract_investigator_agencies(body_text):
    """Extract federal investigator agencies mentioned in a press release.

    Looks ONLY for literal HHS-OIG mentions in investigator-context phrases
    (no inference). DOJ press releases almost always include a "credits"
    paragraph that names each investigator; we scan a window around
    investigator-signal phrases and require an HHS-OIG match.

    Dashboard scope (2026-04-21): only HHS-OIG is tracked in
    related_agencies. DEA/FDA/FBI/etc. were removed — those cases are
    captured via area tags (Opioids, Medical Devices) on DOJ items.

    Returns a list, always ['HHS-OIG'] or []. No defaulting — if the
    body doesn't literally credit HHS-OIG, this returns [].
    """
    if not body_text:
        return []
    # Investigator-signal phrases that DOJ releases use to credit investigators
    signal_re = re.compile(
        r"\b(investigat(?:ed|ion|ing|ors?)|special\s+agent|"
        r"announced\s+by|announced\s+the|thanked|conducted\s+by|"
        r"is\s+investigating|was\s+investigated|jointly\s+announced)\b",
        re.IGNORECASE,
    )
    # HHS-OIG name variants
    oig_re = re.compile(
        r"\bHHS[-\s]?OIG\b|"
        r"\bHHS\s+Office\s+of\s+Inspector\s+General\b|"
        r"\bOffice\s+of\s+Inspector\s+General\s+(?:for\s+the\s+)?"
        r"(?:U\.?S\.?\s+)?(?:Department\s+of\s+)?Health\s+and\s+Human\s+Services\b|"
        r"\bDepartment\s+of\s+Health\s+and\s+Human\s+Services[-,]?\s+"
        r"Office\s+of\s+Inspector\s+General\b",
        re.IGNORECASE,
    )
    # Scan 600-char windows around each investigator signal; look for HHS-OIG
    for m in signal_re.finditer(body_text):
        window = body_text[max(0, m.start() - 200): m.end() + 400]
        if oig_re.search(window):
            return ['HHS-OIG']
    return []


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
                detail_text, _, canonical_title, canonical_date = fetch_detail_page(session, href)
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
                    # related_agencies extracted from body — only HHS-OIG
                    # when the release literally credits them as investigator
                    '_related_agencies': extract_investigator_agencies(detail_text),
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

    Walks the consolidated DOJ USAO listing at /usao/pressreleases
    across multiple pages. USAO press releases come in from all 93
    districts combined, ~20-50/day — a single page (~25 items) covers
    less than one day of output, so items can scroll off between our
    7:17 UTC daily runs. Paginating to 5 pages (normal) / 20 pages
    (backfill) recovers the last ~3-5 days / ~2-3 weeks respectively
    and makes the scraper resilient to timing gaps.

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
    base_url = "https://www.justice.gov/usao/pressreleases"
    items = []
    try:
        from audit_new_items import fetch_doj_topics, has_hc_topic
    except ImportError as e:
        log(f"  DOJ-USAO: cannot import topic helpers: {e}")
        return []

    backfill = globals().get('BACKFILL_MODE', False)
    max_pages = 20 if backfill else 5

    try:
        candidates = []
        seen = set()
        prev_count = 0
        for page_n in range(max_pages):
            page_url = base_url if page_n == 0 else f"{base_url}?page={page_n}"
            try:
                soup = scrape_page_with_browser(page_url)
            except Exception as e:
                log(f"    DOJ-USAO page {page_n}: fetch failed ({e})")
                break
            page_new = 0
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
                page_new += 1
            # Early-stop: if a page added 0 new candidates, the pagination
            # probably walked off the end (or the listing is cached).
            if page_new == 0 and page_n > 0:
                log(f"    DOJ-USAO: page {page_n} had 0 new candidates, stopping pagination")
                break
            prev_count = len(candidates)

        log(f"    DOJ-USAO: {len(candidates)} candidates across {page_n + 1} pages, checking topic tags...")
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
                    detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
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
                    '_related_agencies': extract_investigator_agencies(detail_text),
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, link)
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
    """Scrape HHS-OIG audit/inspection reports.

    Normal mode: pages 1-5 (100 items, ~2-3 months of reports).
    Backfill mode: pages 1-15 (300 items, ~6-9 months).
    """
    base_url = "https://oig.hhs.gov/reports/all/"
    DATE_RE = re.compile(r'Issued\s+(\d{2}/\d{2}/\d{4})')
    backfill = globals().get('BACKFILL_MODE', False)
    floor = globals().get('BACKFILL_FLOOR', '2025-01-01')
    # Backfill walks up to 50 pages (~1000 items, ~2 years of reports).
    # Early-stops when a full page falls below the floor.
    max_pages = 50 if backfill else 5
    items = []
    prev_len = 0
    for page in range(1, max_pages + 1):
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
                # Skip clean-bill-of-health audits. HHS-OIG uses several stock
                # phrases when an auditee passed compliance review:
                #   "in accordance with"
                #   "Generally Complied With [...] Requirements"
                #   "Generally Ensured That"
                #   "Generally Met [Federal/Medicare/Medicaid] Requirements"
                #   "Complied With Federal Requirements"
                # None of these are fraud findings — auditee did the right
                # thing and the OIG is just documenting that. Skip them.
                if re.search(r'\b(in\s+accordance\s+with|generally\s+complied\s+with|'
                             r'generally\s+ensured\s+that|'
                             r'generally\s+met\s+(federal|medicare|medicaid)\s+requirements|'
                             r'complied\s+with\s+(federal|medicare|medicaid)\s+requirements|'
                             r'substantially\s+complied|did\s+comply)\b',
                             title, re.I):
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
                # Fetch detail page for description, canonical title, canonical date
                detail_text, _, canonical_title, canonical_date = fetch_detail_page(session, href)
                if canonical_title:
                    title = canonical_title
                # Body-level clean-bill-of-health check. HHS-OIG audits where
                # the auditee complied often don't hit the title filter above
                # but DO have a stock phrase in the What OIG Found / Recommen-
                # dations section. Scan the first ~3000 chars (covers the
                # abstract + key findings) for any such phrase. Match =
                # compliance finding = skip.
                if detail_text:
                    head = detail_text[:3000].lower()
                    compliance_signals = [
                        "oig has no recommendations",
                        "no recommendations",
                        "oig is making no recommendations",
                        "oig recommends no corrective action",
                        "no exceptions noted",
                        "auditee substantially complied",
                        "agency substantially complied",
                        "provider substantially complied",
                        "state substantially complied",
                        "generally complied with federal requirements",
                        "generally complied with medicare requirements",
                        "generally complied with medicaid requirements",
                        "met medicare requirements",
                        "met medicaid requirements",
                    ]
                    # Only skip if a compliance signal appears AND there's no
                    # counter-signal (fraud/improper payment/kickback) that
                    # indicates the audit still matters
                    fraud_signal = re.search(
                        r"\b(fraud|kickback|improper\s+payment|overpayment|"
                        r"false\s+claim|enforcement|excluded\s+provider|"
                        r"suspension|referral|improperly|"
                        r"unallowable|exceeded\s+medicare|program\s+integrity\s+concern)\b",
                        head)
                    if any(sig in head for sig in compliance_signals) and not fraud_signal:
                        log(f"  skipping OIG no-issue audit (body compliance signal): {title[:80]}")
                        continue
                # Prefer structured canonical date over the listing-page regex.
                # If they disagree by >7 days, log it — listing sometimes beats
                # the structured tag (e.g. "last-modified" vs "published").
                # Policy: for HHS-OIG reports, the listing page's "Issued"
                # date is the authoritative date (it's the date OIG printed
                # on the report and used for backfills). Only fall back to
                # canonical_date when the listing didn't provide one.
                # This keeps historical backfills and new scrapes consistent.
                if canonical_date:
                    if date_str:
                        try:
                            listing_iso = parse_date(date_str, strict=True)
                            if listing_iso:
                                d1 = datetime.strptime(listing_iso, '%Y-%m-%d')
                                d2 = datetime.strptime(canonical_date, '%Y-%m-%d')
                                if abs((d1 - d2).days) > 7:
                                    log(f"  NOTE: OIG reports listing date {listing_iso} "
                                        f"disagrees with canonical {canonical_date} by "
                                        f"{abs((d1-d2).days)}d for {href} — keeping listing date")
                        except Exception:
                            pass
                    else:
                        # No listing date — use canonical as fallback
                        date_str = canonical_date
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
            # Backfill early-stop: if every item added this page parses
            # to a date older than the floor, stop walking.
            if backfill and page >= 2:
                page_items = items[prev_len:]
                parsed_dates = []
                for it in page_items:
                    pd = it.get('pub_date', '')
                    if pd:
                        try:
                            parsed_dates.append(parse_date(pd))
                        except Exception:
                            pass
                if parsed_dates and max(parsed_dates) < floor:
                    log(f"  OIG reports backfill: page {page} all older than {floor}, stopping")
                    break
            prev_len = len(items)
        except Exception as e:
            log(f"  WARNING: OIG reports page {page} - {e}", "yellow")
    return items


# Fraud-keyword gate for MACPAC/MedPAC publications. Both commissions
# publish extensively on payment policy, access, and enrollment —
# important healthcare policy but not in our scope. Require fraud-
# specific vocabulary in title OR body before accepting an item.
_MACPAC_MEDPAC_FRAUD_GATE = re.compile(
    r"\b("
    r"fraud|integrity|waste.{0,15}abuse|abuse.{0,15}waste|"
    r"improper\s+payment|overpayment|kickback|false\s+claim|"
    r"qui\s+tam|anti-?fraud|program\s+integrity|"
    r"excluded?\s+provider|enforcement|suspension|moratorium|"
    r"corrective\s+action|takedown|strike\s+force|"
    r"upcod|risk\s+adjustment\s+(fraud|upcoding|manipulation)"
    r")\b",
    re.IGNORECASE,
)


def _fraud_gate_check(title, body, max_body_chars=2000):
    """True if title OR first ~2k chars of body mention fraud-specific terms.

    Used for MACPAC/MedPAC where most publications are general policy and
    only a subset touch fraud/integrity. Scanning early body (not full body)
    keeps the gate strict — passing mentions buried deep in a policy paper
    don't qualify.
    """
    if _MACPAC_MEDPAC_FRAUD_GATE.search(title or ""):
        return True
    return bool(_MACPAC_MEDPAC_FRAUD_GATE.search((body or "")[:max_body_chars]))


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
            # Skip general biannual Reports to Congress (March/June payment-
            # policy reports cover broad Medicare landscape, not fraud-focused).
            # Topical issue briefs + comment letters remain eligible.
            if re.search(r'^(march|june|december|annual)\s+\d{4}\s+'
                         r'report\s+to\s+(the\s+)?congress', title, re.I):
                continue
            # Fetch detail page for description + canonical title
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Fraud-keyword gate: MedPAC publishes extensively on Medicare
            # payment policy, access, and benefits — most of it isn't
            # fraud-focused. Require fraud/integrity vocabulary in title
            # or early body text before accepting.
            if not _fraud_gate_check(title, detail_text):
                continue
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
            # Skip general biannual Reports to Congress. These span the entire
            # Medicaid/CHIP landscape (payment, access, enrollment, managed
            # care, program integrity, etc.) and are too broad to tag as a
            # single fraud-oversight action. Individual topical chapters are
            # already skipped above; specific issue briefs + comment letters
            # remain eligible.
            if re.search(r'^(march|june|december|annual)\s+\d{4}\s+'
                         r'report\s+to\s+(the\s+)?congress', title, re.I):
                continue
            # Fetch detail page
            detail_text = ""
            _detail_title = ""
            try:
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Fraud-keyword gate: skip publications where neither title nor
            # early body mentions fraud/integrity/waste/abuse. MACPAC publishes
            # many general policy items (enrollment, payment, access) that
            # aren't in scope for this dashboard.
            if not _fraud_gate_check(title, detail_text):
                continue
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


def scrape_hhs_press(session):
    """Scrape HHS press room (hhs.gov/press-room).

    HHS-proper (the department, distinct from HHS-OIG) publishes
    announcements about anti-fraud task forces, General Counsel hires
    tied to fraud enforcement, Secretary statements on Medicaid/Medicare
    integrity initiatives, and cross-agency coordination efforts. These
    don't appear on the OIG or CMS streams.

    Most HHS press releases are NOT fraud-related (they cover grants,
    programs, vaccine policy, public health). We pre-filter on title
    keywords before fetching detail pages.

    Normal mode: pages 0-2 (30 items, ~1 month).
    Backfill mode: pages 0-20 (full ~210-item archive), with floor
    early-stop.

    HHS bot-blocks generic requests (403) even with Sec-Fetch-* headers —
    requires Playwright for browser fingerprinting, same as CMS.
    """
    if not HAS_PLAYWRIGHT:
        log("    Skipping HHS press (requires Playwright)")
        return []
    base_url = "https://www.hhs.gov/press-room/index.html"
    # Title pre-filter: only fetch detail pages for items with fraud-enforcement
    # vocabulary. Broader than HC_KEYWORDS (which flood on "medicare"/"medicaid")
    # but narrower than just any HC mention.
    FRAUD_SIGNAL = re.compile(
        r"\b(fraud|kickback|false\s+claim|qui\s+tam|anti-?kickback|"
        r"enforcement|strike\s+force|task\s+force|investigat|"
        r"indictment|sentenc|guilty|convict|plea|takedown|"
        r"overpay|improper\s+payment|moratorium|corrective\s+action|"
        r"program\s+integrity|anti-?fraud|waste.{0,10}abuse|"
        r"u\.?s\.?\s+attorney|prosecut|whistleblower|exclus|debarment|"
        r"special\s+focus|medicaid\s+integrity|medicare\s+integrity)\b",
        re.IGNORECASE,
    )
    backfill = globals().get('BACKFILL_MODE', False)
    floor = globals().get('BACKFILL_FLOOR', '2025-01-01')
    max_pages = 20 if backfill else 2
    items = []
    prev_len = 0
    for page_n in range(max_pages + 1):
        url = base_url if page_n == 0 else f"{base_url}?page={page_n}"
        try:
            soup = scrape_page_with_browser(url)
            cards = soup.select('li.usa-collection__item.teaser-news')
            if not cards:
                # Fallback selector in case HHS tweaks class names
                cards = soup.select('li.usa-collection__item')
            for card in cards:
                a_tag = card.select_one('h2.usa-collection__heading a')
                if not a_tag:
                    a_tag = card.select_one('a.usa-link')
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                # Pre-filter: skip items without fraud-enforcement vocabulary
                if not FRAUD_SIGNAL.search(title):
                    continue
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.hhs.gov' + href
                # Date from listing card
                date_str = ""
                time_el = card.select_one('time')
                if time_el:
                    date_str = time_el.get('datetime', '').split('T')[0] or time_el.get_text(strip=True)
                # Fetch detail page for canonical title + body
                detail_text = ""
                _detail_title = ""
                try:
                    detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
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
            # Backfill early-stop
            if backfill and page_n >= 1:
                page_items = items[prev_len:]
                parsed_dates = []
                for it in page_items:
                    pd = it.get('pub_date', '')
                    if pd:
                        try:
                            parsed_dates.append(parse_date(pd))
                        except Exception:
                            pass
                if parsed_dates and max(parsed_dates) < floor:
                    log(f"  HHS press backfill: page {page_n} all older than {floor}, stopping")
                    break
            prev_len = len(items)
        except Exception as e:
            log(f"  WARNING: HHS press scrape page {page_n} - {e}", "yellow")
    return items


def scrape_whitehouse(session):
    """Scrape whitehouse.gov for healthcare-fraud-relevant releases.

    WH publishes at two listing pages:
      - /releases/  — general press releases, fact sheets
      - /presidential-actions/  — executive orders, proclamations

    Both are relatively sparse on HC-fraud content (WH generally only
    covers it when there's a major announcement), so we use a narrow
    title pre-filter to avoid polluting the review queue with
    unrelated WH content (tax, foreign policy, defense, etc.).
    """
    items = []
    # Pre-filter: only fetch items whose title looks HC-fraud-relevant.
    # Broader than the enforcement filter — WH typically announces things
    # at a level above specific schemes (e.g., task force creation).
    HC_TITLE_FILTER = re.compile(
        r"\b("
        r"fraud|medicare|medicaid|tricare|health\s*care|healthcare|"
        r"affordable\s+care|obamacare|\baca\b|"
        r"prescription|pharmac|opioid|drug\s+abuse|"
        r"hospital|hospice|nursing\s+home|telehealth|"
        r"hhs\b|cms\b"
        r")\b",
        re.I,
    )
    listing_urls = [
        "https://www.whitehouse.gov/releases/",
        "https://www.whitehouse.gov/presidential-actions/",
    ]
    seen_hrefs = set()
    for list_url in listing_urls:
        try:
            resp = session.get(list_url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')
            # Iterate h2/h3/h4 with anchor children — standard WP pattern
            for h in soup.find_all(['h2', 'h3', 'h4']):
                a_tag = h.find('a', href=True)
                if not a_tag:
                    continue
                href = a_tag.get('href', '')
                if not href or href in seen_hrefs:
                    continue
                # Skip the listing/index itself
                if href.rstrip('/').endswith('/releases') or href.rstrip('/').endswith('/presidential-actions'):
                    continue
                # Only accept full release URLs (contain a year segment)
                if not re.search(r'/(releases|presidential-actions)/\d{4}/', href):
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 15:
                    continue
                # Pre-filter for HC-fraud vocabulary
                if not HC_TITLE_FILTER.search(title):
                    continue
                seen_hrefs.add(href)
                # Try to pick up date near the heading
                date_str = ""
                nearby_time = h.find_next('time')
                if nearby_time:
                    date_str = nearby_time.get('datetime', '')[:10] or nearby_time.get_text(strip=True)
                # Fetch detail for body, canonical title, canonical date
                detail_text = ""
                _detail_title = ""
                _detail_date = None
                try:
                    detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, href)
                except Exception:
                    pass
                if _detail_title:
                    title = _detail_title
                if _detail_date:
                    date_str = _detail_date
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
            log(f"  WARNING: White House scrape ({list_url}) - {e}", "yellow")
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
                detail_text, _, _detail_title, _detail_date = fetch_detail_page(session, full_href)
            except Exception:
                pass
            if _detail_title:
                title = _detail_title
            # Structured date from detail page first, body-text regex fallback
            date_str = _detail_date or ""
            if not date_str and detail_text:
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
    if scrape_mode == 'cms_fraud':
        return scrape_cms_fraud_page(session)
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
    if scrape_mode == 'hhs_press':
        return scrape_hhs_press(session)
    if scrape_mode == 'whitehouse':
        return scrape_whitehouse(session)
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
                             'Hearing, Technology/Innovation). '
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

    # If an incoming item references an existing audit report via _report_ref
    # (e.g. an OIG news release summarizing a report already on the dashboard),
    # we want to skip it. Rather than threading this through all dedup sites,
    # add the known report URLs to `existing_links` so they match OIG press
    # releases that stashed _report_ref during scraping.
    for a in data.get("actions", []):
        link = a.get("link", "")
        if link and "/reports/all/" in link:
            existing_links.add(normalize_link(link))

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

                # Use full detail text if available (from scrapers that
                # fetch detail pages). This is critical for CMS items
                # where fraud keywords appear deep in the body, past
                # the 600-char description truncation point.
                full_text = item.get('_full_text', '')
                search_text = f"{title} {desc_clean} {full_text}"
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
                # Dedup-against-report: if this item references an OIG report
                # URL that's already on the dashboard (captured from scrape_
                # oig_press body), skip — the report is the canonical action
                # and the news release is just a summary.
                report_ref = item.get('_report_ref')
                if report_ref and normalize_link(report_ref) in existing_links:
                    log(f"  skipping OIG news release (references existing report: {report_ref[:80]})")
                    continue

                date_str = item.get('pub_date', '')
                # If already YYYY-MM-DD, keep it; otherwise parse
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                    date_str = parse_date(date_str)

                # Enforce Jan 2025 floor only. We do NOT skip items
                # older than last_scraped_date because agencies sometimes
                # backdate press releases or publish items days/weeks
                # after the issue date. Dedup (link + title) prevents
                # duplicates without losing backdated items.
                if date_str < '2025-01-01':
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

                # Action type first — used as a hint for state extraction
                # (body-text fallback is skipped for policy/hearing types
                # per state rule v3 refinement).
                action_type = ('Investigative Report' if is_media
                               else get_action_type(title, search_text,
                                                    agency=feed.get('agency'),
                                                    link=link))

                # State detection: USAO -> party-state -> non-demonym title
                # -> city-if-no-USAO -> corroborated demonym -> body-fallback
                # (only for enforcement/investigation types). Policy items
                # (hearings, rules, reports) skip body-fallback so they
                # don't get wrongly assigned state from incidental body
                # mentions. See get_state() and state_tag_meaning_tbd.md.
                state = get_state(search_text, title=title, link=link,
                                   item_type=action_type)
                tags = generate_tags(title, full_text)

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
                    amt_info = extract_amount(search_text, title=title)
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
                    # extract the actual investigator agencies from the body
                    # (only HHS-OIG is tracked). If body doesn't literally
                    # credit HHS-OIG, leave related_agencies empty — don't
                    # default.
                    if actual_agency != 'HHS-OIG':
                        body_for_inv = item.get('_full_text') or desc_clean
                        related_agencies.extend(
                            extract_investigator_agencies(body_for_inv)
                        )

                # Merge in related_agencies from the scraper (e.g. DOJ-OPA
                # and DOJ-USAO set _related_agencies: ['HHS-OIG'] on items
                # that passed the HC Fraud topic gate, since OIG investigates
                # virtually all federal healthcare fraud cases).
                for ra in item.get('_related_agencies', []):
                    if ra not in related_agencies:
                        related_agencies.append(ra)

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
                link_label = derive_link_label(
                    actual_agency, link, feed_name=feed['name'], is_media=is_media
                )

                # Agency/domain consistency check — warn when an item's agency
                # doesn't match its link domain. This catches ingest mistakes
                # like agency=CMS with link=whitehouse.gov. When they mismatch,
                # the most common correct fix is: flip the primary agency to
                # the publisher (matching the domain) and move the original
                # agency to related_agencies.
                _AGENCY_DOMAINS = {
                    'DOJ':          'justice.gov',
                    'CMS':          'cms.gov',
                    'HHS':          'hhs.gov',
                    'HHS-OIG':      'oig.hhs.gov',
                    'GAO':          'gao.gov',
                    'Treasury':     ('fincen.gov', 'treasury.gov', 'home.treasury.gov'),
                    'White House':  'whitehouse.gov',
                    'Congress':     ('house.gov', 'senate.gov', 'congress.gov'),
                    # DEA/FDA removed from agency map 2026-04-21
                    'MedPAC':       'medpac.gov',
                    'MACPAC':       'macpac.gov',
                }
                def _link_matches_agency(agency, link):
                    if not agency or not link:
                        return True
                    domains = _AGENCY_DOMAINS.get(agency)
                    if domains is None:
                        return True  # unknown agency; don't warn
                    if isinstance(domains, str):
                        domains = (domains,)
                    return any(d in link.lower() for d in domains)
                if not _link_matches_agency(actual_agency, link) and feed.get('source_type') == 'official':
                    log(f"  WARNING: agency '{actual_agency}' does not match domain of link {link[:80]} — check classification", "yellow")

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
