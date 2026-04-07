$raw = [System.IO.File]::ReadAllText('data/actions.json', [System.Text.Encoding]::UTF8)

# Fix any remaining mojibake - scan for the actual byte patterns
# Check for Ã© (C3 A9 in UTF-8 when the file has double-encoded é)
$eAcuteMoji = [char]0x00C3, [char]0x00A9 -join ''
if ($raw.Contains($eAcuteMoji)) {
    $raw = $raw.Replace($eAcuteMoji, [string][char]0x00E9)
    Write-Output "Fixed e-acute mojibake"
}

# Check for any remaining â patterns
$patterns = @(
    @([char]0x00E2, [char]0x20AC, [char]0x201D -join '', [string][char]0x2014),  # em dash
    @([char]0x00E2, [char]0x20AC, [char]0x201C -join '', [string][char]0x2013),  # en dash
    @([char]0x00E2, [char]0x20AC, [char]0x2122 -join '', [string][char]0x2019),  # right single quote
    @([char]0x00E2, [char]0x20AC, [char]0x2026 -join '', [string][char]0x2026)   # ellipsis
)
foreach ($p in $patterns) {
    if ($raw.Contains($p[0])) {
        $raw = $raw.Replace($p[0], $p[1])
        Write-Output "Fixed pattern: $($p[0].Length) chars -> $($p[1])"
    }
}

# Parse JSON
$j = $raw | ConvertFrom-Json

# === REMOVE DUPLICATE MEDIA ENTRIES ===
$removeIds = @(
    # Media that duplicates official DOJ/CMS entries
    'media-2026-03-11-867051112',                    # Becker's on Aetna (dup of doj-2026-03-11-aetna-fca-settlement)
    'media-2026-03-09-1806600621',                   # Hospice News on Oregon bill (dup of legislation-2026-03-04-oregon-hospice-fraud-bill)
    'media-2025-03-26-seoul-medical-62m-ma-upcoding',# dup of doj-2025-03-26-seoul-medical-medicare-advantage
    'media-2025-04-21-walgreens-300m-opioid-settlement', # dup of doj-2025-04-21-walgreens-opioid-settlement
    'media-2025-04-29-gilead-202m-hiv-kickbacks',    # dup of doj-2025-04-29-gilead-sciences-hiv-kickbacks
    'media-2025-05-07-fresno-31m-kickback-settlement', # dup of doj-2025-05-14-fresno-community-health-fca
    'media-2025-05-ca-hospice-armenian-crime-ring',  # dup of doj-2025-11-california-hospice-gang-sentenced
    'media-2025-01-09-wavy-chesapeake-hospital-indictment', # dup of doj-2025-01-08-chesapeake-hospital-indictment
    'media-2025-10-07-cbs-arizona-wound-graft-sentencing', # dup of doj-2025-01-31-arizona-wound-graft-plea
    # Commentary/opinion not exposing new fraud
    'media-2025-11-10-hospice-news-ca-tx-fraud-sentencings', # covers cases already in official entries
    'media-2025-11-15-fierce-cms-improper-payments', # reports CMS data already in cms-2026-01-fy2025-improper-payments
    'media-2026-02-03-washington-monthly-cms-ma-crackdown', # opinion on existing MA actions
    'media-2026-01-27-washington-monthly-uhg-upcoding', # opinion, overlaps Grassley report
    'media-2026-01-02-cnn-minnesota-fraud-key-figures'  # profiles existing MN fraud coverage
)

$before = $j.actions.Count
$j.actions = @($j.actions | Where-Object { $_.id -notin $removeIds })
$after = $j.actions.Count
Write-Output "Removed $($before - $after) duplicate media entries ($before -> $after)"

# === SAVE ===
$output = $j | ConvertTo-Json -Depth 10
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $output, $utf8NoBOM)
Write-Output "Saved."
