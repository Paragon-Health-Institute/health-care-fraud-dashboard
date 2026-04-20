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

from tag_allowlist import (
    ALLOWED_TAGS,
    PROGRAM_TAGS,
    AREA_TAGS,
    auto_tags as regex_auto_tags,
    strip_boilerplate,
    apply_co_apply,
)

AI_MODEL = "claude-haiku-4-5-20251001"

# Maximum source-text length we send to the API. Longer texts get
# truncated to this many characters; the title is always included
# in full at the top.
MAX_TEXT_CHARS = 8000


def _build_system_prompt() -> str:
    programs = sorted(PROGRAM_TAGS)
    areas = sorted(AREA_TAGS)
    return f"""You are a strict tag extractor for a healthcare fraud dashboard. Your job is to identify which tags from a fixed allowlist are DIRECTLY named in the article's text — never inferred — and to provide a verbatim citation for each tag you select.

## ALLOWED TAGS

You may ONLY use tags from these two categories. Never invent tags.

PROGRAMS (which payer was defrauded):
{json.dumps(programs)}

VULNERABLE AREAS (which service area was abused):
{json.dumps(areas)}

## CORE PRINCIPLE: EXTRACTION, NOT INFERENCE

Your job is to EXTRACT tags whose canonical term (or an obvious synonym) literally appears in the source text. You are NOT a subject-matter expert adding context. If the source does not literally mention a program or service area, do not tag it — even if you know the case is probably about that program.

Examples that should NOT get tagged:
- Title "Oversight of Fraud and Misuse of Federal Funds in Minnesota" — no specific program or area in the source. Return []. Do not infer Medicaid from your external knowledge of the MN fraud context.
- Title "The President's 2026 Health Care Agenda" with thin body — no specific program/area mentioned. Return []. Do not infer Medicare/Medicaid/ACA.
- A DOJ press release about an ACA enrollment fraud case that boilerplate-mentions "Centers for Medicare & Medicaid Services" as the investigating agency — extract ACA only, not Medicare or Medicaid (the boilerplate agency name is not evidence of program fraud).

## EXTRACTION RULES

1. **Title evidence is strongest.** If a tag's canonical term appears in the title, extract it. Prefer title-sourced tags.

2. **Body evidence must be non-boilerplate.** If a tag's canonical term appears only in the body, the context must show the item is ABOUT that program/area — not just a passing mention in investigator-citation lines, agency-name boilerplate, or unrelated background.

3. **Boilerplate exclusions — DO NOT count these as evidence:**
   - "Centers for Medicare & Medicaid Services" (the agency name) is not evidence for Medicare or Medicaid.
   - "HHS-OIG investigated the case" is not evidence for any specific program.
   - "Medicare, Medicaid, and TRICARE" appearing in a standard federal-health-programs enumeration is not evidence for all three; only tag the program(s) that are the subject.
   - Parenthetical name expansions, glossary-style references.

4. **Synonyms are allowed when they are CLEAR, not inferential:**
   - "Durable Medical Equipment" = DME. "DMEPOS" = DME.
   - "Medi-Cal" = Medicaid (California name).
   - "Obamacare" = ACA. "Affordable Care Act" = ACA. "Premium tax credit fraud" = ACA.
   - "Psychotherapy" / "Psychiatrist" / "Counselor" / "Mental health clinic" = Mental Health.
   - "Pill mill" = Opioids + Pharmacy (if a pharmacy operates it).
   - A company NAME ALONE (Centene, UnitedHealth, Molina) is NOT evidence for a program tag.

5. **Program tag rules:**
   - "Medicare Advantage" requires the phrase "Medicare Advantage", "MA plan", "Part C", or explicit MA-specific billing context. When it applies, also apply "Medicare".
   - "Medicare" applies when the word "Medicare" appears as the subject of the case (not just in CMS boilerplate). Also apply "Medicare" whenever you apply "Hospice", "DME", or "Skin Substitutes" — those are Medicare-specific service/product categories (Hospice is a Medicare Part A benefit; DMEPOS and Skin Substitutes are Medicare Part B).
   - "Medicaid Managed Care" requires the phrase "Medicaid Managed Care", "Medicaid MCO", or explicit context that a Medicaid managed care plan is the payer. When it applies, also apply "Medicaid".
   - "Medicaid" applies when the word "Medicaid" or "Medi-Cal" appears as the subject.
   - "TRICARE" requires the word TRICARE or CHAMPUS.
   - "ACA" requires Affordable Care Act / Obamacare / ACA marketplace / ACA subsid / premium tax credit. A bare acronym "ACA" with no context is insufficient.

6. **Area tag rules:**
   - "Opioids" requires opioids, fentanyl, oxycodone, hydrocodone, controlled substances, or pill mills. Adderall/stimulants are NOT opioids.
   - "Mental Health" requires psychiatry, psychology, psychotherapy, counseling, or "mental health" as the subject. Do NOT apply to autism or addiction cases (those have their own tags).
   - "Autism/ABA" requires autism, applied behavior analysis, or ABA therapy as the subject.
   - "Addiction Treatment" requires substance use / addiction / rehab / sober living / suboxone / methadone clinics as the subject.
   - "Hospital" requires hospital billing / hospital fraud / hospital-group defendant; NOT "investigated by hospital staff" or incidental hospital mentions.
   - "Genetic Testing" requires genetic/genomic testing — not just lab tests.
   - "Lab Testing" requires a laboratory, toxicology, pathology lab, COVID testing fraud, or urine drug testing as the subject.
   - "Wound Care" requires wound care / wound grafts. Often co-occurs with Skin Substitutes.
   - "Skin Substitutes" requires allograft / skin graft / amniotic membrane products.
   - "DME" requires DME / DMEPOS / power wheelchair / orthotic brace as the subject.
   - "Medical Devices" requires device maker / implant / device kickback (not DMEPOS).
   - "Telehealth" requires telehealth or telemedicine as the subject.
   - "Home Health" / "Nursing Home" / "Assisted Living" / "Adult Day Care" / "Personal Care" / "Hospice" / "Pharmacy" / "Physical Therapy" / "Prenatal Care" / "Ambulance" / "Off-Label" — require the specific care setting / service to be the subject (literal term or obvious synonym).

7. **Verbatim citations.** For every tag you select, cite a verbatim phrase (8+ words long) from the source as evidence. The phrase must contain the canonical term or its synonym and must appear in the source EXACTLY as written. Do not paraphrase. Do not cite headline boilerplate or agency-signature blocks.

8. **Hearings and announcements with thin bodies.** Many congressional hearing pages contain only the hearing title and logistics (witnesses, date, location). If nothing specific about a program or area is stated beyond the title, return only the tags literally in the title. If the title is generic ("Oversight of Fraud in Minnesota"), return [].

9. **Be conservative.** When in doubt, do not tag. An empty array is always valid. A clean small set of correct tags is strictly better than a large noisy set.

## OUTPUT

Return ONLY a JSON array. No markdown fences, no text outside the array. Each element is an object with two keys:

[
  {{"tag": "Medicare Advantage", "evidence": "verbatim 8+ word phrase from source containing the literal term"}},
  {{"tag": "Wound Care", "evidence": "verbatim 8+ word phrase from source containing the literal term"}}
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

    # Defense-in-depth: strip known DOJ boilerplate passages (Strike Force
    # paragraph, ACA enforcement-authority sentences, "including Medicare,
    # Medicaid, and the Affordable Care Act" enumerations, etc.) BEFORE
    # passing to the AI or falling back to regex. The system prompt
    # already instructs the model to ignore boilerplate, but pre-stripping
    # removes the failure mode entirely. Validation still happens against
    # the original text so evidence citations must match real source
    # content, but the model's INPUT is the cleaned version.
    clean_body = strip_boilerplate(full_text) if full_text else ""

    # Anchor source for validation: title + body (truncated for prompt).
    # Validation uses the ORIGINAL full text so cited phrases can match
    # anything the source actually says.
    source_for_prompt = clean_body[:MAX_TEXT_CHARS]
    source_for_validation = _normalize_for_validation(f"{title} {full_text}")

    # If no client, fall back to regex (use cleaned body so fallback
    # also benefits from boilerplate stripping).
    if client is None:
        return apply_co_apply(regex_auto_tags(f"{title} {clean_body}"))

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
        return apply_co_apply(regex_auto_tags(f"{title} {clean_body}"))

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
        return apply_co_apply(regex_auto_tags(f"{title} {clean_body}"))

    if not isinstance(raw, list):
        if debug:
            print(f"  [tag_extractor] non-array response: {type(raw)}", file=sys.stderr)
        return apply_co_apply(regex_auto_tags(f"{title} {clean_body}"))

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
        regex_tags = regex_auto_tags(f"{title} {clean_body}")
        if regex_tags:
            if debug:
                print(f"  [tag_extractor] AI returned 0, falling back to regex: {regex_tags}", file=sys.stderr)
            return apply_co_apply(regex_tags)

    # Apply co-apply rules to AI-validated tags (Hospice -> Medicare,
    # DME -> Medicare, Skin Substitutes -> Medicare, MA -> Medicare,
    # MCO -> Medicaid). The prompt instructs the model to do this,
    # but apply defensively in case the model misses a parent.
    return apply_co_apply(validated)


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
