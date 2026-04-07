$srcFile = 'C:\Users\khall\.claude\projects\C--windows-system32\d682ea9e-d3ec-4109-a29e-35e650185a10\tool-results\toolu_01HD24C3qLmJ5BfWZxoZ4PaW.json'
$raw = Get-Content $srcFile -Raw

# The file wraps content in a JSON structure - find the text field
$parsed = $raw | ConvertFrom-Json

# It's an array of tool result objects
foreach ($item in $parsed) {
    if ($item.type -eq 'text') {
        $text = $item.text
        # Extract the JSON array from the text
        $start = $text.IndexOf('[')
        $end   = $text.LastIndexOf(']')
        if ($start -ge 0 -and $end -gt $start) {
            $jsonArray = $text.Substring($start, $end - $start + 1)
            Set-Content -Path 'C:\Users\khall\HealthcareFraudDashboard\research_actions.json' -Value $jsonArray -Encoding UTF8
            Write-Host "Extracted JSON array, length: $($jsonArray.Length)"
            # Count entries
            $actions = $jsonArray | ConvertFrom-Json
            Write-Host "Number of actions: $($actions.Count)"
            break
        }
    }
}
