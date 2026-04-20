# Scraping Coverage Report

*Auto-generated 2026-04-20 12:44 UTC from `build_scraping_report.py`. Source of truth is live code + data; to edit narrative sections, edit `_scraping_report_template.md`. Feed list, scraper descriptions, and coverage counts are regenerated from `update.py`, `.github/workflows/*.yml`, and `data/actions.json`.*

Summary: 23 configured feeds, 18 scrape_* functions.

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

| Workflow | Schedule | File |
|---|---|---|
| Daily Fraud Dashboard Update | Daily 7:17 UTC | `daily-update.yml` |
| Daily Congressional Hearings Update | Daily 9:13 UTC | `hearings-update.yml` |
| Daily Media Investigations Update | Daily 8:42 UTC | `media-update.yml` |
| Weekly News-Source Upgrade Check | Suns 10:07 UTC | `news-source-check.yml` |
| Daily Oversight Update | Daily 8:23 UTC | `oversight-update.yml` |
| Daily Scraping Report Rebuild | Daily 11:31 UTC | `scraping-report.yml` |
| Weekly Landing Page Monitor | Mons 9:43 UTC | `weekly-monitor.yml` |

Times are deliberately off-minute (not `:00` or `:30`) to spread API load. Each workflow auto-commits changes to `main` when results change.

---

## Feeds by agency

### DOJ

- **`DOJ-OPA`** — *official* (enabled)
  - Function: `scrape_doj_opa()`
  - Scrape DOJ Office of Public Affairs press releases using Playwright.
  - URL: https://www.justice.gov/news/press-releases
  - URL: https://www.justice.gov
- **`DOJ`** — *official* (**disabled**)
  - Method: RSS feed
  - URL: https://www.justice.gov/news/rss
- **`DOJ-USAO`** — *official* (enabled)
  - Function: `scrape_doj_usao()`
  - Scrape DOJ USAO (district-level) press releases using Playwright.
  - URL: https://www.justice.gov/usao/pressreleases
  - URL: https://www.justice.gov

### HHS-OIG

- **`HHS-OIG`** — *official* (enabled)
  - Function: `scrape_oig()`
  - Scrape HHS-OIG enforcement actions page.
  - URL: https://oig.hhs.gov/fraud/enforcement/?type=criminal-and-civil-actions
  - URL: https://oig.hhs.gov/fraud/enforcement/
- **`HHS-OIG-RPT`** — *official* (enabled)
  - Function: `scrape_oig_reports()`
  - Scrape HHS-OIG audit/inspection reports.
  - URL: https://oig.hhs.gov/reports/all/
  - URL: https://oig.hhs.gov
- **`HHS-OIG-PR`** — *official* (enabled)
  - Function: `scrape_oig_press()`
  - Scrape HHS-OIG newsroom press releases.
  - URL: https://oig.hhs.gov/newsroom/news-releases-articles/
  - URL: https://oig.hhs.gov

### CMS

- **`CMS`** — *official* (enabled)
  - Function: `scrape_cms()`
  - Scrape CMS newsroom press releases with pagination.
  - URL: https://www.cms.gov/newsroom?page={page_n}
  - URL: https://www.cms.gov
- **`CMS-Fraud`** — *official* (enabled)
  - Function: `scrape_cms_fraud_page()`
  - Scrape cms.gov/fraud — CMS's dedicated anti-fraud landing page.
  - URL: https://www.cms.gov/fraud
  - URL: https://www.cms.gov

### HHS

- **`HHS`** — *official* (**disabled**)
  - Function: `scrape_hhs_press()`
  - Scrape HHS press room (hhs.gov/press-room).
  - URL: https://www.hhs.gov/press-room/index.html
  - URL: https://www.hhs.gov

### Congress

- **`H-Oversight`** — *official* (enabled)
  - Function: `scrape_h_oversight()`
  - Scrape House Oversight Committee press releases using Playwright.
  - URL: https://oversight.house.gov/release/
- **`H-E&C`** — *official* (enabled)
  - Function: `scrape_energy_commerce()`
  - Scrape House Energy & Commerce press releases using Playwright.
  - URL: https://energycommerce.house.gov/news/press-release
  - URL: https://energycommerce.house.gov
- **`S-Finance`** — *official* (enabled)
  - Method: RSS feed
  - URL: https://www.finance.senate.gov/rss/feeds/?type=press
- **`S-HELP`** — *official* (enabled)
  - Function: `scrape_help_committee()`
  - Scrape Senate HELP Committee press releases using Playwright.
  - URL: https://www.help.senate.gov/chair/newsroom
  - URL: https://www.help.senate.gov
- **`H-W&M`** — *official* (enabled)
  - Function: `scrape_ways_means()`
  - Scrape House Ways & Means Committee news using Playwright.
  - URL: https://waysandmeans.house.gov/news/
  - URL: https://waysandmeans.house.gov
- **`S-Judiciary`** — *official* (enabled)
  - Function: `scrape_senate_judiciary()`
  - Scrape Senate Judiciary Committee press releases.
  - URL: https://www.judiciary.senate.gov{path}
  - URL: https://www.judiciary.senate.gov
- **`H-Judiciary`** — *official* (enabled)
  - Function: `scrape_house_judiciary()`
  - Scrape House Judiciary Committee press releases using Playwright.
  - URL: https://judiciary.house.gov/news
  - URL: https://judiciary.house.gov

### White House

- **`WhiteHouse`** — *official* (enabled)
  - Function: `scrape_whitehouse()`
  - Scrape whitehouse.gov for healthcare-fraud-relevant releases.
  - URL: https://www.whitehouse.gov/releases/
  - URL: https://www.whitehouse.gov/presidential-actions/

### GAO

- **`GAO`** — *official* (enabled)
  - Method: RSS feed
  - URL: https://www.gao.gov/rss/reports.xml

### DEA

- **`DEA`** — *official* (enabled)
  - Method: RSS feed
  - URL: https://www.dea.gov/press-releases/rss

### MedPAC

- **`MedPAC`** — *official* (enabled)
  - Function: `scrape_medpac()`
  - Scrape MedPAC documents listing.
  - URL: https://www.medpac.gov/document/

### MACPAC

- **`MACPAC`** — *official* (enabled)
  - Function: `scrape_macpac()`
  - Scrape MACPAC publications listing.
  - URL: https://www.macpac.gov/publication/

### Treasury

- **`FinCEN`** — *official* (enabled)
  - Function: `scrape_fincen()`
  - Scrape FinCEN press releases + advisories.
  - URL: https://www.fincen.gov/news/press-releases
  - URL: https://www.fincen.gov

### FDA

- **`FDA`** — *official* (**disabled**)
  - Method: RSS feed
  - URL: https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml


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

| Source | Items |
|---|---|
| DOJ | 523 |
| HHS-OIG | 53 |
| CMS | 30 |
| Congress | 26 |
| White House | 5 |
| GAO | 5 |
| MACPAC | 4 |
| Treasury | 3 |
| HHS | 2 |
| Media (manual) | 22 |
| **Total** | **673** |

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
