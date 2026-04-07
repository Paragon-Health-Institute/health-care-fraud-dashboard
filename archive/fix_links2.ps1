$path = 'C:\Users\khall\HealthcareFraudDashboard\data\actions.json'
$data = (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json)

# --- Link fixes ---
$linkFixes = @{
    'cms-2026-01-27-newsom-demand'             = 'https://www.mcknightshomecare.com/news/oz-accuses-california-governor-of-tolerating-home-care-fraud-requests-action-plan/'
    'cms-2026-02-05-hospice-spreading'         = 'https://www.cms.gov/newsroom/press-releases/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud'
    'cms-doj-2026-01-19-california-billion-return' = 'https://www.cms.gov/newsroom/press-releases/cms-increasing-oversight-states-illegally-using-federal-medicaid-funding-health-care-illegal'
    'hhs-2026-02-04-ai-fraud-detection'        = 'https://www.hhs.gov/press-room/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud.html'
    'doj-2025-05-12-white-collar-enforcement-plan' = 'https://www.justice.gov/opa/speech/head-criminal-division-matthew-r-galeotti-delivers-remarks-sifmas-anti-money-laundering'
}

# --- Specific tweet URLs found ---
# account -> post_url keyed by action id
$tweetFixes = @{
    'cms-2026-01-minnesota-audit-announcement' = @{ account = '@DrOzCMS'; url = 'https://x.com/DrOzCMS/status/2014797297670906325' }
    'cms-2026-01-27-newsom-demand'             = @{ account = '@DrOzCMS'; url = 'https://x.com/DrOzCMS/status/2017324143654363327' }
    'oig-2026-01-22-maine-autism-audit'        = @{ account = '@DrOzCMS'; url = 'https://x.com/DrOzCMS/status/2019894194685506029' }
}

foreach ($action in $data.actions) {
    if ($linkFixes.ContainsKey($action.id)) {
        Write-Host "LINK [$($action.id)]: $($action.link)" -ForegroundColor Yellow
        $action.link = $linkFixes[$action.id]
        Write-Host "  --> $($action.link)" -ForegroundColor Green
    }
    if ($tweetFixes.ContainsKey($action.id)) {
        $fix = $tweetFixes[$action.id]
        foreach ($post in $action.social_posts) {
            if ($post.account -eq $fix.account -or $post.account -eq '@JimONeill') {
                Write-Host "TWEET [$($action.id)] $($post.account): $($post.post_url)" -ForegroundColor Yellow
                $post.account  = $fix.account
                $post.post_url = $fix.url
                Write-Host "  --> $($post.post_url)" -ForegroundColor Cyan
                break
            }
        }
    }
}

Set-Content $path -Value ($data | ConvertTo-Json -Depth 20) -Encoding UTF8
Write-Host "`nDone." -ForegroundColor Green
