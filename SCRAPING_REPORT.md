# Scraping Coverage Report

Generated 2026-04-17. Lives at `SCRAPING_REPORT.md`.

This report documents every scraping source the dashboard pulls from, organized by dashboard tab → agency → source. For each source it covers: what's scraped, how it's scraped, what filtering is applied, and known limitations.

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

From those queues, items are either promoted to `actions.json` (passed), rejected (added to `rejected_links`), or stay pending.

---

## Scheduling

| Workflow | Schedule (UTC) | Purpose |
|---|---|---|
| `daily-update.yml` | 7:17 AM daily | Enforcement pass — runs `update.py` with enforcement filter, opens a PR with new items for the Federal Enforcement tab |
| `oversight-update.yml` | 8:23 AM daily | Oversight pass — runs `update.py --oversight-only`, routes items through AI review before auto-committing |
| `media-update.yml` | 8:42 AM daily | Media investigations pass |
| `hearings-update.yml` | 9:13 AM daily | Congress.gov API pass — new standalone pipeline for hearings |
| `weekly-monitor.yml` | Mondays 9:43 AM | Landing-page structure check — alerts if a scraper suddenly returns zero (catches silent breakage) |
| `news-source-check.yml` | Sundays 10:07 AM | Re-checks news-sourced items for newly-published official .gov sources, auto-swaps links |

Times are deliberately off-minute (not `:00` or `:30`) to spread load.

---

## Federal Enforcement tab sources

The tab filters `actions.json` to `type in {Criminal Enforcement, Civil Action}`. All items come from DOJ sources (plus a small number of HHS-OIG-hosted items with DOJ prosecutions behind them).

### DOJ

DOJ is by far the largest source (~522 items).

#### 1. `DOJ-OPA` (DOJ Office of Public Affairs) — `scrape_doj_opa`
- **URL:** https://www.justice.gov/news/press-releases
- **Method:** Playwright (Chrome). Paginates through the OPA press release listing.
- **Filtering:**
  - Only keeps items DOJ itself has tagged with the `Health Care Fraud` topic. DOJ's own taxonomy is treated as authoritative per the project's editorial rule.
  - Secondary HC-keyword fallback for items that don't yet have the topic tag indexed.
- **Backfill:** Walks pages until it hits `BACKFILL_FLOOR` (default 2025-01-01) or runs out.
- **Limitations:** justice.gov returns 403 to plain `requests`; Playwright is mandatory.

#### 2. `DOJ-USAO` (U.S. Attorneys' Offices) — `scrape_doj_usao`
- **URL:** https://www.justice.gov/usao/pressreleases
- **Method:** Playwright. Each USAO district publishes its own PR feed under the combined index.
- **Filtering:** Same as OPA — prefer `Health Care Fraud` topic tag, fallback on HC keywords.
- **State extraction:** District slug (e.g. `/usao-cdca/` = Central District of California) maps to state. Implemented in `extract_usao_state()` on the roadmap.
- **Limitations:** 403-blocked to requests, Playwright only.

#### 3. `DOJ` (RSS feed) — **disabled**
- URL would be https://www.justice.gov/news/rss but the feed is stale; kept in config as disabled for documentation.

### HHS-OIG (investigates, DOJ prosecutes — appears on Enforcement via linked cases)

#### 4. `HHS-OIG` enforcement actions — `scrape_oig`
- **URL:** https://oig.hhs.gov/fraud/enforcement/?type=criminal-and-civil-actions
- **Method:** Plain `requests` + BeautifulSoup. Paginates the listing.
- **Behavior:** Each OIG action page is fetched; if it links to a DOJ press release, the DOJ URL is substituted as the canonical `link` (cleaner provenance). Body text + title extracted from the canonical page.
- **Backfill:** Walks pages until all dates below `BACKFILL_FLOOR`.

---

## Federal Oversight & Accountability tab sources

Items with `type != Criminal Enforcement / Civil Action`. Most use the same scrapers as Enforcement but route differently based on the computed `type`.

### HHS-OIG

#### 5. `HHS-OIG-RPT` (audits/reports) — `scrape_oig_reports`
- **URL:** https://oig.hhs.gov/reports/all/
- **Method:** `requests` + BeautifulSoup, paginates.
- **Filtering:**
  - **Skip clean-bill-of-health audits.** If title has stock phrases ("Generally Complied With", "Substantially Complied", "Did Comply", "Met Federal Requirements"), the audit is auditee-compliant and doesn't belong on a fraud dashboard.
  - **Body-level compliance check** (added recently): scans the first ~3000 chars of each audit's body for phrases like "no recommendations", "auditee substantially complied" with no fraud counter-signal. Skips if compliance-only.
  - Skips IT/cybersecurity audits (not HC fraud).
- **Backfill:** Floor-based early-stop, up to 50 pages.

#### 6. `HHS-OIG-PR` (newsroom press releases) — `scrape_oig_press`
- **URL:** https://oig.hhs.gov/newsroom/news-releases-articles/
- **Method:** `requests` + BeautifulSoup.
- **Filtering:**
  - Skips "At a Glance" summaries (they're duplicates of full semiannual reports).
  - **Dedup against audit reports**: if the body references a `/reports/all/` URL already on the dashboard, the news release is dropped as a summary duplicate.

### CMS

#### 7. `CMS` (newsroom) — `scrape_cms`
- **URL:** https://www.cms.gov/newsroom + pagination
- **Method:** Playwright required (CMS newsroom is JS-rendered — plain requests returns blank).
- **Backfill:** 40 pages max with floor-based early-stop.

#### 8. `CMS-Fraud` (anti-fraud landing page) — `scrape_cms_fraud_page`
- **URL:** https://www.cms.gov/fraud
- **Method:** Playwright (JS-rendered).
- **Filtering:** Only accepts linked PDFs / documents (not navigation items). Pre-filter requires the link text/URL to mention fraud, crush, fdoc, wiser, hospice, moratorium, integrity, improper, radv, dmepos, hot-spot, dual-enrollment, or annual-report.
- **What this catches:** CMS's quarterly fact sheets, FDOC materials, CRUSH, DMEPOS hot-spot analyses, RADV audits, dual-enrollment data — content that lives outside the newsroom feed.

### White House

#### 9. `WhiteHouse` — `scrape_whitehouse` (new)
- **URLs:** https://www.whitehouse.gov/releases/ + https://www.whitehouse.gov/presidential-actions/
- **Method:** `requests` + BeautifulSoup on listing pages; detail fetches on each candidate.
- **Filtering:** Narrow HC-fraud title filter. WH publishes broadly (tax, defense, etc.); scraper only keeps items with fraud/medicare/medicaid/healthcare/opioid/HHS/CMS terms in the title.
- **Low-volume source** — WH only covers HC-fraud for major announcements (task force creation, state-level suspensions, Vance-led initiatives).

### HHS (parent department, separate from HHS-OIG)

#### 10. `HHS` — `scrape_hhs_press` — **disabled**
- **URL:** https://www.hhs.gov/press-room/index.html
- **Status:** Scaffolding exists but disabled. hhs.gov is behind Akamai Bot Manager which 403s both `requests` and default Playwright. Would need `playwright-stealth` to bypass. HHS-proper items (~1–2/month) are currently curated manually.

### Congress

Congress scraping is split across committee scrapers + a separate Congress.gov API pipeline. All commit items with `agency = Congress`.

#### Committee press-release scrapers
Each committee has its own listing-page scraper. All apply the same filters at the end:
- **Commentary rejection:** auto-rejects press releases on `/chairmans-news/`, `/op-ed/`, `/floor-remarks/`, `/dear-colleague/` paths
- **Hearing-about rejection:** rejects press releases that describe a hearing (announce / opening statement / wrap-up / committee-to-hold / recap). Hearings are captured via the Congress.gov API instead; these press releases would be duplicates.
- **Bill-intro rejection:** rejects "Member X introduces bill" press releases (not systematically tracked).

| # | Name | Function | URL | Method |
|---|---|---|---|---|
| 11 | H-Oversight | `scrape_h_oversight` | oversight.house.gov/release/ | Playwright |
| 12 | H-E&C | `scrape_energy_commerce` | energycommerce.house.gov/news/press-release | Playwright |
| 13 | S-Finance | RSS | https://www.finance.senate.gov/rss/feeds/?type=press | RSS + browser_fallback |
| 14 | S-HELP | `scrape_help_committee` | help.senate.gov/chair/newsroom | Playwright |
| 15 | H-W&M | `scrape_ways_means` | waysandmeans.house.gov/news/ | Playwright |
| 16 | S-Judiciary | `scrape_senate_judiciary` | judiciary.senate.gov | Requests |
| 17 | H-Judiciary | `scrape_house_judiciary` | judiciary.house.gov/news | Playwright |

Each committee scraper has an HC-fraud pre-filter. Without it, committees surface large volumes of unrelated content (immigration, defense, tax, foreign policy).

#### Congress.gov hearings API — `scrape_congress_hearings.py` (standalone)
- **Endpoint:** `https://api.congress.gov/v3/committee-meeting/{congress}/{chamber}`
- **Requires:** `CONGRESS_GOV_API_KEY` repo secret
- **Concurrency:** `ThreadPoolExecutor` with 8 workers
- **Method:**
  1. Enumerate every committee meeting in 119th Congress (both chambers).
  2. Fetch detail for each via API.
  3. `is_hearing()` — discard markups/votes/business meetings. Uses `meeting.type` field as authoritative. Also accepts Senate "Hearings to examine..." title pattern (Senate meetings have `type=Meeting` with no documents).
  4. **Layered filter:**
     - **Tier 1:** Explicit fraud-in-healthcare phrase in title → auto-include
     - **Tier 2:** Generic "fraud" keyword + HC-relevant committee → auto-include
     - **Tier 3:** HHS/CMS/DOJ witness signal alone → review queue
     - **Tier 4:** HC title context + HC committee, no fraud word → review queue
     - **Tier 5:** HC committee with vague title → review queue
  5. **Committee URL resolution:** `resolve_committee_url()` slugifies the hearing title, HEAD-checks the expected committee URL (e.g., oversight.house.gov/hearing/<slug>/, finance.senate.gov/hearings/<slug>). Falls back to congress.gov/event URL if committee page isn't reachable.
- **Dedup:** content-word overlap with 1-day date slack against existing `Hearing`-type items.
- **Review queue:** `data/tmp_hearings_review_queue.json` (hearings with ambiguous signal — 418 items currently queued, needs human triage).

### GAO

#### 18. `GAO` — RSS (browser fallback)
- **URL:** https://www.gao.gov/rss/reports.xml
- **Method:** RSS with browser fallback for bot-blocked responses.
- **Filtering:** HC-keyword required (GAO publishes on every federal agency; narrow to HC fraud).

### DEA

#### 19. `DEA` — RSS (browser fallback)
- **URL:** https://www.dea.gov/press-releases/rss
- **Method:** RSS, falls back to Playwright on 403.
- **Filtering:** Narrow to HC provider cases (pill mills, doctor prosecutions). Most DEA prosecutions are about drug trafficking, not HC fraud.

### MedPAC / MACPAC

#### 20. `MedPAC` — `scrape_medpac`
- **URL:** https://www.medpac.gov/document/
- **Filtering:** **Fraud-gate required** — title or early body must mention fraud, kickback, improper payment, program integrity, or similar. MedPAC publishes extensively on Medicare payment policy; only fraud-focused items qualify. Skips general biannual Reports to Congress.

#### 21. `MACPAC` — `scrape_macpac`
- **URL:** https://www.macpac.gov/publication/
- **Filtering:** Same fraud-gate as MedPAC. Skips biannual reports and general policy issue briefs.

### Treasury / FinCEN

#### 22. `FinCEN` — `scrape_fincen`
- **URL:** https://www.fincen.gov/news/press-releases
- **Filtering:** Narrow HC-keyword pre-filter at title stage (health care / medicare / medicaid / prescription / hospital / hospice / pharmac / fraud scheme). FinCEN publishes heavily on non-HC topics (sanctions, crypto, real estate).

### FDA

#### 23. `FDA` — RSS — **disabled**
- **URL:** https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml
- **Status:** Disabled. FDA fraud cases usually get prosecuted through DOJ and appear there; standalone FDA announcements are rare.

---

## Media Investigations tab sources

The Media tab (`data/media.json`) is **currently manually curated**. No active scrapers. All items are added manually by the maintainer.

The codebase has scaffolding for media-scraping feeds, but they are intentionally disabled:
- `media-update.yml` runs daily but the workflow's only live action is AI review of any manually-added items to confirm they pass the "third-party investigative fraud journalism" classifier.
- Historical commits reference disabled scrapers for ProPublica, KFF Health News, STAT, NY Times health-fraud, etc. Those are kept disabled because their feeds carried too many non-fraud items.

---

## Date extraction (all scrapers)

Common helper: `_extract_canonical_date(soup, url, response_headers)` — priority chain:
1. `<meta property="article:published_time">` (OpenGraph)
2. JSON-LD `datePublished` (schema.org)
3. `<time datetime="...">` (HTML5)
4. URL path `/YYYY/MM/DD/` pattern
5. HTTP `Last-Modified` header

If none of those resolve, scraper falls back to body-text regex (`Month DD, YYYY` pattern), then a date-parse of the listing-page date string if present. Final fallback is `parse_date(strict=False)` which logs a WARNING and stores today's date (intentionally loud so format gaps get noticed).

Items with `YYYY-MM` format (month-only) display as "Jun, 2025" in the UI. Used for source documents (e.g., CMS PDFs) that state only month+year with no explicit publication day.

---

## Tag extraction (all scrapers)

`update.py` calls `generate_tags(title, full_text)` during ingest. This:
1. Uses `tag_extractor.extract_tags_with_evidence` (AI anchored extractor with evidence citations) when `ANTHROPIC_API_KEY` is set.
2. Falls back to `tag_allowlist.auto_tags` (regex matcher) otherwise.

**Strict extraction rule (active policy):** Tags are never inferred from external knowledge — only literal keyword matches + recognized synonyms. Body-text mentions of program names (Medicare, Medicaid) require 2+ occurrences to count, to suppress boilerplate agency-name false positives. Area-tag mentions require 1+ occurrence but from the title or early body.

---

## State extraction

`get_state(text)` — iterates `STATE_MAP` longest-first to prevent the "West Virginia matches Virginia first" bug. State extraction prefers title over body (body often mentions unrelated states from defendant's prior convictions, comparison data, etc.). Multi-state support: the `state` field is a comma-separated string when multiple states apply (e.g., "CA, FL").

Currently single-state extraction only via keyword match. Planned: USAO district → state fallback (e.g., `/usao-ri/` → RI even if title doesn't name it), and city → state fallback for items that name a city only.

---

## Validation checks at ingest (update.py)

- **Agency/domain consistency warning:** WARNING logged if an official item's link domain doesn't match the assigned agency (e.g., `agency=CMS` with `link=whitehouse.gov`). Catches classification mistakes at ingest.
- **parse_date fail-loud:** unparseable dates log WARNING and default to today (visible, not silent).

---

## Review queues (gatekeeping between scraper + dashboard)

- `data/needs_review.json` — enforcement queue (items scraped but flagged for human/AI review)
- `data/needs_review_oversight.json` — oversight queue
- `data/tmp_hearings_review_queue.json` — Congress.gov hearings queue (~418 pending)
- `rejected_links` lists — permanent rejections, scraper skips these forever

---

## Current coverage (as of 2026-04-17)

| Agency | Items in actions.json |
|---|---|
| DOJ | 522 |
| HHS-OIG | 52 |
| CMS | 30 |
| Congress | 26 |
| White House | 5 |
| GAO | 5 |
| MACPAC | 4 |
| Treasury | 3 |
| HHS | 1 |

Media tab: 20 manually curated stories.

---

## Known gaps / known limitations

- **HHS press room** is Akamai-blocked — currently disabled scaffolding
- **FDA** RSS disabled — low incremental value (DOJ captures the prosecutions)
- **Congress.gov hearings** has 418 "review" items sitting in a queue that needs human triage
- **DOGE actions** are not systematically tracked (no standalone agency feed; only 2 items mention DOGE)
- **State tag coverage:** items that name only a city (e.g., "Sarasota Memorial Hospital") currently go untagged; AI state extraction or city-dictionary is on the roadmap
- **Bot-blocked sources** (DOJ, GAO, WH-behind-Akamai situations) require Playwright and are slower
