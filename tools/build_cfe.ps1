<#
Збирає .cfe розширення з проєкту EDT без робочої області користувача й без його бази:
EDT CLI у тимчасовій робочій області -> перевірка проєкту EDT -> XML -> тимчасова файлова база ->
перевірка конфігурації -> .cfe.

Основна конфігурація тимчасової бази - заготовка з однією мовою «Русский»: розширення не запозичує
об'єктів, крім кореня конфігурації й мови, а запозичені об'єкти зіставляються за іменем, тож .cfe
застосовується до будь-якої конфігурації з цією мовою. Перевірка конфігурації (/CheckConfig) компілює
модулі розширення платформою в усіх контекстах; помилка перевірки зупиняє збирання. Перевірка проєкту
EDT (validate) - ті самі перевірки, що в робочій області EDT з налаштуваннями за замовчуванням, зокрема
типи властивостей структур за документуючими коментарями; будь-яке зауваження зупиняє збирання
(-NoValidate - лише показати).

Приклади:
  powershell -ExecutionPolicy Bypass -File tools\build_cfe.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_cfe.ps1 -Output C:\dist\mcp1c.cfe `
    -Platform 'C:\Program Files\1cv8\8.3.27.2130\bin\1cv8.exe'

Потрібні 1C:EDT (1cedtcli.exe) і платформа 1С (1cv8.exe) тієї ж або новішої версії, що Runtime-Version
у DT-INF/PROJECT.PMF проєкту. Код виходу 1 - збирання не вдалося; подробиці - у журналі в -WorkDir.
#>
param(
    [string]$Project = (Join-Path $PSScriptRoot '..\exts\mcp1c'),
    [string]$Output = (Join-Path $PSScriptRoot '..\build\mcp1c.cfe'),
    [string]$Platform = '',
    [string]$EdtCli = '',
    [string]$WorkDir = (Join-Path $env:TEMP 'mcp1c-build-cfe'),
    [switch]$NoCheck,
    [switch]$NoValidate
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$utf8 = New-Object System.Text.UTF8Encoding $false
$log = Join-Path $WorkDir 'build.log'

function Log([string]$Text) {
    $line = '{0:HH:mm:ss} {1}' -f (Get-Date), $Text
    [IO.File]::AppendAllText($log, $line + "`r`n", $utf8)
    # Write-Host, а не вивід функції: Run повертає лише код виходу.
    Write-Host $line
}

function Quote([string]$Text) { '"' + $Text + '"' }

function WriteText([string]$Path, [string]$Text) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
    [IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n").Replace("`n", "`r`n"), $utf8)
}

function ReadAny([string]$Path) {
    # Журнали платформи й EDT бувають в UTF-8, UTF-16 і Windows-1251.
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 2 -and (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or $bytes[1] -eq 0)) {
        return [Text.Encoding]::Unicode.GetString($bytes).TrimStart([char]0xFEFF)
    }
    try { return (New-Object System.Text.UTF8Encoding $false, $true).GetString($bytes).TrimStart([char]0xFEFF) }
    catch { return [Text.Encoding]::GetEncoding(1251).GetString($bytes) }
}

function Run([string]$Name, [string]$Exe, [string]$Arguments) {
    Log "$Name> $Arguments"
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $WorkDir "$Name.out") -RedirectStandardError (Join-Path $WorkDir "$Name.err")
    foreach ($file in @("$Name.out", "$Name.err", "$Name.log")) {
        $path = Join-Path $WorkDir $file
        if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) { Log ("  [$file] " + (ReadAny $path).Trim()) }
    }
    Log "$Name exit $($process.ExitCode)"
    return $process.ExitCode
}

function Newest([string[]]$Patterns) {
    # Найновіший файл за версією в шляху (8.3.27.2130, 2026.1).
    $found = foreach ($pattern in $Patterns) { Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue }
    $found | Sort-Object { ([regex]::Matches($_.FullName, '\d+') | ForEach-Object { $_.Value.PadLeft(8, '0') }) -join '.' } |
        Select-Object -Last 1 -ExpandProperty FullName
}

try {
    if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
    New-Item -ItemType Directory -Path $WorkDir | Out-Null
    $Project = (Resolve-Path $Project).Path
    if (-not $Platform) { $Platform = Newest @("$env:ProgramFiles\1cv8\8.*\bin\1cv8.exe", "${env:ProgramFiles(x86)}\1cv8\8.*\bin\1cv8.exe") }
    if (-not $EdtCli) {
        $EdtCli = Newest @("$env:LOCALAPPDATA\1C\1cedtstart\installations\*\1cedt\1cedtcli.exe",
            "$env:ProgramFiles\1C\1CE\components\1c-edt-*\1cedtcli.exe")
    }
    if (-not $Platform -or -not (Test-Path $Platform)) { throw 'не знайдено 1cv8.exe: вкажіть -Platform' }
    if (-not $EdtCli -or -not (Test-Path $EdtCli)) { throw 'не знайдено 1cedtcli.exe: вкажіть -EdtCli' }
    Log "project $Project"
    Log "platform $Platform"
    Log "EDT CLI $EdtCli"

    # Проєкт копіюється: EDT CLI пише службові файли в каталог проєкту.
    $manifest = [IO.File]::ReadAllText((Join-Path $Project 'DT-INF\PROJECT.PMF'))
    $runtime = [regex]::Match($manifest, 'Runtime-Version:\s*(\S+)').Groups[1].Value
    $baseName = [regex]::Match($manifest, 'Base-Project:\s*(\S+)').Groups[1].Value
    if (-not $runtime -or -not $baseName) { throw 'у DT-INF/PROJECT.PMF немає Runtime-Version або Base-Project' }
    $projects = Join-Path $WorkDir 'projects'
    $extension = Join-Path $projects (Split-Path $Project -Leaf)
    $base = Join-Path $projects $baseName
    New-Item -ItemType Directory -Path $projects | Out-Null
    Copy-Item $Project $extension -Recurse

    # Заготовка основної конфігурації: класи вкладених об'єктів - як у кореня розширення, мова «Русский».
    $extensionMdo = [IO.File]::ReadAllText((Join-Path $Project 'src\Configuration\Configuration.mdo'))
    $contained = ([regex]::Matches($extensionMdo, '<containedObjects classId="([^"]+)"') | ForEach-Object {
        '  <containedObjects classId="{0}" objectId="{1}"/>' -f $_.Groups[1].Value, [guid]::NewGuid() }) -join "`n"
    $compatibility = [regex]::Match($extensionMdo, '<configurationExtensionCompatibilityMode>([^<]+)<').Groups[1].Value
    if (-not $compatibility) { $compatibility = $runtime }
    WriteText (Join-Path $base '.project') @"
<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
	<name>$baseName</name>
	<comment></comment>
	<projects>
	</projects>
	<buildSpec>
		<buildCommand>
			<name>org.eclipse.xtext.ui.shared.xtextBuilder</name>
			<arguments>
			</arguments>
		</buildCommand>
	</buildSpec>
	<natures>
		<nature>org.eclipse.xtext.ui.shared.xtextNature</nature>
		<nature>com._1c.g5.v8.dt.core.V8ConfigurationNature</nature>
	</natures>
</projectDescription>
"@
    WriteText (Join-Path $base 'DT-INF\PROJECT.PMF') "Manifest-Version: 1.0`nRuntime-Version: $runtime`n"
    WriteText (Join-Path $base 'src\Configuration\Configuration.mdo') @"
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:Configuration xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass" uuid="$([guid]::NewGuid())">
  <name>Конфигурация</name>
$contained
  <configurationExtensionCompatibilityMode>$runtime</configurationExtensionCompatibilityMode>
  <defaultRunMode>ManagedApplication</defaultRunMode>
  <usePurposes>PersonalComputer</usePurposes>
  <scriptVariant>Russian</scriptVariant>
  <defaultLanguage>Language.Русский</defaultLanguage>
  <dataLockControlMode>Managed</dataLockControlMode>
  <objectAutonumerationMode>NotAutoFree</objectAutonumerationMode>
  <modalityUseMode>DontUse</modalityUseMode>
  <synchronousPlatformExtensionAndAddInCallUseMode>DontUse</synchronousPlatformExtensionAndAddInCallUseMode>
  <compatibilityMode>$compatibility</compatibilityMode>
  <languages uuid="$([guid]::NewGuid())">
    <name>Русский</name>
    <synonym>
      <key>ru</key>
      <value>Русский</value>
    </synonym>
    <languageCode>ru</languageCode>
  </languages>
</mdclass:Configuration>
"@

    # EDT CLI: проєкт, якого немає в робочій області, імпортується в неї сам; заготовка - першою.
    $workspace = "-data $(Quote (Join-Path $WorkDir 'workspace')) -command"
    $xmlBase = Join-Path $WorkDir 'xml\base'
    $xmlExtension = Join-Path $WorkDir 'xml\extension'
    if ((Run 'edt-base' $EdtCli "$workspace export --project $(Quote $base) --configuration-files $(Quote $xmlBase)") -ne 0) {
        throw 'EDT CLI не вивантажив заготовку конфігурації'
    }
    if ((Run 'edt-extension' $EdtCli "$workspace export --project $(Quote $extension) --configuration-files $(Quote $xmlExtension)") -ne 0) {
        throw 'EDT CLI не вивантажив розширення'
    }

    # Перевірка проєкту EDT: проєкти вже імпортовано вивантаженням.
    $issues = Join-Path $WorkDir 'edt-validate.tsv'
    $projectName = [regex]::Match([IO.File]::ReadAllText((Join-Path $Project '.project')), '<name>([^<]+)</name>').Groups[1].Value
    if ((Run 'edt-validate' $EdtCli "$workspace validate --file $(Quote $issues) --project-name-list $projectName") -ne 0 -or
        -not (Test-Path $issues)) {
        throw 'EDT CLI не перевірив проєкт'
    }
    $found = @(Get-Content $issues -Encoding UTF8 | Where-Object { $_.Trim() })
    foreach ($line in $found) {
        # Колонки: час, важливість, ..., проєкт, ..., об'єкт, рядок, текст.
        $columns = $line -split "`t"
        Log ('  EDT: {0} {1} {2}: {3}' -f $columns[1], $columns[5], $columns[6], $columns[7])
    }
    Log "EDT validate: $($found.Count) issue(s)"
    if ($found.Count -gt 0 -and -not $NoValidate) { throw "перевірка проєкту EDT: зауважень $($found.Count)" }

    # Тимчасова база: заготовка, розширення, застосування, перевірка, .cfe.
    $name = [regex]::Match($extensionMdo, '<name>([^<]+)</name>').Groups[1].Value
    $infobase = Join-Path $WorkDir 'infobase'
    $cfe = Join-Path $WorkDir "$name.cfe"
    $designer = "DESIGNER /F $(Quote $infobase) /DisableStartupDialogs /DisableStartupMessages"
    function OutLog([string]$Step) { "/Out $(Quote (Join-Path $WorkDir "$Step.log"))" }
    if ((Run 'ib-create' $Platform "CREATEINFOBASE File=$(Quote $infobase) $(OutLog 'ib-create')") -ne 0) { throw 'не створено тимчасову базу' }
    if ((Run 'ib-base' $Platform "$designer $(OutLog 'ib-base') /LoadConfigFromFiles $(Quote $xmlBase) /UpdateDBCfg") -ne 0) {
        throw 'не завантажено заготовку конфігурації'
    }
    if ((Run 'ib-extension' $Platform "$designer $(OutLog 'ib-extension') /LoadConfigFromFiles $(Quote $xmlExtension) -Extension $name") -ne 0) {
        throw 'не завантажено розширення'
    }
    if ((Run 'ib-apply' $Platform "$designer $(OutLog 'ib-apply') /UpdateDBCfg -Extension $name") -ne 0) {
        throw 'розширення не застосовується до заготовки конфігурації'
    }
    if (-not $NoCheck) {
        $check = "/CheckConfig -ConfigLogIntegrity -IncorrectReferences -ThinClient -WebClient -Server -ExternalConnection " +
            "-ThickClientOrdinaryApplication -HandlersExistence -EmptyHandlers -ExtendedModulesCheck -Extension $name"
        if ((Run 'ib-check' $Platform "$designer $(OutLog 'ib-check') $check") -ne 0) { throw 'перевірка конфігурації знайшла помилки' }
    }
    if ((Run 'ib-dump' $Platform "$designer $(OutLog 'ib-dump') /DumpCfg $(Quote $cfe) -Extension $name") -ne 0) { throw 'не вивантажено .cfe' }

    New-Item -ItemType Directory -Force -Path (Split-Path $Output) | Out-Null
    Copy-Item $cfe $Output -Force
    Log ('{0}: {1} bytes, SHA-256 {2}' -f (Resolve-Path $Output).Path, (Get-Item $Output).Length,
        (Get-FileHash $Output -Algorithm SHA256).Hash)
} catch {
    if (Test-Path $WorkDir) { Log ('ERROR ' + $_.Exception.Message) } else { Write-Host ('ERROR ' + $_.Exception.Message) }
    exit 1
}
