"""Add missing Congress/GAO items from backfill research."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
existing_links = {a.get('link', '') for a in d['actions']}

new_items = [
    {
        "id": "congress-2026-03-17-house-ec-cms-fraud-hearing",
        "date": "2026-03-17",
        "agency": "Congress",
        "type": "Congressional Hearing",
        "title": "House E&C Hearing: Protecting Patients and Safeguarding Taxpayer Dollars — The Role of CMS in Combatting Medicare and Medicaid Fraud",
        "description": "House Energy & Commerce Subcommittee on Oversight and Investigations held a hearing on the Trump Administration's efforts to proactively tackle Medicare and Medicaid fraud, with testimony on CMS enforcement actions, the CRUSH initiative, and vulnerable programs targeted by fraud schemes.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["Dr. Mehmet Oz"],
        "link": "https://energycommerce.house.gov/posts/chairman-joyce-delivers-opening-statement-at-subcommittee-on-oversight-and-investigations-hearing-on-ongoing-investigation-into-medicare-and-medicaid-programs-nationwide",
        "link_label": "House E&C",
        "social_posts": [],
        "tags": ["Congressional", "Medicare", "Medicaid", "Program Integrity", "CRUSH"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "congress-2026-01-20-house-ec-mn-medicaid-investigation-launch",
        "date": "2026-01-20",
        "agency": "Congress",
        "type": "Investigation",
        "title": "House E&C Launches Investigation into Ongoing Medicaid Fraud in Minnesota",
        "description": "House Energy & Commerce Committee leaders launched a formal investigation into ongoing Medicaid fraud in Minnesota, requesting documents from Governor Walz and the Department of Human Services. The fraud scheme, potentially operating since 2013, involves overbilling, false records, identity theft, and phantom claims.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://energycommerce.house.gov/posts/e-and-c-leaders-launch-investigation-into-ongoing-medicaid-fraud-in-minnesota",
        "link_label": "House E&C",
        "social_posts": [],
        "tags": ["Congressional", "Medicaid", "False Claims", "Identity Theft", "Organized Crime"],
        "entities": [],
        "state": "MN",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "congress-2025-07-02-house-oversight-ny-medicaid-investigation",
        "date": "2025-07-02",
        "agency": "Congress",
        "type": "Investigation",
        "title": "House Oversight Launches Investigation of Fraud in New York's Medicaid Programs",
        "description": "Chairman Comer launched an investigation into allegations that New York State misrepresented federal Medicaid fund sources involving Nassau University Medical Center. The alleged scheme has reportedly cost taxpayers over $1 billion over 20+ years. Comer requested a staff briefing from CMS Administrator Dr. Oz.",
        "amount": "$1B+",
        "amount_numeric": 1000000000,
        "officials": ["Chairman James Comer", "Dr. Mehmet Oz"],
        "link": "https://oversight.house.gov/release/comer-takes-new-action-in-investigation-of-fraud-in-new-yorks-medicaid-programs/",
        "link_label": "House Oversight",
        "social_posts": [],
        "tags": ["Congressional", "Medicaid", "Improper Payments", "Program Integrity"],
        "entities": ["Nassau University Medical Center"],
        "state": "NY",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "congress-2025-12-house-oversight-mn-investigation-widened",
        "date": "2025-12-01",
        "agency": "Congress",
        "type": "Investigation",
        "title": "House Oversight Widens Investigation into Minnesota Social Services and Medicaid Fraud",
        "description": "Chairman Comer widened the investigation into extensive money laundering and fraud in Minnesota's social services programs, following findings by the U.S. Attorney for the District of Minnesota. A legislative audit revealed a grantee receiving nearly $680,000 for a single month without documentation.",
        "amount": None,
        "amount_numeric": 0,
        "officials": ["Chairman James Comer"],
        "link": "https://oversight.house.gov/release/chairman-comer-widens-investigation-into-fraud-in-minnesotas-social-services-programs/",
        "link_label": "House Oversight",
        "social_posts": [],
        "tags": ["Congressional", "Medicaid", "Money Laundering", "Organized Crime", "Improper Payments"],
        "entities": [],
        "state": "MN",
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "legislation-2025-hr1784-medicare-fraud-detection-act",
        "date": "2025-03-01",
        "agency": "Congress",
        "type": "Legislation",
        "title": "H.R. 1784: Medicare Fraud Detection and Deterrence Act of 2025 Introduced",
        "description": "Bill introduced requiring CMS to deactivate standard unique health identifiers of healthcare providers excluded from federal programs due to fraud, preventing excluded providers from continuing to bill Medicare.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.congress.gov/bill/119th-congress/house-bill/1784",
        "link_label": "Congress.gov",
        "social_posts": [],
        "tags": ["Congressional", "Medicare", "Program Integrity", "Legislation"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "legislation-2025-s3593-healthcare-fraud-penalties",
        "date": "2025-06-01",
        "agency": "Congress",
        "type": "Legislation",
        "title": "S. 3593: Bill to Increase Health Care Fraud Penalties Introduced in Senate",
        "description": "Senate bill introduced to increase criminal and civil penalties for healthcare fraud convictions and to strengthen enforcement tools available to federal prosecutors.",
        "amount": None,
        "amount_numeric": 0,
        "officials": [],
        "link": "https://www.congress.gov/bill/119th-congress/senate-bill/3593",
        "link_label": "Congress.gov",
        "social_posts": [],
        "tags": ["Congressional", "Legislation", "Program Integrity"],
        "entities": [],
        "state": None,
        "source_type": "official",
        "auto_fetched": False
    },
    {
        "id": "cms-2025-mn-medicaid-payment-deferrals",
        "date": "2025-10-01",
        "agency": "CMS",
        "type": "Administrative Action",
        "title": "CMS Defers $259M in Federal Medicaid Payments to Minnesota, Freezes Provider Enrollment",
        "description": "CMS temporarily deferred $259 million in federal Medicaid payments to Minnesota for FY2025 claims and froze provider enrollment. Payments deferred for 14 high-risk programs worth $3.75 billion annually, marking an aggressive new federal approach to state Medicaid fraud.",
        "amount": "$259M",
        "amount_numeric": 259000000,
        "officials": ["Dr. Mehmet Oz"],
        "link": "https://www.kff.org/medicaid/cms-new-approach-to-federal-medicaid-spending-in-cases-of-potential-fraud/",
        "link_label": "KFF Analysis",
        "social_posts": [],
        "tags": ["Medicaid", "Program Integrity", "Improper Payments"],
        "entities": [],
        "state": "MN",
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

print(f"\nAdded {added} items. Total: {len(d['actions'])}")
