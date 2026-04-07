# Read as raw bytes to preserve encoding
$raw = [System.IO.File]::ReadAllText('data/actions.json', [System.Text.Encoding]::UTF8)

# === 1. FIX MOJIBAKE CHARACTERS ===
# UTF-8 double-encoded as Windows-1252 produces these byte sequences
# em dash U+2014: C3A2 C280 C294 in file = "Ã¢â‚¬â€"" but displays as various mojibake
# The actual strings in the file we need to match:
$emDash = [char]0x00E2, [char]0x0080, [char]0x0094 -join ''      # â€" -> em dash
$enDash = [char]0x00E2, [char]0x0080, [char]0x0093 -join ''      # â€" -> en dash
$rsQuote = [char]0x00E2, [char]0x0080, [char]0x0099 -join ''     # â€™ -> right single quote
$ellipsis = [char]0x00E2, [char]0x0080, [char]0x00A6 -join ''    # â€¦ -> ellipsis
$eAcute = [char]0x00C3, [char]0x00A9 -join ''                     # Ã© -> e-acute

$raw = $raw.Replace($emDash, [string][char]0x2014)
$raw = $raw.Replace($enDash, [string][char]0x2013)
$raw = $raw.Replace($rsQuote, [string][char]0x2019)
$raw = $raw.Replace($ellipsis, [string][char]0x2026)
$raw = $raw.Replace($eAcute, [string][char]0x00E9)

Write-Output "Mojibake replacements done"

# === 2. PARSE JSON ===
$j = $raw | ConvertFrom-Json

# === 3. FIX MISSING DOLLAR SIGNS IN TITLES ===
$dollarFixes = @{
    'hhs-oig-2026-03-12-az-cardiology-vein' = 'Arizona Cardiology Group to Pay $4.75M to Resolve Allegations of Unnecessary Vein Ablations'
    'hhs-oig-2026-03-10-montgomery-home-care' = 'CEO of Montgomery County Home Care Agency Sentenced to Incarceration for $1.7 Million Medicaid Fraud Scheme'
    'hhs-oig-2026-03-09-chiropractor-14-9m' = 'Chiropractor Sentenced to 43 Months in Prison for $14.9 Million Health Care Fraud and Kickback Scheme'
    'hhs-oig-2026-03-09-psychiatrist-360k' = 'Psychiatrist Reaches $360,000 Civil Settlement to Resolve Allegations of False Claims'
    'hhs-oig-2026-03-09-dme-owner-59m' = 'Owner of Durable Medical Equipment Company Sentenced for $59 Million Medicare Fraud'
    'hhs-oig-2026-03-06-amerisourcebergen-1m' = 'AmerisourceBergen Subsidiary Agrees to Pay $1 Million for Allegedly Paying Kickbacks'
    'hhs-oig-2026-03-06-kansas-doctor-8m' = 'Kansas Doctor Sentenced to 3 Years in Prison for $8 Million Medicare Fraud'
    'hhs-oig-2026-03-06-mexican-man-6-85m' = 'Man Sentenced to 14 Years in Federal Prison for Leading a $6.85 Million Health Care Fraud Scheme'
    'media-2026-01-08-doj-oklahoma-dme-30m-indictment' = 'DOJ: Oklahoma Medical Supply Company Owner Indicted for $30M Health Care Fraud Scheme'
    'media-2026-02-10-doj-mn-fraud-tourists-ai' = "DOJ: 'Fraud Tourists' Plead Guilty to `$4.5M Minneapolis Medicaid Fraud Using AI-Fabricated Records"
    'media-2026-03-05-doj-russian-400m-medicare-laundering' = 'DOJ: Russian Citizen Charged with Laundering $12.2M Connected to $400M in Fraudulent Medicare Claims'
    'media-2026-03-12-fox-la-doctor-600m-npi-fraud' = "Fox News: 87-Year-Old LA Doctor's Medicare Number Linked to `$600M in Fraudulent Billing"
    'media-2026-02-12-doj-chicago-10m-foreign-nationals' = 'DOJ: Two Foreign Nationals Indicted in Chicago as Part of $10M Health Care Fraud Scheme'
}

foreach ($a in $j.actions) {
    if ($dollarFixes.ContainsKey($a.id)) {
        $a.title = $dollarFixes[$a.id]
        Write-Output "Fixed title: $($a.id)"
    }
}

# === 4. FIX GENERIC LINKS ===
$linkFixes = @{
    'doj-2026-01-fraud-enforcement-division' = 'https://www.whitehouse.gov/fact-sheets/2026/01/fact-sheet-president-donald-j-trump-establishes-new-department-of-justice-division-for-national-fraud-enforcement/'
    'cms-2026-01-minnesota-audit-announcement' = 'https://www.fox9.com/news/fraud-minnesota-trump-admin-audit-mn-medicaid-receipts-defer-payment-14-programs'
    'cms-hhs-2026-01-minnesota-mission' = 'https://kstp.com/kstp-news/top-news/dr-oz-on-medicaid-fraud-fact-finding-mission-in-minnesota-2b-could-be-at-stake/'
    'cms-2026-01-california-hospice-investigation' = 'https://hospicenews.com/2026/01/12/cms-doj-aggressively-cracking-down-on-hospice-fraud/'
    'cms-2026-01-27-newsom-demand' = 'https://homehealthcarenews.com/2026/01/dr-oz-demands-action-to-root-out-in-home-care-fraud-in-california/'
    'cms-2026-02-05-hospice-spreading' = 'https://www.mcknightshomecare.com/news/cms-expands-enhanced-oversight-to-hospice-providers-in-two-new-states/'
    'whitehouse-2026-02-04-ca-task-force' = 'https://www.cbsnews.com/news/trump-anti-fraud-task-force-targeting-california-jd-vance/'
    'oig-2026-01-22-maine-autism-audit' = 'https://oig.hhs.gov/newsroom/news-releases-articles/hhs-oig-audit-finds-maine-made-at-least-456-million-in-improper-medicaid-payments-for-autism-services/'
    'hhs-2026-02-04-ai-fraud-detection' = 'https://www.cms.gov/newsroom/press-releases/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud'
    'cms-doj-2026-01-19-california-billion-return' = 'https://www.foxnews.com/politics/key-trump-agency-vows-claw-back-over-1b-benefitting-illegals-blue-states'
    'media-2025-01-azcir-propublica-az-medicaid-deaths' = 'https://azcir.org/news/2025/01/27/arizona-deaths-sober-living-homes-fumbled-response-medicaid-fraud/'
    'hhs-oig-2026-03-13-rocky-hill-pharmacy' = 'https://www.justice.gov/usao-edtn/pr/federal-jury-convicts-three-women-conspiracy-commit-wire-fraud-related-rocky-hill'
    'hhs-oig-2026-03-13-medical-center-shutdown' = 'https://oig.hhs.gov/fraud/enforcement/da-fbi-and-us-department-of-health-human-services-office-of-the-inspector-general-shut-down-medical-center-committing-healthcare-fraud/'
    'hhs-oig-2026-03-12-az-cardiology-vein' = 'https://www.justice.gov/opa/pr/arizona-cardiology-group-pay-475m-resolve-allegations-unnecessary-vein-ablations'
    'hhs-oig-2026-03-12-10-medicaid-providers' = 'https://www.ohioattorneygeneral.gov/Media/News-Releases/March-2026/10-Medicaid-Providers-Facing-Fraud-Charges'
    'hhs-oig-2026-03-11-greenville-ceo-indicted' = 'https://www.justice.gov/usao-sc/pr/former-greenville-ceo-employees-indicted-multi-million-dollar-health-care-fraud-scheme'
    'hhs-oig-2026-03-10-montgomery-home-care' = 'https://www.attorneygeneral.gov/taking-action/ceo-of-montgomery-county-home-care-agency-sentenced-to-incarceration-ordered-to-pay-for-1-7-million-medicaid-fraud-scheme/'
    'hhs-oig-2026-03-09-chiropractor-14-9m' = 'https://www.justice.gov/usao-nj/pr/chiropractor-sentenced-43-months-prison-149-million-health-care-fraud-and-kickback'
    'hhs-oig-2026-03-09-psychiatrist-360k' = 'https://www.justice.gov/usao-edmo/pr/psychiatrist-reaches-civil-settlement-360000-resolve-allegations-false-claims-federal'
    'hhs-oig-2026-03-09-dme-owner-59m' = 'https://www.justice.gov/opa/pr/owner-durable-medical-equipment-company-sentenced-59m-medicare-fraud'
    'hhs-oig-2026-03-06-amerisourcebergen-1m' = 'https://www.justice.gov/usao-ma/pr/amerisourcebergen-subsidiary-agrees-pay-1-million-allegedly-paying-kickbacks-health-care'
    'hhs-oig-2026-03-06-illinois-dme' = 'https://www.justice.gov/usao-ma/pr/illinois-man-sentenced-two-years-prison-durable-medical-equipment-scheme'
    'hhs-oig-2026-03-06-kansas-doctor-8m' = 'https://www.justice.gov/usao-edmo/pr/kansas-doctor-sentenced-3-years-prison-8-million-medicare-fraud'
    'hhs-oig-2026-03-06-mexican-man-6-85m' = 'https://www.justice.gov/usao-wdtx/pr/mexican-man-sentenced-14-years-federal-prison-leading-685m-healthcare-fraud-scheme'
    'hhs-oig-2026-03-06-west-memphis-medicaid' = 'https://arkansasag.gov/news-release/attorney-general-griffin-announces-medicaid-fraud-conviction/'
    'hhs-oig-2026-03-06-rhode-island-plea' = 'https://www.mass.gov/news/ags-office-secures-guilty-plea-suspended-sentence-and-restitution-from-rhode-island-resident-who-stole-more-than-220000-from-worcester-rest-home-and-its-elderly-residents'
}

$labelFixes = @{
    'doj-2026-01-fraud-enforcement-division' = 'White House Fact Sheet'
    'cms-2026-01-minnesota-audit-announcement' = 'FOX 9 News Report'
    'cms-hhs-2026-01-minnesota-mission' = 'KSTP News Report'
    'cms-2026-01-california-hospice-investigation' = 'Hospice News Report'
    'cms-2026-01-27-newsom-demand' = 'Home Health Care News'
    'cms-2026-02-05-hospice-spreading' = "McKnight's Home Care"
    'whitehouse-2026-02-04-ca-task-force' = 'CBS News Report'
    'oig-2026-01-22-maine-autism-audit' = 'HHS-OIG News Release'
    'hhs-2026-02-04-ai-fraud-detection' = 'CMS Press Release'
    'cms-doj-2026-01-19-california-billion-return' = 'Fox News Report'
    'media-2025-01-azcir-propublica-az-medicaid-deaths' = 'AZCIR Investigation'
    'hhs-oig-2026-03-13-rocky-hill-pharmacy' = 'DOJ Press Release'
    'hhs-oig-2026-03-13-medical-center-shutdown' = 'HHS-OIG Enforcement'
    'hhs-oig-2026-03-12-az-cardiology-vein' = 'DOJ Press Release'
    'hhs-oig-2026-03-12-10-medicaid-providers' = 'Ohio AG Press Release'
    'hhs-oig-2026-03-11-greenville-ceo-indicted' = 'DOJ Press Release'
    'hhs-oig-2026-03-10-montgomery-home-care' = 'PA AG Press Release'
    'hhs-oig-2026-03-09-chiropractor-14-9m' = 'DOJ Press Release'
    'hhs-oig-2026-03-09-psychiatrist-360k' = 'DOJ Press Release'
    'hhs-oig-2026-03-09-dme-owner-59m' = 'DOJ Press Release'
    'hhs-oig-2026-03-06-amerisourcebergen-1m' = 'DOJ Press Release'
    'hhs-oig-2026-03-06-illinois-dme' = 'DOJ Press Release'
    'hhs-oig-2026-03-06-kansas-doctor-8m' = 'DOJ Press Release'
    'hhs-oig-2026-03-06-mexican-man-6-85m' = 'DOJ Press Release'
    'hhs-oig-2026-03-06-west-memphis-medicaid' = 'Arkansas AG Press Release'
    'hhs-oig-2026-03-06-rhode-island-plea' = 'MA AG Press Release'
}

foreach ($a in $j.actions) {
    if ($linkFixes.ContainsKey($a.id)) {
        $a.link = $linkFixes[$a.id]
        Write-Output "Fixed link: $($a.id)"
    }
    if ($labelFixes.ContainsKey($a.id)) {
        $a.link_label = $labelFixes[$a.id]
    }
}

# === 5. SAVE ===
$output = $j | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText('data/actions.json', $output, [System.Text.Encoding]::UTF8)
Write-Output ""
Write-Output "All fixes applied and saved. Total entries: $($j.actions.Count)"
