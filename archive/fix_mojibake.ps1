# Read file as raw text
$raw = [System.IO.File]::ReadAllText('data/actions.json', [System.Text.Encoding]::UTF8)

Write-Output "File length: $($raw.Length) chars"

# The mojibake is triple-encoded UTF-8. The em dash U+2014 bytes (E2 80 94)
# were treated as CP1252, producing â (U+00E2) € (U+20AC) " (U+0094->U+201D in some encodings)
# When re-encoded to UTF-8, each of those characters becomes multi-byte.

# Build the mojibake strings from their Unicode codepoints as they appear in the file
# Em dash: â + € + (control char 0x94 which in the file appears as right-double-quote U+201D or similar)
$emDashMoji = [char]0x00E2, [char]0x20AC, [char]0x201D -join ''  # â€" (right dq variant)
$enDashMoji = [char]0x00E2, [char]0x20AC, [char]0x201C -join ''  # â€" (left dq variant -- en dash 0x2013)
$enDashMoji2 = [char]0x00E2, [char]0x20AC, [char]0x0093 -join '' # alternate encoding
$rsqMoji = [char]0x00E2, [char]0x20AC, [char]0x2122 -join ''     # â€™ (right single quote)
$rsqMoji2 = [char]0x00E2, [char]0x20AC, [char]0x0099 -join ''    # alternate
$ellMoji = [char]0x00E2, [char]0x20AC, [char]0x00A6 -join ''     # â€¦ (ellipsis)
$eAcuteMoji = [char]0x00C3, [char]0x00A9 -join ''                 # Ã© -> é

# Count before
$count = 0
foreach ($pattern in @($emDashMoji, $enDashMoji, $enDashMoji2, $rsqMoji, $rsqMoji2, $ellMoji, $eAcuteMoji)) {
    $c = ($raw.Split($pattern).Length - 1)
    if ($c -gt 0) { Write-Output "  Pattern found $c times" }
    $count += $c
}

# Do replacements
$raw = $raw.Replace($emDashMoji, [string][char]0x2014)
$raw = $raw.Replace($enDashMoji, [string][char]0x2013)
$raw = $raw.Replace($enDashMoji2, [string][char]0x2013)
$raw = $raw.Replace($rsqMoji, [string][char]0x2019)
$raw = $raw.Replace($rsqMoji2, [string][char]0x2019)
$raw = $raw.Replace($ellMoji, [string][char]0x2026)
$raw = $raw.Replace($eAcuteMoji, [string][char]0x00E9)

Write-Output "Replacements applied"

# Write back
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $raw, $utf8NoBOM)
Write-Output "Saved. New length: $($raw.Length)"
