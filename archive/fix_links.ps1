$path = 'C:\Users\khall\HealthcareFraudDashboard\data\actions.json'
$json = Get-Content $path -Raw -Encoding UTF8
$data = $json | ConvertFrom-Json

$fixes = @{
    'doj-2025-03-kentucky-addiction'          = 'https://www.justice.gov/opa/pr/three-convicted-fraudulently-billing-over-8-million-medicare-and-medicaid-through-opioid'
    'doj-2025-11-florida-aca-enrollment'       = 'https://www.justice.gov/opa/pr/president-insurance-brokerage-firm-and-ceo-marketing-company-convicted-233m-affordable-care'
    'doj-2026-01-15-brooklyn-daycare'          = 'https://www.justice.gov/usao-edny/pr/two-individuals-plead-guilty-68-million-fraud-scheme-brooklyn-based-adult-day-cares'
    'doj-2026-01-22-florida-nursing'           = 'https://www.justice.gov/opa/pr/florida-nursing-assistant-convicted-114m-health-care-fraud-scheme-targeting-medicare'
    'doj-2026-01-fraud-enforcement-division'   = 'https://www.whitehouse.gov/fact-sheets/2026/01/fact-sheet-president-donald-j-trump-establishes-new-department-of-justice-division-for-national-fraud-enforcement/'
    'cms-2026-01-minnesota-audit-announcement' = 'https://www.cms.gov/newsroom/press-releases/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud'
    'cms-hhs-2026-01-minnesota-mission'        = 'https://www.hhs.gov/press-room/trump-administration-prioritizes-affordability-announcing-major-crackdown-health-care-fraud.html'
    'cms-2026-01-california-hospice-investigation' = 'https://www.cms.gov/blog/cms-taking-action-address-benefit-integrity-issues-related-hospice-care'
    'oig-2026-01-22-maine-autism-audit'        = 'https://oig.hhs.gov/newsroom/news-releases-articles/hhs-oig-audit-finds-maine-made-at-least-456-million-in-improper-medicaid-payments-for-autism-services/'
    'cms-2026-01-medicaid-financing-loophole'  = 'https://www.cms.gov/newsroom/press-releases/cms-shuts-down-massive-medicaid-tax-loophole-saving-billions-federal-taxpayers-restoring-federal'
    'cms-2026-01-14-california-illegal-immigrants' = 'https://www.cms.gov/newsroom/press-releases/cms-increasing-oversight-states-illegally-using-federal-medicaid-funding-health-care-illegal'
    'whitehouse-2026-02-04-ca-task-force'      = 'https://www.whitehouse.gov/presidential-actions/2026/02/protecting-the-national-security-and-welfare-of-the-united-states-and-its-citizens-from-criminal-actors-and-other-public-safety-threats/'
}

$updated = 0
foreach ($action in $data.actions) {
    # Fix main links
    if ($fixes.ContainsKey($action.id)) {
        $old = $action.link
        $action.link = $fixes[$action.id]
        Write-Host "LINK [$($action.id)]: $old -> $($action.link)" -ForegroundColor Green
        $updated++
    }

    # Fix social posts: @DrOz -> @DrOzCMS, update URLs
    foreach ($post in $action.social_posts) {
        if ($post.account -eq '@DrOz') {
            $post.account = '@DrOzCMS'
            $post.post_url = 'https://x.com/DrOzCMS'
            Write-Host "SOCIAL [$($action.id)]: @DrOz -> @DrOzCMS" -ForegroundColor Cyan
            $updated++
        }
    }
}

# Apply the one confirmed specific tweet URL (Newsom/Medicare post, late Jan 2026)
foreach ($action in $data.actions) {
    if ($action.id -eq 'cms-2026-01-27-newsom-demand') {
        foreach ($post in $action.social_posts) {
            if ($post.account -eq '@DrOzCMS') {
                $post.post_url = 'https://x.com/DrOzCMS/status/2017324143654363327'
                Write-Host "TWEET [$($action.id)]: set specific post URL" -ForegroundColor Cyan
            }
        }
    }
}

$out = $data | ConvertTo-Json -Depth 20
Set-Content $path -Value $out -Encoding UTF8
Write-Host ""
Write-Host "Done. $updated items updated." -ForegroundColor Green
