"""Review pending media items using Claude API and create a GitHub issue for approval.

1. Reads data/pending.json (media items staged by update.ps1)
2. Sends each to Claude Haiku to evaluate relevance and enrich metadata
3. Creates a GitHub issue listing relevant items for user approval
4. Clears pending.json after processing
"""
import json, sys, os, subprocess

from tag_allowlist import ALLOWED_TAGS, PROGRAM_TAGS, AREA_TAGS, filter_tags

def main(pending_path="data/pending.json"):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not os.path.exists(pending_path):
        print("review: no pending file found")
        return

    with open(pending_path, "r", encoding="utf-8-sig") as f:
        pending = json.load(f)

    items = pending.get("items", [])
    if not items:
        print("review: no pending items")
        return

    print(f"review: {len(items)} pending media item(s)")

    # Also load existing actions to check for dupes by link
    actions_path = "data/actions.json"
    with open(actions_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    existing_links = {a.get("link", "") for a in data["actions"]}

    # Dedupe pending against existing and drop items older than 14 days
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    items = [i for i in items if i.get("link", "") not in existing_links and i.get("date", "9999") >= cutoff]
    if not items:
        print("review: all pending items already in dashboard")
        _clear_pending(pending_path)
        return

    # Cap to avoid timeout
    MAX_REVIEW = 25
    if len(items) > MAX_REVIEW:
        print(f"review: capping to {MAX_REVIEW} items (of {len(items)})")
        items = items[:MAX_REVIEW]

    # If no API key, just list items without enrichment
    if not api_key:
        print("review: no ANTHROPIC_API_KEY, listing items without filtering")
        relevant = [{"item": i, "enriched": {}} for i in items]
    else:
        relevant = _filter_with_api(items, api_key)

    if not relevant:
        print("review: no relevant items found")
        _clear_pending(pending_path)
        return

    # Save enriched items for later approval
    enriched_path = "data/reviewed.json"
    with open(enriched_path, "w", encoding="utf-8") as f:
        json.dump({"items": [r["item"] for r in relevant]}, f, indent=4, ensure_ascii=False)

    # Create GitHub issue
    _create_issue(relevant, gh_token)

    # Clear pending
    _clear_pending(pending_path)


def _filter_with_api(items, api_key):
    try:
        import anthropic
    except ImportError:
        print("review: anthropic not installed")
        return [{"item": i, "enriched": {}} for i in items]

    client = anthropic.Anthropic(api_key=api_key)

    program_list = ", ".join(sorted(PROGRAM_TAGS))
    area_list = ", ".join(sorted(AREA_TAGS))

    SYSTEM_PROMPT = f"""You are a healthcare fraud enforcement data analyst. You will be given the title of a news article. Determine if it belongs on a dashboard tracking federal healthcare fraud enforcement actions.

RELEVANT: enforcement actions, indictments, convictions, sentencings, civil settlements, audits finding improper payments, congressional investigations into fraud, investigative journalism exposing specific fraud schemes, new fraud task forces, regulatory actions against fraud.

NOT RELEVANT: general healthcare policy, opinion/editorial, partisan commentary, consumer advice, items where fraud is only mentioned tangentially, general industry news, stock/business coverage unless about fraud charges.

Return ONLY valid JSON:
{{
  "relevant": true/false,
  "reason": "one sentence explaining why relevant or not",
  "type": "Criminal Enforcement" or "Civil Action" or "Audit" or "Investigation" or "Investigative Report" or "Congressional Hearing" or "Legislation" or "Administrative Action",
  "state": "Two-letter abbreviation or null",
  "tags": ["from approved list — programs + vulnerable areas only"],
  "agency": "DOJ/CMS/HHS/HHS-OIG/GAO/Congress/White House/State Agency/Media"
}}

APPROVED TAG LIST — use ONLY these. The dashboard's pill tags mean exactly two things:
  (1) which PROGRAM got defrauded, and
  (2) which vulnerable SERVICE AREA was abused.
Do NOT include status/method/committee/company tags. Anything outside this list is discarded.

Programs: {program_list}
Vulnerable areas: {area_list}

Hard rules: never output `description`, `title`, `amount`, `amount_numeric`, `officials`, or `entities`. The dashboard does not store people, companies, descriptions, or oversight dollar amounts."""

    relevant = []

    for item in items:
        title = item.get("title", "")
        msg = f"Title: {title}"

        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": msg}]
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)

            if result.get("relevant"):
                # Apply enrichment. Description / title / officials /
                # entities / amount are intentionally never written on
                # media items (all oversight-side). See project memory.
                item.pop("description", None)
                item["type"] = result.get("type", item.get("type"))
                item["tags"] = filter_tags(result.get("tags", []))
                item["entities"] = []
                item["officials"] = []
                item["amount"] = ""
                item["amount_numeric"] = 0
                if result.get("state"):
                    item["state"] = result["state"]
                if result.get("agency"):
                    item["agency"] = result["agency"]

                relevant.append({"item": item, "enriched": result})
                print(f"  RELEVANT: {title[:70]}")
            else:
                print(f"  skipped: {title[:70]} — {result.get('reason','')}")

        except Exception as e:
            print(f"  ERROR: {title[:50]} — {e}")
            continue

    return relevant


def _create_issue(relevant, gh_token):
    if not relevant:
        return

    title = f"📋 {len(relevant)} media item(s) for dashboard review"

    body_lines = [
        "The daily scan found the following media items that appear relevant to the healthcare fraud dashboard.",
        "",
        "**Reply with the numbers you want to add** (e.g., `add 1, 3, 5`) or `add all` / `skip all`.",
        "",
        "---",
        ""
    ]

    for i, r in enumerate(relevant, 1):
        item = r["item"]
        enriched = r.get("enriched", {})
        body_lines.append(f"### {i}. {item.get('title', 'Untitled')}")
        body_lines.append("")
        body_lines.append(f"- **Source:** [{item.get('link_label', 'Link')}]({item.get('link', '')})")
        body_lines.append(f"- **Date:** {item.get('date', '?')}")
        body_lines.append(f"- **Type:** {enriched.get('type', item.get('type', '?'))}")
        body_lines.append(f"- **Agency:** {enriched.get('agency', item.get('agency', '?'))}")
        if enriched.get("state"):
            body_lines.append(f"- **State:** {enriched['state']}")
        if enriched.get("amount"):
            body_lines.append(f"- **Amount:** {enriched['amount']}")
        if enriched.get("tags"):
            body_lines.append(f"- **Tags:** {', '.join(enriched['tags'])}")
        if enriched.get("reason"):
            body_lines.append(f"- **Why relevant:** {enriched['reason']}")
        body_lines.append("")
        body_lines.append("---")
        body_lines.append("")

    body = "\n".join(body_lines)

    # Create issue via gh CLI
    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body, "--label", "media-review"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"review: created issue — {result.stdout.strip()}")
        else:
            print(f"review: gh issue create failed — {result.stderr}")
            # Fallback: print to stdout so it's visible in workflow logs
            print("=== ITEMS FOR REVIEW ===")
            print(body)
    except FileNotFoundError:
        print("review: gh CLI not available, printing to stdout")
        print("=== ITEMS FOR REVIEW ===")
        print(body)


def _clear_pending(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": None, "items": []}, f)
    print("review: cleared pending.json")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/pending.json"
    main(path)
