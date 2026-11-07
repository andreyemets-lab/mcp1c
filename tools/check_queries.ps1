# Проверка текстов запросов расширения на платформе: каждый текст из tools/query_texts.py
# разбирается методом Запрос.НайтиПараметры() во внешнем соединении с базой, где установлено
# расширение. Запросы не выполняются, данные не читаются. Код возврата 1 - есть ошибки.
param(
    [Parameter(Mandatory = $true)] [string]$Queries,
    [Parameter(Mandatory = $true)] [string]$Connection
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function M($o, $n, [object[]]$a) { $r = [System.__ComObject].InvokeMember($n, [Reflection.BindingFlags]::InvokeMethod, $null, $o, $a); ,$r }
function Err($e) { $x = $e.Exception; while ($x.InnerException) { $x = $x.InnerException }; $x.Message }

$list = Get-Content -LiteralPath $Queries -Raw -Encoding UTF8 | ConvertFrom-Json
$conn = (New-Object -ComObject V83.COMConnector).Connect($Connection)
$failed = 0
$skipped = 0
foreach ($item in $list) {
    if ($item.partial) { $skipped++; continue }
    try {
        # Строки из JSON приводятся к [string]: обертку PowerShell COM передает как объект.
        $query = M $conn 'NewObject' @('Запрос', [string]$item.text)
        [void](M $query 'НайтиПараметры' @())
    } catch {
        $failed++
        "$($item.file):$($item.line): $(Err $_)"
    }
}
"checked $($list.Count - $skipped), failed $failed, skipped (partial) $skipped"
if ($failed -gt 0) { exit 1 }
