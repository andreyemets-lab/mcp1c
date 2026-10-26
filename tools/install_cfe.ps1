<#
Встановлює або оновлює розширення з .cfe через зовнішнє з'єднання (режим 1С:Підприємство): спершу
перевіряє застосовність до конфігурації бази, потім записує. Нове розширення створюється з вимкненими
безпечним режимом і захистом від небезпечних дій (README, «Встановлення»); у наявного властивості
не змінюються - лише вміст. Зміни діють для нових сеансів.

Якщо нова версія змінює структуру даних розширення, запис потребує монопольного доступу до бази:
завершіть сеанси, зокрема конфігуратор і агент EDT, підключені до неї. Запуск від користувача
з правом адміністрування.

Приклади:
  powershell -ExecutionPolicy Bypass -File tools\install_cfe.ps1 -CheckOnly `
    -Connection 'File="C:\Bases\Demo";Usr="Адміністратор";Pwd="";'
  powershell -ExecutionPolicy Bypass -File tools\install_cfe.ps1 -Cfe build\mcp1c.cfe `
    -Connection 'Srvr="app01";Ref="erp";Usr="Адміністратор";Pwd="...";'

Код виходу 1 - розширення не записано.
#>
param(
    [Parameter(Mandatory = $true)] [string]$Connection,
    [string]$Cfe = (Join-Path $PSScriptRoot '..\build\mcp1c.cfe'),
    [string]$Name = 'mcp1c',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Аргументи COM: рядки приводяться до [string], одиночний об'єкт передається через унарну кому -
# інакше PowerShell передає обгортку або розгортає колекцію 1С.
function P($Object, $Property) { $r = [System.__ComObject].InvokeMember($Property, [Reflection.BindingFlags]::GetProperty, $null, $Object, $null); , $r }
function S($Object, $Property, $Value) { [void][System.__ComObject].InvokeMember($Property, [Reflection.BindingFlags]::SetProperty, $null, $Object, @($Value)) }
function M($Object, $Method, [object[]]$Arguments) { $r = [System.__ComObject].InvokeMember($Method, [Reflection.BindingFlags]::InvokeMethod, $null, $Object, $Arguments); , $r }
function ErrorText($ErrorRecord) { $e = $ErrorRecord.Exception; while ($e.InnerException) { $e = $e.InnerException }; $e.Message }

function FindExtension($Manager) {
    # Получить(Отбор) через COM не приймає структуру відбору - пошук за іменем серед усіх розширень.
    $all = M $Manager 'Получить' @()
    for ($i = 0; $i -lt (M $all 'Количество' @()); $i++) {
        $item = M $all 'Получить' @($i)
        if ([string](P $item 'Имя') -eq $Name) { return , $item }
    }
    return $null
}

function Describe($Connection1C, $Extension) {
    'version {0}, hash {1}, safe mode {2}, active {3}' -f (P $Extension 'Версия'),
        (M $Connection1C 'Base64Строка' (, (P $Extension 'ХешСумма'))), (P $Extension 'БезопасныйРежим'), (P $Extension 'Активно')
}

try {
    $Cfe = (Resolve-Path $Cfe).Path
    'cfe: {0}, {1} bytes, SHA-256 {2}' -f $Cfe, (Get-Item $Cfe).Length, (Get-FileHash $Cfe -Algorithm SHA256).Hash
    $connection1C = (New-Object -ComObject V83.COMConnector).Connect($Connection)
    $manager = P $connection1C 'РасширенияКонфигурации'
    $extension = FindExtension $manager
    if ($null -eq $extension) {
        'extension {0}: not installed, a new one will be created' -f $Name
        $extension = M $manager 'Создать' @()
        S $extension 'БезопасныйРежим' $false
        $protection = M $connection1C 'NewObject' @([string]'ОписаниеЗащитыОтОпасныхДействий')
        S $protection 'ПредупреждатьОбОпасныхДействиях' $false
        S $extension 'ЗащитаОтОпасныхДействий' $protection
    } else {
        'before: ' + (Describe $connection1C $extension)
    }
    $data = M $connection1C 'NewObject' @([string]'ДвоичныеДанные', [string]$Cfe)
    $problems = M $extension 'ПроверитьВозможностьПрименения' @($data, $false)
    $critical = 0
    for ($i = 0; $i -lt (M $problems 'Количество' @()); $i++) {
        $problem = M $problems 'Получить' @($i)
        $importance = [string](M $connection1C 'String' (, (P $problem 'Важность')))
        if ($importance -match 'Критич|Critical') { $critical++ }
        "  [$importance] " + (P $problem 'Описание')
    }
    'applicability: {0} problem(s), critical {1}' -f (M $problems 'Количество' @()), $critical
    if ($CheckOnly) { 'check only: nothing written'; exit 0 }
    if ($critical -gt 0) { throw 'critical problems: nothing written' }
    [void](M $extension 'Записать' (, $data))
    'after: ' + (Describe $connection1C (FindExtension $manager))
} catch {
    'ERROR: ' + (ErrorText $_)
    exit 1
}
