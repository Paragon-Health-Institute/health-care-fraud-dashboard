$j = Get-Content 'data/actions.json' -Raw | ConvertFrom-Json

# === DOUBLE-COUNTING FIXES ===

# Criminal: Zero out sub-cases of the $14.6B national takedown
$takedownSubcases = @(
    'doj-2025-06-operation-gold-rush',          # $10.6B - sub-case of takedown
    'doj-2025-06-opioid-fraud',                  # already 0
    'doj-2025-06-arizona-skin-grafts',           # already 0
    'doj-2025-06-gary-cox-dmerx-conviction',     # $1B - sub-case of takedown
    'doj-2025-06-farrukh-ali-arizona-substance-abuse'  # $650M - sub-case of takedown
)

# Criminal: Fichidzhyan $17M is part of the $16M CA hospice gang case (same ring)
# Keep the $16M on the gang sentenced entry, zero Fichidzhyan
$hospiceDups = @(
    'doj-2025-05-06-fichidzhyan-sentenced-hospice'  # $17M -> 0 (part of $16M CA hospice gang)
)

# Civil: FCA annual baseline is $5.7B - zero out individual FY2025 civil cases (before Oct 2025)
# Cases dated before Oct 1, 2025 are covered by FCA aggregate
$fy2025CivilCases = @(
    'doj-2025-12-dana-farber-grant-fraud-settlement',    # Dec 2025 = FY2026, keep
    'doj-2025-12-virginia-lab-kickbacks-settlement'       # Dec 2025 = FY2026, keep
    # All Jan-Sep 2026 cases are FY2026, keep those too
    # The FCA aggregate covers FY2025 (Oct 2024 - Sep 2025)
    # Actually looking again - these are all either FY2026 or the FCA aggregate itself
    # No individual FY2025 civil cases to zero out since they're all dated FY2026
)

# Audit: The semiannual reports overlap with CMS improper payments
# Spring covers Oct 2024 - Mar 2025, Fall covers Apr - Sep 2025 = combined FY2025
# CMS FY2025 improper payments ($56.5B) is the definitive FY2025 number
# The semiannual reports include OIG enforcement actions, not just improper payments
# They are different metrics - but summing all 3 is misleading
# Best approach: keep CMS improper payments as the definitive audit number,
# zero the semiannual reports since they aggregate differently
$auditOverlaps = @(
    'hhs-oig-2025-12-oig-spring-semiannual-report',  # $16.6B -> 0 (overlaps with individual audits + CMS total)
    'hhs-oig-2026-01-fall-semiannual-report'           # $19.04B -> 0 (same)
)

# CMS Admin: MN deferral of $259.5M overlaps with the earlier $380M MN audit announcement
# The Feb crackdown package ($259.5M) is the specific action; zero the earlier vague announcement
$cmsOverlaps = @(
    'cms-2026-01-minnesota-audit-announcement'  # $380M -> 0 (superseded by specific $259.5M deferral)
)

foreach ($a in $j.actions) {
    if ($a.id -in $takedownSubcases -and $a.amount_numeric -gt 0) {
        Write-Output "Zeroed takedown sub-case: $($a.id) ($($a.amount_numeric) -> 0)"
        $a.amount_numeric = 0
        $a.amount = $null
    }
    if ($a.id -in $hospiceDups -and $a.amount_numeric -gt 0) {
        Write-Output "Zeroed hospice dup: $($a.id) ($($a.amount_numeric) -> 0)"
        $a.amount_numeric = 0
        $a.amount = $null
    }
    if ($a.id -in $auditOverlaps -and $a.amount_numeric -gt 0) {
        Write-Output "Zeroed audit overlap: $($a.id) ($($a.amount_numeric) -> 0)"
        $a.amount_numeric = 0
        $a.amount = $null
    }
    if ($a.id -in $cmsOverlaps -and $a.amount_numeric -gt 0) {
        Write-Output "Zeroed CMS overlap: $($a.id) ($($a.amount_numeric) -> 0)"
        $a.amount_numeric = 0
        $a.amount = $null
    }
}

# === SAVE ===
$output = $j | ConvertTo-Json -Depth 10
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $output, $utf8NoBOM)
Write-Output ""
Write-Output "Double-counting fixes applied and saved."
