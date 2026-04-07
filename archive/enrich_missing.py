"""One-time script to enrich entries missing descriptions and tags."""
import json

with open("data/actions.json", "r", encoding="utf-8-sig") as f:
    data = json.load(f)

enrichments = {
    "https://oig.hhs.gov/fraud/enforcement/alabama-doctor-sentenced-to-over-one-year-in-prison-for-27-million-telemedicine-health-care-fraud-scheme/": {
        "description": "Tommie Robinson, a 44-year-old Alabama doctor, was sentenced to 16 months in prison for operating a telemedicine fraud scheme that defrauded healthcare programs of $2.7 million. Robinson submitted claims for medically unnecessary durable medical equipment and genetic testing through telemedicine services. He pleaded guilty to one count of health care fraud and was ordered to pay $2,784,733.49 in restitution.",
        "tags": ["Medicare", "Telemedicine", "DME Fraud", "Sentencing", "Guilty Plea"],
        "officials": ["Tommie Robinson"],
        "state": "AL",
    },
    "https://oig.hhs.gov/fraud/enforcement/florida-doctor-pleads-guilty-to-making-false-statements-in-connection-with-multi-million-dollar-health-care-fraud-scheme/": {
        "description": "Simon Grinshteyn, 52, of Florida, pleaded guilty to one count of making false statements relating to health care matters. Grinshteyn signed orders for medically unnecessary genetic testing and durable medical equipment without having any direct provider-patient relationship, causing Medicare to pay over $3.1 million in fraudulent claims. Sentencing is scheduled for June 24, 2026.",
        "tags": ["Medicare", "Genetic Testing", "DME Fraud", "False Statements", "Guilty Plea"],
        "officials": ["Simon Grinshteyn"],
        "state": "FL",
        "amount": "$3.1 million",
        "amount_numeric": 3100000,
    },
    "https://oig.hhs.gov/fraud/enforcement/mississippi-man-ordered-to-pay-31-million-for-role-in-healthcare-kickback-scheme/": {
        "description": "Robert L. Crites, 67, of Batesville, Mississippi, was ordered to pay $31,039,134.82 in a federal judgment for orchestrating an illegal kickback scheme. Crites, through his companies Health Services Plus and TriCom LLC, identified and referred patients to Cloverland Pharmacy in Alabama, primarily targeting TRICARE beneficiaries. The pharmacy compensated Crites for each referral in violation of the Anti-Kickback Statute and False Claims Act.",
        "tags": ["TRICARE", "Kickback", "False Claims Act", "Pharmacy Fraud", "Civil Action"],
        "officials": ["Robert L. Crites"],
        "entities": ["Health Services Plus", "TriCom LLC", "Cloverland Pharmacy"],
        "state": "MS",
        "amount": "$31 million",
        "amount_numeric": 31000000,
    },
    "https://oig.hhs.gov/fraud/enforcement/consent-judgment-entered-against-bucks-county-company-resolving-allegations-of-false-claims-for-billing-group-art-classes-in-assisted-living-and-adult-day-facilities-as-occupational-therapy/": {
        "description": "A consent judgment was entered against Segal Arts LLC and owner Irina Segal of Bucks County, Pennsylvania, for submitting false Medicare claims for one-on-one occupational therapy services that were actually group art-and-crafts sessions at assisted living and adult day facilities in Pennsylvania and New Jersey. The company billed Medicare for medically necessary therapeutic exercises that were never delivered.",
        "tags": ["Medicare", "False Claims Act", "False Billing", "Assisted Living", "Consent Judgment"],
        "officials": ["Irina Segal"],
        "entities": ["Segal Arts LLC"],
        "state": "PA",
    },
    "https://oig.hhs.gov/fraud/enforcement/owner-of-now-closed-milwaukee-prenatal-care-coordination-company-sentenced-to-121-months-imprisonment-for-healthcare-fraud-scheme/": {
        "description": "Markita Barnes, 33, of Milwaukee, was sentenced to 121 months in prison for operating a healthcare fraud scheme through her prenatal care coordination company. Barnes was convicted on 10 counts of healthcare fraud, 3 counts of false statements, 3 counts of anti-kickback violations, obstruction, money laundering, and aggravated identity theft. She defrauded a Medicaid program designed for at-risk pregnant women of $2.36 million, causing Wisconsin to scale back the benefit program.",
        "tags": ["Medicaid", "Prenatal Care", "Kickback", "Money Laundering", "Identity Theft", "Sentencing"],
        "officials": ["Markita Barnes"],
        "state": "WI",
        "amount": "$2.36 million",
        "amount_numeric": 2360000,
    },
    "https://oig.hhs.gov/fraud/enforcement/former-greenville-ceo-employees-indicted-in-multi-million-dollar-health-care-fraud-scheme/": {
        "description": "Kevin S. Murdock, Thomas C. Lee, and Vidhya V. Narayanan were indicted in South Carolina on 16 counts for operating a fraudulent COVID-19 testing scheme through Premier Medical Laboratory Services in Greenville. The defendants submitted false claims to federal healthcare programs by billing for individual tests that had actually been pooled together, using software tampering to generate millions in fraudulent proceeds.",
        "tags": ["Medicare", "COVID-19 Testing", "Laboratory Fraud", "Indictment", "False Claims"],
        "officials": ["Kevin S. Murdock", "Thomas C. Lee", "Vidhya V. Narayanan"],
        "entities": ["Premier Medical Laboratory Services"],
        "state": "SC",
    },
    "https://oig.hhs.gov/fraud/enforcement/aetna-agrees-to-pay-1177-million-to-resolve-allegations-that-it-violated-the-false-claims-act-by-submitting-or-failing-to-correct-inaccurate-diagnoses-for-medicare-advantage-enrollees/": {
        "description": "Aetna Inc. agreed to pay $117.7 million to resolve False Claims Act allegations that it submitted inaccurate diagnosis codes for Medicare Advantage enrollees to inflate risk adjustment payments from CMS. The company either submitted false diagnoses or failed to correct erroneous codes, including knowingly submitting inaccurate morbid obesity diagnoses between 2018 and 2023. A Corporate Integrity Agreement was imposed. A whistleblower, a former Aetna coding auditor, received $2,012,500.",
        "tags": ["Medicare Advantage", "False Claims Act", "Upcoding", "Risk Adjustment", "Whistleblower", "Civil Settlement"],
        "entities": ["Aetna Inc."],
    },
    "https://www.justice.gov/usao-edwi/pr/owner-now-closed-milwaukee-prenatal-care-coordination-company-sentenced-60-months": {
        "description": "Lakia Jackson, 36, was sentenced to 60 months in federal prison for a healthcare fraud scheme that stole over $2.5 million from Wisconsin Medicaid's prenatal care coordination program. Jackson offered women kickbacks in exchange for their Medicaid identification numbers and then falsely billed the state for prenatal care services that were minimally provided or never rendered. She was ordered to forfeit and pay restitution of $2,361,799.17.",
        "tags": ["Medicaid", "Prenatal Care", "Kickback", "False Claims", "Sentencing"],
        "officials": ["Lakia Jackson"],
        "state": "WI",
        "amount": "$2.5 million",
        "amount_numeric": 2500000,
    },
    "https://www.justice.gov/usao-or/pr/pakistani-national-residing-southern-california-charged-fraudulently-billing-medicare": {
        "description": "A Pakistani national residing in Southern California was charged with fraudulently billing Medicare plans for medically unnecessary services. The defendant allegedly submitted false claims to Medicare through healthcare providers, generating significant fraudulent proceeds from the federal healthcare program.",
        "tags": ["Medicare", "False Claims", "Foreign Nationals", "Indictment"],
    },
    "https://www.whitehouse.gov/fact-sheets/2026/01/fact-sheet-president-donald-j-trump-establishes-new-department-of-justice-division-for-national-fraud-enforcement/": {
        "tags": ["Structural/Organizational", "DOJ", "Fraud Enforcement", "Executive Action"],
    },
}

updated = 0
for action in data["actions"]:
    link = action.get("link", "")
    if link in enrichments:
        e = enrichments[link]
        for key, val in e.items():
            # Don't overwrite existing non-empty descriptions
            if key == "description" and action.get(key, "").strip():
                continue
            action[key] = val
        updated += 1

with open("data/actions.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Enriched {updated} entries")

# Verify
missing_desc = sum(1 for a in data["actions"] if not a.get("description", "").strip())
missing_tags = sum(1 for a in data["actions"] if not a.get("tags"))
print(f"Remaining: {missing_desc} missing descriptions, {missing_tags} missing tags")
