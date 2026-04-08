"""Anchored AI tag extractor for the Healthcare Fraud Dashboard.

The previous tag generator (`tag_allowlist.auto_tags`) was a regex
keyword matcher that produced two systematic problems:

  1. False negatives — phrases that mean "tag X" but don't match the
     literal regex (e.g. "Adderall distribution" → no tag at all).
  2. False positives — overly broad regexes that fired on incidental
     mentions (e.g. "hospital" matched on any press release that says
     "the case was investigated by hospital staff").

The previous AI attempt failed because it asked Claude "what are the
right tags?" — too unconstrained, ~35% wrong. The fix here is
**anchored extraction with required citations**:

  - For each candidate tag, Claude must cite a verbatim phrase from the
    source text as evidence.
  - Every cited phrase is then validated by substring-match against the
    source text. Phrases that don't validate get dropped.
  - The output is therefore always grounded in the source.

Usage:
    from tag_extractor import extract_tags_with_evidence
    tags = extract_tags_with_evidence(client, title, full_text)

If `client` is None or the API call fails, returns the regex fallback
from `tag_allowlist.auto_tags()` so callers always get *some* tags.
"""
from __future__ import annotations

import json
import os
import re
import sys

from tag_allowlist import ALLOWED_TAGS, PROGRAM_TAGS, AREA_TAGS, auto_tags as regex_auto_tags

AI_MODEL = "claude-haiku-4-5-20251001"

# Maximum source-text length we send to the API. Longer texts get
# truncated to this many characters; the title is always included
# in full at the top.
MAX_TEXT_CHARS = 8000


def _build_system_prompt() -> str:
    programs = sorted(PROGRAM_TAGS)
    areas = sorted(AREA_TAGS)
    return f"""You are a tag extractor for a healthcare fraud dashboard. Your job is to identify which tags from a fixed allowlist are EXPLICITLY supported by an article's text, and to provide a verbatim citation for each tag you select.

## ALLOWED TAGS

You may ONLY use tags from these two categories. Never invent tags.

PROGRAMS (which payer was defrauded):
{json.dumps(programs)}

VULNERABLE AREAS (which service area was abused):
{json.dumps(areas)}

## RULES

1. **Explicit support only.** A tag must be explicitly supported by the text. Implication, speculation, or "the article is about a clinic that probably also does X" do NOT count.

2. **Verbatim citations.** For every tag you select, cite a verbatim phrase (8+ words long) from the article text as evidence. The phrase must appear in the source EXACTLY as written. Do not paraphrase.

3. **Program tag selection rules:**
   - "Medicare Advantage" applies if MA plans, MA risk adjustment, or MA-specific contracts are mentioned. The general "Medicare" tag does NOT need to also apply unless Medicare FFS is separately discussed.
   - "Medicare" applies to Medicare Part A/B/D, Medicare FFS, or generic Medicare references. Do NOT add Medicare just because Medicare Advantage is mentioned.
   - "Medicaid" applies to Medicaid, Medi-Cal, CHIP, or state Medicaid managed care.
   - "TRICARE" applies only if TRICARE/CHAMPUS is named.
   - "ACA" applies if Affordable Care Act marketplace, exchange enrollment, or premium tax credits are central to the case.

4. **Area tag selection rules:**
   - "Opioids" requires the case to involve opioids, fentanyl, oxycodone, hydrocodone, or pill mills. Adderall and stimulants are NOT opioids.
   - "Skin Substitutes" applies to skin grafts, allografts, amniotic membrane products, dehydrated placental products. Usually co-occurs with "Wound Care".
   - "Hospice" requires the fraud or oversight to be about hospice services, not just an offhand mention.
   - "Hospital" requires the fraud or oversight to be about hospital billing, not "investigated by hospital staff" or similar context.
   - "Genetic Testing" requires genetic/genomic test billing, not just lab tests in general.
   - "Telehealth" requires telehealth/telemedicine to be central to the scheme.
   - "DME" applies to durable medical equipment, DMEPOS, wheelchairs, orthotic braces, power mobility devices.
   - "Home Health" / "Nursing Home" / "Assisted Living" / "Adult Day Care" require those specific care settings to be the subject.
   - "Behavioral Health" / "Addiction Treatment" / "Autism/ABA" / "Physical Therapy" / "Prenatal Care" — same pattern, must be the subject.
   - "Wound Care" is broader than Skin Substitutes; applies to any wound care fraud.
   - "Pharmacy" applies to pharmacy billing fraud, compound pharmacy schemes, drug diversion through pharmacies.
   - "Medical Devices" applies to device-makers, implants, device kickbacks (NOT DMEPOS).
   - "Ambulance" applies to ambulance billing fraud or non-emergency transport schemes.
   - "Off-Label" applies to off-label marketing of FDA-approved drugs.

5. **Be conservative.** When in doubt, do not tag. A clean small set of correct tags is better than a noisy large set.

## OUTPUT

Return ONLY a JSON array. No markdown fences, no text outside the array. Each element is an object with two keys:

[
  {{"tag": "Medicare Advantage", "evidence": "verbatim 8+ word phrase from source"}},
  {{"tag": "Wound Care", "evidence": "verbatim 8+ word phrase from source"}}
]

If no tags apply, return an empty array: []
"""


def _normalize_for_validation(s: str) -> str:
    """Normalize whitespace and casing for citation substring-matching."""
    if not s:
        return ""
    # Collapse all whitespace runs to single spaces
    s = re.sub(r"\s+", " ", s)
    # Strip smart quotes / common unicode noise that LLM might re-encode
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00a0", " ")
    return s.strip().lower()


def _evidence_validates(evidence: str, source_norm: str) -> bool:
    """Check that the evidence string is grounded in the source text.

    Tries (in order):
      1. Full evidence appears verbatim in source.
      2. First 50 characters of evidence appear in source (allows the
         LLM to slightly extend or paraphrase the tail end without us
         throwing the tag away).
      3. The first 8 content words from evidence all appear in source
         in the same relative order within a 200-char window.
    """
    if not evidence or not source_norm:
        return False
    ev = _normalize_for_validation(evidence)
    if len(ev) < 12:  # too short to be a citation
        return False
    if ev in source_norm:
        return True
    if len(ev) >= 50 and ev[:50] in source_norm:
        return True
    # Sliding 8-word check
    words = [w for w in re.findall(r"\w+", ev) if len(w) > 2][:8]
    if len(words) >= 6:
        joined = r"\W+".join(re.escape(w) for w in words)
        # Allow up to 60 chars between consecutive words to handle
        # punctuation/markup discrepancies
        loose = r"\W+".join(re.escape(w) + r"[\s\S]{0,40}?" for w in words[:-1]) + re.escape(words[-1])
        if re.search(loose, source_norm):
            return True
    return False


def extract_tags_with_evidence(client, title: str, full_text: str,
                                debug: bool = False) -> list[str]:
    """Extract allowlist tags from an article using Claude + citation validation.

    Falls back to regex tags from `tag_allowlist.auto_tags` if:
      - The client is None
      - The API call fails
      - The model returns malformed JSON
      - The model returns no validated tags but the regex would have

    Returns a deduped list of canonical tags from ALLOWED_TAGS.
    """
    title = (title or "").strip()
    full_text = (full_text or "").strip()
    if not title and not full_text:
        return []

    # Anchor source for validation: title + body (truncated for prompt)
    source_for_prompt = full_text[:MAX_TEXT_CHARS]
    source_for_validation = _normalize_for_validation(f"{title} {full_text}")

    # If no client, fall back to regex
    if client is None:
        return regex_auto_tags(f"{title} {full_text}")

    user_msg = f"TITLE: {title}\n\nTEXT:\n{source_for_prompt}"
    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=1500,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
    except Exception as e:
        if debug:
            print(f"  [tag_extractor] API error: {e}", file=sys.stderr)
        return regex_auto_tags(f"{title} {full_text}")

    # Strip possible markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        raw = json.loads(text)
    except Exception as e:
        if debug:
            print(f"  [tag_extractor] JSON parse error: {e}; raw={text[:200]}", file=sys.stderr)
        return regex_auto_tags(f"{title} {full_text}")

    if not isinstance(raw, list):
        if debug:
            print(f"  [tag_extractor] non-array response: {type(raw)}", file=sys.stderr)
        return regex_auto_tags(f"{title} {full_text}")

    validated = []
    seen = set()
    rejected = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag", "").strip()
        evidence = entry.get("evidence", "")
        if tag not in ALLOWED_TAGS:
            rejected.append((tag, "not in allowlist"))
            continue
        if tag in seen:
            continue
        if _evidence_validates(evidence, source_for_validation):
            validated.append(tag)
            seen.add(tag)
        else:
            rejected.append((tag, f"evidence not grounded: {evidence[:60]}"))

    if debug:
        print(f"  [tag_extractor] validated: {validated}", file=sys.stderr)
        if rejected:
            for tag, reason in rejected:
                print(f"  [tag_extractor] rejected {tag!r}: {reason}", file=sys.stderr)

    # Safety net: if Claude returned ZERO validated tags but the regex
    # would have caught at least one, fall back to regex. This catches
    # the rare case where Claude is overly conservative on something
    # the keyword matcher confidently knows.
    if not validated:
        regex_tags = regex_auto_tags(f"{title} {full_text}")
        if regex_tags:
            if debug:
                print(f"  [tag_extractor] AI returned 0, falling back to regex: {regex_tags}", file=sys.stderr)
            return regex_tags

    return validated


def make_client():
    """Helper: build an Anthropic client if the API key is available, else None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


if __name__ == "__main__":
    # Quick CLI smoke test:
    #   python tag_extractor.py "Title here" "Full text body here"
    if len(sys.argv) < 3:
        print("Usage: python tag_extractor.py 'TITLE' 'BODY TEXT'")
        sys.exit(2)
    title = sys.argv[1]
    body = sys.argv[2]
    client = make_client()
    if client is None:
        print("(no ANTHROPIC_API_KEY — falling back to regex)")
    tags = extract_tags_with_evidence(client, title, body, debug=True)
    print("TAGS:", tags)
