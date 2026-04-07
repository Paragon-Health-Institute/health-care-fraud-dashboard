$file = 'C:\Users\khall\HealthcareFraudDashboard\data\actions.json'
$content = Get-Content $file -Raw -Encoding UTF8

# UTF-8 bytes for em dash (U+2014): 0xE2 0x80 0x94
# Read as Windows-1252: a-circumflex (U+00E2) + euro (U+20AC) + right-double-quote (U+201D)
$mojibakeEmDash = [char]0x00E2 + [char]0x20AC + [char]0x201D
$emDash = [char]0x2014

# UTF-8 bytes for en dash (U+2013): 0xE2 0x80 0x93
# Read as Windows-1252: a-circumflex (U+00E2) + euro (U+20AC) + left-double-quote (U+201C)
$mojibakeEnDash = [char]0x00E2 + [char]0x20AC + [char]0x201C
$enDash = [char]0x2013

# UTF-8 bytes for e-acute (U+00E9): 0xC3 0xA9
# Read as Windows-1252: A-tilde (U+00C3) + copyright (U+00A9)
$mojibakeEAcute = [char]0x00C3 + [char]0x00A9
$eAcute = [char]0x00E9

$fixed = $content
$fixed = $fixed -replace [regex]::Escape($mojibakeEmDash), $emDash
$fixed = $fixed -replace [regex]::Escape($mojibakeEnDash), $enDash
$fixed = $fixed -replace [regex]::Escape($mojibakeEAcute), $eAcute

$badLeft = ([regex]::Matches($fixed, [regex]::Escape([char]0x00E2 + [char]0x20AC))).Count
Write-Host "Remaining mojibake after fix: $badLeft"

[System.IO.File]::WriteAllText($file, $fixed, [System.Text.Encoding]::UTF8)
Write-Host "File saved."
