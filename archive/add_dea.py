"""Add DEA enforcement actions from research."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
existing_links = {a.get('link', '') for a in d['actions']}

new_items = [
    {
        "id": "dea-2025-04-22-walgreens-350m-opioid-settlement",
        "date": "2025-04-22",
        "agency": "DEA",
        "type": "Civil Action",
        "title": "Walgreens Agrees to Pay Up to $350M for Illegally Filling Opioid Prescriptions",
        "description": "DOJ, DEA, and HHS-OIG announced a settlement with Walgreens for knowingly filling millions of invalid controlled substance prescriptions between 2012 and 2023, including excessive opioid prescriptions and early refills, then seeking Medicare reimbursement via false claims. Walgreens must enter a 7-year compliance agreement with DEA.",
        "amount": "$350M",
        "amount_numeric": 350000000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/walgreens-agrees-pay-350m-illegally-filling-unlawful-opioid-prescriptions-and-submitting",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Pharmacy Fraud", "Opioids", "Medicare", "False Claims", "Drug Diversion"],
        "entities": ["Walgreens"],
        "state": None,
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-01-07-smithers-467-counts-opioid",
        "date": "2025-01-07",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Martinsville Doctor Convicted on 467 Federal Counts of Opioid Distribution",
        "description": "Dr. Joel Smithers of Martinsville, VA convicted of 466 counts of illegally prescribing Schedule II controlled substances and maintaining drug-involved premises. Smithers prescribed controlled substances to every patient, distributing over 500,000 Schedule II pills. Sentenced to 40 years.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.justice.gov/usao-wdva/pr/martinsville-doctor-convicted-467-federal-counts-drug-distribution",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Pill Mill", "Drug Diversion"],
        "entities": [],
        "state": "VA",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-02-08-syed-new-haven-psychiatrist",
        "date": "2025-02-08",
        "agency": "DEA",
        "type": "Civil Action",
        "title": "New Haven Psychiatrist Pays $455K, Excluded 20 Years for Unnecessary Opioid Prescriptions",
        "description": "Dr. Naimetulla Ahmed Syed of New Haven, CT agreed to pay $455,439 to resolve allegations he issued medically unnecessary controlled substance prescriptions including the 'holy trinity' combination of opioids, benzodiazepines, and muscle relaxants, and billed Medicare and Medicaid for unnecessary visits. Agreed to 20-year exclusion from federal healthcare programs.",
        "amount": "$455K",
        "amount_numeric": 455439,
        "officials": [],
        "link": "https://www.dea.gov/press-releases/2025/02/08/new-haven-psychiatrist-pay-more-450k-settle-false-claims-act-and",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Drug Diversion", "Medicare", "Medicaid", "False Claims"],
        "entities": [],
        "state": "CT",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-03-14-randall-nc-udt-fraud",
        "date": "2025-03-14",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "North Carolina Doctor Sentenced for $2M Opioid and Unnecessary Drug Testing Fraud",
        "description": "Dr. Wendell Lewis Randall, owner of the National Institute of Toxicology in Mt. Airy, NC, sentenced to 30 months for prescribing opioids without medical necessity and requiring all patients to submit to unnecessary urine drug tests, billing Medicare for $753K and Medicaid for $1.3M in fraudulent claims.",
        "amount": "$2.05M",
        "amount_numeric": 2049747,
        "officials": [],
        "link": "https://www.dea.gov/press-releases/2025/03/14/doctor-sentenced-for-health-care-fraud-and-money-laundering",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Medicare", "Medicaid", "Lab Fraud", "Drug Diversion", "Money Laundering"],
        "entities": [],
        "state": "NC",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-06-26-okafor-dc-pill-mill-18yr",
        "date": "2025-06-26",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "D.C. Physician Sentenced to 18 Years for Operating Nationwide Opioid Pill Mill",
        "description": "Dr. Ndubuski Joseph Okafor sentenced to 18 years for operating a pill mill from his D.C. clinic, prescribing opioids to individuals using false identities across at least 45 states, resulting in hundreds of thousands of opioid units prescribed.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.dea.gov/press-releases/2025/06/26/physician-sentenced-18-years-prison-for-operating-pill-mill-his-northwest",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Pill Mill", "Drug Diversion", "Multi-State"],
        "entities": [],
        "state": "DC",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-09-26-health-fit-pharmacy-houston-pill-mill",
        "date": "2025-09-26",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Houston Pill Mill Pharmacy Owner Sentenced to 12 Years; 500,000+ Opioid Pills Dispensed",
        "description": "Arthur Billings, owner of Health Fit Pharmacy (a cash-only pill mill in Houston), sentenced to 12 years and ordered to forfeit $2.6 million. Three pharmacists also sentenced. The pharmacy dispensed over 500,000 opioid pills to individuals sent by drug traffickers, using prescriptions written in names of physicians whose identities were stolen.",
        "amount": "$2.6M",
        "amount_numeric": 2600000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/pharmacy-owner-and-pharmacists-sentenced-pill-mill-scheme-involving-hundreds-thousands",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Pharmacy Fraud", "Opioids", "Pill Mill", "Drug Diversion", "Identity Theft"],
        "entities": ["Health Fit Pharmacy"],
        "state": "TX",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2026-01-13-atlantic-biologicals-opioid-dpa",
        "date": "2026-01-13",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Miami Pharmaceutical Wholesaler Admits Selling 14 Million Opioid Doses to Pill Mill Pharmacies",
        "description": "Atlantic Biologicals Corporation entered a deferred prosecution agreement admitting its unit National Apothecary Solutions sold over 14 million opioid doses to Houston-area pill mill pharmacies from 2017 to 2023, knowing they would be dispensed outside legitimate medical practice. Paid $450,000 criminal penalty.",
        "amount": "$450K",
        "amount_numeric": 450000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/atlantic-biologicals-corporation-enters-deferred-prosecution-agreement-opioid-distribution",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Pill Mill", "Drug Diversion", "Pharmaceutical"],
        "entities": ["Atlantic Biologicals Corporation"],
        "state": "FL",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2025-01-14-stockton-np-opioid-lawsuit",
        "date": "2025-01-14",
        "agency": "DEA",
        "type": "Civil Action",
        "title": "DOJ Sues Stockton Nurse Practitioner for Selling Opioid Prescriptions via Telegram",
        "description": "DOJ filed a civil complaint against nurse practitioner Joan Rubinger of Stockton, CA for a nationwide scheme to sell illegal opioid prescriptions for cash via Telegram. Rubinger issued over 900 illegitimate prescriptions without examinations, providing customers price lists to select their own drugs.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.dea.gov/press-releases/2025/01/14/justice-department-sues-stockton-based-nurse-practitioner-stop-her-sale",
        "link_label": "DEA Press Release",
        "social_posts": [],
        "tags": ["Opioids", "Drug Diversion"],
        "entities": [],
        "state": "CA",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "dea-2026-03-09-great-neck-pill-mill-7yr",
        "date": "2026-03-09",
        "agency": "DEA",
        "type": "Criminal Enforcement",
        "title": "Great Neck, NY Doctor Sentenced to 7 Years for Operating Oxycodone Pill Mill",
        "description": "Dr. Roya Jafari-Hassad of Great Neck, NY sentenced to 7 years for operating an oxycodone pill mill from her family practice, making hundreds of thousands of dollars selling prescriptions under the table from 2019 to 2022. Ordered to pay $150,000 fine and $152,765 in restitution.",
        "amount": "$303K",
        "amount_numeric": 302765,
        "officials": [],
        "link": "https://oig.hhs.gov/fraud/enforcement/long-island-medical-doctor-sentenced-to-7-years-in-prison-for-operating-oxycodone-pill-mill-out-of-her-great-neck-office/",
        "link_label": "HHS-OIG",
        "social_posts": [],
        "tags": ["Opioids", "Pill Mill", "Drug Diversion"],
        "entities": [],
        "state": "NY",
        "source_type": "official",
        "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
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

print(f"\nAdded {added} DEA items. Total: {len(d['actions'])}")
