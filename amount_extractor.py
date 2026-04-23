"""Anchored AI amount extractor for the Healthcare Fraud Dashboard.

Same pattern as tag_extractor: ask Claude to identify the fraud-size
amount in a press release AND require a verbatim citation the code
then validates. No citation = no amount (returns None). The claimed
dollar figure must also appear inside the cited sentence.

This prevents hallucination by design:
  - If Claude makes up a number, the citation won't match the source.
  - If Claude cites a real sentence but misstates the number, the
    number-in-citation check fails.
  - In either case, the extractor returns None and callers fall back
    to the regex extractor (which can't hallucinate, just mis-pick).

Usage:
    from amount_extractor import extract_amount_with_evidence
    result = extract_amount_with_evidence(client, title, body)
    # result is None or {"display": "$525,520", "numeric": 525520,
    #                    "evidence": "...", "kind": "stated_loss"}
"""
from __future__ import annotations

import json
import os
import re
import sys

AI_MODEL = "claude-haiku-4-5-20251001"
MAX_TEXT_CHARS = 12000


SYSTEM_PROMPT = """You are a strict dollar-amount extractor for a healthcare fraud dashboard. Your job is to identify the SINGLE best dollar figure representing the size of the fraud in a press release and cite the verbatim sentence containing that figure.

## WHAT COUNTS AS FRAUD SIZE

In order of preference (highest first):

1. **Stated loss / scheme size** — money the government actually paid, false claims submitted, or scheme total. Phrases like "Medicare paid $X," "submitted over $X in false claims," "caused a loss of $X to Medicare," "fraudulent scheme totaling $X."

2. **Civil FCA settlement or judgment** — e.g., "agreed to pay $X to resolve," "$X judgment," "pay $X million to settle False Claims Act allegations."

3. **Restitution ordered** — "ordered to pay $X in restitution."

4. **Forfeiture of proceeds of the fraud** — "forfeit $X traceable to the offense."

## WHAT TO EXCLUDE (return null instead)

- **Criminal penalty adjusted for ability to pay** (non-prosecution / deferred prosecution agreements where the penalty is negotiated based on the defendant's capacity, not the fraud size).
- **Statutory fines or maximum fines** — "faces a fine of up to $250,000," "maximum penalty of $500,000."
- **Unrelated dollar figures** — unrelated assets, loan values, the defendant's salary, total DOJ recoveries over a decade, national takedown aggregates, etc.
- **Boilerplate aggregate figures** — "Since January 2009, DOJ has recovered over $75 billion…" is boilerplate, never the case amount.

If the press release is only a charge/indictment announcement without any dollar figure naming the fraud size, return null.

## OUTPUT (strict)

Return ONLY a single JSON object, no markdown fences:

{"amount_numeric": 525520, "display": "$525,520", "kind": "stated_loss", "evidence": "the government presented evidence that Rossi is responsible for a total combined loss of $525,520.61"}

Where:
- `amount_numeric`: integer or float, dollars (e.g., 525520 for $525,520; 135600000 for $135.6 million; 80000000 for $80 million)
- `display`: short human-readable string ($525,520 / $1.43 Million / $135.6 Million / $80 Million). Use "Million" suffix for >= $1,000,000, "Billion" for >= $1,000,000,000, and a comma-formatted dollar figure otherwise.
- `kind`: one of "stated_loss", "settlement", "judgment", "restitution", "forfeiture"
- `evidence`: a verbatim phrase (12+ words) copied EXACTLY from the source text that contains the dollar figure. Must include the actual dollar amount as written in the source.

If no suitable fraud-size amount is named in the source, return exactly:

{"amount_numeric": null, "display": null, "kind": null, "evidence": null}

Do not guess. Do not infer. Do not paraphrase the evidence. If you're unsure, return null.
"""


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = (s.replace("\u2018", "'").replace("\u2019", "'")
           .replace("\u201c", '"').replace("\u201d", '"')
           .replace("\u2013", "-").replace("\u2014", "-")
           .replace("\u00a0", " "))
    return s.strip().lower()


def _evidence_in_source(evidence: str, source_norm: str) -> bool:
    """Citation must appear in source (allow small tail slop)."""
    ev = _normalize(evidence)
    if len(ev) < 12:
        return False
    if ev in source_norm:
        return True
    if len(ev) >= 60 and ev[:60] in source_norm:
        return True
    # Sliding 8-word loose match
    words = [w for w in re.findall(r"\w+", ev) if len(w) > 2][:10]
    if len(words) >= 6:
        loose = r"\W+".join(re.escape(w) + r"[\s\S]{0,40}?" for w in words[:-1]) + re.escape(words[-1])
        if re.search(loose, source_norm):
            return True
    return False


def _figure_in_evidence(numeric, evidence: str) -> bool:
    """The claimed dollar figure must literally appear inside the citation."""
    if numeric is None or not evidence:
        return False
    ev = evidence.lower()
    # Accept a variety of formats the release might use
    candidates = set()
    # Exact integer with commas
    candidates.add(f"${int(numeric):,}".lower())
    # No commas
    candidates.add(f"${int(numeric)}".lower())
    # Millions / billions rounded
    if numeric >= 1_000_000_000:
        b = numeric / 1_000_000_000
        for s in (f"${b:.0f} billion", f"${b:.1f} billion", f"${b:.2f} billion"):
            candidates.add(s.lower())
    if numeric >= 1_000_000:
        m = numeric / 1_000_000
        for s in (f"${m:.0f} million", f"${m:.1f} million", f"${m:.2f} million",
                  f"${m:.0f}m", f"${m:.1f}m"):
            candidates.add(s.lower())
    # Thousands
    if 1_000 <= numeric < 1_000_000:
        k = numeric / 1_000
        candidates.add(f"${k:.0f},000".lower())
        candidates.add(f"${k:.0f}k".lower())
    # Check any candidate appears in the evidence text
    for c in candidates:
        if c in ev:
            return True
    # Fallback: check the digits-only version (e.g. "525,520.61" -> "525520")
    digits = re.sub(r"[^\d]", "", str(int(numeric)))
    ev_digits = re.sub(r"[^\d]", "", ev)
    if digits and digits in ev_digits:
        return True
    return False


def extract_amount_with_evidence(client, title: str, body: str,
                                 debug: bool = False):
    """Extract fraud-size amount + validated citation, or None.

    Returns dict {numeric, display, kind, evidence} on success, or None
    if the AI abstains or validation fails. Never hallucinates: if the
    cited phrase is not in the source, or the claimed dollar figure is
    not inside the citation, this returns None.
    """
    title = (title or "").strip()
    body = (body or "").strip()
    if not body and not title:
        return None
    if client is None:
        if debug:
            print("  [amount_extractor] no client", file=sys.stderr)
        return None

    source_for_prompt = body[:MAX_TEXT_CHARS]
    source_norm = _normalize(f"{title} {body}")
    user_msg = f"TITLE: {title}\n\nTEXT:\n{source_for_prompt}"

    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
    except Exception as e:
        if debug:
            print(f"  [amount_extractor] API error: {e}", file=sys.stderr)
        return None

    # Strip markdown fences
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
            print(f"  [amount_extractor] JSON parse error: {e}; raw={text[:200]}", file=sys.stderr)
        return None

    if not isinstance(raw, dict):
        return None

    numeric = raw.get("amount_numeric")
    evidence = raw.get("evidence")
    kind = raw.get("kind")
    display = raw.get("display")

    # Abstention: AI explicitly returns nulls
    if numeric is None:
        if debug:
            print("  [amount_extractor] AI abstained (null amount)", file=sys.stderr)
        return None

    try:
        numeric = float(numeric)
    except (TypeError, ValueError):
        if debug:
            print(f"  [amount_extractor] non-numeric amount: {numeric!r}", file=sys.stderr)
        return None

    # Validate citation is in source
    if not _evidence_in_source(evidence or "", source_norm):
        if debug:
            print(f"  [amount_extractor] REJECT: citation not in source: {evidence!r}",
                  file=sys.stderr)
        return None

    # Validate claimed dollar figure appears in citation
    if not _figure_in_evidence(numeric, evidence or ""):
        if debug:
            print(f"  [amount_extractor] REJECT: amount {numeric} not in citation: {evidence!r}",
                  file=sys.stderr)
        return None

    return {
        "numeric": numeric,
        "display": display or f"${int(numeric):,}",
        "kind": kind,
        "evidence": evidence,
    }


def make_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


if __name__ == "__main__":
    # Quick CLI: python amount_extractor.py "TITLE" "BODY"
    if len(sys.argv) < 3:
        print("Usage: python amount_extractor.py 'TITLE' 'BODY TEXT'")
        sys.exit(2)
    title = sys.argv[1]
    body = sys.argv[2]
    client = make_client()
    if client is None:
        print("(no ANTHROPIC_API_KEY — cannot run)")
        sys.exit(1)
    result = extract_amount_with_evidence(client, title, body, debug=True)
    print("RESULT:", json.dumps(result, indent=2))
