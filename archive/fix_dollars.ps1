$j = Get-Content 'data/actions.json' -Raw | ConvertFrom-Json

# Fix amount fields
$amountFixes = @{
    'hhs-oig-2026-03-12-az-cardiology-vein' = '$4.75 million'
    'hhs-oig-2026-03-10-montgomery-home-care' = '$1.7 million'
    'hhs-oig-2026-03-09-chiropractor-14-9m' = '$14.9 million'
    'hhs-oig-2026-03-09-psychiatrist-360k' = '$360,000'
    'hhs-oig-2026-03-09-dme-owner-59m' = '$59 million'
    'hhs-oig-2026-03-06-amerisourcebergen-1m' = '$1 million'
    'hhs-oig-2026-03-06-kansas-doctor-8m' = '$8 million'
    'hhs-oig-2026-03-06-mexican-man-6-85m' = '$6.85 million'
    'hhs-oig-2026-03-06-rhode-island-plea' = '$220,000+'
    'media-2026-01-08-doj-oklahoma-dme-30m-indictment' = '$30 million (claims); $17 million (paid)'
    'media-2026-01-28-hospice-news-ca-280-licenses-revoked' = '$1.6 billion (recovered from Medi-Cal); $2.5 billion (estimated LA fraud)'
    'media-2026-02-10-doj-mn-fraud-tourists-ai' = '$3.5 million'
    'media-2026-02-12-doj-chicago-10m-foreign-nationals' = '$10 million'
    'media-2026-03-05-doj-russian-400m-medicare-laundering' = '$400 million (fraudulent claims); $12.2 million (laundered)'
    'media-2026-03-11-fednet-cms-crush-ai-war-room' = '$2 billion (saved by AI war room since March 2025)'
    'media-2026-03-12-fox-la-doctor-600m-npi-fraud' = '$600 million (fraudulent billing)'
}

# Fix descriptions - replace stripped dollar amounts
$descFixes = @{
    'hhs-oig-2026-03-12-az-cardiology-vein' = @(
        @('.75 million to settle', '$4.75 million to settle')
    )
    'hhs-oig-2026-03-10-montgomery-home-care' = @(
        @('.7 million Medicaid', '$1.7 million Medicaid')
    )
    'hhs-oig-2026-03-09-chiropractor-14-9m' = @(
        @('.9 million healthcare', '$14.9 million healthcare')
    )
    'hhs-oig-2026-03-09-psychiatrist-360k' = @(
        @(',000 to settle', '$360,000 to settle')
    )
    'hhs-oig-2026-03-09-dme-owner-59m' = @(
        @(' million Medicare fraud scheme involving', '$59 million Medicare fraud scheme involving')
    )
    'hhs-oig-2026-03-06-amerisourcebergen-1m' = @(
        @('pay  million to resolve', 'pay $1 million to resolve')
    )
    'hhs-oig-2026-03-06-kansas-doctor-8m' = @(
        @(' million Medicare fraud scheme', '$8 million Medicare fraud scheme')
    )
    'hhs-oig-2026-03-06-mexican-man-6-85m' = @(
        @('.85 million healthcare', '$6.85 million healthcare')
    )
    'hhs-oig-2026-03-06-rhode-island-plea' = @(
        @(',000 for theft', '$220,000 for theft')
    )
    'media-2026-01-08-doj-oklahoma-dme-30m-indictment' = @(
        @('approximately  in false claims', 'approximately $30 million in false claims'),
        @('paid approximately .', 'paid approximately $17 million.'),
        @('misused + in COVID', 'misused $300K+ in COVID')
    )
    'media-2026-01-28-hospice-news-ca-280-licenses-revoked' = @(
        @('more than .6 billion', 'more than $1.6 billion')
    )
    'media-2026-02-10-doj-mn-fraud-tourists-ai' = @(
        @('of .5M', 'of $3.5M')
    )
    'media-2026-02-12-doj-chicago-10m-foreign-nationals' = @(
        @('submit  in fraudulent', 'submit $10 million in fraudulent')
    )
    'media-2026-03-05-doj-russian-400m-medicare-laundering' = @(
        @('submitted + in false', 'submitted $400M+ in false'),
        @('reimbursed .7M', 'reimbursed $16.7M'),
        @('of which .2M', 'of which $12.2M')
    )
    'media-2026-03-11-fednet-cms-crush-ai-war-room' = @(
        @('has saved  billion', 'has saved $2 billion')
    )
    'media-2026-03-12-fox-la-doctor-600m-npi-fraud' = @(
        @('bill nearly  to Medicare', 'bill nearly $600 million to Medicare'),
        @('including  in 2024', 'including $260 million in 2024')
    )
}

foreach ($a in $j.actions) {
    # Fix amounts
    if ($amountFixes.ContainsKey($a.id)) {
        $a.amount = $amountFixes[$a.id]
        Write-Output "Fixed amount: $($a.id) -> $($a.amount)"
    }

    # Fix descriptions
    if ($descFixes.ContainsKey($a.id)) {
        foreach ($pair in $descFixes[$a.id]) {
            $old = $pair[0]
            $new = $pair[1]
            if ($a.description.Contains($old)) {
                $a.description = $a.description.Replace($old, $new)
                Write-Output "  Fixed desc: '$old' -> '$new'"
            } else {
                Write-Output "  WARNING: '$old' not found in $($a.id)"
            }
        }
    }
}

# Save
$output = $j | ConvertTo-Json -Depth 10
$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $output, $utf8NoBOM)
Write-Output ""
Write-Output "Done. Saved."
