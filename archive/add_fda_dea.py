"""Add FDA/DEA enforcement actions and fix existing item tags."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
by_id = {a['id']: a for a in d['actions']}
existing_links = {a.get('link', '') for a in d['actions']}

# ============================================================
# FIX EXISTING ITEMS - ensure correct tags
# ============================================================
fixes = {
    'doj-2025-06-operation-gold-rush': {
        'tags': ['Medicare', 'DME Fraud', 'Identity Theft', 'Organized Crime', 'National Takedown', 'Foreign Nationals']
    },
    'doj-2025-03-20-kentucky-opioid-clinics-conviction': {
        'tags': ['Medicare', 'Medicaid', 'Opioids', 'Addiction Treatment', 'False Claims']
    },
    'doj-2025-04-29-gilead-sciences-hiv-kickbacks': {
        'tags': ['Pharmaceutical', 'Kickbacks', 'Anti-Kickback', 'False Claims Act', 'Medicare', 'Medicaid', 'Whistleblower'],
        'entities': ['Gilead Sciences']
    },
    'doj-2026-03-11-aetna-fca-settlement': {
        'tags': ['Medicare Advantage', 'False Claims Act', 'Risk Adjustment', 'Whistleblower'],
        'entities': ['Aetna']
    },
    'doj-2026-01-dr-merchia-independent-health-fca-prior': {
        'tags': ['Medicare Advantage', 'False Claims Act', 'Risk Adjustment', 'Whistleblower'],
        'entities': ['Independent Health']
    },
    'doj-2025-01-24-pfizer-biohaven-kickbacks': {
        'tags': ['Pharmaceutical', 'Kickbacks', 'Anti-Kickback', 'False Claims Act', 'Medicare', 'Whistleblower'],
        'entities': ['Pfizer', 'Biohaven']
    },
    'doj-2025-02-06-medisca-awp-settlement': {
        'tags': ['Pharmaceutical', 'False Claims Act', 'TRICARE', 'Whistleblower', 'Overbilling'],
        'entities': ['Medisca']
    },
    'doj-2025-12-dana-farber-grant-fraud-settlement': {
        'tags': ['Research Fraud', 'Whistleblower'],
        'entities': ['Dana-Farber Cancer Institute']
    },
    'doj-2026-02-oasis-hospital-fca-settlement': {
        'tags': ['Kickbacks', 'Anti-Kickback', 'False Claims Act', 'Medicare'],
        'entities': ['OASIS Hospital', 'USPI']
    },
    'doj-2026-02-atlanta-gastro-settlement': {
        'tags': ['Kickbacks', 'Anti-Kickback', 'False Claims Act', 'Medicare', 'Lab Fraud'],
        'entities': ['Atlanta Gastroenterology Associates']
    },
    'doj-2025-05-01-medicare-advantage-insurers-complaint': {
        'tags': ['Medicare Advantage', 'Kickbacks', 'Anti-Kickback', 'False Claims Act', 'Whistleblower'],
        'entities': ['CVS Health', 'Aetna', 'Elevance Health', 'Humana', 'eHealth', 'GoHealth', 'SelectQuote']
    },
    'doj-2025-07-cms-dof-data-fusion-center': {
        'tags': ['Medicare', 'Medicaid', 'AI', 'Technology/Innovation', 'Program Integrity']
    },
}

for aid, updates in fixes.items():
    if aid in by_id:
        for key, val in updates.items():
            by_id[aid][key] = val
        print(f"  FIXED: {aid} -> {len(updates)} field(s)")

# ============================================================
# ADD NEW ITEMS
# ============================================================
new_items = [
    {
        "id": "fda-2025-11-20-done-global-adderall-conviction",
        "date": "2025-11-20",
        "agency": "FDA",
        "type": "Criminal Enforcement",
        "title": "Done Global CEO and Clinical President Convicted in $100M Adderall Distribution Scheme",
        "description": "A federal jury convicted Ruthia He (CEO) and David Brody (clinical president) of Done Global for illegally distributing Adderall over the internet and healthcare fraud conspiracy. Done Global arranged prescriptions for over 40 million stimulant pills, generating $100M+ in revenue. First federal drug distribution prosecution related to telehealth.",
        "amount": "$100M",
        "amount_numeric": 100000000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/founderceo-and-clinical-president-digital-health-company-convicted-100m-adderall",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Drug Diversion", "Pharmaceutical", "Telehealth", "False Claims"],
        "entities": ["Done Global"],
        "state": "CA",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-02-06-talbot-louisiana-opioid-sentencing",
        "date": "2025-02-06",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Louisiana Physician Sentenced to 87 Months for Illegally Distributing 1.8 Million Opioid Doses",
        "description": "Louisiana physician Dr. Adrian Talbot sentenced to 87 months in prison for illegally distributing over 1.8 million doses of Schedule II controlled substances and defrauding healthcare programs of $5.4 million. Talbot pre-signed opioid prescriptions for patients he never examined.",
        "amount": "$5.4M",
        "amount_numeric": 5400000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/louisiana-doctor-sentenced-illegally-distributing-over-18m-doses-opioids-54m-health-care",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Drug Diversion", "Medicare", "Medicaid", "False Claims"],
        "entities": [],
        "state": "LA",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "doj-2025-02-06-four-pharmacists-13m-sentencing",
        "date": "2025-02-06",
        "agency": "DOJ",
        "type": "Criminal Enforcement",
        "title": "Four Pharmacists Sentenced for $13M Medicare/Medicaid Prescription Fraud in Michigan and Ohio",
        "description": "Four pharmacists sentenced (2 to 10 years) for billing Medicare, Medicaid, and Blue Cross Blue Shield of Michigan over $13 million for prescription medications never dispensed at five pharmacies across Michigan and Ohio.",
        "amount": "$13M",
        "amount_numeric": 13000000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/four-pharmacists-sentenced-roles-13m-medicare-medicaid-and-private-insurer-fraud-conspiracy",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Medicare", "Medicaid", "Pharmacy Fraud", "False Claims", "Drug Diversion"],
        "entities": [],
        "state": "MI",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "doj-2025-01-mckinsey-650m-opioid-resolution",
        "date": "2025-01-01",
        "agency": "DOJ",
        "type": "Criminal Enforcement",
        "title": "McKinsey & Company Pays $650M to Resolve Criminal and Civil Opioid Fraud Charges",
        "description": "McKinsey entered a deferred prosecution agreement for conspiring with Purdue Pharma to aid in misbranding OxyContin. The $650M resolution includes $323M for FCA violations. First time a consulting firm was held criminally accountable for healthcare fraud.",
        "amount": "$650M",
        "amount_numeric": 650000000,
        "officials": [],
        "link": "https://www.justice.gov/archives/opa/pr/justice-department-announces-resolution-criminal-and-civil-investigations-mckinsey-companys",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Pharmaceutical", "False Claims Act", "Kickbacks"],
        "entities": ["McKinsey & Company", "Purdue Pharma"],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "fda-2025-08-29-kimberly-clark-40m-surgical-gowns",
        "date": "2025-08-29",
        "agency": "FDA",
        "type": "Criminal Enforcement",
        "title": "Kimberly-Clark Pays $40.4M for Selling Adulterated MicroCool Surgical Gowns",
        "description": "Kimberly-Clark agreed to pay up to $40.4 million via a deferred prosecution agreement for selling millions of adulterated surgical gowns. An employee conducted fraudulent testing to avoid submitting a new 510(k) premarket notification to FDA.",
        "amount": "$40.4M",
        "amount_numeric": 40400000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/kimberly-clark-corporation-pay-40m-resolve-criminal-charge-related-sale-adulterated",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Medical Devices", "False Claims"],
        "entities": ["Kimberly-Clark"],
        "state": "TX",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-07-03-operation-profit-over-patients",
        "date": "2025-07-03",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "DEA Operation Profit Over Patients: 51 Arrests, 15 Million Pills of Diverted Opioids",
        "description": "DEA executed Operation Profit Over Patients as part of the National Healthcare Fraud Takedown, resulting in 51 arrests and 122 criminal charges against 74 individuals (44 licensed medical professionals) for diverting over 15 million pills of prescription opioids.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.dea.gov/stories/2025/2025-07/2025-07-03/dea-executes-operation-profit-over-patients-dismantle-health-care",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Drug Diversion", "National Takedown"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "dea-2025-11-17-pensacola-drug-diversion",
        "date": "2025-11-17",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Four Pensacola Women Plead Guilty to Unlawful Diversion of Controlled Substances",
        "description": "Four Pensacola, Florida women pleaded guilty to unlawful diversion of controlled substances, including conspiracy to distribute oxycodone, hydrocodone, and amphetamine.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.dea.gov/press-releases/2025/11/17/pensacola-women-plead-guilty-illegal-drug-diversion",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Drug Diversion", "Opioids"],
        "entities": [],
        "state": "FL",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "fda-2025-03-12-ar-research-clinical-trial-fraud",
        "date": "2025-03-12",
        "agency": "FDA",
        "type": "Criminal Enforcement",
        "title": "Florida Research Facility Owners Plead Guilty in Asthma Clinical Trial Fraud",
        "description": "Angela Baquero and Ricardo Acuna, owners of A&R Research Group in Pembroke Pines, Florida, pleaded guilty to conspiracy to commit wire fraud for submitting fabricated data in asthma drug trials to drug sponsors and ultimately the FDA.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://cglawfirm.com/2025/03/12/florida-research-facility-owners-plead-in-clinical-trial-fraud-case/",
        "link_label": "News Report",
        "social_posts": [],
        "tags": ["Research Fraud", "Pharmaceutical"],
        "entities": ["A&R Research Group"],
        "state": "FL",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "fda-2025-12-washington-cpap-fraud",
        "date": "2025-12-01",
        "agency": "FDA",
        "type": "Criminal Enforcement",
        "title": "Washington Sleep Clinic Owner Pleads Guilty to Selling Adulterated CPAP Devices",
        "description": "A physician and owner of a Washington state sleep clinic pleaded guilty to adulterating and misbranding medical devices. He purchased at least 500 used and recalled Philips CPAP/BiPAP machines, directed staff to remove defective foam, and distributed them to patients.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.ropesgray.com/en/insights/alerts/2026/01/fda-enforcement-review-looking-back-at-2025-and-bracing-for-continued-unpredictability-in-2026",
        "link_label": "Ropes & Gray Analysis",
        "social_posts": [],
        "tags": ["Medical Devices", "False Claims"],
        "entities": [],
        "state": "WA",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "doj-2025-06-teva-450m-copaxone-kickback",
        "date": "2025-06-01",
        "agency": "DOJ",
        "type": "Civil Action",
        "title": "Teva Pharmaceuticals Pays $450M to Resolve Copaxone Kickback Allegations",
        "description": "Teva Pharmaceuticals agreed to pay $450 million to resolve FCA and Anti-Kickback allegations. For nearly a decade, Teva funneled hundreds of millions to co-pay assistance foundations structured to benefit only Copaxone while steadily raising the drug's price to increase Medicare reimbursements.",
        "amount": "$450M",
        "amount_numeric": 450000000,
        "officials": [],
        "link": "https://www.beneschlaw.com/resources/third-party-co-pay-assistance-program-kickback-scheme-results-in-dollar450-million-doj-settlement.html",
        "link_label": "Legal Analysis",
        "social_posts": [],
        "tags": ["Pharmaceutical", "Kickbacks", "Anti-Kickback", "False Claims Act", "Medicare"],
        "entities": ["Teva Pharmaceuticals"],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "doj-2025-07-08-cvs-omnicare-949m-judgment",
        "date": "2025-07-08",
        "agency": "DOJ",
        "type": "Civil Action",
        "title": "CVS Omnicare Ordered to Pay $949M for Dispensing Drugs Without Valid Prescriptions",
        "description": "A federal judge ordered CVS Omnicare to pay $948.8 million for dispensing drugs to elderly and disabled people in long-term care facilities without valid prescriptions. Omnicare filed over 3.3 million false claims between 2010 and 2018.",
        "amount": "$949M",
        "amount_numeric": 948800000,
        "officials": [],
        "link": "https://www.healthcaredive.com/news/cvs-omnicare-949-million-government-fraud-penalty/752544/",
        "link_label": "Healthcare Dive",
        "social_posts": [],
        "tags": ["Medicare", "Medicaid", "Pharmacy Fraud", "False Claims Act", "Whistleblower", "Nursing Home"],
        "entities": ["CVS", "Omnicare"],
        "state": "NY",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "doj-2025-08-19-cvs-caremark-290m-medicare-partd",
        "date": "2025-08-19",
        "agency": "DOJ",
        "type": "Civil Action",
        "title": "CVS Caremark Ordered to Pay $290M for Defrauding Medicare Part D Program",
        "description": "A federal court ordered CVS Caremark to pay nearly $290 million for deliberately manipulating prescription drug cost data to overcharge Medicare Part D. Originated from whistleblower Sarah Behnke, former Aetna actuary.",
        "amount": "$290M",
        "amount_numeric": 289900000,
        "officials": [],
        "link": "https://www.complianceweek.com/regulatory-enforcement/judge-orders-cvs-to-pay-nearly-290m-for-medicare-false-claims/36172.article",
        "link_label": "Compliance Week",
        "social_posts": [],
        "tags": ["Medicare", "Pharmacy Fraud", "False Claims Act", "Whistleblower"],
        "entities": ["CVS Caremark"],
        "state": "PA",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "doj-2025-06-30-wound-care-1b-fraud-indictment",
        "date": "2025-06-30",
        "agency": "DOJ",
        "type": "Criminal Enforcement",
        "title": "Seven Charged in $1.1 Billion Wound Care Fraud Scheme Targeting Elderly Medicare Patients",
        "description": "Seven defendants (five medical professionals) charged in $1.1 billion in fraudulent Medicare claims for amniotic wound allografts. Defendants targeted vulnerable elderly patients in hospice care, applying medically unnecessary wound grafts and receiving millions in illegal kickbacks.",
        "amount": "$1.1B",
        "amount_numeric": 1100000000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/national-health-care-fraud-takedown-results-324-defendants-charged-connection-over-146",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Medicare", "Wound Care", "Kickbacks", "False Claims", "Medical Devices", "National Takedown"],
        "entities": [],
        "state": "AZ",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "doj-2025-11-health-safety-unit",
        "date": "2025-11-01",
        "agency": "DOJ",
        "type": "Structural/Organizational",
        "title": "DOJ Forms Health and Safety Unit for FDA-Related Criminal Enforcement",
        "description": "DOJ formed the Health and Safety Unit after absorbing the CFPB criminal portfolio. Working closely with FDA, the HSU brought four corporate enforcement actions in its first months, including cases involving adulterated surgical gowns and forged FDA approvals.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.ropesgray.com/en/insights/alerts/2026/01/fda-enforcement-review-looking-back-at-2025-and-bracing-for-continued-unpredictability-in-2026",
        "link_label": "Ropes & Gray Analysis",
        "social_posts": [],
        "tags": ["Medical Devices", "Pharmaceutical", "Task Force"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["FDA"]
    },
    {
        "id": "fda-2025-09-dtc-advertising-crackdown",
        "date": "2025-09-09",
        "agency": "FDA",
        "type": "Administrative Action",
        "title": "FDA Issues 200+ Enforcement Letters in DTC Prescription Drug Advertising Crackdown",
        "description": "Following a White House memorandum, FDA dramatically increased enforcement of direct-to-consumer prescription drug advertising, issuing over 200 enforcement letters in 2025 including 74 to pharma/biologic manufacturers. Only 5 letters were issued before the September 9 directive.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.cov.com/en/news-and-insights/insights/2026/03/fda-advertising-and-promotion-enforcement-activities-2025-year-in-review",
        "link_label": "Covington Analysis",
        "social_posts": [],
        "tags": ["Pharmaceutical", "Off-Label"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
]

added = 0
for item in new_items:
    if item['link'] not in existing_links:
        d['actions'].append(item)
        existing_links.add(item['link'])
        added += 1
        print(f"  ADD: {item['title'][:70]}")
    else:
        print(f"  SKIP: {item['title'][:70]}")

with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=4, ensure_ascii=False)

print(f"\nAdded {added} new items. Total: {len(d['actions'])}")
