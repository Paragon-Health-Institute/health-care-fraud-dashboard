"""Add items to fill blank states on the map."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
existing_links = {a.get('link', '') for a in d['actions']}

new_items = [
    {
        "id": "state-2025-01-mt-55m-insurance-scheme-native-americans",
        "date": "2025-01-15",
        "agency": "State Agency",
        "type": "Investigation",
        "title": "Montana Auditor Investigates $55M Insurance Scheme Targeting Native Americans",
        "description": "Montana State Auditor James Brown announced an investigation into out-of-state substance use treatment facilities that carried out a deceptive scheme targeting Native people in Montana, resulting in up to $55 million in fraudulent health insurance claims. PacificSource flagged the suspected fraud.",
        "amount": "$55M",
        "amount_numeric": 55000000,
        "officials": ["State Auditor James Brown"],
        "link": "https://www.bozemandailychronicle.com/news/montana-auditor-out-of-state-providers-targeted-native-people-in-55m-insurance-scheme/article_4a9c5e42-fd38-565c-b01c-02fd7f92c0bb.html",
        "link_label": "Bozeman Daily Chronicle",
        "social_posts": [], "tags": ["Addiction Treatment", "Native American", "False Claims", "Organized Crime"],
        "entities": ["PacificSource"], "state": "MT", "source_type": "news", "auto_fetched": False,
        "related_agencies": ["HHS"]
    },
    {
        "id": "state-2025-wv-32m-medicaid-overpayments-ineligible",
        "date": "2025-10-23",
        "agency": "State Agency",
        "type": "Audit",
        "title": "West Virginia Audit Reveals $32.4M in Medicaid Payments for Incarcerated and Deceased Individuals",
        "description": "A 2025 audit revealed West Virginia may have paid Medicaid participant fees for thousands of ineligible individuals who were incarcerated or dead. The state is working to recover up to $32.4 million in improper payments.",
        "amount": "$32.4M",
        "amount_numeric": 32400000,
        "officials": [],
        "link": "https://westvirginiawatch.com/2025/10/23/the-real-fraud-isnt-in-medicaid-its-in-the-profits-of-corporate-insurers/",
        "link_label": "West Virginia Watch",
        "social_posts": [], "tags": ["Medicaid", "Improper Payments", "Program Integrity"],
        "entities": [], "state": "WV", "source_type": "news", "auto_fetched": False,
        "related_agencies": ["CMS"]
    },
    {
        "id": "oig-2025-ms-mfcu-unreported-overpayments-4-5m",
        "date": "2025-06-01",
        "agency": "HHS-OIG",
        "type": "Audit",
        "title": "HHS-OIG Audit: Mississippi Failed to Report $4.5M in MFCU Medicaid Overpayments",
        "description": "Federal audit found Mississippi failed to report and return MFCU-determined Medicaid overpayments totaling $4.5 million ($3.7M federal share) across 20 cases in FY 2021-2023. OIG recommended Mississippi return $3.5M in federal share.",
        "amount": "$4.5M",
        "amount_numeric": 4500000,
        "officials": [],
        "link": "https://oig.hhs.gov/reports/all/2025/mississippi-did-not-report-and-return-all-medicaid-overpayments-for-the-states-medicaid-fraud-control-unit-cases/",
        "link_label": "HHS-OIG Report",
        "social_posts": [], "tags": ["Medicaid", "Improper Payments", "Program Integrity"],
        "entities": [], "state": "MS", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "doj-2025-ms-mitias-orthopaedics-1-87m",
        "date": "2025-06-01",
        "agency": "DOJ",
        "type": "Civil Action",
        "title": "Mississippi Orthopedic Clinic Pays $1.87M for Billing Compound Drugs as Brand-Name Products",
        "description": "Mitias Orthopaedics and its owner agreed to pay $1.87 million to settle allegations of injecting Medicare/Medicaid beneficiaries with drugs purchased from compound pharmacies while billing as FDA-approved, brand-name products.",
        "amount": "$1.87M",
        "amount_numeric": 1870714,
        "officials": [],
        "link": "https://www.fcacounsel.com/blog/false-claims-act-case-against-mississippi-orthopedic-clinic-results-in-1-87-million-settlement/",
        "link_label": "FCA Counsel",
        "social_posts": [], "tags": ["Medicare", "Medicaid", "Pharmaceutical", "False Claims Act"],
        "entities": ["Mitias Orthopaedics"], "state": "MS", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "doj-2025-id-amerihealth-clinics-2m",
        "date": "2025-06-01",
        "agency": "DOJ",
        "type": "Civil Action",
        "title": "Idaho AmeriHealth Clinics Consents to $2M Judgment for Using Vulnerable Staff to Submit False Claims",
        "description": "AmeriHealth Clinics consented to a $2 million judgment for False Claims Act violations involving a scheme using vulnerable and inexperienced medical staff to submit false claims to Medicare, Medicaid, and TRICARE.",
        "amount": "$2M",
        "amount_numeric": 2000000,
        "officials": [],
        "link": "https://www.justice.gov/usao-id/pr/amerihealth-clinics-consent-2-million-judgment-resolve-healthcare-fraud-allegations",
        "link_label": "DOJ Press Release",
        "social_posts": [], "tags": ["Medicare", "Medicaid", "TRICARE", "False Claims Act"],
        "entities": ["AmeriHealth Clinics"], "state": "ID", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "state-2025-05-ut-holdaway-medicaid-fraud-12-9m",
        "date": "2025-05-01",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "Utah Woman Sentenced to 15 Years for $12.9M in False Medicaid Claims Through Treatment Centers",
        "description": "Deaun Larson Holdaway sentenced to up to 15 years for submitting over 7,700 false Medicaid claims through MATR treatment locations, totaling $12.9 million in Medicaid payments. Ordered to pay $2.6 million in restitution.",
        "amount": "$12.9M",
        "amount_numeric": 12900000,
        "officials": [],
        "link": "https://www.abc4.com/news/crime/medicaid-fraud-case-utah-woman/",
        "link_label": "ABC4 News",
        "social_posts": [], "tags": ["Medicaid", "Addiction Treatment", "False Claims"],
        "entities": ["MATR"], "state": "UT", "source_type": "news", "auto_fetched": False,
        "related_agencies": ["DOJ"]
    },
    {
        "id": "doj-2025-07-nd-bismarck-1-8m-fraud",
        "date": "2025-07-01",
        "agency": "DOJ",
        "type": "Criminal Enforcement",
        "title": "Bismarck Man Charged with $1.8M Government Fraud Including False Medicaid Claims",
        "description": "A Bismarck, North Dakota man was charged with taking $1.8 million through government fraud, including fraudulent Medicaid claims submitted between January 2022 and September 2024. Case brought as part of the 2025 National Healthcare Fraud Takedown.",
        "amount": "$1.8M",
        "amount_numeric": 1800000,
        "officials": [],
        "link": "https://northdakotamonitor.com/2025/07/01/bismarck-man-accused-of-taking-1-8-million-in-government-fraud-case/",
        "link_label": "North Dakota Monitor",
        "social_posts": [], "tags": ["Medicaid", "False Claims", "National Takedown"],
        "entities": [], "state": "ND", "source_type": "news", "auto_fetched": False
    },
    {
        "id": "state-2025-nm-ag-kiss-1-6m-children-medicaid-fraud",
        "date": "2025-06-01",
        "agency": "State Agency",
        "type": "Civil Action",
        "title": "NM AG Files Lawsuit Alleging $1.6M in Fraudulent Children's Medicaid Claims and Identity Theft",
        "description": "NM AG Raul Torrez filed a lawsuit (91 counts of fraud and identity theft) against operators of Kids in Need of Support Services (KISS) for $1.63 million in fraudulent Medicaid claims for services never rendered while illegally using children's Social Security numbers.",
        "amount": "$1.63M",
        "amount_numeric": 1626496,
        "officials": ["AG Raul Torrez"],
        "link": "https://nmdoj.gov/press-release/attorney-general-raul-torrez-files-lawsuit-alleging-over-1-6-million-in-fraudulent-medicaid-claims-and-identity-theft-of-children/",
        "link_label": "NM AG Press Release",
        "social_posts": [], "tags": ["Medicaid", "Identity Theft", "False Claims"],
        "entities": ["KISS"], "state": "NM", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "state-2025-nm-marshall-equine-970k-medicaid",
        "date": "2025-06-01",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "NM Therapist Indicted on 18 Felony Counts for Nearly $1M in Fraudulent Medicaid Claims",
        "description": "Nancy Marshall, therapist and owner of Equine Assisted Programs of Southern New Mexico, indicted on 18 felony counts for submitting false Medicaid claims in excess of $970,000 for equine-assisted therapy services.",
        "amount": "$970K",
        "amount_numeric": 970000,
        "officials": [],
        "link": "https://oig.hhs.gov/fraud/enforcement/the-new-mexico-department-of-justice-charges-nancy-marshall-with-18-felony-counts-related-to-fraudulent-medicaid-claims-totaling-nearly-1-million/",
        "link_label": "HHS-OIG",
        "social_posts": [], "tags": ["Medicaid", "Behavioral Health", "False Claims"],
        "entities": ["Equine Assisted Programs"], "state": "NM", "source_type": "official", "auto_fetched": False,
        "related_agencies": ["HHS-OIG"]
    },
]

added = 0
for item in new_items:
    if item['link'] not in existing_links:
        d['actions'].append(item)
        existing_links.add(item['link'])
        added += 1
        print(f"  ADD [{item.get('state','??')}]: {item['title'][:65]}")
    else:
        print(f"  SKIP: {item['title'][:65]}")

with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=4, ensure_ascii=False)

print(f"\nAdded {added}. Total: {len(d['actions'])}")
