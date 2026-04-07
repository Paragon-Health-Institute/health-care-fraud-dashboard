import json

with open('data/actions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# === TAGS TO REMOVE (redundant, too generic, overly specific) ===
remove_tags = {
    # Redundant - everything is healthcare fraud
    'Healthcare Fraud', 'healthcare fraud', 'health care fraud', 'fraud',
    # Agency already shown in agency field
    'DOJ', 'CMS', 'HHS', 'HHS-OIG', 'FBI',
    # Already in type/title
    'sentenced', 'conviction', 'Conviction', 'guilty plea', 'Guilty Plea', 'sentencing',
    'audit', 'Audit', 'Audit Series',
    # Too generic / process words
    'structural', 'Structural', 'enforcement', 'Investigation', 'investigation',
    'rule', 'Rule', 'regulation', 'record', 'administrative', 'reorganization',
    'expansion', 'Coordination', 'priority', 'exclusions', 'National', 'Crackdown',
    'On-site', 'Action Plan', 'savings', 'waste', 'anti-fraud', 'Anti-Fraud',
    'fraud prevention', 'Fraud Prevention', 'Fraud Detection',
    # Overly specific medical/procedure terms
    'catheter', 'amniotic graft', 'AWP', 'compound cream', 'TCD', 'ultrasound',
    'EHR', 'sleep medicine', 'gastroenterology', 'pathology', 'ophthalmology',
    'debridement', 'skin substitute', 'orthotics', 'orthotic braces', 'braces',
    'compound pharmacy', 'imaging centers', 'vision testing', 'cardiovascular',
    'price inflation',
    # Too vague
    'corporate enforcement', 'corporate integrity agreement', 'Corporate Integrity Agreement',
    'prior felon', 'technology', 'Technology', 'enrollment', 'eligibility',
    'agents', 'brokers', 'marketplace', 'annual report', 'semiannual report',
}

# === CONSOLIDATION MAP (normalize to Title Case standard) ===
consolidate = {
    # Kickbacks
    'kickbacks': 'Kickbacks', 'Kickback': 'Kickbacks',
    'Anti-Kickback Statute': 'Anti-Kickback', 'anti-kickback statute': 'Anti-Kickback',
    'Anti-Kickback': 'Anti-Kickback',
    # Identity Theft
    'identity theft': 'Identity Theft',
    # DME
    'DME': 'DME Fraud', 'DME fraud': 'DME Fraud', 'DME Fraud': 'DME Fraud',
    'Durable Medical Equipment': 'DME Fraud', 'DMEPOS': 'DME Fraud',
    # Hospice
    'hospice': 'Hospice Fraud', 'Hospice': 'Hospice Fraud',
    'hospice fraud': 'Hospice Fraud', 'sham hospice': 'Hospice Fraud',
    # Home Health
    'home health': 'Home Health Fraud', 'Home Care': 'Home Health Fraud',
    'Home Health Fraud': 'Home Health Fraud',
    # Upcoding / Risk Adjustment
    'upcoding': 'Upcoding', 'risk adjustment': 'Risk Adjustment',
    'diagnosis coding': 'Upcoding', 'Diagnosis Coding': 'Upcoding',
    'diagnosis codes': 'Upcoding',
    # Whistleblower
    'whistleblower': 'Whistleblower', 'qui tam': 'Whistleblower',
    # Money Laundering
    'money laundering': 'Money Laundering',
    # Genetic Testing
    'genetic testing': 'Genetic Testing',
    # COVID
    'COVID-19 Fraud': 'COVID-19',
    # Nursing Home
    'nursing home': 'Nursing Home', 'skilled nursing': 'Nursing Home',
    # Lab Fraud
    'laboratory': 'Lab Fraud', 'Laboratory Fraud': 'Lab Fraud', 'Labs': 'Lab Fraud',
    # Opioids
    'opioid': 'Opioids', 'Opioid Fraud': 'Opioids',
    'controlled substances': 'Opioids', 'Controlled Substances Act': 'Opioids',
    # Telehealth
    'telemedicine': 'Telehealth', 'telehealth': 'Telehealth',
    # Substance Abuse / Addiction
    'Substance Abuse': 'Addiction Treatment', 'substance abuse': 'Addiction Treatment',
    'Addiction Treatment': 'Addiction Treatment', 'addiction treatment': 'Addiction Treatment',
    'Addiction Treatment Fraud': 'Addiction Treatment',
    'Sober Living Fraud': 'Addiction Treatment',
    # Pharmacy
    'pharmacy': 'Pharmacy Fraud', 'Pharmacy Fraud': 'Pharmacy Fraud',
    # ACA
    'Affordable Care Act': 'ACA', 'Obamacare': 'ACA',
    'Marketplace Fraud': 'ACA Fraud', 'enrollment fraud': 'ACA Fraud',
    'Enrollment Fraud': 'ACA Fraud', 'Subsidies': 'ACA Fraud',
    'premium subsidies': 'ACA Fraud', 'Premium Tax Credits': 'ACA Fraud',
    'SEP': 'ACA Fraud', 'Brokers': 'ACA Fraud',
    'insurance broker': 'ACA Fraud',
    # Congress
    'Congressional Hearing': 'Congressional', 'Congressional Investigation': 'Congressional',
    # Pharmaceutical
    'pharmaceutical': 'Pharmaceutical', 'Prescription Drug': 'Pharmaceutical',
    'Prescription Fraud': 'Pharmaceutical', 'prescription fraud': 'Pharmaceutical',
    'speaker programs': 'Pharmaceutical',
    # Skin Grafts / Wound Care
    'Skin Grafts': 'Wound Care', 'wound care': 'Wound Care',
    # Legislation
    'State Legislation': 'Legislation',
    # Medical device
    'medical device': 'Medical Devices', 'Medical Devices': 'Medical Devices', 'FDA': 'Medical Devices',
    # Adult Day Care
    'adult day care': 'Adult Day Care', 'Adult Day Care': 'Adult Day Care',
    # AI
    'Artificial Intelligence': 'AI', 'AI Fraud Detection': 'AI',
    # Program Integrity
    'Program Integrity': 'Program Integrity', 'CMS enforcement': 'Program Integrity',
    # Takedown
    'takedown': 'National Takedown',
    # Organized Crime
    'Transnational Crime': 'Organized Crime', 'Transnational': 'Organized Crime',
    'Organized Crime': 'Organized Crime', 'sham company': 'Organized Crime',
    'sham clinics': 'Organized Crime',
    # Foreign Nationals
    'Foreign Influence': 'Foreign Nationals', 'Pakistan': 'Foreign Nationals',
    # State-specific standardization
    'Los Angeles': 'California',
    # Misc
    'health insurance': 'Health Insurance', 'Health Insurance': 'Health Insurance',
    'software platform': 'AI',
    'data fusion': 'AI', 'analytics': 'AI', 'cloud computing': 'AI',
    'duplicate enrollment': 'Program Integrity',
    'Data Transparency': 'DOGE', 'Data Breach': 'Identity Theft',
    'criminal indictment': None,  # remove
    'unnecessary surgery': 'Unnecessary Procedures',
    'unnecessary testing': 'Unnecessary Procedures',
    'physician referral': 'Stark Law',
    'physician self-referral': 'Stark Law',
    'Stark Law': 'Stark Law',
    'CMS funds diversion': 'Fraud Diversion',
    'MSO': None,  # too niche
    'non-prosecution agreement': None,
    'loophole': None,
    'financing gimmick': None,
    'provider tax': 'Medicaid Financing',
    'Financing': 'Medicaid Financing',
    'deferral': None,
    'moratorium': None,
    'RFI': None,
    'Working group': None, 'working group': None,
    'NDAA': 'Legislation',
    'PBM Reform': 'Legislation',
    'Transparency': None,
    'License Moratorium': 'Legislation',
    'Cybercrime': 'Cybersecurity',
    'cybersecurity': 'Cybersecurity',
    'housing fraud': 'Housing Fraud', 'Housing Fraud': 'Housing Fraud',
    'CHIP': 'Medicaid',
    'physician': None,
    'hospital': 'Hospital Fraud',
    'radiology': None,
    'research fraud': 'Research Fraud',
    'NIH grants': 'Research Fraud',
    'cancer research': 'Research Fraud',
    'data manipulation': 'Research Fraud',
    'overpayment': 'Improper Payments',
    'capitation payments': 'Improper Payments',
    'managed care': 'Managed Care',
    'deceased enrollees': 'Improper Payments',
    'incarcerated': 'Improper Payments',
    'improper payments': 'Improper Payments',
    'restitution': None,
    '15 years': None,
    '20 years': None,
    '$1 billion': None,
    'ADAP': None,
    'HIV': 'Pharmaceutical',
    'disability discrimination': None,
    'White-Collar Enforcement Plan': None,
    'Criminal Division': None,
    'Miami': 'Florida',
    'telemarketing': None,
    'RADV': 'Medicare Advantage',
    'Feeding Our Future': 'Minnesota',
    'Work Requirements': 'Legislation',
    'Private Equity': None,
    'State Settlement': None,
    'State Enforcement': None,
    'State Investigation': None,
    'DOD': 'Military Healthcare',
    'military healthcare': 'Military Healthcare',
    'Elder Fraud': 'Elder Fraud',
    'Serial Fraudster': None,
    'Wire Fraud': None,
    'Clinic Fraud': None,
    'Behavioral Health': 'Behavioral Health',
    'ABA Therapy': 'Behavioral Health',
    'ABA Services': 'Behavioral Health',
    'Autism Services': 'Behavioral Health',
    'Autism': 'Behavioral Health',
    'Children': None,
    'Maine': None,  # already have state field
    'Queens': 'New York',
    'Boston': 'Massachusetts',
    'bribes': 'Kickbacks',
    'bribery': 'Kickbacks',
    'Payment Withholding': None,
    'Payment Deferral': None,
    'Recoupment': None,
    'States': None,
    'Indiana': None,  # use state field
    'Indigenous Communities': 'Native American',
}

changes = 0
for a in data['actions']:
    old_tags = a.get('tags') or []
    new_tags = []
    for t in old_tags:
        # Remove if in remove set
        if t in remove_tags:
            changes += 1
            continue
        # Consolidate if in map
        if t in consolidate:
            mapped = consolidate[t]
            if mapped is None:
                changes += 1
                continue
            t = mapped
        # Title Case any remaining all-lowercase tags
        if t == t.lower() and len(t) > 3:
            t = t.title()
            changes += 1
        new_tags.append(t)
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for t in new_tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    if len(deduped) != len(new_tags):
        changes += len(new_tags) - len(deduped)
    a['tags'] = deduped

print(f"Made {changes} tag changes")

# === SAVE ===
with open('data/actions.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# === VERIFY: print final tag list ===
from collections import Counter
tags = Counter()
for a in data['actions']:
    for t in (a.get('tags') or []):
        tags[t] += 1
print(f"\nFinal tags ({len(tags)} unique):")
for tag, count in tags.most_common():
    print(f"  {count:3d}  {tag}")
