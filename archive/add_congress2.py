"""Add missing Congress/GAO items from second research pass."""
import json

d = json.load(open('data/actions.json', 'r', encoding='utf-8-sig'))
existing_links = {a.get('link', '') for a in d['actions']}

new_items = [
    {
        "id": "congress-2025-09-04-senate-finance-hhs-secretary-hearing",
        "date": "2025-09-04",
        "agency": "Congress",
        "type": "Congressional Hearing",
        "title": "Senate Finance Hearing: The President's 2026 Health Care Agenda — HHS Secretary Kennedy Testifies on Fraud Prevention",
        "description": "HHS Secretary Robert F. Kennedy Jr. testified before Senate Finance. Chairman Crapo questioned Kennedy on fraud prevention. CMS discovered 2.8 million Americans enrolled in duplicate Medicaid or ACA Exchange plans, with projected savings of $14 billion annually from removing them.",
        "amount": "$14B annual savings",
        "amount_numeric": 14000000000,
        "officials": ["Robert F. Kennedy Jr.", "Chairman Mike Crapo"],
        "link": "https://www.finance.senate.gov/hearings/the-presidents-2026-health-care-agenda",
        "link_label": "Senate Finance Committee",
        "social_posts": [], "tags": ["Congressional", "Medicare", "Medicaid", "ACA", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "congress-2026-02-12-senate-help-child-care-fraud-hearing",
        "date": "2026-02-12",
        "agency": "Congress",
        "type": "Congressional Hearing",
        "title": "Senate HELP Hearing: Restoring Integrity — Preventing Fraud in Child Care Assistance Programs",
        "description": "Chairman Cassidy convened a hearing examining rampant fraud in federal child care funding, triggered by Minnesota's scandal where 1 in 10 child care dollars was stolen or misused. Followed Cassidy's demand for documents from Governor Walz.",
        "amount": None, "amount_numeric": 0,
        "officials": ["Chairman Bill Cassidy"],
        "link": "https://www.help.senate.gov/rep/newsroom/press/next-week-senate-help-committee-to-hold-hearing-on-child-care-fraud-protecting-american-taxpayers",
        "link_label": "Senate HELP Committee",
        "social_posts": [], "tags": ["Congressional", "Medicaid", "Improper Payments"],
        "entities": [], "state": "MN", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "congress-2026-03-wm-oversight-healthcare-fraud-hearing",
        "date": "2026-03-12",
        "agency": "Congress",
        "type": "Congressional Hearing",
        "title": "House Ways & Means Oversight Subcommittee Hearing: Improving Efforts to Combat Health Care Fraud",
        "description": "Hearing on current policies and programs designed to prevent and punish Medicare fraud, as well as innovative fraud prevention practices. HHS-OIG testified on improving efforts to combat healthcare fraud.",
        "amount": None, "amount_numeric": 0, "officials": [],
        "link": "https://waysandmeans.house.gov/event/oversight-subcommittee-hearing-on-improving-efforts-to-combat-health-care-fraud/",
        "link_label": "House Ways & Means",
        "social_posts": [], "tags": ["Congressional", "Medicare", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "congress-2026-01-09-ec-wm-la-hospice-fraud-inquiry",
        "date": "2026-01-09",
        "agency": "Congress",
        "type": "Investigation",
        "title": "Six Committee Chairmen Request HHS-OIG Briefing on LA County Hospice and Home Health Fraud",
        "description": "Six chairmen from House E&C and Ways & Means sent a letter to HHS-OIG requesting a briefing on hospice fraud in LA County. Auditors found 112 hospices at the same address, $1.2 billion in improper home health payments, and $198 million in suspected hospice fraud. Armenian organized crime networks identified as key players.",
        "amount": "$1.2B",
        "amount_numeric": 1200000000,
        "officials": [],
        "link": "https://energycommerce.house.gov/posts/chairmen-guthrie-joyce-griffith-smith-schweikert-and-buchanan-ask-hhs-oig-about-ongoing-hha-and-hospice-fraud-in-los-angeles-county-1",
        "link_label": "House E&C",
        "social_posts": [], "tags": ["Congressional", "Medicare", "Hospice Fraud", "Home Health Fraud", "Organized Crime"],
        "entities": [], "state": "CA", "source_type": "official", "auto_fetched": False
    },
    {
        "id": "congress-2026-02-10-judiciary-subpoenas-aca-insurers",
        "date": "2026-02-10",
        "agency": "Congress",
        "type": "Investigation",
        "title": "House Judiciary Subpoenas 8 Major Health Insurers Over ACA Enrollment Fraud",
        "description": "Subpoenas issued to Blue Shield of California, Centene, CVS Health, Elevance Health, GuideWell, HCSC, Kaiser Permanente, and Oscar Health demanding information on fraud-protection measures, enrollees with unused subsidies, broker payments, and internal fraud audits.",
        "amount": None, "amount_numeric": 0,
        "officials": ["Chairman Jim Jordan"],
        "link": "https://judiciary.house.gov/media/press-releases/chairmen-jordan-fitzgerald-and-van-drew-subpoena-insurance-providers-documents",
        "link_label": "House Judiciary",
        "social_posts": [], "tags": ["Congressional", "ACA", "Program Integrity"],
        "entities": ["Blue Shield of California", "Centene", "CVS Health", "Elevance Health", "GuideWell", "HCSC", "Kaiser Permanente", "Oscar Health"],
        "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "doge-2026-02-13-medicaid-data-release",
        "date": "2026-02-13",
        "agency": "White House",
        "type": "Technology/Innovation",
        "title": "DOGE Releases Largest Medicaid Dataset in History to Crowdsource Fraud Detection",
        "description": "DOGE released aggregated provider-level Medicaid claims data covering fee-for-service, managed care, and CHIP claims from 2018-2024 to crowdsource fraud detection. DOGE gained access to CMS systems in February 2025.",
        "amount": None, "amount_numeric": 0,
        "officials": [],
        "link": "https://www.axios.com/2026/02/14/elon-musk-doge-medicaid-fraud-hhs-database",
        "link_label": "Axios",
        "social_posts": [], "tags": ["DOGE", "Medicaid", "Program Integrity", "AI"],
        "entities": [], "state": None, "source_type": "news", "auto_fetched": False
    },
    {
        "id": "gao-2025-02-25-high-risk-list",
        "date": "2025-02-25",
        "agency": "GAO",
        "type": "Audit",
        "title": "GAO 2025 High-Risk List: Medicare and Medicaid Maintain High-Risk Status; 129 Open Recommendations",
        "description": "GAO biennial report identified 38 high-risk areas. Medicare and Medicaid maintained high-risk status with 64 and 65 open recommendations respectively, including improving hospice oversight, addressing Medicare Advantage risks, and strengthening Medicaid provider screening. Programs on the list represent 80% of government-wide improper payments.",
        "amount": None, "amount_numeric": 0, "officials": [],
        "link": "https://www.gao.gov/products/gao-25-107743",
        "link_label": "GAO Report",
        "social_posts": [], "tags": ["Medicare", "Medicaid", "Medicare Advantage", "Program Integrity", "Improper Payments", "Hospice Fraud"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "gao-2025-06-26-medicaid-managed-care-improper-payments",
        "date": "2025-06-26",
        "agency": "GAO",
        "type": "Audit",
        "title": "GAO Report: Medicaid Managed Care Improper Payment Estimate Near 0% Despite Known Fraud Risks",
        "description": "GAO raised concerns that Medicaid managed care's near-0% improper payment estimate masks real fraud risks. Between October 2021 and February 2025, CMS audits identified $33 million in overpayments. About 75% of Medicaid beneficiaries (74 million people) receive coverage through managed care.",
        "amount": "$33M identified",
        "amount_numeric": 33000000, "officials": [],
        "link": "https://www.gao.gov/products/gao-25-107770",
        "link_label": "GAO Report",
        "social_posts": [], "tags": ["Medicaid", "Improper Payments", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "congress-2025-07-21-crapo-applauds-cms-duplicate-enrollment",
        "date": "2025-07-21",
        "agency": "Congress",
        "type": "Administrative Action",
        "title": "Senate Finance Chair Crapo Applauds CMS Finding 2.8M Duplicate Medicaid/ACA Enrollments",
        "description": "Chairman Crapo praised CMS after the agency found 2.8 million Americans enrolled in both Medicaid and ACA Exchange plans simultaneously. Eliminating duplicate enrollment projected to save $14 billion annually.",
        "amount": "$14B annual savings",
        "amount_numeric": 14000000000,
        "officials": ["Chairman Mike Crapo", "Dr. Mehmet Oz"],
        "link": "https://www.finance.senate.gov/chairmans-news/crapo-applauds-cms-efforts-to-root-out-fraud-saving-taxpayers-billions",
        "link_label": "Senate Finance Committee",
        "social_posts": [], "tags": ["Congressional", "Medicaid", "ACA", "Program Integrity", "Improper Payments"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "medpac-2025-ma-upcoding-analysis",
        "date": "2025-06-01",
        "agency": "Congress",
        "type": "Investigative Report",
        "title": "MedPAC/CRFB Analysis: Medicare Advantage Upcoding to Cost $40B in 2025; $1.3 Trillion Over Decade",
        "description": "MedPAC found upcoding will increase Medicare payments to private insurers by an estimated 10% ($40 billion) in 2025. CRFB estimated MA overpayments of $1.3 trillion over the next decade. CMS Administrator Oz pledged to go after upcoding during his Senate confirmation.",
        "amount": "$40B/year",
        "amount_numeric": 40000000000,
        "officials": ["Dr. Mehmet Oz"],
        "link": "https://www.crfb.org/blogs/new-data-suggests-ma-overpayments-13-trillion-over-next-decade",
        "link_label": "CRFB Analysis",
        "social_posts": [], "tags": ["Medicare Advantage", "Improper Payments", "Risk Adjustment", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "legislation-2025-s2066-medicare-transaction-fraud-act",
        "date": "2025-06-12",
        "agency": "Congress",
        "type": "Legislation",
        "title": "S. 2066: Medicare Transaction Fraud Prevention Act — Pilot Program for Predictive Risk Scoring",
        "description": "Bill establishing a 2-year pilot program to test predictive risk-scoring algorithms for oversight of Medicare payments for durable medical equipment and clinical lab tests. Sponsored by Senator Tim Sheehy.",
        "amount": None, "amount_numeric": 0,
        "officials": ["Senator Tim Sheehy"],
        "link": "https://www.congress.gov/bill/119th-congress/senate-bill/2066/text",
        "link_label": "Congress.gov",
        "social_posts": [], "tags": ["Congressional", "Medicare", "DME Fraud", "Lab Fraud", "AI", "Legislation"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "legislation-2026-hr7155-stop-fraud-federal-programs",
        "date": "2026-01-20",
        "agency": "Congress",
        "type": "Legislation",
        "title": "H.R. 7155: Stop Fraud in Federal Programs Act of 2026",
        "description": "Increases penalties for theft or bribery concerning programs receiving federal funds. Also requires audits under the summer food service program. Referred to Committees on Judiciary and Education and Workforce.",
        "amount": None, "amount_numeric": 0, "officials": [],
        "link": "https://www.congress.gov/bill/119th-congress/house-bill/7155/all-info",
        "link_label": "Congress.gov",
        "social_posts": [], "tags": ["Congressional", "Medicaid", "Legislation", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "legislation-2026-hr7677-closing-provider-fraud-gap",
        "date": "2026-02-25",
        "agency": "Congress",
        "type": "Legislation",
        "title": "H.R. 7677: Closing the Provider Fraud Gap Act — Passed Committee 35-0",
        "description": "Requires the Comptroller General to study fraud prevention in federal early childhood education, child care, and child nutrition programs. Passed House Education and Workforce Committee 35-0 on March 5, 2026.",
        "amount": None, "amount_numeric": 0, "officials": [],
        "link": "https://www.congress.gov/bill/119th-congress/house-bill/7677/all-info",
        "link_label": "Congress.gov",
        "social_posts": [], "tags": ["Congressional", "Medicaid", "Legislation", "Program Integrity"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
    },
    {
        "id": "legislation-2025-ending-improper-payments-deceased",
        "date": "2025-07-01",
        "agency": "Congress",
        "type": "Legislation",
        "title": "Ending Improper Payments to Deceased People Act Passes Senate HSGAC Unanimously",
        "description": "Permanently amends the Social Security Act to allow SSA to share the Death Master File with Treasury's Do Not Pay system, preventing improper payments to deceased individuals. The Treasury recovered $31 million in fraud during the prior version's implementation.",
        "amount": "$31M recovered",
        "amount_numeric": 31000000,
        "officials": ["Senator John Kennedy", "Senator Gary Peters"],
        "link": "https://www.kennedy.senate.gov/public/2025/7/senate-homeland-security-committee-unanimously-passes-kennedy-peters-bill-to-end-government-payments-to-deceased-americans",
        "link_label": "Senator Kennedy",
        "social_posts": [], "tags": ["Congressional", "Medicare", "Medicaid", "Improper Payments", "Legislation"],
        "entities": [], "state": None, "source_type": "official", "auto_fetched": False
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
