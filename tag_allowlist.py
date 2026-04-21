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
    "Medicaid Managed Care",
    "TRICARE",
    "ACA",
})

AREA_TAGS = frozenset({
    "DME",
    "Hospice",
    "Pharmacy",
    "Genetic Testing",
    "Lab Testing",
    "Telehealth",
    "Home Health",
    "Nursing Home",
    "Medical Devices",
    "Autism/ABA",
    "Wound Care",
    "Adult Day Care",
    "Mental Health",
    "Prenatal Care",
    "Skin Substitutes",
    "Personal Care",
    "Physical Therapy",
    "Assisted Living",
    "Medical Transportation",
    "Addiction Treatment",
    "Opioids",
    "Drug Pricing",
})

ALLOWED_TAGS = PROGRAM_TAGS | AREA_TAGS


# Co-apply rules: presence of KEY implies presence of VALUE.
#
# Strict interpretation: only include co-applies where the child is an
# unambiguous SUBprogram of the parent. Medicare Advantage IS Medicare
# (a specific Medicare program variant); Medicaid Managed Care IS
# Medicaid.
#
# Service/product categories like Hospice, DME, Skin Substitutes are
# NOT strict subprograms — they can be covered under Medicare OR
# Medicaid (Medicaid covers hospice for dual-eligibles; state Medicaid
# DME exists; TRICARE covers DME too). Tagging Hospice doesn't imply
# the case is exclusively Medicare. Users who want Medicare must have
# it explicitly in the body text or manually added.
CO_APPLY = {
    "Medicare Advantage":    "Medicare",
    "Medicaid Managed Care": "Medicaid",
}


def apply_co_apply(tags):
    """Given a list/set of tags, add parent tags per CO_APPLY rules.
    Returns a new list preserving order, with parents inserted after
    their first triggering child. Idempotent.
    """
    if not tags:
        return []
    result = []
    seen = set()
    for t in tags:
        if t in seen: continue
        seen.add(t); result.append(t)
        parent = CO_APPLY.get(t)
        if parent and parent not in seen:
            seen.add(parent); result.append(parent)
    return result


# ---------------------------------------------------------------------------
# DOJ boilerplate stripping
# ---------------------------------------------------------------------------
# DOJ press releases reliably end with boilerplate paragraphs describing the
# Medicare Fraud Strike Force, ACA enforcement authority, and multi-agency
# partnerships. These paragraphs enumerate programs and fraud types
# generically ("including Medicare, Medicaid, and the Affordable Care Act")
# and cause false-positive tags when the press release is about something
# else entirely (a pure Medicare DME scheme gets tagged ACA because the
# boilerplate mentions ACA once).
#
# `strip_boilerplate(text)` blanks out these known-boilerplate passages so
# tag detection only sees substantive case content. Use before running
# `auto_tags` on body text.
#
# Patterns are intentionally specific — they match only well-established
# DOJ boilerplate phrases so legitimate mentions are never removed.

import re as _re

_BOILERPLATE_PATTERNS = [
    # Strike Force operational footer
    _re.compile(
        r"(?:The\s+)?(?:Health\s+Care\s+Fraud|Medicare\s+Fraud)\s+"
        r"(?:Unit'?s?\s+)?Strike\s+Force\s+(?:operates|operated)\s+"
        r"(?:in\s+)?\d+\s+(?:strike\s+force\s+)?(?:districts|teams)[^.]*\.",
        _re.IGNORECASE,
    ),
    # Strike Force "since inception" historical record
    _re.compile(
        r"(?:Since\s+its?\s+inception\s+in\s+\w+\s+\d{4}[^.]*?)?"
        r"(?:have\s+)?charged\s+more\s+than\s+[\d,]+\s+defendants\s+"
        r"who\s+(?:have\s+)?(?:collectively\s+)?billed[^.]*?"
        r"(?:billion|million)[^.]*\.",
        _re.IGNORECASE,
    ),
    # ACA enforcement authority paragraph(s) — the main ACA false-positive source
    _re.compile(
        r"The\s+Affordable\s+Care\s+Act\s+"
        r"(?:significantly\s+)?(?:increased|gave|expanded|provided)\s+"
        r"(?:HHS(?:'s)?\s+|authorities\s+|the\s+federal\s+government\s+)?"
        r"(?:ability|authority|tools?|authorities)[^.]*\.",
        _re.IGNORECASE,
    ),
    # CMS suspension-authority + ACA
    _re.compile(
        r"(?:The\s+)?(?:HHS\s+)?Centers\s+for\s+Medicare\s+(?:&|and)\s+"
        r"Medicaid\s+Services[^.]*?suspension\s+authority[^.]*?"
        r"Affordable\s+Care\s+Act[^.]*\.",
        _re.IGNORECASE,
    ),
    # Generic "including Medicare, Medicaid, and the Affordable Care Act" enumeration
    _re.compile(
        r"\b(?:including|such\s+as)\s+Medicare,?\s+Medicaid,?\s+"
        r"(?:and\s+(?:the\s+)?Affordable\s+Care\s+Act|"
        r"(?:TRICARE|the\s+Indian\s+Health\s+Service),?\s+and\s+"
        r"(?:the\s+)?Affordable\s+Care\s+Act)",
        _re.IGNORECASE,
    ),
    # Health Care Fraud Unit leadership paragraph
    _re.compile(
        r"The\s+Health\s+Care\s+Fraud\s+Unit\s+leads[^.]*\.",
        _re.IGNORECASE,
    ),
    # "indictment is merely an allegation" standard disclaimer
    _re.compile(
        r"An?\s+(?:indictment|information|complaint)\s+is\s+merely\s+"
        r"an?\s+allegation[^.]*presumed\s+innocent[^.]*\.",
        _re.IGNORECASE,
    ),
    # CMS agency name — "Centers for Medicare & Medicaid Services" and
    # "Medicare and Medicaid Services" variants. These are pure agency-name
    # mentions and should NOT count as Medicare/Medicaid program tags.
    # Masked here so tag regex only sees substantive program mentions.
    _re.compile(
        r"(?:Centers\s+for\s+)?Medicare\s+(?:&|and)\s+Medicaid\s+Services"
        r"(?:'s)?",
        _re.IGNORECASE,
    ),
]


def strip_boilerplate(text):
    """Blank out known DOJ boilerplate passages in text.

    Replaces each matched passage with spaces of equal length so that
    offsets into the text don't shift (callers that care about position
    can still reason about the document). Use before running `auto_tags`
    on body text to suppress boilerplate-driven false positives like
    ACA being tagged on a pure Medicare DME case because the standard
    Strike Force paragraph enumerates it.

    Returns the cleaned text. If input is falsy, returns "".
    """
    if not text:
        return ""
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(lambda m: " " * len(m.group(0)), text)
    return text


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
#
# **STRICT EXTRACTION RULE:** Each pattern matches only TERMS THAT LITERALLY
# APPEAR IN SOURCE TEXT. No inferential triggers, no industry-context guessing.
# If a tag can't be matched by a literal keyword or a recognized synonym,
# it doesn't apply.
#
# Examples of what we DON'T do:
#   - "Risk adjustment" alone doesn't imply Medicare Advantage (could be
#     MA, could be ACA, could be ERISA plans — ambiguous).
#   - "MCO" alone doesn't imply Medicaid Managed Care (could be commercial).
#   - Company names (Centene, Molina, UnitedHealth) aren't used as proxies
#     for a program — the source text must literally mention the program.
TAG_PATTERNS = [
    # ---------- Programs ----------
    # Medicare Advantage: explicit phrase or "MA plan/enrollee/contract" usage.
    (r"\bmedicare\s+advantage\b|\bmedicare\s+part\s+c\b|\bma\s+plan\b|\b(ma|medicare\s+advantage)\s+enrollees?\b", "Medicare Advantage"),
    # Medicare: literal word match, but the boilerplate agency phrase "centers for medicare & medicaid services" and variants must not count alone.
    (r"\bmedicare\b(?!\s*&\s*medicaid\s+services\b)", "Medicare"),
    # Medicaid: literal word match, excluding the boilerplate agency phrase.
    (r"\bmedicaid\b(?!\s+services\b(?:\s|\.|,|$))|\bmedi-cal\b", "Medicaid"),
    # Medicaid Managed Care: require explicit phrase. MCO/managed-care-organization
    # alone is ambiguous (commercial MCOs exist) so require a nearby 'medicaid'.
    (r"medicaid\s+managed[-\s]care|medicaid\s+mco\b|managed[-\s]care.{0,30}medicaid|"
     r"medicaid.{0,30}managed[-\s]care\s+plan|"
     # Medicaid + Managed Care Organization(s)/MCOs co-mention (widened window)
     r"medicaid.{0,150}managed[-\s]care\s+organization|"
     r"managed[-\s]care\s+organization.{0,150}medicaid|"
     # Capitation payments to MCOs — the characteristic Medicaid MCO payment
     r"capitation\s+payments?\s+to\s+managed[-\s]care",
     "Medicaid Managed Care"),
    (r"\btricare\b|\bchampus\b", "TRICARE"),
    # ACA: require an explicit ACA phrase. "ACA" as a bare acronym can match
    # non-healthcare contexts; keep the 3-letter form gated to clear contexts.
    (r"affordable\s+care\s+act|obamacare|aca\s+marketplace|aca\s+exchange|"
     r"aca\s+enrollment|aca\s+subsid|aca\s+premium\s+tax\s+credit|"
     r"premium\s+tax\s+credit", "ACA"),

    # ---------- Areas ----------
    (r"\bdurable\s+medical\s+equipment\b|\bdmepos\b|\bdme\s+(supplier|fraud|scheme|provider|billing)\b|"
     r"power\s+(wheelchair|mobility)|orthotic\s+brace", "DME"),
    (r"\bhospice\b", "Hospice"),
    # Pharmacy: require explicit pharmacy word, not just "pharmaceutical"
    # (which pulls in any drug-manufacturer FCA case without pharmacy billing).
    (r"\bpharmac(y|ies|ist)\b|\bcompound\s+pharmac|pill\s+mill\s+pharmacy", "Pharmacy"),
    # Genetic Testing — specific before Lab Testing
    (r"\bgenetic\s+test(ing|s)?\b|\bcgx\b|\bpgx\b|pharmacogenom|"
     r"cancer\s+genomic|hereditary\s+cancer\s+(test|panel)", "Genetic Testing"),
    # Lab Testing — require explicit lab/laboratory vocab or specific test fraud
    (r"\b(clinical\s+)?laborator(y|ies)\b|\btoxicolog|"
     r"\burine\s+drug\s+test|blood\s+test\s+fraud|"
     r"\bcovid(-19)?\s+test(ing)?\s+(scheme|fraud|billing)|"
     r"pathology\s+lab|unnecessary\s+lab\s+test", "Lab Testing"),
    (r"\btelehealth\b|\btelemedicin(e|al)\b", "Telehealth"),
    (r"\bhome\s+health\b(?!\s+aides?\s+who\s+|\s+agency\s+staff)", "Home Health"),
    (r"\bnursing\s+homes?\b|\bskilled\s+nursing\b|\blong[-\s]term\s+care\s+facility\b", "Nursing Home"),
    # Medical Devices: require explicit device word, not just "medical"
    (r"\bmedical\s+device(s)?\b|\bdevice\s+(manufactur|kickback)", "Medical Devices"),
    # Autism/ABA: explicit phrase required. "ABA" as bare acronym shouldn't count.
    (r"\bautism\b|\bapplied\s+behavior\s+analysis\b|\baba\s+therapy\b|\baba\s+services\b", "Autism/ABA"),
    (r"\bwound\s+care\b|wound\s+graft|skin\s+graft\s+fraud", "Wound Care"),
    (r"\badult\s+day\s+care\b|\badult\s+day\s+services?\b|\badult\s+day\s+health\b", "Adult Day Care"),
    # Mental Health (renamed from Behavioral Health): require the service,
    # clinic, or scheme type — not just a defendant's profession. A
    # "psychologist was arrested" mention doesn't mean the case is ABOUT
    # mental health services; we need the fraud itself to be
    # mental-health-focused.
    (r"\bmental\s+health\s+(clinic|services|provider|billing|fraud|program|practice|treatment)\b|"
     r"\bpsychiatr(y|ic)\s+(clinic|services|practice|billing|fraud)\b|"
     r"\bpsychotherap(y|ist)\b|"
     r"\bcounseling\s+(services|fraud|clinic|practice)\b|"
     r"\bmental\s+illness\s+treatment\b|"
     r"\bbehavioral\s+health\s+(clinic|services|practice|billing|provider)\b",
     "Mental Health"),
    (r"\bprenatal\s+care\b|prenatal\s+coordination", "Prenatal Care"),
    (r"\bskin\s+substitute|allograft\b|amniotic\s+membrane\s+product", "Skin Substitutes"),
    (r"\bpersonal\s+care\s+(attendant|assistant|service|program|aide)\b|"
     r"\bpca\s+(fraud|service|program|scheme)\b|"
     r"\bpcs\s+(service|program|fraud)\b|"
     r"home\s+care\s+attendant|"
     r"consumer[-\s]directed\s+personal|\bcdpap\b", "Personal Care"),
    (r"\bphysical\s+therap(y|ist)\b", "Physical Therapy"),
    (r"\bassisted\s+living\b", "Assisted Living"),
    # Covers both ambulance fraud (Medicare) and NEMT fraud (Medicaid).
    # Regulators and DOJ typically talk about "medical transportation"
    # as the umbrella term spanning both.
    (r"\bambulance\b|non[-\s]emergency\s+(medical\s+)?transport|"
     r"\bNEMT\b|"
     r"\bmedical\s+transportation\b", "Medical Transportation"),
    (r"\baddiction\s+(treatment|recovery)\b|\bsober\s+living\b|"
     r"\bsubstance\s+abuse\s+treatment\b|\brehab(ilitation)?\s+(fraud|scheme|clinic)\b|"
     r"\bsuboxone\b|\bmethadone\s+(fraud|clinic)\b|"
     r"\bopioid\s+treatment\s+program\b", "Addiction Treatment"),
    (r"\bopioid(s)?\b|\bfentanyl\b|\boxycodone\b|\bhydrocodone\b|"
     r"\bcontrolled\s+substance\b|\bpill\s+mill\b", "Opioids"),
    # Drug Pricing: manufacturer/PBM/state-rebate/340B vector. Distinct
    # from Pharmacy (dispensing) and Opioids (controlled substances).
    # Captures: drug rebates, 340B program, PBM spread/rebate fraud,
    # inflated average wholesale price (AWP), physician-administered
    # drug rebate programs, Medicaid Drug Rebate Program.
    (r"\bdrug\s+rebate(s)?\b|\bmedicaid\s+drug\s+rebate\b|"
     r"\b340b\b|\bpbm\s+(rebate|spread|pricing|fraud)\b|"
     r"\bpharmacy\s+benefit\s+manager|"
     r"\bpharmaceutical\s+(pricing|price\s+fix)|\bdrug\s+pricing\b|"
     r"\baverage\s+wholesale\s+price\b|\bawp\s+fraud\b|"
     r"\bphysician[-\s]administered\s+drug|"
     r"\bbest\s+price\s+(reporting|fraud|rule)|"
     # Medicare Part B drug payment / biosimilar / ASP-based pricing
     r"\bbiosimilar(s)?\b|"
     r"\bpart\s+b\s+(drug|payment|biologic)|"
     r"\baverage\s+sales\s+price\b|\bASP\s+(payment|pricing|data)|"
     r"\bmedicare\s+(drug|biologic)\s+pric|"
     r"\bnoncovered\s+version",
     "Drug Pricing"),
]


def auto_tags(text):
    """Generate allowlist tags from a text blob via regex matching.

    Always returns tags from `ALLOWED_TAGS` only — safe to use as the
    sole source of tags in scrapers. Strict: literal term matches only.
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
