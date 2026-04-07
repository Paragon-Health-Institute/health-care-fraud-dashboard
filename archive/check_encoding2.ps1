$file = 'C:\Users\khall\HealthcareFraudDashboard\data\actions.json'
$content = Get-Content $file -Raw -Encoding UTF8
$bad = [char]0x00E2 + [char]0x20AC
$matches = [regex]::Matches($content, [regex]::Escape($bad) + '.')
Write-Host "Remaining mojibake sequences (showing a-circ + euro + next char):"
$seen = @{}
foreach ($m in $matches) {
    $seq = $m.Value
    $lastChar = $seq[-1]
    $codepoint = [int][char]$lastChar
    $key = "U+{0:X4}" -f $codepoint
    if (-not $seen[$key]) {
        $seen[$key] = $true
        Write-Host "  Pattern: a-circ + euro + char U+$($codepoint.ToString('X4')) = '$lastChar'"
        # Show context
        $idx = $m.Index
        $start = [Math]::Max(0, $idx - 20)
        $end = [Math]::Min($content.Length, $idx + 23)
        Write-Host "  Context: ...$($content.Substring($start, $end - $start))..."
    }
}
