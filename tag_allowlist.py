"""Canonical tag allowlist for the Healthcare Fraud Dashboard.

All scripts that write tags to data/*.json MUST import from this module
and pass tags through `filter_tags()` before saving. Items may only carry
two categories of tags:

  1. PROGRAMS  — which payer / program got defrauded
  2. AREAS     — which vulnerable service area was abused

Anything else (status like "Convicted", fraud method like "Kickbacks",
committee names, company names, etc.) is removed.

To add a new tag, append it to the appropriate set below. The new tag
must clearly belong to one of the two categories.
"""

PROGRAM_TAGS = frozenset({
    "Medicare",
    "Medicaid",
    "Medicare Advantage",
    "TRICARE",
    "ACA",
})

AREA_TAGS = frozenset({
    "DME",
    "Hospice",
    "Pharmacy",
    "Genetic Testing",
    "Telehealth",
    "Home Health",
    "Nursing Home",
    "Medical Devices",
    "Autism/ABA",
    "Wound Care",
    "Adult Day Care",
    "Behavioral Health",
    "Prenatal Care",
    "Skin Substitutes",
    "Physical Therapy",
    "Assisted Living",
    "Ambulance",
    "Hospital",
    "Addiction Treatment",
    "Opioids",
    "Off-Label",
})

ALLOWED_TAGS = PROGRAM_TAGS | AREA_TAGS


def filter_tags(tags):
    """Return a list of tags filtered to the allowlist, preserving order
    and removing duplicates. Accepts None / non-list input safely.
    """
    if not tags:
        return []
    seen = set()
    result = []
    for t in tags:
        if not isinstance(t, str):
            continue
        if t in ALLOWED_TAGS and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# Regex patterns mapped to allowlist tags. Use only canonical tag names.
# Used by scrapers to auto-tag from text. Each pattern is case-insensitive.
TAG_PATTERNS = [
    # Programs
    (r"\bmedicare advantage\b|\brisk adjust", "Medicare Advantage"),
    (r"\bmedicare\b", "Medicare"),
    (r"\bmedicaid\b|\bmedi-cal\b", "Medicaid"),
    (r"\btricare\b", "TRICARE"),
    (r"affordable care act|\baca\b|obamacare", "ACA"),
    # Areas
    (r"\bdurable medical|\bdme\b|\bdmepos\b|wheelchair|orthotic brace|power mobility", "DME"),
    (r"\bhospice\b", "Hospice"),
    (r"\bpharmac", "Pharmacy"),
    (r"genetic test", "Genetic Testing"),
    (r"telehealth|telemedic", "Telehealth"),
    (r"\bhome health\b", "Home Health"),
    (r"nursing home|skilled nursing|long.term care facility", "Nursing Home"),
    (r"medical device|implant.*fraud", "Medical Devices"),
    (r"autism|\baba\b therapy|applied behavior", "Autism/ABA"),
    (r"wound care|wound.*graft", "Wound Care"),
    (r"adult day care|daycare.*fraud", "Adult Day Care"),
    (r"behavioral health|mental health.*fraud|psychiatric.*fraud|counseling.*fraud", "Behavioral Health"),
    (r"prenatal care|prenatal.*coordination", "Prenatal Care"),
    (r"skin substitute|allograft", "Skin Substitutes"),
    (r"physical therapy", "Physical Therapy"),
    (r"assisted living", "Assisted Living"),
    (r"ambulance", "Ambulance"),
    (r"hospital.*fraud|hospital.*scheme", "Hospital"),
    (r"addiction|sober living|substance abuse.*treatment|rehab.*fraud|suboxone|methadone.*fraud", "Addiction Treatment"),
    (r"opioid|fentanyl|oxycodone|controlled substance|pill mill|hydrocodone", "Opioids"),
    (r"off-label", "Off-Label"),
]


def auto_tags(text):
    """Generate allowlist tags from a text blob via regex matching.

    Always returns tags from `ALLOWED_TAGS` only — safe to use as the
    sole source of tags in scrapers.
    """
    import re
    if not text:
        return []
    lower = text.lower()
    out = []
    seen = set()
    for pattern, tag in TAG_PATTERNS:
        if tag in seen:
            continue
        if re.search(pattern, lower):
            out.append(tag)
            seen.add(tag)
    return out
