"""Add state-level healthcare fraud enforcement actions."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
existing_links = {a.get('link', '') for a in d['actions']}

new_items = [
    {
        "id": "state-2025-12-18-ny-ag-americare-55m",
        "date": "2025-12-18",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "NY AG Secures $55M from Americare for Underpaying Home Health Aides While Billing Medicaid Full Rate",
        "description": "AG James secured $55M from Americare — $45M in unpaid wages to 10,000+ home health aides and $10M to NY Medicaid for False Claims Act violations. Americare systematically underpaid workers while billing Medicaid for full wage parity reimbursement (2014-2020). Largest wage parity settlement ever by NY AG.",
        "amount": "$55M",
        "amount_numeric": 55000000,
        "officials": ["AG Letitia James"],
        "link": "https://ag.ny.gov/press-release/2025/attorney-general-james-secures-45-million-underpaid-home-health-aides",
        "link_label": "NY AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Home Health Fraud", "False Claims Act", "Whistleblower"],
        "entities": ["Americare"], "state": "NY", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2025-06-30-ny-ag-medical-transport-takedown-13m",
        "date": "2025-06-30",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "NY AG Medical Transportation Fraud Takedown: $13M+ in Settlements, 16 Companies, 2 Criminal Convictions",
        "description": "AG James announced settlements with 16 companies totaling $13M+, lawsuits against 7 more, and criminal convictions of 2 individuals for Medicaid medical transportation fraud. Schemes included billing for fake trips, inflating mileage, adding fake tolls, and paying patient kickbacks.",
        "amount": "$13M+",
        "amount_numeric": 13000000,
        "officials": ["AG Letitia James"],
        "link": "https://ag.ny.gov/press-release/2025/attorney-general-james-secures-more-13-million-sweeping-takedown-transportation",
        "link_label": "NY AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "False Claims", "Kickbacks", "Organized Crime"],
        "entities": [], "state": "NY", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2025-03-tx-ag-molina-40m",
        "date": "2025-03-01",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "TX AG Secures $40M from Molina Healthcare for Concealing Failures in Medicaid STAR+PLUS Assessments",
        "description": "AG Paxton secured $40M from Molina Healthcare of Texas for failing to timely assess Medicaid STAR+PLUS beneficiaries (disabled, blind, aged 65+) for required services and concealing non-compliance from the state. Whistleblower qui tam case.",
        "amount": "$40M",
        "amount_numeric": 40000000,
        "officials": ["AG Ken Paxton"],
        "link": "https://www.texasattorneygeneral.gov/news/releases/attorney-general-ken-paxton-secures-40-million-texas-following-medicaid-fraud-investigation-molina-0",
        "link_label": "TX AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "False Claims", "Whistleblower"],
        "entities": ["Molina Healthcare"], "state": "TX", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2025-10-13-ca-ag-health-net-40m",
        "date": "2025-10-13",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "CA AG Secures $40M from Health Net for Misleading Mental Health Provider Directories",
        "description": "AG Bonta secured $40M from Health Net for misleading consumers with inaccurate mental health and medical provider directories. Psychiatrist listings had a 35%+ error rate. Includes $12M cash payment plus $28.5M in directory improvements over 6 years.",
        "amount": "$40M",
        "amount_numeric": 40000000,
        "officials": ["AG Rob Bonta"],
        "link": "https://oag.ca.gov/news/press-releases/attorney-general-bonta-secures-40-million-settlement-health-net-misleading",
        "link_label": "CA AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Medi-Cal", "Behavioral Health"],
        "entities": ["Health Net"], "state": "CA", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["CMS"]
    },
    {
        "id": "state-2025-01-30-ca-ag-qol-medical-47m",
        "date": "2025-01-30",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "CA AG Announces $47M Settlement Against QOL Medical for Kickback Scheme Using Free Test Kits",
        "description": "AG Bonta announced $47M settlement against QOL Medical and CEO Frederick Cooper for a kickback scheme using free C13 test kits to drive sales of drug Sucraid (2018-2022). Primarily federal recovery with CA receiving $384K.",
        "amount": "$47M",
        "amount_numeric": 47000000,
        "officials": ["AG Rob Bonta"],
        "link": "https://oag.ca.gov/news/press-releases/attorney-general-bonta-combats-medi-cal-fraud-announces-47-million-settlement",
        "link_label": "CA AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Medi-Cal", "Kickbacks", "Anti-Kickback", "False Claims Act"],
        "entities": ["QOL Medical"], "state": "CA", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "state-2025-01-14-mi-ag-acadia-healthcare-20m",
        "date": "2025-01-14",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "MI AG Leads Multistate $19.85M Settlement with Acadia Healthcare for Behavioral Health Fraud",
        "description": "MI AG Nessel led multistate settlement (FL, GA, MI, NV + federal) with Acadia Healthcare for false claims at inpatient behavioral health facilities. Acadia admitted patients not eligible for inpatient treatment, failed to discharge when appropriate, and knowingly understaffed facilities.",
        "amount": "$19.85M",
        "amount_numeric": 19850000,
        "officials": ["AG Dana Nessel"],
        "link": "https://www.michigan.gov/ag/news/press-releases/2025/01/14/ag-nessel-reaches-multistate-medicaid-fraud-settlement-with-behavioral-health-facility",
        "link_label": "MI AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Behavioral Health", "False Claims", "Multi-State"],
        "entities": ["Acadia Healthcare"], "state": "MI", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2025-01-02-ca-ag-rb-medical-10m",
        "date": "2025-01-02",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "CA AG Secures $10M from R&B Medical Group for Kickback Scheme and Illegal Lab Self-Referrals",
        "description": "AG Bonta secured $10M from owners of R&B Medical Group, Universal Diagnostic Laboratories, and Southern California Medical Center for kickback scheme and illegal self-referrals to their own labs (2014-2021).",
        "amount": "$10M",
        "amount_numeric": 10000000,
        "officials": ["AG Rob Bonta"],
        "link": "https://oag.ca.gov/news/press-releases/attorney-general-bonta-combats-medi-cal-fraud-securing-10-million-settlement",
        "link_label": "CA AG Press Release",
        "social_posts": [], "tags": ["Medi-Cal", "Kickbacks", "Lab Fraud", "Stark Law"],
        "entities": ["R&B Medical Group"], "state": "CA", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "state-2026-01-nc-ag-bethany-medical-8-8m",
        "date": "2026-01-15",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "NC AG Secures $8.8M from Bethany Medical Center for Unnecessary Opioid Drug Testing",
        "description": "AG Jackson secured $8.8M from Bethany Medical Center and founder Dr. Lenin Peters for billing Medicare, Medicaid, and TRICARE for medically unnecessary monthly urine drug tests on opioid patients regardless of individual need (2018-2023). Whistleblower case.",
        "amount": "$8.8M",
        "amount_numeric": 8828890,
        "officials": ["AG Jeff Jackson"],
        "link": "https://ncdoj.gov/attorney-general-jeff-jackson-announces-8-8-million-health-care-fraud-settlement/",
        "link_label": "NC AG Press Release",
        "social_posts": [], "tags": ["Medicare", "Medicaid", "TRICARE", "Opioids", "Lab Fraud", "Whistleblower"],
        "entities": ["Bethany Medical Center"], "state": "NC", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "state-2025-05-nc-ag-reign-inspirations-4-7m",
        "date": "2025-05-01",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "NC AG Obtains $4.7M Judgment for Phantom Medicaid Home Visits",
        "description": "AG Jackson obtained $4.7M consent judgment against Steven Osbey for fraud through Reign & Inspirations, which billed NC Medicaid for physician home visits that never occurred (2017-2020).",
        "amount": "$4.7M",
        "amount_numeric": 4711159,
        "officials": ["AG Jeff Jackson"],
        "link": "https://ncdoj.gov/attorney-general-jeff-jackson-reaches-4-7-million-medicaid-fraud-settlement/",
        "link_label": "NC AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "False Claims", "Home Health Fraud"],
        "entities": ["Reign & Inspirations"], "state": "NC", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2025-02-06-ny-ag-imran-shams-7m",
        "date": "2025-02-06",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "NY AG Secures 8-25 Year Prison Sentence for Serial Medicaid Fraudster Who Paid Patients Kickbacks",
        "description": "AG James secured 8-1/3 to 25 years for Imran Shams, a serial healthcare fraudster who ran Multi-Specialty clinic paying Medicaid recipients $20-$50 kickbacks for unnecessary/fraudulent medical tests. $7M restitution ordered. Shams was already serving a 13-year federal sentence.",
        "amount": "$7M",
        "amount_numeric": 7000000,
        "officials": ["AG Letitia James"],
        "link": "https://ag.ny.gov/press-release/2025/attorney-general-james-secures-prison-sentence-serial-health-care-fraudster",
        "link_label": "NY AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Kickbacks", "False Claims"],
        "entities": [], "state": "NY", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "state-2025-ca-ag-abrons-medi-cal-20m",
        "date": "2025-06-01",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "CA AG Secures 4-Year Sentence for $20M Medi-Cal Fraud Diverting HIV and Antipsychotic Drugs",
        "description": "AG Bonta secured sentencing of Oscar B. Abrons III to 4 years for running 'God's Property,' an unlicensed clinic paying Medi-Cal beneficiaries cash for medically unnecessary prescriptions for HIV meds and antipsychotics, which were diverted to the illicit market. $20M+ loss to Medi-Cal.",
        "amount": "$20M+",
        "amount_numeric": 20000000,
        "officials": ["AG Rob Bonta"],
        "link": "https://oag.ca.gov/news/press-releases/attorney-general-bonta-secures-sentencing-southern-california-healthcare",
        "link_label": "CA AG Press Release",
        "social_posts": [], "tags": ["Medi-Cal", "Drug Diversion", "Pharmaceutical", "Kickbacks"],
        "entities": [], "state": "CA", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "state-2025-ct-ag-assured-rx-39m",
        "date": "2025-01-15",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "CT AG Wins $39M Judgment Against Florida Pharmacy for Kickback Scheme Targeting State Employees",
        "description": "Hartford Superior Court found Florida-based Assured Rx liable for $39M under CT False Claims Act for a kickback scheme paying retired state employees for costly compound drug prescriptions covered by the state health plan, costing the state ~$10M.",
        "amount": "$39M",
        "amount_numeric": 39000000,
        "officials": ["AG William Tong"],
        "link": "https://portal.ct.gov/ag/press-releases/2024-press-releases/attorney-general-tong-announces-false-claims-act-judgment-against-assured-rx-pharmacy",
        "link_label": "CT AG Press Release",
        "social_posts": [], "tags": ["Pharmacy Fraud", "Kickbacks", "False Claims Act"],
        "entities": ["Assured Rx"], "state": "CT", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "state-2026-01-14-mn-ag-guardian-health-3-2m",
        "date": "2026-01-14",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "MN AG Charges Guardian Home Health Services Owner with $3.2M Medicaid Fraud",
        "description": "AG Ellison's MFCU charged Mohamed Abdirashid Omarxeyd with 8 felony counts for using Guardian Home Health Services to bilk MN Medicaid of $3.2M by billing for personal care, companion care, and homemaking services never provided (2020-2024).",
        "amount": "$3.2M",
        "amount_numeric": 3200000,
        "officials": ["AG Keith Ellison"],
        "link": "https://www.ag.state.mn.us/Office/Communications/2026/01/14_MedicaidFraud.asp",
        "link_label": "MN AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Home Health Fraud", "False Claims"],
        "entities": ["Guardian Home Health Services"], "state": "MN", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
    {
        "id": "state-2026-02-25-mn-map-act-legislation",
        "date": "2026-02-25",
        "agency": "State Agency",
        "type": "Legislation",
        "title": "MN AG Introduces Medical Assistance Protection (MAP) Act: 18 New MFCU Staff, Racketeering Authority",
        "description": "AG Ellison introduced bipartisan MAP Act to expand MFCU capacity: adds 18 new staff, broadens fraud definition, adds Medicaid fraud to the state racketeering statute, and expands subpoena powers for financial records. Passed House Judiciary Committee March 10, 2026.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["AG Keith Ellison"],
        "link": "https://www.ag.state.mn.us/Office/Communications/2026/02/25_MedicaidFraud.asp",
        "link_label": "MN AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Legislation", "Program Integrity"],
        "entities": [], "state": "MN", "source_type": "official", "auto_fetched": False
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

print(f"\nAdded {added}. Total: {len(d['actions'])}")
