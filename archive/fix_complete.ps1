# STEP 1: Do all JSON-level fixes first (double-counting zeroing)
$j = Get-Content 'data/actions.json' -Raw | ConvertFrom-Json

$zeroOut = @(
    'doj-2025-06-gary-cox-dmerx-conviction',
    'doj-2025-06-farrukh-ali-arizona-substance-abuse',
    'doj-2025-05-06-fichidzhyan-sentenced-hospice',
    'hhs-oig-2025-12-oig-spring-semiannual-report',
    'hhs-oig-2026-01-fall-semiannual-report',
    'cms-2026-01-minnesota-audit-announcement'
)

foreach ($a in $j.actions) {
    if ($a.id -in $zeroOut -and $a.amount_numeric -gt 0) {
        Write-Output "Zeroed: $($a.id) ($($a.amount_numeric) -> 0)"
        $a.amount_numeric = 0
        $a.amount = $null
    }
}

# Save JSON
$output = $j | ConvertTo-Json -Depth 10
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $output, $utf8NoBOM)
Write-Output "JSON changes saved."

# STEP 2: Now do ALL text-level fixes on the raw file (mojibake, dollar signs)
$raw = [System.IO.File]::ReadAllText('data/actions.json', $utf8NoBOM)

# Fix mojibake - the ConvertTo-Json produces this pattern: Ã¢â‚¬â€ for em dash
# These are the actual Unicode codepoints in the file after JSON serialization
$emDash1 = [char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x201C -join ''   # en dash Ã¢â‚¬"
$emDash2 = [char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x201D -join ''   # not sure variant
$emDash3 = [char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x2014 -join ''   # another variant
$ellipsis1 = [char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x00A6 -join '' # ellipsis Ã¢â‚¬¦
$eAcute1 = [char]0x00C3, [char]0x00A9 -join ''                                # Ã© -> é

# Count before
$c1 = ([regex]::Matches($raw, [regex]::Escape($emDash1))).Count
$c2 = ([regex]::Matches($raw, [regex]::Escape($emDash2))).Count
Write-Output "emDash1 matches: $c1, emDash2 matches: $c2"

# But let me just search for what's actually there
# From the grep output: Ã¢â‚¬â€ which is: C3 A2 E2 82 AC E2 80 94 in UTF-8
# In Unicode: U+00C3 U+00A2 U+20AC U+2014
# And also: Ã¢â‚¬â€œ which would be for en dash
# Let me try all combinations

# Build from the hex we know
$patterns = @(
    @(([char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x2014 -join ''), [string][char]0x2014),  # em dash variant 1
    @(([char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x201C -join ''), [string][char]0x2013),  # en dash (â€œ = left dq)
    @(([char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x201D -join ''), [string][char]0x2014),  # em dash (â€ = right dq)
    @(([char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x00A6 -join ''), [string][char]0x2026),  # ellipsis
    @(([char]0x00C3, [char]0x00A2, [char]0x20AC, [char]0x2122 -join ''), [string][char]0x2019),  # right single quote
    @(([char]0x00C3, [char]0x00A9 -join ''), [string][char]0x00E9)                                # e-acute
)

foreach ($p in $patterns) {
    $count = ([regex]::Matches($raw, [regex]::Escape($p[0]))).Count
    if ($count -gt 0) {
        $raw = $raw.Replace($p[0], $p[1])
        Write-Output "Replaced $count occurrences of mojibake pattern (len=$($p[0].Length))"
    }
}

# Also try the simpler grep-visible patterns
# From grep output the pattern is literally: Ã¢â‚¬â€
$testStr = 'Ã¢â‚¬â€'
$tc = ([regex]::Matches($raw, [regex]::Escape($testStr))).Count
Write-Output "Literal 'Ã¢â‚¬â€' matches: $tc"

# Save
[System.IO.File]::WriteAllText('data/actions.json', $raw, $utf8NoBOM)
Write-Output "Text fixes saved."
