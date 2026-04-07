"""One-time script to backfill missing media coverage from curated outlets."""
import json
from datetime import datetime

with open("data/actions.json", "r", encoding="utf-8-sig") as f:
    data = json.load(f)

existing_links = set(a.get("link", "") for a in data["actions"])

new_entries = [
    # STAT News
    {
        "id": "media-2026-03-18-stat-disability",
        "date": "2026-03-18",
        "agency": "Media",
        "type": "Investigative Report",
        "title": "STAT News: Trump Fraud Crackdown Threatens Disability Services, Advocates Warn",
        "description": "STAT News reports that the Trump administration's aggressive healthcare fraud crackdown, led by CMS Administrator Mehmet Oz, is disproportionately threatening essential services for disabled Americans. The broad targeting of state Medicaid funding and DMEPOS moratorium risks endangering millions who depend on home care, wheelchairs, and accessibility services. Disability advocates argue the crackdown uses fraud as an excuse to cut critical programs, particularly after Congress's $1 trillion Medicaid reduction.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["Mehmet Oz"],
        "link": "https://www.statnews.com/2026/03/18/trump-health-fraud-crackdown-disability-concerns/",
        "link_label": "STAT News Report",
        "social_posts": [],
        "tags": ["Medicaid", "Disability Services", "DME", "HCBS", "Policy Impact"],
        "entities": ["CMS"],
        "state": None,
        "source_type": "news",
        "auto_fetched": False,
    },
    {
        "id": "media-2026-02-05-stat-blue-states",
        "date": "2026-02-05",
        "agency": "Media",
        "type": "Investigative Report",
        "title": "STAT News: HHS Anti-Fraud Crackdown Sweeps Up Mainly Democratic-Led States",
        "description": "STAT News investigation reveals that CMS Administrator Mehmet Oz's aggressive anti-fraud initiative is primarily targeting Democratic-led states, representing a departure from traditional federal enforcement that focused on individual providers. Oz has released videos highlighting suspected fraudulent activity, including the concentration of hospices in specific Los Angeles neighborhoods.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["Mehmet Oz"],
        "link": "https://www.statnews.com/2026/02/05/hhs-fraud-crackdown-blue-states/",
        "link_label": "STAT News Report",
        "social_posts": [],
        "tags": ["Medicaid", "CMS", "Hospice Fraud", "Policy", "State Investigations"],
        "entities": ["CMS", "HHS"],
        "state": None,
        "source_type": "news",
        "auto_fetched": False,
    },
    # Bloomberg Law
    {
        "id": "media-2025-02-27-bloomberg-hcat",
        "date": "2025-02-27",
        "agency": "Media",
        "type": "Civil Action",
        "title": "Bloomberg Law: Healthcare Associates of Texas Must Pay $16.5 Million for Medicare Fraud",
        "description": "A federal judge upheld a jury verdict ordering Healthcare Associates of Texas (HCAT) to pay $16.5 million for submitting over 20,000 false Medicare claims. The court rejected the statutory minimum $300 million penalty as unconstitutionally excessive. The whistleblower case was brought by former employee Cheryl Taylor under the False Claims Act.",
        "amount": "$16.5 million",
        "amount_numeric": 16500000,
        "officials": ["Cheryl Taylor"],
        "link": "https://news.bloomberglaw.com/health-law-and-business/healthcare-associates-must-pay-16-5-million-for-medicare-fraud",
        "link_label": "Bloomberg Law Report",
        "social_posts": [],
        "tags": ["Medicare", "False Claims Act", "Whistleblower", "Civil Action"],
        "entities": ["Healthcare Associates of Texas"],
        "state": "TX",
        "source_type": "news",
        "auto_fetched": False,
    },
    # Bloomberg Law - Vohra already exists, Humana already exists
    # DOJ - CEO software $1B sentenced
    {
        "id": "doj-2025-12-22-dmerx-ceo-sentenced",
        "date": "2025-12-22",
        "agency": "DOJ",
        "type": "Criminal Enforcement",
        "title": "CEO of Health Care Software Company Sentenced to 15 Years for $1 Billion Medicare Fraud Conspiracy",
        "description": "The CEO of Power Mobility Doctor Rx (DMERx) was sentenced to 15 years in prison and ordered to pay over $452 million in restitution for operating a platform that generated false doctors' orders to defraud Medicare and other federal health care programs of more than $1 billion. The software generated fraudulent prescriptions for durable medical equipment, including power wheelchairs and other mobility devices, that were medically unnecessary or never provided to patients.",
        "amount": "$1 billion",
        "amount_numeric": 1000000000,
        "officials": [],
        "link": "https://www.justice.gov/opa/pr/ceo-health-care-software-company-sentenced-1b-fraud-conspiracy",
        "link_label": "DOJ Press Release",
        "social_posts": [],
        "tags": ["Medicare", "DME Fraud", "Software Fraud", "Sentencing", "False Claims"],
        "entities": ["Power Mobility Doctor Rx", "DMERx"],
        "state": "AZ",
        "source_type": "official",
        "auto_fetched": False,
    },
    # NY Comptroller Medicaid fraud indictment
    {
        "id": "state-2025-11-01-ny-comptroller-medicaid",
        "date": "2025-11-01",
        "agency": "State Agency",
        "type": "Criminal Enforcement",
        "title": "NY Comptroller DiNapoli and DA Hoovler Announce Indictment in Medicaid Fraud Case",
        "description": "New York State Comptroller Thomas DiNapoli and Orange County District Attorney David Hoovler announced the indictment of Rohail Raja and Sharma Alam on charges of Grand Larceny and Conspiracy for stealing over $3.5 million from the New York State Medicaid program through fraudulent billing schemes.",
        "amount": "$3.5 million",
        "amount_numeric": 3500000,
        "officials": ["Rohail Raja", "Sharma Alam"],
        "link": "https://www.osc.ny.gov/press/releases/2025/11/new-york-state-comptroller-dinapoli-and-district-attorney-hoovler-announce-indictment-medicaid-fraud",
        "link_label": "NY Comptroller Press Release",
        "social_posts": [],
        "tags": ["Medicaid", "Grand Larceny", "Indictment", "State Enforcement"],
        "entities": [],
        "state": "NY",
        "source_type": "news",
        "auto_fetched": False,
    },
    # MFCU Annual Report FY2025
    {
        "id": "hhs-oig-2026-03-01-mfcu-annual-report",
        "date": "2026-03-01",
        "agency": "HHS-OIG",
        "type": "Audit",
        "title": "HHS-OIG: Medicaid Fraud Control Units Annual Report FY2025 — $2 Billion in Combined Recoveries",
        "description": "HHS-OIG released its annual report on Medicaid Fraud Control Units (MFCUs), reporting combined criminal and civil recoveries of nearly $2 billion for fiscal year 2025. Criminal recoveries from convictions totaled $1.3 billion and civil recoveries totaled $706 million across all state MFCUs.",
        "amount": "$2 billion",
        "amount_numeric": 2000000000,
        "officials": [],
        "link": "https://oig.hhs.gov/reports/all/2026/medicaid-fraud-control-units-annual-report-fiscal-year-2025/",
        "link_label": "HHS-OIG Report",
        "social_posts": [],
        "tags": ["Medicaid", "MFCU", "Annual Report", "Audit"],
        "entities": ["HHS-OIG"],
        "state": None,
        "source_type": "official",
        "auto_fetched": False,
    },
    # DMEPOS moratorium
    {
        "id": "cms-2026-02-25-dmepos-moratorium",
        "date": "2026-02-25",
        "agency": "CMS",
        "type": "Rule/Regulation",
        "title": "CMS Imposes Six-Month Nationwide Moratorium on New Medicare DMEPOS Supplier Enrollment",
        "description": "As part of the Trump administration's CRUSH (Comprehensive Regulations to Uncover Suspicious Healthcare) initiative, CMS imposed a six-month moratorium on new Medicare enrollment for durable medical equipment, prosthetics, orthotics, and supplies (DMEPOS) suppliers nationwide. The moratorium aims to prevent fraudulent suppliers from entering Medicare while CMS deploys AI-based detection tools to identify suspicious billing patterns.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["Mehmet Oz"],
        "link": "https://www.cms.gov/newsroom/press-releases/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud",
        "link_label": "CMS Press Release",
        "social_posts": [],
        "tags": ["Medicare", "DME", "DMEPOS", "Moratorium", "CRUSH", "Rule/Regulation"],
        "entities": ["CMS"],
        "state": None,
        "source_type": "official",
        "auto_fetched": False,
    },
]

added = 0
for entry in new_entries:
    if entry["link"] in existing_links:
        print(f"  SKIP (dup link): {entry['title'][:70]}")
        continue
    data["actions"].append(entry)
    existing_links.add(entry["link"])
    added += 1
    print(f"  ADDED: {entry['date']} | {entry['title'][:70]}")

data["metadata"]["last_updated"] = datetime.now().isoformat()

with open("data/actions.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\nAdded {added} entries. Total: {len(data['actions'])}")
