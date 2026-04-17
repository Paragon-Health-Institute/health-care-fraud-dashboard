# Scraping Coverage Report

*Auto-generated {{GENERATED_AT}} from `build_scraping_report.py`. Source of truth is live code + data; to edit narrative sections, edit `_scraping_report_template.md`. Feed list, scraper descriptions, and coverage counts are regenerated from `update.py`, `.github/workflows/*.yml`, and `data/actions.json`.*

Summary: {{AUTO_FEED_COUNT}} configured feeds, {{AUTO_SCRAPER_COUNT}} scrape_* functions.

---

## Dashboard architecture

Three tabs:
1. **Federal Enforcement** — criminal prosecutions + civil FCA settlements (`type` = Criminal Enforcement or Civil Action)
2. **Federal Oversight & Accountability** — everything else in `data/actions.json` (Audits, Reports, Hearings, Administrative Actions, Rule/Regulation, Investigations, Structural/Organizational, Legislation, Presidential Action)
3. **Media Investigations** — third-party investigative journalism in `data/media.json`

All scrapers write to `data/actions.json` (enforcement + oversight share the same file, split by `type`) or `data/media.json`.

Items that pass scraping but fail the HC-keyword / fraud-signal gates go to one of two review queues:
- `data/needs_review.json` — enforcement candidates
- `data/needs_review_oversight.json` — oversight candidates

From those queues, items are either promoted to `actions.json`, rejected (added to `rejected_links`), or stay pending.

---

## Scheduling

{{AUTO_SCHEDULE}}

Times are deliberately off-minute (not `:00` or `:30`) to spread API load. Each workflow auto-commits changes to `main` when results change.

---

## Feeds by agency

{{AUTO_FEEDS}}

---

## Cross-cutting mechanics

### Date extraction

`_extract_canonical_date()` in `update.py` extracts a publication date from any scraped detail page via priority chain:
1. `<meta property="article:published_time">` (OpenGraph)
2. JSON-LD `datePublished` (schema.org)
3. `<time datetime="...">` (HTML5)
4. URL path `/YYYY/MM/DD/` pattern
5. HTTP `Last-Modified` header

If none resolve, scraper falls back to body-text regex then `parse_date(strict=False)` which defaults to today and logs a WARNING. Items where the source states only month+year use `YYYY-MM` format and display as "Jun, 2025".

### Tag extraction

`update.py`'s `generate_tags(title, full_text)`:
1. Uses `tag_extractor.extract_tags_with_evidence` (AI anchored extractor with evidence citations) when `ANTHROPIC_API_KEY` is set
2. Falls back to `tag_allowlist.auto_tags` (regex matcher) otherwise

**Strict extraction rule**: tags are never inferred from external knowledge — only literal keyword matches or recognized synonyms. Body-text mentions of program names (Medicare, Medicaid) require 2+ occurrences to count, to suppress boilerplate agency-name false positives. Area-tag mentions require 1+ occurrence.

### State extraction

`get_state(text)` iterates `STATE_MAP` longest-first to prevent the "West Virginia matches Virginia first" bug. Prefers title over body (body often mentions unrelated states — defendant's prior convictions, comparison data, etc.). Multi-state items use a comma-separated string (e.g., `"CA, FL"`).

### Validation at ingest

- **Agency/domain consistency warning**: WARNING logged if an official item's `link` domain doesn't match the assigned `agency` (e.g., `agency=CMS` with `link=whitehouse.gov`).
- **parse_date fail-loud**: unparseable dates log WARNING and default to today.

### Dedup

Items are deduped against existing `actions.json` by:
- Normalized `link` (lowercase host, strip `www.`, strip trailing slash, drop tracking params)
- Normalized `title` (lowercase, strip non-alphanumeric)
- `_report_ref` (OIG press releases that link to an existing audit-report URL are skipped)

---

## Review queues

- `data/needs_review.json` — enforcement items scraped but flagged for AI/human review
- `data/needs_review_oversight.json` — oversight items
- `data/tmp_hearings_review_queue.json` — Congress.gov hearings with ambiguous signal
- `rejected_links` lists in each review file — permanent rejections; the scraper skips these forever

---

## Current coverage

{{AUTO_COVERAGE}}

---

## Known gaps + limitations

- **HHS press room** (`scrape_hhs_press`) is disabled — hhs.gov is behind Akamai Bot Manager which 403s both `requests` and default Playwright. Would need `playwright-stealth` tooling to bypass. HHS-proper items are currently curated manually (~1–2/month).
- **FDA** RSS feed is disabled — FDA fraud cases mostly surface through DOJ prosecutions which appear via `DOJ-OPA`/`DOJ-USAO`.
- **Congress.gov hearings** review queue (`data/tmp_hearings_review_queue.json`) has ~400 items with ambiguous signal awaiting human triage. These are hearings on HC-relevant committees with vague titles.
- **DOGE actions** are not systematically tracked. Only 2 items mention DOGE and both are tangential to healthcare-fraud reporting.
- **State tag coverage**: items that name only a city (e.g., "Sarasota Memorial Hospital") currently go untagged with a state. On the roadmap: city → state fallback dictionary + USAO district → state extraction from justice.gov URLs (`/usao-ri/` → RI).
- **Bot-blocked sources** — DOJ, GAO, and some committee sites return 200-with-empty-body to plain `requests`. All require Playwright fallback, which makes those scrapers slower but more reliable.

---

## Scraper naming convention

Scrapers that fetch via Python `requests`:
- `scrape_oig`, `scrape_oig_reports`, `scrape_oig_press` (HHS-OIG)
- `scrape_fincen`, `scrape_whitehouse` (Treasury, WH)
- `scrape_senate_judiciary` (Senate)

Scrapers that require Playwright (JS-rendered or bot-blocked):
- `scrape_doj_opa`, `scrape_doj_usao` (DOJ)
- `scrape_cms`, `scrape_cms_fraud_page` (CMS)
- `scrape_h_oversight`, `scrape_energy_commerce`, `scrape_help_committee`, `scrape_ways_means`, `scrape_house_judiciary` (committees)
- `scrape_hhs_press` (disabled)

Standalone pipelines:
- `scrape_congress_hearings.py` — Congress.gov API (requires `CONGRESS_GOV_API_KEY`)
- `retag_existing.py` — re-tag existing items via AI extractor
- `retag_strict.py` — re-tag with strict extraction rules (title + 2-occurrence body)
- `check_news_sources.py` — weekly news-sourced upgrade scanner

---

## Tag allowlist

Program tags (6): Medicare, Medicaid, Medicare Advantage, Medicaid Managed Care, TRICARE, ACA
Area tags (23): DME, Hospice, Pharmacy, Genetic Testing, Lab Testing, Telehealth, Home Health, Nursing Home, Medical Devices, Autism/ABA, Wound Care, Adult Day Care, Mental Health, Prenatal Care, Skin Substitutes, Personal Care, Physical Therapy, Assisted Living, Ambulance, Hospital, Addiction Treatment, Opioids, Off-Label

Co-apply rules:
- Medicare Advantage → also Medicare
- Medicaid Managed Care → also Medicaid

Source of truth: `tag_allowlist.py`.
