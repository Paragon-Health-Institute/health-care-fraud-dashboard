$raw = [System.IO.File]::ReadAllText('data/actions.json', [System.Text.Encoding]::UTF8)

$fixes = @(
    # hhs-oig entries with stripped $ in descriptions
    @{ old = 'agreed to pay .75 million to settle'; new = 'agreed to pay $4.75 million to settle' }
    @{ old = 'operating a .7 million Medicaid'; new = 'operating a $1.7 million Medicaid' }
    @{ old = 'a .9 million healthcare fraud'; new = 'a $14.9 million healthcare fraud' }
    @{ old = 'to pay ,000 to settle'; new = 'to pay $360,000 to settle' }
    @{ old = 'a  million Medicare fraud scheme involving fraudulent DME'; new = 'a $59 million Medicare fraud scheme involving fraudulent DME' }
    @{ old = 'to pay  million to resolve allegations of paying unlawful'; new = 'to pay $1 million to resolve allegations of paying unlawful' }
    @{ old = 'an  million Medicare fraud scheme'; new = 'an $8 million Medicare fraud scheme' }
    @{ old = 'a .85 million healthcare fraud'; new = 'a $6.85 million healthcare fraud' }
    @{ old = 'exceeding ,000 for theft'; new = 'exceeding $220,000 for theft' }
    # media entries
    @{ old = 'approximately  in false claims'; new = 'approximately $30 million in false claims' }
    @{ old = 'paid approximately .'; new = 'paid approximately $17 million.' }
    @{ old = 'misused + in COVID'; new = 'misused $300K+ in COVID' }
    @{ old = 'more than .6 billion in federal funds'; new = 'more than $1.6 billion in federal funds' }
    @{ old = 'of .5M'; new = 'of $3.5M' }
    @{ old = 'submit  in fraudulent billing to Medicare'; new = 'submit $10 million in fraudulent billing to Medicare' }
    @{ old = 'submitted + in false Medicare'; new = 'submitted $400M+ in false Medicare' }
    @{ old = 'reimbursed .7M'; new = 'reimbursed $16.7M' }
    @{ old = 'of which .2M was wired'; new = 'of which $12.2M was wired' }
    @{ old = 'has saved  billion since'; new = 'has saved $2 billion since' }
    @{ old = 'bill nearly  to Medicare'; new = 'bill nearly $600 million to Medicare' }
    @{ old = 'including  in 2024'; new = 'including $260 million in 2024' }
)

$count = 0
foreach ($fix in $fixes) {
    if ($raw.Contains($fix.old)) {
        $raw = $raw.Replace($fix.old, $fix.new)
        $count++
        Write-Output "Fixed: '$($fix.old)' -> '$($fix.new)'"
    } else {
        Write-Output "NOT FOUND: '$($fix.old)'"
    }
}

$utf8NoBOM = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText('data/actions.json', $raw, $utf8NoBOM)
Write-Output ""
Write-Output "Applied $count fixes. Saved."
