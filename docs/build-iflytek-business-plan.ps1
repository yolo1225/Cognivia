[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sourcePath = Join-Path $PSScriptRoot '科大讯飞命题-商业计划书初稿.md'
$htmlPath = Join-Path $PSScriptRoot '科大讯飞命题-商业计划书.html'
$outputPath = Join-Path $projectRoot 'deliverables\Cognivia-科大讯飞命题商业计划书.docx'

$markdown = Get-Content -LiteralPath $sourcePath -Raw -Encoding utf8
$markdown = $markdown -replace '(?s)^# Cognivia.*?---\s*', ''
$markdown = $markdown -replace '(?m)^### ', '@@H2@@ '
$markdown = $markdown -replace '(?m)^## ', '# '
$markdown = $markdown -replace '(?m)^@@H2@@ ', '## '
$fragment = (ConvertFrom-Markdown -InputObject $markdown).Html

$cover = @'
<div class="cover">
  <p class="cover-kicker">全国大学生创业服务网 · 产业赛道 · 产教协同创新组</p>
  <h1>Cognivia</h1>
  <p class="cover-title">大模型驱动的自适应学习路径决策与伴学智能体</p>
  <p class="cover-subtitle">面向科大讯飞股份有限公司命题的商业计划书</p>
  <div class="cover-rule"></div>
  <p class="cover-meta">应用方向：人工智能应用开发实训</p>
  <p class="cover-meta">项目定位：可追溯知识治理与自适应伴学决策</p>
  <p class="cover-meta">文档版本：提交版基础文稿</p>
  <p class="cover-meta">日期：2026 年 9 月</p>
  <p class="cover-note">本文严格区分项目已验证能力与拟合作事项；未经授权，不宣称已接入科大讯飞产品、数据或平台。</p>
</div>
<div class="page-break"></div>
'@

$style = @'
<style>
@page { size: A4; margin: 2.2cm 2.0cm 1.9cm 2.0cm; }
body { font-family: "Microsoft YaHei", "SimSun", sans-serif; color: #172033; font-size: 10.5pt; line-height: 1.62; }
h1 { color: #143B66; font-size: 18pt; line-height: 1.35; margin: 22pt 0 10pt; padding-bottom: 5pt; border-bottom: 2px solid #2E75B6; page-break-after: avoid; }
h2 { color: #1F4E79; font-size: 13pt; line-height: 1.35; margin: 15pt 0 7pt; page-break-after: avoid; }
p { margin: 0 0 8pt; text-align: justify; }
li { margin: 3pt 0; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0 12pt; font-size: 9pt; page-break-inside: avoid; }
th { background: #1F4E79; color: #FFFFFF; font-weight: bold; padding: 6pt; text-align: left; }
td { border: 1px solid #C9D5E1; padding: 5pt; vertical-align: top; }
tr:nth-child(even) td { background: #F7FAFC; }
blockquote { margin: 10pt 0; padding: 8pt 11pt; background: #EFF6FC; border-left: 4px solid #2E75B6; color: #243B55; }
code { font-family: Consolas, "Microsoft YaHei", monospace; color: #174E7B; }
.page-break { page-break-before: always; }
.cover { min-height: 22cm; padding-top: 1.6cm; text-align: center; }
.cover h1 { border: 0; color: #143B66; font-size: 34pt; margin: 42pt 0 16pt; padding: 0; text-align: center; }
.cover-kicker { color: #2E75B6; font-size: 10.5pt; font-weight: bold; letter-spacing: 1pt; text-align: center; }
.cover-title { color: #172033; font-size: 22pt; font-weight: bold; line-height: 1.45; margin: 0 auto 16pt; text-align: center; }
.cover-subtitle { color: #4E6478; font-size: 14pt; margin: 0 auto 30pt; text-align: center; }
.cover-rule { background: #2E75B6; height: 3px; margin: 0 auto 28pt; width: 55%; }
.cover-meta { color: #334A62; font-size: 11.5pt; margin: 6pt 0; text-align: center; }
.cover-note { background: #EFF6FC; color: #425A70; font-size: 9pt; line-height: 1.5; margin: 34pt auto 0; padding: 10pt 14pt; text-align: left; width: 72%; }
</style>
'@

$html = "<!DOCTYPE html><html><head><meta charset=`"utf-8`">$style</head><body>$cover$fragment</body></html>"
Set-Content -LiteralPath $htmlPath -Value $html -Encoding utf8

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($htmlPath, $false, $false)

    $section = $document.Sections.Item(1)
    $section.PageSetup.TopMargin = 62
    $section.PageSetup.BottomMargin = 52
    $section.PageSetup.LeftMargin = 57
    $section.PageSetup.RightMargin = 57
    $section.PageSetup.DifferentFirstPageHeaderFooter = $true

    $header = $section.Headers.Item(1).Range
    $header.Text = 'Cognivia  |  自适应学习路径决策与伴学智能体'
    $header.ParagraphFormat.Alignment = 2
    $header.Font.NameFarEast = 'Microsoft YaHei'
    $header.Font.Size = 8.5
    $header.Font.Color = 7829367

    $footer = $section.Footers.Item(1).Range
    $footer.Text = 'Cognivia  |  第 '
    $footer.ParagraphFormat.Alignment = 1
    $footer.Font.NameFarEast = 'Microsoft YaHei'
    $footer.Font.Size = 9
    $footer.Collapse(0)
    $pageField = $footer.Fields.Add($footer, 33)
    $suffixRange = $pageField.Result.Duplicate
    $suffixRange.Collapse(0)
    $suffixRange.InsertAfter(' 页')

    $tocRange = $document.Content
    $tocRange.Find.ClearFormatting()
    $tocRange.Find.Text = '一、执行摘要'
    if ($tocRange.Find.Execute()) {
        $contentStart = $tocRange.Start
        $tocHeading = $document.Range($contentStart, $contentStart)
        $tocHeading.Text = "目录`r"
        $tocHeading = $document.Range($contentStart, $contentStart + 3)
        $tocHeading.Style = -2
        $tocHeading.ParagraphFormat.PageBreakBefore = $true
        $tocHeading.Font.NameFarEast = 'Microsoft YaHei'
        $tocHeading.Font.Size = 18
        $tocHeading.Font.Color = 6706756
        $tocInsert = $document.Range($contentStart + 3, $contentStart + 3)
        $document.TablesOfContents.Add($tocInsert, $true, 1, 2) | Out-Null

        $contentRange = $document.Content
        $contentRange.Find.ClearFormatting()
        $contentRange.Find.Text = '一、执行摘要'
        if ($contentRange.Find.Execute()) {
            $contentRange.ParagraphFormat.PageBreakBefore = $true
        }
    }

    foreach ($table in $document.Tables) {
        $table.Range.Font.NameFarEast = 'Microsoft YaHei'
        $table.Range.Font.Size = 9
        $table.Rows.Item(1).Range.Font.Bold = $true
    }

    foreach ($paragraph in $document.Paragraphs) {
        $text = $paragraph.Range.Text.Trim()
        $inTable = $paragraph.Range.Information(12)
        if ($paragraph.OutlineLevel -eq 10 -and -not $inTable -and $text -and
            $text -notmatch '^(目录$|Cognivia$|全国大学生创业服务网)') {
            $paragraph.Range.ParagraphFormat.FirstLineIndent = 21
            $paragraph.Range.ParagraphFormat.Alignment = 3
        }
    }

    $document.Fields.Update() | Out-Null
    $document.Repaginate()
    $document.SaveAs2($outputPath, 16)
}
finally {
    if ($null -ne $document) {
        $document.Close(0)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($document) | Out-Null
    }
    if ($null -ne $word) {
        $word.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
}

Write-Host "Generated $outputPath"
