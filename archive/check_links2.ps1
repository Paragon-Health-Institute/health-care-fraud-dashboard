$data = (Get-Content 'C:\Users\khall\HealthcareFraudDashboard\data\actions.json' -Raw | ConvertFrom-Json).actions

# Show vague links
Write-Host "=== VAGUE LINKS ===" -ForegroundColor Yellow
$vague = @('newsroom', 'usao-edky', 'usao-sdfl', 'usao-edny', '/opa"', 'index.html', 'reuters.com"', 'reports-and-publications', 'press-releases"')
foreach ($a in $data) {
    $isVague = $false
    foreach ($v in $vague) {
        if ($a.link -like "*$v*") { $isVague = $true }
    }
    if ($isVague) {
        Write-Host "$($a.id)"
        Write-Host "  title: $($a.title)"
        Write-Host "  link:  $($a.link)"
    }
}

Write-Host ""
Write-Host "=== SOCIAL POSTS ===" -ForegroundColor Yellow
foreach ($a in $data) {
    if ($a.social_posts.Count -gt 0) {
        Write-Host "$($a.id)"
        Write-Host "  title: $($a.title)"
        foreach ($p in $a.social_posts) {
            Write-Host "  account: $($p.account)  url: $($p.post_url)"
            Write-Host "  text: $($p.post_text)"
        }
    }
}
