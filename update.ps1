param([switch]$Silent)

$ErrorActionPreference = 'Continue'
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
$DataFile  = Join-Path $ScriptDir "data/actions.json"

$Keywords = @(
    'health care fraud', 'healthcare fraud', 'medicare fraud', 'medicaid fraud',
    'hospice fraud', 'home care fraud', 'home health fraud', 'prescription fraud',
    'opioid fraud', 'health fraud', 'fraud takedown',
    'false claims', 'false billing', 'improper billing', 'kickback', 'overbilling',
    'upcoding', 'phantom billing', 'identity theft.*medicare', 'durable medical',
    'program integrity'
)

# ALL matched items must also contain at least one healthcare-specific term
$HealthcareTerms = @(
    'medicare', 'medicaid', 'tricare', 'health care', 'healthcare', 'hospital',
    'clinic', 'physician', 'medical', 'patient', 'prescription', 'pharmacist',
    'pharmacy', 'hospice', 'home health', 'nursing home', 'assisted living',
    '\bcms\b', '\bhhs\b', '\boig\b', 'health insurance', 'health plan',
    'clinical', 'diagnosis', 'therapy', 'dental fraud', 'ambulance fraud',
    '\bdme\b', 'durable medical', 'behavioral health', 'substance abuse',
    'affordable care act', 'aca enrollment', 'chip program'
)

$Feeds = @(
    # --- Official agency feeds ---
    @{ Name = 'DOJ';     Agency = 'DOJ';     Url = 'https://www.justice.gov/news/rss';                       Enabled = $true; SourceType = 'official' },
    @{ Name = 'HHS-OIG'; Agency = 'HHS-OIG'; Url = 'https://oig.hhs.gov/rss/oig-rss.xml';                   Enabled = $true; SourceType = 'official' },
    @{ Name = 'CMS';     Agency = 'CMS';     Url = 'https://www.cms.gov/newsroom/rss/press-releases';        Enabled = $true; SourceType = 'official' },
    @{ Name = 'HHS';     Agency = 'HHS';     Url = 'https://www.hhs.gov/rss/news.xml';                       Enabled = $true; SourceType = 'official' },
    @{ Name = 'DOJ-USAO';Agency = 'DOJ';     Url = 'https://www.justice.gov/usao/pressreleases/rss';         Enabled = $true; SourceType = 'official' },
    @{ Name = 'GAO';     Agency = 'GAO';     Url = 'https://www.gao.gov/rss/reports.xml';                    Enabled = $true; SourceType = 'official' },
    @{ Name = 'H-Oversight'; Agency = 'Congress'; Url = 'https://oversight.house.gov/feed/';                  Enabled = $true; SourceType = 'official' },
    @{ Name = 'H-E&C';      Agency = 'Congress'; Url = 'https://energycommerce.house.gov/feed/';             Enabled = $true; SourceType = 'official' },
    @{ Name = 'S-Finance';   Agency = 'Congress'; Url = 'https://www.finance.senate.gov/rss/feeds/?type=press'; Enabled = $true; SourceType = 'official' },
    @{ Name = 'S-HELP';      Agency = 'Congress'; Url = 'https://www.help.senate.gov/rss/feeds/?type=press';   Enabled = $true; SourceType = 'official' },
    @{ Name = 'FDA';     Agency = 'FDA';     Url = 'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml'; Enabled = $true; SourceType = 'official' },
    @{ Name = 'DEA';     Agency = 'DEA';     Url = 'https://www.dea.gov/press-releases/rss'; Enabled = $true; SourceType = 'official' },
    # --- Media / investigative feeds (staged for review, not added directly) ---
    @{ Name = 'Hospice News';       Agency = 'Media'; Url = 'https://hospicenews.com/feed/';                          Enabled = $true; SourceType = 'news' },
    @{ Name = 'Home Health Care News'; Agency = 'Media'; Url = 'https://homehealthcarenews.com/feed/';                Enabled = $true; SourceType = 'news' },
    @{ Name = 'KFF Health News';    Agency = 'Media'; Url = 'https://kffhealthnews.org/feed/';                        Enabled = $true; SourceType = 'news' },
    @{ Name = 'Fierce Healthcare';  Agency = 'Media'; Url = 'https://www.fiercehealthcare.com/rss/xml';               Enabled = $true; SourceType = 'news' },
    @{ Name = 'ProPublica';         Agency = 'Media'; Url = 'https://www.propublica.org/feeds/propublica/main';        Enabled = $true; SourceType = 'news' },
    @{ Name = 'Google News';        Agency = 'Media'; Url = 'https://news.google.com/rss/search?q=%22healthcare+fraud%22+OR+%22medicare+fraud%22+OR+%22medicaid+fraud%22&hl=en-US&gl=US&ceid=US:en'; Enabled = $true; SourceType = 'news' },
    # --- State AG RSS feeds (where available) ---
    @{ Name = 'NC-AG';  Agency = 'State Agency'; Url = 'https://ncdoj.gov/category/news-releases/feed/';  Enabled = $true; SourceType = 'news' },
    @{ Name = 'PA-AG';  Agency = 'State Agency'; Url = 'https://www.attorneygeneral.gov/feed/';           Enabled = $true; SourceType = 'news' },
    # --- Google News: state AG / MFCU fraud coverage ---
    @{ Name = 'GN-AG-Medicaid';    Agency = 'Media'; Url = 'https://news.google.com/rss/search?q=%22attorney+general%22+%22medicaid+fraud%22&hl=en-US&gl=US&ceid=US:en'; Enabled = $true; SourceType = 'news' },
    @{ Name = 'GN-MFCU';           Agency = 'Media'; Url = 'https://news.google.com/rss/search?q=%22medicaid+fraud+control+unit%22+OR+%22MFCU%22+fraud&hl=en-US&gl=US&ceid=US:en'; Enabled = $true; SourceType = 'news' },
    @{ Name = 'GN-AG-Settlement';  Agency = 'Media'; Url = 'https://news.google.com/rss/search?q=%22attorney+general%22+%22healthcare+fraud%22+settlement&hl=en-US&gl=US&ceid=US:en'; Enabled = $true; SourceType = 'news' }
)

function Write-Log { param([string]$Msg, [string]$Color = 'White'); if (-not $Silent) { Write-Host "  $Msg" -ForegroundColor $Color } }
function Test-AnyKeyword { param([string]$Text); $lower = $Text.ToLower(); foreach ($kw in $Keywords) { if ($lower -match $kw) { return $true } }; return $false }
function Test-HealthcareContext { param([string]$Text); $lower = $Text.ToLower(); foreach ($term in $HealthcareTerms) { if ($lower -match $term) { return $true } }; return $false }

function Get-ActionType {
    param([string]$Title, [string]$Desc)
    $text = "$Title $Desc".ToLower()
    if ($text -match 'signed into law|enacted|passes bill|bill signed|legislation|executive order|presidential memo|law.*(takes|went) effect') { return 'Legislation' }
    if ($text -match 'hearing|committee\s+(hearing|held|examine|vote)|testimony|testif|subcommittee.*hearing|gao.*(report|finds|audit)|congressional.*report|senate.*report|house.*report') { return 'Congressional Hearing' }
    if ($text -match 'plead|convict|indict|charg|guilty|arrest|prosecut') { return 'Criminal Enforcement' }
    if ($text -match 'civil|settlement|civil.+action|false claims act')    { return 'Civil Action' }
    if ($text -match 'audit|review|report|oig')                            { return 'Audit' }
    if ($text -match 'rule|regulation|final.+rule|proposed.+rule|loophole'){ return 'Rule/Regulation' }
    if ($text -match 'task force|division|unit|strike force|creat')        { return 'Structural/Organizational' }
    if ($text -match 'investigat|fact.?find|mission')                      { return 'Investigation' }
    if ($text -match 'ai|artificial intelligence|machine learning')        { return 'Technology/Innovation' }
    return 'Administrative Action'
}

function Get-StateName {
    param([string]$Text)
    $stateMap = @{ 'Alabama'='AL';'Alaska'='AK';'Arizona'='AZ';'Arkansas'='AR';'California'='CA';'Colorado'='CO';'Connecticut'='CT';'Delaware'='DE';'Florida'='FL';'Georgia'='GA';'Hawaii'='HI';'Idaho'='ID';'Illinois'='IL';'Indiana'='IN';'Iowa'='IA';'Kansas'='KS';'Kentucky'='KY';'Louisiana'='LA';'Maine'='ME';'Maryland'='MD';'Massachusetts'='MA';'Michigan'='MI';'Minnesota'='MN';'Mississippi'='MS';'Missouri'='MO';'Montana'='MT';'Nebraska'='NE';'Nevada'='NV';'New Hampshire'='NH';'New Jersey'='NJ';'New Mexico'='NM';'New York'='NY';'North Carolina'='NC';'North Dakota'='ND';'Ohio'='OH';'Oklahoma'='OK';'Oregon'='OR';'Pennsylvania'='PA';'Rhode Island'='RI';'South Carolina'='SC';'South Dakota'='SD';'Tennessee'='TN';'Texas'='TX';'Utah'='UT';'Vermont'='VT';'Virginia'='VA';'Washington'='WA';'West Virginia'='WV';'Wisconsin'='WI';'Wyoming'='WY' }
    foreach ($state in $stateMap.Keys) { if ($Text -match "\b$state\b") { return $stateMap[$state] } }
    return $null
}

function Get-ExtractAmount {
    param([string]$Text)
    if ($Text -match '\$[\d,]+(?:\.\d+)?\s*billion') { return @{ display = $Matches[0]; numeric = [double]($Matches[0] -replace '[\$,billion\s]','') * 1e9 } }
    if ($Text -match '\$[\d,]+(?:\.\d+)?\s*million')  { return @{ display = $Matches[0]; numeric = [double]($Matches[0] -replace '[\$,million\s]','') * 1e6 } }
    return $null
}

function New-ActionId {
    param([string]$Agency, [string]$Date, [string]$Link)
    $hash = [System.Math]::Abs(($Link ?? $Date + $Agency).GetHashCode())
    return "$($Agency.ToLower() -replace '\W','-')-$Date-$hash"
}

Write-Log "Loading existing data..." Cyan
$data = Get-Content $DataFile -Raw -Encoding UTF8 | ConvertFrom-Json

# Load pending media items too (for dedup)
$PendingFile = Join-Path $ScriptDir "data/pending.json"
$pendingData = if (Test-Path $PendingFile) { Get-Content $PendingFile -Raw -Encoding UTF8 | ConvertFrom-Json } else { @{ items = @() } }

$existingLinks = @{}
foreach ($a in $data.actions) { if ($a.link) { $existingLinks[$a.link] = $true } }
foreach ($a in $pendingData.items) { if ($a.link) { $existingLinks[$a.link] = $true } }

$added = 0
$mediaAdded = 0
$newActions = [System.Collections.Generic.List[object]]::new()
$newMedia   = [System.Collections.Generic.List[object]]::new()

foreach ($feed in ($Feeds | Where-Object { $_.Enabled })) {
    Write-Log "Fetching $($feed.Name)..." White
    try {
        $resp = Invoke-WebRequest -Uri $feed.Url -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
        [xml]$xml = $resp.Content
        $items = $xml.rss.channel.item
        if (-not $items) { $items = $xml.feed.entry }
        if (-not $items) { continue }

        $count = 0
        foreach ($item in $items) {
            $title   = ($item.title.'#text' ?? $item.title) -as [string]
            $desc    = ($item.description.'#text' ?? $item.description ?? $item.summary.'#text' ?? '') -as [string]
            $link    = ($item.link ?? $item.link.href ?? '') -as [string]
            $pubDate = ($item.pubDate ?? $item.published ?? $item.updated ?? '') -as [string]

            if (-not $title) { continue }
            $descClean = $desc -replace '<[^>]+>', '' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&nbsp;',' '
            $descClean = $descClean.Trim()

            $searchText = "$title $descClean"
            if (-not (Test-AnyKeyword $searchText)) { continue }
            if (-not (Test-HealthcareContext $searchText)) { continue }
            # Media feeds require fraud keyword in TITLE (not just description) to reduce noise
            if ($feed.SourceType -eq 'news' -and -not (Test-AnyKeyword $title)) { continue }
            if ($link -and $existingLinks.ContainsKey($link)) { continue }

            $dateStr = try { [DateTime]::Parse($pubDate).ToString('yyyy-MM-dd') } catch { (Get-Date).ToString('yyyy-MM-dd') }
            $amtInfo  = Get-ExtractAmount "$title $descClean"
            $stateAbb = Get-StateName "$title $descClean"
            $atype    = Get-ActionType $title $descClean

            $isMedia    = $feed.SourceType -eq 'news'

            # Federal Enforcement tab rule: non-media items MUST link to a
            # .gov source. Drop anything else, even if real — see project memory.
            if (-not $isMedia -and $link) {
                try {
                    $host = ([Uri]$link).Host.ToLower() -replace '^www\.',''
                    if (-not ($host.EndsWith('.gov') -or $host.EndsWith('.mil'))) {
                        Write-Log "  skipping non-.gov link for enforcement candidate: $link" Yellow
                        continue
                    }
                } catch { continue }
            }

            $idPrefix   = $isMedia ? 'media' : ($feed.Agency.ToLower() -replace '\W','-')
            $linkLabel  = $isMedia ? "$($feed.Name) Report" : "$($feed.Name) Press Release"
            $actionType = $isMedia ? 'Investigative Report' : $atype
            $amtDisp    = $amtInfo ? $amtInfo.display : $null
            $amtNum     = $amtInfo ? $amtInfo.numeric : 0

            # NOTE: description field is intentionally NOT written.
            # Tags are left empty here — Python ingest (update.py / enrich.py)
            # is the canonical tag generator and applies the allowlist in
            # tag_allowlist.py. See project memory for details.
            $entry = [PSCustomObject]@{
                id             = "$idPrefix-$dateStr-$([System.Math]::Abs(($link ?? $dateStr + $feed.Agency).GetHashCode()))"
                date           = $dateStr
                agency         = $feed.Agency
                type           = $actionType
                title          = ($title -replace '\s+', ' ').Trim()
                amount         = $amtDisp
                amount_numeric = $amtNum
                officials      = @()
                link           = $link
                link_label     = $linkLabel
                social_posts   = @()
                tags           = @()
                entities       = @()
                state          = $stateAbb
                source_type    = $feed.SourceType
                auto_fetched   = $true
            }
            if ($isMedia) {
                $newMedia.Add($entry)
                $mediaAdded++
            } else {
                $newActions.Add($entry)
                $added++
            }
            if ($link) { $existingLinks[$link] = $true }
            $count++
        }
        Write-Log "  $($feed.Name): $count new items." $(if ($count -gt 0) {'Green'} else {'Gray'})
    } catch {
        Write-Log "  WARNING: $($feed.Name) - $($_.Exception.Message)" Yellow
    }
}

$data.metadata.last_updated = (Get-Date).ToString('o')

if ($added -gt 0) {
    $all = [System.Collections.Generic.List[object]]::new()
    foreach ($a in $data.actions) { $all.Add($a) }
    foreach ($a in $newActions) { $all.Add($a) }
    $data.actions = $all.ToArray()
    Write-Log "Added $added official action(s)." Green
} else {
    Write-Log "No new official actions found." Cyan
}

# Save official actions
$data | ConvertTo-Json -Depth 10 | Set-Content $DataFile -Encoding UTF8

# Save media items to pending file for review
if ($mediaAdded -gt 0) {
    $allPending = [System.Collections.Generic.List[object]]::new()
    foreach ($a in $pendingData.items) { $allPending.Add($a) }
    foreach ($a in $newMedia) { $allPending.Add($a) }
    $pendingOut = @{ updated = (Get-Date).ToString('o'); items = $allPending.ToArray() }
    $pendingOut | ConvertTo-Json -Depth 10 | Set-Content $PendingFile -Encoding UTF8
    Write-Log "Staged $mediaAdded media item(s) for review." Yellow
}

Write-Log "Saved." Green
Write-Output "ADDED:$added MEDIA_STAGED:$mediaAdded"
