import json, re

with open('data/actions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

actions = data['actions']
print(f"Loaded {len(actions)} entries")

# === 1. REMOVE DUPLICATE MEDIA ENTRIES ===
remove_ids = {
    'media-2026-03-11-867051112',
    'media-2026-03-09-1806600621',
    'media-2025-03-26-seoul-medical-62m-ma-upcoding',
    'media-2025-04-21-walgreens-300m-opioid-settlement',
    'media-2025-04-29-gilead-202m-hiv-kickbacks',
    'media-2025-05-07-fresno-31m-kickback-settlement',
    'media-2025-05-ca-hospice-armenian-crime-ring',
    'media-2025-01-09-wavy-chesapeake-hospital-indictment',
    'media-2025-10-07-cbs-arizona-wound-graft-sentencing',
    'media-2025-11-10-hospice-news-ca-tx-fraud-sentencings',
    'media-2025-11-15-fierce-cms-improper-payments',
    'media-2026-02-03-washington-monthly-cms-ma-crackdown',
    'media-2026-01-27-washington-monthly-uhg-upcoding',
    'media-2026-01-02-cnn-minnesota-fraud-key-figures',
}
before = len(actions)
actions = [a for a in actions if a['id'] not in remove_ids]
print(f"Removed {before - len(actions)} duplicate media entries ({before} -> {len(actions)})")

# === 2. FIX DOUBLE-COUNTING (zero amount_numeric) ===
zero_ids = {
    'doj-2025-06-gary-cox-dmerx-conviction',       # sub-case of $14.6B takedown
    'doj-2025-06-farrukh-ali-arizona-substance-abuse', # sub-case of takedown
    'doj-2025-05-06-fichidzhyan-sentenced-hospice', # part of CA hospice gang case
    'hhs-oig-2025-12-oig-spring-semiannual-report', # overlaps with CMS FY2025 total
    'hhs-oig-2026-01-fall-semiannual-report',       # overlaps with CMS FY2025 total
    'cms-2026-01-minnesota-audit-announcement',     # superseded by specific $259.5M deferral
}
for a in actions:
    if a['id'] in zero_ids and (a.get('amount_numeric') or 0) > 0:
        print(f"  Zeroed: {a['id']} ({a['amount_numeric']} -> 0)")
        a['amount_numeric'] = 0
        a['amount'] = None

# === 3. FIX MISSING DOLLAR SIGNS IN AMOUNTS ===
amount_fixes = {
    'hhs-oig-2026-03-12-az-cardiology-vein': '$4.75 million',
    'hhs-oig-2026-03-10-montgomery-home-care': '$1.7 million',
    'hhs-oig-2026-03-09-chiropractor-14-9m': '$14.9 million',
    'hhs-oig-2026-03-09-psychiatrist-360k': '$360,000',
    'hhs-oig-2026-03-09-dme-owner-59m': '$59 million',
    'hhs-oig-2026-03-06-amerisourcebergen-1m': '$1 million',
    'hhs-oig-2026-03-06-kansas-doctor-8m': '$8 million',
    'hhs-oig-2026-03-06-mexican-man-6-85m': '$6.85 million',
    'hhs-oig-2026-03-06-rhode-island-plea': '$220,000+',
    'media-2026-01-08-doj-oklahoma-dme-30m-indictment': '$30 million (claims); $17 million (paid)',
    'media-2026-01-28-hospice-news-ca-280-licenses-revoked': '$1.6 billion (recovered from Medi-Cal); $2.5 billion (estimated LA fraud)',
    'media-2026-02-10-doj-mn-fraud-tourists-ai': '$3.5 million',
    'media-2026-02-12-doj-chicago-10m-foreign-nationals': '$10 million',
    'media-2026-03-05-doj-russian-400m-medicare-laundering': '$400 million (fraudulent claims); $12.2 million (laundered)',
    'media-2026-03-11-fednet-cms-crush-ai-war-room': '$2 billion (saved by AI war room since March 2025)',
    'media-2026-03-12-fox-la-doctor-600m-npi-fraud': '$600 million (fraudulent billing)',
}
for a in actions:
    if a['id'] in amount_fixes:
        a['amount'] = amount_fixes[a['id']]
        print(f"  Fixed amount: {a['id']} -> {a['amount']}")

# === 4. FIX MISSING DOLLAR SIGNS IN DESCRIPTIONS ===
desc_fixes = [
    ('to pay .75 million to settle', 'to pay $4.75 million to settle'),
    ('operating a .7 million Medicaid', 'operating a $1.7 million Medicaid'),
    ('a .9 million healthcare fraud', 'a $14.9 million healthcare fraud'),
    ('pay ,000 to settle civil', 'pay $360,000 to settle civil'),
    ('a  million Medicare fraud scheme involving fraudulent DME', 'a $59 million Medicare fraud scheme involving fraudulent DME'),
    ('pay  million to resolve allegations of paying unlawful', 'pay $1 million to resolve allegations of paying unlawful'),
    ('an  million Medicare fraud scheme', 'an $8 million Medicare fraud scheme'),
    ('a .85 million healthcare fraud operation', 'a $6.85 million healthcare fraud operation'),
    ('exceeding ,000 for theft', 'exceeding $220,000 for theft'),
    ('approximately  in false claims', 'approximately $30 million in false claims'),
    ('paid approximately .', 'paid approximately $17 million.'),
    ('misused + in COVID', 'misused $300K+ in COVID'),
    ('more than .6 billion in federal funds', 'more than $1.6 billion in federal funds'),
    ('program of .5M', 'program of $3.5M'),
    ('submit  in fraudulent billing', 'submit $10 million in fraudulent billing'),
    ('submitted + in false Medicare', 'submitted $400M+ in false Medicare'),
    ('reimbursed .7M', 'reimbursed $16.7M'),
    ('of which .2M was wired', 'of which $12.2M was wired'),
    ('has saved  billion since', 'has saved $2 billion since'),
    ('bill nearly  to Medicare', 'bill nearly $600 million to Medicare'),
    ('including  in 2024', 'including $260 million in 2024'),
]
desc_count = 0
for a in actions:
    for old, new in desc_fixes:
        if old in (a.get('description') or ''):
            a['description'] = a['description'].replace(old, new)
            desc_count += 1
print(f"Fixed {desc_count} description dollar signs")

# === 5. FIX MISSING DOLLAR SIGNS IN TITLES ===
title_fixes = {
    'hhs-oig-2026-03-12-az-cardiology-vein': 'Arizona Cardiology Group to Pay $4.75M to Resolve Allegations of Unnecessary Vein Ablations',
    'hhs-oig-2026-03-10-montgomery-home-care': 'CEO of Montgomery County Home Care Agency Sentenced to Incarceration for $1.7 Million Medicaid Fraud Scheme',
    'hhs-oig-2026-03-09-chiropractor-14-9m': 'Chiropractor Sentenced to 43 Months in Prison for $14.9 Million Health Care Fraud and Kickback Scheme',
    'hhs-oig-2026-03-09-psychiatrist-360k': 'Psychiatrist Reaches $360,000 Civil Settlement to Resolve Allegations of False Claims',
    'hhs-oig-2026-03-09-dme-owner-59m': 'Owner of Durable Medical Equipment Company Sentenced for $59 Million Medicare Fraud',
    'hhs-oig-2026-03-06-amerisourcebergen-1m': 'AmerisourceBergen Subsidiary Agrees to Pay $1 Million for Allegedly Paying Kickbacks',
    'hhs-oig-2026-03-06-kansas-doctor-8m': 'Kansas Doctor Sentenced to 3 Years in Prison for $8 Million Medicare Fraud',
    'hhs-oig-2026-03-06-mexican-man-6-85m': 'Man Sentenced to 14 Years in Federal Prison for Leading a $6.85 Million Health Care Fraud Scheme',
    'media-2026-01-08-doj-oklahoma-dme-30m-indictment': 'DOJ: Oklahoma Medical Supply Company Owner Indicted for $30M Health Care Fraud Scheme',
    'media-2026-02-10-doj-mn-fraud-tourists-ai': "DOJ: 'Fraud Tourists' Plead Guilty to $4.5M Minneapolis Medicaid Fraud Using AI-Fabricated Records",
    'media-2026-02-12-doj-chicago-10m-foreign-nationals': 'DOJ: Two Foreign Nationals Indicted in Chicago as Part of $10M Health Care Fraud Scheme',
    'media-2026-03-05-doj-russian-400m-medicare-laundering': 'DOJ: Russian Citizen Charged with Laundering $12.2M Connected to $400M in Fraudulent Medicare Claims',
    'media-2026-03-12-fox-la-doctor-600m-npi-fraud': "Fox News: 87-Year-Old LA Doctor's Medicare Number Linked to $600M in Fraudulent Billing",
}
for a in actions:
    if a['id'] in title_fixes:
        a['title'] = title_fixes[a['id']]

data['actions'] = actions

# === 6. WRITE JSON ===
with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\nDone. {len(actions)} entries saved.")

# === 7. VERIFY ===
with open('data/actions.json', 'r', encoding='utf-8') as f:
    raw = f.read()

problems = []
# Check for missing $ in amounts
for a in data['actions']:
    amt = a.get('amount') or ''
    if re.match(r'^\.\d|^,\d|^ [a-z]', amt):
        problems.append(f"Bad amount: {a['id']}: {amt}")
# Check for mojibake
if 'â€' in raw or 'Ã©' in raw or 'Ã¢' in raw:
    problems.append("Mojibake found in file!")

if problems:
    print("PROBLEMS:")
    for p in problems:
        print(f"  {p}")
else:
    print("All checks passed!")
