# === STEP 1: Remove duplicate media entries via JSON ===
$j = Get-Content 'data/actions.json' -Raw | ConvertFrom-Json

$removeIds = @(
    'media-2026-03-11-867051112',
    'media-2026-03-09-1806600621',
    'media-2025-03-26-seoul-medical-62m-ma-upcoding',
    'media-2025-04-21-walgreens-300m-opioid-settlement',
    'media-2025-04-29-gilead-202m-hiv-kickbacks',
    'media-2025-05-07-fresno-31m-kickback-settlement',
    'media-2025-05-ca-hospice-armenian-crime-ring',
    'media-2025-01-09-wavy-chesapeake-hospital-indictment',
    'media-2025-10-07-cbs-arizona-wound-graft-sentencing',
    'media-2025-11-10-hospice-news-ca-tx-fraud-sentencings',
    'media-2025-11-15-fierce-cms-improper-payments',
    'media-2026-02-03-washington-monthly-cms-ma-crackdown',
    'media-2026-01-27-washington-monthly-uhg-upcoding',
    'media-2026-01-02-cnn-minnesota-fraud-key-figures'
)

$before = $j.actions.Count
$j.actions = @($j.actions | Where-Object { $_.id -notin $removeIds })
$after = $j.actions.Count
Write-Output "Removed $($before - $after) duplicate media entries ($before -> $after)"

# Save JSON (this preserves encoding properly)
$output = $j | ConvertTo-Json -Depth 10
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $output, $utf8NoBOM)

# === STEP 2: Fix dollar signs via raw string replacement ===
$raw = [System.IO.File]::ReadAllText('data/actions.json', [System.Text.Encoding]::UTF8)

# Amount field fixes (these are JSON-escaped strings)
$raw = $raw.Replace('"amount":  ".75 million"', '"amount":  "$4.75 million"')
$raw = $raw.Replace('"amount":  ".7 million"', '"amount":  "$1.7 million"')
$raw = $raw.Replace('"amount":  ".9 million"', '"amount":  "$14.9 million"')
$raw = $raw.Replace('"amount":  ",000"', '"amount":  "$360,000"')
$raw = $raw.Replace('"amount":  " million",', '"amount":  "$59 million",')  # dme-owner context
$raw = $raw.Replace('"amount":  ",000+"', '"amount":  "$220,000+"')
$raw = $raw.Replace('"amount":  ".85 million"', '"amount":  "$6.85 million"')
$raw = $raw.Replace('"amount":  " million (claims);  million (paid)"', '"amount":  "$30 million (claims); $17 million (paid)"')
$raw = $raw.Replace('"amount":  ".6 billion (recovered from Medi-Cal); .5 billion (estimated LA fraud)"', '"amount":  "$1.6 billion (recovered from Medi-Cal); $2.5 billion (estimated LA fraud)"')
$raw = $raw.Replace('"amount":  ".5 million"', '"amount":  "$3.5 million"')
$raw = $raw.Replace('"amount":  " million (fraudulent claims); .2 million (laundered)"', '"amount":  "$400 million (fraudulent claims); $12.2 million (laundered)"')
$raw = $raw.Replace('"amount":  " billion (saved by AI war room since March 2025)"', '"amount":  "$2 billion (saved by AI war room since March 2025)"')
$raw = $raw.Replace('"amount":  " million (fraudulent billing)"', '"amount":  "$600 million (fraudulent billing)"')

# Description fixes - unique context strings
$raw = $raw.Replace('to pay .75 million to settle', 'to pay $4.75 million to settle')
$raw = $raw.Replace('a .7 million Medicaid fraud', 'a $1.7 million Medicaid fraud')
$raw = $raw.Replace('a .9 million healthcare fraud', 'a $14.9 million healthcare fraud')
$raw = $raw.Replace('pay ,000 to settle civil', 'pay $360,000 to settle civil')
$raw = $raw.Replace('a  million Medicare fraud scheme involving fraudulent DME', 'a $59 million Medicare fraud scheme involving fraudulent DME')
$raw = $raw.Replace('pay  million to resolve allegations of paying unlawful', 'pay $1 million to resolve allegations of paying unlawful')
$raw = $raw.Replace('an  million Medicare fraud scheme', 'an $8 million Medicare fraud scheme')
$raw = $raw.Replace('a .85 million healthcare fraud operation', 'a $6.85 million healthcare fraud operation')
$raw = $raw.Replace('exceeding ,000 for theft', 'exceeding $220,000 for theft')
$raw = $raw.Replace('approximately  in false claims', 'approximately $30 million in false claims')
$raw = $raw.Replace('paid approximately .', 'paid approximately $17 million.')
$raw = $raw.Replace('misused + in COVID', 'misused $300K+ in COVID')
$raw = $raw.Replace('more than .6 billion in federal funds', 'more than $1.6 billion in federal funds')
$raw = $raw.Replace('program of .5M', 'program of $3.5M')
$raw = $raw.Replace('submit  in fraudulent billing', 'submit $10 million in fraudulent billing')
$raw = $raw.Replace('submitted + in false Medicare', 'submitted $400M+ in false Medicare')
$raw = $raw.Replace('reimbursed .7M', 'reimbursed $16.7M')
$raw = $raw.Replace('of which .2M was wired', 'of which $12.2M was wired')
$raw = $raw.Replace('has saved  billion since', 'has saved $2 billion since')
$raw = $raw.Replace('bill nearly  to Medicare', 'bill nearly $600 million to Medicare')
$raw = $raw.Replace('including  in 2024', 'including $260 million in 2024')

# Handle remaining " million" amount fields that haven't been caught
# These are for amerisourcebergen and kansas-doctor which share the generic pattern
# Already handled by specific context above, but let's check for any " million" amounts left

[System.IO.File]::WriteAllText('data/actions.json', $raw, $utf8NoBOM)
Write-Output "Dollar sign fixes applied. Saved."

# === STEP 3: Verify ===
$j2 = Get-Content 'data/actions.json' -Raw | ConvertFrom-Json
$broken = @()
foreach ($a in $j2.actions) {
    if ($a.amount -ne $null -and ($a.amount -match '^\.' -or $a.amount -match '^,' -or $a.amount -match '^ [a-z]')) {
        $broken += "$($a.id): $($a.amount)"
    }
}
if ($broken.Count -gt 0) {
    Write-Output "STILL BROKEN amounts:"
    $broken | ForEach-Object { Write-Output "  $_" }
} else {
    Write-Output "All amount fields look correct."
}

# Check for " million" pattern in amounts (two leading spaces = missing $+number)
foreach ($a in $j2.actions) {
    if ($a.amount -ne $null -and $a.amount -match '^ +million') {
        Write-Output "STILL BROKEN: $($a.id): '$($a.amount)'"
    }
}
