"""Enrich auto-fetched actions using Claude API.

Reads actions.json, finds entries with auto_fetched=true that have empty tags,
sends them to Claude Haiku for classification, and writes back enriched data.
Also filters out irrelevant items.

Schema rules (see project memory and tag_allowlist.py):
  - The `description` field is NOT written. We never persist descriptions.
  - Tags are restricted to the canonical allowlist via filter_tags().
"""
import json, sys, os

from tag_allowlist import ALLOWED_TAGS, PROGRAM_TAGS, AREA_TAGS, filter_tags

def enrich_actions(data_path="data/actions.json"):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("enrich: ANTHROPIC_API_KEY not set, skipping enrichment")
        return 0

    try:
        import anthropic
    except ImportError:
        print("enrich: anthropic package not installed, skipping")
        return 0

    client = anthropic.Anthropic(api_key=api_key)

    with open(data_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # Find items needing enrichment: auto_fetched with empty tags
    to_enrich = [a for a in data["actions"] if a.get("auto_fetched") and not a.get("tags")]

    if not to_enrich:
        print("enrich: no items need enrichment")
        return 0

    print(f"enrich: {len(to_enrich)} item(s) to process")

    program_list = ", ".join(sorted(PROGRAM_TAGS))
    area_list = ", ".join(sorted(AREA_TAGS))

    SYSTEM_PROMPT = f"""You are a healthcare fraud enforcement data analyst. You will be given the title, source agency, and link of a news item or government press release. Your job is to return structured JSON metadata.

## Your task

1. Determine if this item is RELEVANT to a healthcare fraud enforcement dashboard that tracks federal enforcement actions against healthcare fraud (criminal cases, civil settlements, audits, investigations, legislation, regulatory actions). Items that are relevant: enforcement actions, indictments, convictions, sentencings, settlements, audits finding improper payments, congressional investigations, new fraud task forces, executive orders on fraud, investigative journalism exposing fraud schemes. Items that are NOT relevant: general healthcare policy, opinion pieces, partisan commentary, items where fraud is mentioned only tangentially, consumer advice articles, items about non-healthcare fraud.

2. If relevant, classify and extract metadata.

## Hard rules

- Do NOT output a `title` field. The dashboard preserves the original press-release headline verbatim and never lets the model rewrite it.
- Do NOT output a `description` field. Descriptions are not stored on the dashboard.

## Output format

Return ONLY valid JSON, no markdown fencing, no explanation:

{{
  "relevant": true/false,
  "type": one of: "Criminal Enforcement", "Civil Action", "Audit", "Investigation", "Investigative Report", "Congressional Hearing", "Legislation", "Executive Order", "Rule/Regulation", "Administrative Action", "Structural/Organizational", "Technology/Innovation",
  "state": "Two-letter state abbreviation if specific to one state, null if national/multi-state",
  "amount": "Dollar amount as string like '$52M' or '$14.6B' or null if none",
  "amount_numeric": numeric value in dollars (e.g. 52000000) or 0,
  "tags": [array of applicable tags from the APPROVED LIST below — pick ONLY tags that clearly apply],
  "entities": [array of company/organization names involved, e.g. "CVS", "UnitedHealth", "DMERx"],
  "officials": [array of named government officials mentioned, e.g. "Dr. Mehmet Oz", "President Trump"],
  "agency": "The government agency primarily responsible for this action. One of: DOJ, CMS, HHS, HHS-OIG, GAO, Congress, White House, State Agency, Media. Use 'Media' only when the media outlet itself conducted the investigation (e.g. ProPublica expose, CBS investigation). If the article is news coverage of a DOJ indictment, the agency is DOJ, not Media.",
  "related_agencies": ["If agency is Media or State Agency, which federal agency is most related (DOJ, CMS, HHS-OIG, etc.), or null"]
}}

## APPROVED TAG LIST — use ONLY these tags. Do not invent new tags.

The dashboard's pill tags mean exactly two things:
  (1) which PROGRAM got defrauded, and
  (2) which vulnerable SERVICE AREA was abused.

Do NOT include status tags ("Convicted", "Indicted", "Settlement"),
fraud-method tags ("Kickbacks", "Upcoding", "False Claims"),
committee names, or company names. Any tag outside this list will be discarded.

Programs: {program_list}
Vulnerable fraud areas: {area_list}

Do NOT output a description field — descriptions are not stored on the dashboard."""

    # Cap batch size to avoid GitHub Actions timeout
    MAX_BATCH = 30
    if len(to_enrich) > MAX_BATCH:
        print(f"enrich: capping to {MAX_BATCH} items (of {len(to_enrich)})")
        to_enrich = to_enrich[:MAX_BATCH]

    enriched_count = 0
    removed_ids = set()
    import time

    for action in to_enrich:
        title = action.get("title", "")
        agency = action.get("agency", "")
        link = action.get("link", "")
        is_official = action.get("source_type") == "official"

        user_msg = f"Title: {title}\nSource agency: {agency}\nLink: {link}"

        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=800,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}]
                )

                result_text = response.content[0].text.strip()
                # Handle possible markdown fencing
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                    if result_text.endswith("```"):
                        result_text = result_text[:-3]
                    result_text = result_text.strip()

                result = json.loads(result_text)

                if not result.get("relevant", True):
                    removed_ids.add(action["id"])
                    print(f"  REMOVED (irrelevant): {action['id']}")
                    break

                # Apply enrichment. The model is NOT allowed to rewrite the
                # title — it must match the source press release verbatim. We
                # also never write a description (see project memory).
                action.pop("description", None)
                # Defensive: if the model returned a title in violation of the
                # prompt, ignore it.
                result.pop("title", None)
                action["type"] = result.get("type", action.get("type", "Administrative Action"))
                action["tags"] = filter_tags(result.get("tags", []))
                action["entities"] = result.get("entities", [])
                action["officials"] = result.get("officials", [])
                if result.get("state"):
                    action["state"] = result["state"]
                if result.get("amount"):
                    action["amount"] = result["amount"]
                if result.get("amount_numeric"):
                    action["amount_numeric"] = result["amount_numeric"]
                # Only override agency for non-official items (media/news)
                # Official feed items keep their feed-assigned agency
                if not is_official and result.get("agency"):
                    action["agency"] = result["agency"]
                if result.get("related_agencies"):
                    action["related_agencies"] = result["related_agencies"]

                enriched_count += 1
                print(f"  OK: {action['id']} -> {action['type']}, {len(action['tags'])} tags")
                break

            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    wait = 5 * (attempt + 1)
                    print(f"  RATE LIMITED on {action['id']}, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  ERROR on {action['id']}: {e}")
                    break

    # Remove irrelevant items
    if removed_ids:
        data["actions"] = [a for a in data["actions"] if a["id"] not in removed_ids]

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"enrich: done. {enriched_count} enriched, {len(removed_ids)} removed")
    return enriched_count


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/actions.json"
    enrich_actions(path)
