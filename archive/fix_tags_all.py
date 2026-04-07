"""Apply consistent tags across all dashboard entries based on content."""
import json
import re

with open("data/actions.json", "r", encoding="utf-8-sig") as f:
    data = json.load(f)

# Tag rules: (tag_name, regex_pattern)
# Applied to title + description text
TAG_RULES = [
    # --- Program/payer tags ---
    ("Medicare",            r'\bmedicare\b'),
    ("Medicaid",            r'\bmedicaid\b|\bmedi-cal\b'),
    ("Medicare Advantage",  r'medicare advantage|risk adjust'),
    ("TRICARE",             r'\btricare\b'),
    ("ACA",                 r'(?<!\w)aca(?!\w)|affordable care act|marketplace.*fraud|enrollment fraud|obamacare.*fraud'),

    # --- Fraud type tags ---
    ("Hospice Fraud",       r'hospice'),
    ("Home Health Fraud",   r'home health|home care fraud'),
    ("DME Fraud",           r'durable medical|(?<!\w)dme(?!\w)|dmepos|medical equipment|wheelchair|orthotic brace|glucose monitor|power mobility'),
    ("Pharmacy Fraud",      r'pharmacy|pharmacist|prescription fraud|pbm|compounded|compound drug|drug diversion'),
    ("Lab Fraud",           r'laborator(?:y|ies)|lab test|lab owner|clinical lab|fictitious lab|sham lab|blood test.*fraud|urine test.*fraud'),
    ("Genetic Testing",     r'genetic test'),
    ("Nursing Home",        r'nursing home|nursing facility|skilled nursing|long.term care facility'),
    ("Hospital Fraud",      r'hospital.*fraud|hospital.*scheme|hospital.*false claim'),
    ("Telehealth",          r'telehealth|telemedicine'),
    ("Adult Day Care",      r'adult day care|daycare.*fraud'),
    ("Wound Care",          r'wound care|wound.*graft|skin substitute|allograft'),
    ("Opioids",             r'opioid|fentanyl|oxycodone|controlled substance|pill mill|hydrocodone|drug distribution.*scheme'),
    ("Addiction Treatment",  r'addiction|sober living|substance abuse.*treatment|rehab.*fraud|recovery.*fraud|suboxone|methadone.*fraud'),
    ("Behavioral Health",   r'behavioral health|mental health.*fraud|psychiatric.*fraud|counseling.*fraud'),
    ("Medical Devices",     r'medical device|implant.*fraud|defective.*implant'),
    ("Upcoding",            r'upcode|upcoding|unbundl'),
    ("Overbilling",         r'overbill|over.?bill'),
    ("Unnecessary Procedures", r'medically unnecessary|unnecessary.*procedure|unnecessary.*service|unnecessary.*test|never provided'),
    ("NPI Fraud",           r'\bnpi\b.*fraud|\bnpi\b.*loophole|stolen.*npi'),

    # --- Scheme/method tags ---
    ("Kickbacks",           r'kickback|anti-kickback|patient broker|stark law'),
    ("False Claims",        r'false claim|false billing|phantom billing|fraudulent claim|fraudulent billing'),
    ("False Claims Act",    r'false claims act|\bfca\b'),
    ("Identity Theft",      r'identity theft|stolen identit|aggravated identity'),
    ("Money Laundering",    r'money launder'),
    ("Whistleblower",       r'whistleblower|qui tam|relator'),
    ("Foreign Nationals",   r'foreign national|illegal.*enter|azerbaijani|russian.*citizen|pakistani.*national|dominican.*national|cuban.*national|transnational'),
    ("Organized Crime",     r'organized crime|criminal organization|transnational.*criminal|racketeering|criminal enterprise|criminal network'),
    ("COVID-19",            r'covid'),
    ("AI",                  r'artificial intelligence|\bai\b.*fraud|\bai\b.*detect|machine learning|algorithm'),
    ("Tax Evasion",         r'tax evas|tax fraud|irs.*fraud'),
    ("Cybersecurity",       r'cyber.*fraud|cyber.*security|data breach.*fraud'),
    ("Research Fraud",      r'clinical trial.*fraud|research.*fraud'),
    ("Off-Label",           r'off.label'),
    ("Housing Fraud",       r'housing.*fraud|housing.*stabilization.*fraud'),

    # --- Enforcement outcome tags ---
    ("Sentencing",          r'\bsentenced\b|\bsentencing\b'),
    ("Guilty Plea",         r'pleads guilty|plead guilty|guilty plea|admits.*guilt'),
    ("Indictment",          r'\bindicted\b|\bindictment\b|\bcharged\b'),
    ("Civil Action",        r'civil.*settlement|civil.*action|consent.*judgment|consent.*decree|agrees to pay|resolve.*allegation'),

    # --- Structural/policy tags ---
    ("Congressional",       r'congress|committee.*hearing|testimony|oversight.*committee|senate.*report|house.*report|subcommittee'),
    ("Legislation",         r'signed into law|enacted|passes bill|bill signed|executive order'),
    ("CRUSH",               r'\bcrush\b'),
    ("DOGE",                r'\bdoge\b'),
    ("Program Integrity",   r'program integrity|improper payment|audit.*medicaid|audit.*medicare|inspector general|oig.*report|semiannual'),
    ("Strike Force",        r'strike force|task force'),
    ("MFCU",                r'\bmfcu\b|medicaid fraud control unit'),

    # --- Location-specific ---
    ("Native American",     r'native american|indigenous|tribal.*fraud|indian health'),
    ("Prenatal Care",       r'prenatal|maternal.*fraud'),
    ("Elder Fraud",         r'elder.*fraud|elderly.*fraud|senior.*fraud'),
    ("Assisted Living",     r'assisted living'),
]

# Normalize existing inconsistent tags
NORMALIZE = {
    "Kickback": "Kickbacks",
    "Anti-Kickback": "Kickbacks",
    "Anti-Kickback Statute Violation": "Kickbacks",
    "Telemedicine": "Telehealth",
    "Laboratory Fraud": "Lab Fraud",
    "COVID-19 Testing": "COVID-19",
    "Civil Settlement": "Civil Action",
    "State Enforcement": "State Agency",
    "Grand Larceny": "False Claims",
    "Health Care Fraud": "False Claims",
    "Wire Fraud": "False Claims",
    "Identity Fraud": "Identity Theft",
    "False Billing": "False Claims",
    "False Statements": "False Claims",
    "Congressional Investigation": "Congressional",
    "Criminal Enforcement": "Sentencing",
    "Pill Mill": "Opioids",
    "Drug Diversion": "Opioids",
    "DME": "DME Fraud",
    "Medi-Cal": "Medicaid",
    "Stark Law": "Kickbacks",
    "Consent Judgment": "Civil Action",
    "California": None,  # remove non-tag geographic labels
    "Minnesota": None,
    "State Agency": None,
    "Policy": None,
    "Policy Impact": None,
    "State Investigations": None,
    "Annual Report": "Program Integrity",
    "Audit": "Program Integrity",
    "Digital Health": "Telehealth",
    "Workers Compensation": None,
    "Pharmaceutical": "Pharmacy Fraud",
}

# Tags to remove entirely (not useful as tags)
REMOVE_TAGS = {None}

updated = 0
tags_added = 0

for action in data["actions"]:
    text = f"{action.get('title', '')} {action.get('description', '')}".lower()
    tags = action.get("tags", [])
    original_len = len(tags)

    # Normalize existing tags (None means remove)
    tags = [NORMALIZE.get(t, t) for t in tags]
    tags = [t for t in tags if t is not None]

    # Apply rules
    for tag_name, pattern in TAG_RULES:
        if tag_name not in tags and re.search(pattern, text, re.IGNORECASE):
            tags.append(tag_name)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    if deduped != action.get("tags", []):
        action["tags"] = deduped
        new_tags = len(deduped) - original_len
        if new_tags > 0:
            tags_added += new_tags
        updated += 1

with open("data/actions.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Verify
no_tags = sum(1 for a in data["actions"] if not a.get("tags"))
print(f"Updated {updated} entries, added {tags_added} tags")
print(f"Entries with no tags: {no_tags}")
print(f"Total actions: {len(data['actions'])}")
