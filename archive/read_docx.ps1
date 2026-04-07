Add-Type -AssemblyName 'System.IO.Compression.FileSystem'
$zip = [System.IO.Compression.ZipFile]::OpenRead('C:\Users\khall\OneDrive\Documents\WSJ article text.docx')
$entry = $zip.GetEntry('word/document.xml')
$stream = $entry.Open()
$reader = New-Object System.IO.StreamReader($stream)
$xmlContent = [xml]$reader.ReadToEnd()
$reader.Close()
$zip.Dispose()
$ns = @{w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
$paragraphs = Select-Xml -Xml $xmlContent -XPath '//w:p' -Namespace $ns
foreach ($p in $paragraphs) {
    $texts = Select-Xml -Xml $p.Node -XPath './/w:t' -Namespace $ns
    $line = ($texts | ForEach-Object { $_.Node.InnerText }) -join ''
    if ($line.Trim()) { Write-Output $line.Trim() }
}
