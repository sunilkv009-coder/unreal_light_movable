<#
  Builds one of the C++ editor plugins in this repository and installs it into your
  Unreal project. Works for Blueprint-only and C++ projects.

    -PluginName PerformanceOptimizerUI   the "Performance Improvements" tab (default)
    -PluginName CameraMatch              the "Camera Match (from Photo)" tab

  Easiest: double-click Build-PerformanceOptimizerUI.bat or Build-CameraMatch.bat
  (or drag your .uproject onto it).

  What it does:
    1. Finds your .uproject and the engine it uses.
    2. Checks that Visual Studio with C++ is installed.
    3. Compiles the plugin with Unreal's own RunUAT BuildPlugin (in a temp folder).
    4. Copies the result to <Project>\Plugins\<PluginName>
       (for the Performance tab, also LightMobilityTool if it's missing or out of date - asks first).

  It never submits anything, never changes read-only (Perforce) files, and never
  touches your maps or assets.
#>
param(
    [string]$Project,
    [ValidateSet('PerformanceOptimizerUI', 'CameraMatch')]
    [string]$PluginName = 'PerformanceOptimizerUI'
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginSource = Join-Path $Here $PluginName
$PluginInfo = @{
    PerformanceOptimizerUI = @{ Title = 'Performance Improvements tab'; Menu = 'Tools -> Performance Improvements...'; NeedsLightTool = $true }
    CameraMatch            = @{ Title = 'Camera Match (from Photo) tab'; Menu = 'Tools -> Camera Match (from Photo)...'; NeedsLightTool = $false }
}[$PluginName]
$ToolSource = Join-Path $Here 'LightMobilityTool'

function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    $Text" -ForegroundColor Yellow }
function Stop-WithError([string]$Text) {
    Write-Host ''
    Write-Host "ERROR: $Text" -ForegroundColor Red
    exit 1
}
function Ask-YesNo([string]$Question) {
    $answer = Read-Host "$Question (Y/N)"
    return ($answer -match '^[Yy]')
}

function Select-UProject {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Select your Unreal project (.uproject)'
    $dialog.Filter = 'Unreal project (*.uproject)|*.uproject'
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $dialog.FileName }
    return $null
}

function Select-EngineFolder {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Select your Unreal Engine folder (the one that contains "Engine", e.g. C:\Program Files\Epic Games\UE_5.4)'
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $dialog.SelectedPath }
    return $null
}

function Find-EngineDir([string]$Association) {
    if ($Association -match '^\d+\.\d+$') {
        # Epic Games Launcher install
        $key = "HKLM:\SOFTWARE\EpicGames\Unreal Engine\$Association"
        $item = Get-ItemProperty -Path $key -Name 'InstalledDirectory' -ErrorAction SilentlyContinue
        if ($item -and $item.InstalledDirectory -and (Test-Path $item.InstalledDirectory)) { return $item.InstalledDirectory }
        # [IO.Path]::Combine instead of Join-Path: Join-Path fails on drives that don't exist (e.g. no D:).
        foreach ($root in @($env:ProgramFiles, 'C:\Program Files', 'D:\Program Files', 'D:\Epic Games', 'C:\Epic Games')) {
            if (-not $root) { continue }
            foreach ($candidate in @([IO.Path]::Combine($root, 'Epic Games', "UE_$Association"), [IO.Path]::Combine($root, "UE_$Association"))) {
                if (Test-Path -LiteralPath ([IO.Path]::Combine($candidate, 'Engine'))) { return $candidate }
            }
        }
    }
    elseif ($Association) {
        # Source build registered with a GUID
        $builds = Get-ItemProperty -Path 'HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds' -ErrorAction SilentlyContinue
        if ($builds) {
            $prop = $builds.PSObject.Properties[$Association]
            if ($prop -and (Test-Path $prop.Value)) { return $prop.Value }
        }
    }
    return $null
}

function Get-ReadOnlyFiles([string]$Folder) {
    if (-not (Test-Path $Folder)) { return @() }
    return @(Get-ChildItem -Path $Folder -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.IsReadOnly })
}

function Copy-Folder([string]$From, [string]$To, [string[]]$ExcludeDirs) {
    $roboArgs = @($From, $To, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($ExcludeDirs -and $ExcludeDirs.Count -gt 0) { $roboArgs += '/XD'; $roboArgs += $ExcludeDirs }
    & robocopy @roboArgs | Out-Null
    # robocopy: 0-7 = success, 8+ = failure
    if ($LASTEXITCODE -ge 8) { Stop-WithError "Copying $From to $To failed (robocopy code $LASTEXITCODE)." }
}

function Test-FoldersDiffer([string]$A, [string]$B) {
    $filesA = @(Get-ChildItem -Path $A -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' })
    foreach ($file in $filesA) {
        $relative = $file.FullName.Substring($A.Length).TrimStart('\')
        $other = Join-Path $B $relative
        if (-not (Test-Path $other)) { return $true }
        if ((Get-FileHash $file.FullName).Hash -ne (Get-FileHash $other).Hash) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
Write-Host "$($PluginInfo.Title) - build and install" -ForegroundColor White

if (-not (Test-Path (Join-Path $PluginSource "$PluginName.uplugin"))) {
    Stop-WithError "Can't find $PluginName\$PluginName.uplugin next to this script. Run it from the downloaded repository folder."
}

# 1. Project ------------------------------------------------------------------
Write-Step 'Finding your project'
if (-not $Project) { $Project = Select-UProject }
if (-not $Project -or -not (Test-Path $Project) -or ([IO.Path]::GetExtension($Project) -ne '.uproject')) {
    Stop-WithError "No .uproject selected. Drag your .uproject onto Build-$PluginName.bat, or pick it in the dialog."
}
$Project = (Resolve-Path $Project).Path
$ProjectDir = Split-Path -Parent $Project
Write-Ok "Project: $Project"

$uproject = Get-Content -Raw -Path $Project | ConvertFrom-Json
$association = [string]$uproject.EngineAssociation
Write-Ok "Engine association: $association"

# 2. Unreal must be closed (an open editor locks the plugin DLL) ---------------
$editors = @(Get-Process -Name 'UnrealEditor', 'UE4Editor' -ErrorAction SilentlyContinue)
while ($editors.Count -gt 0) {
    Write-Warn 'Unreal Editor is running. Save your work and close it, then press Enter.'
    Read-Host | Out-Null
    $editors = @(Get-Process -Name 'UnrealEditor', 'UE4Editor' -ErrorAction SilentlyContinue)
}

# 3. Visual Studio -----------------------------------------------------------
Write-Step 'Checking Visual Studio (C++)'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsPath = $null
if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
if (-not $vsPath) {
    Stop-WithError ("Visual Studio with C++ was not found.`n" +
        "Install Visual Studio 2022 (free Community edition) from https://visualstudio.microsoft.com/ with the workloads:`n" +
        "  - Game development with C++ (include a Windows 10/11 SDK)`n" +
        "  - Desktop development with C++`n" +
        "  - .NET desktop development`n" +
        "Restart the PC, then run this script again.")
}
Write-Ok "Found: $vsPath"

# 4. Engine ------------------------------------------------------------------
Write-Step 'Finding the engine'
$engineDir = Find-EngineDir $association
if (-not $engineDir) {
    Write-Warn "Couldn't find the engine for '$association' automatically - please select its folder."
    $engineDir = Select-EngineFolder
}
$runUat = $null
if ($engineDir) { $runUat = Join-Path $engineDir 'Engine\Build\BatchFiles\RunUAT.bat' }
if (-not $runUat -or -not (Test-Path $runUat)) {
    Stop-WithError "RunUAT.bat not found under '$engineDir'. Select the folder that contains the 'Engine' folder."
}
Write-Ok "Engine: $engineDir"

# 5. Build (in a folder without spaces) ----------------------------------------
Write-Step 'Compiling the plugin (this takes a few minutes)'
$base = $env:TEMP
if (-not $base -or $base.Contains(' ')) { $base = Join-Path $env:SystemDrive 'Temp' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$work = Join-Path $base "${PluginName}Build_$stamp"
$stagedSource = Join-Path $work "Source\$PluginName"
$built = Join-Path $work "Built\$PluginName"
$log = Join-Path $work 'build.log'
New-Item -ItemType Directory -Force -Path $stagedSource | Out-Null
Copy-Folder $PluginSource $stagedSource @('Binaries', 'Intermediate')

$upluginPath = Join-Path $stagedSource "$PluginName.uplugin"
# Windows PowerShell 5.1 turns build-tool stderr lines into errors; don't stop on them.
$ErrorActionPreference = 'Continue'
& $runUat BuildPlugin "-Plugin=$upluginPath" "-Package=$built" '-TargetPlatforms=Win64' 2>&1 |
    ForEach-Object { "$_" } | Tee-Object -FilePath $log
$buildCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'

$dll = Get-ChildItem -Path (Join-Path $built 'Binaries') -Recurse -Filter "*$PluginName*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($buildCode -ne 0 -or -not $dll) {
    Write-Host ''
    Write-Host 'Build FAILED. Lines with errors:' -ForegroundColor Red
    Select-String -Path $log -Pattern ' error |error C\d+|error LNK|ERROR:' | Select-Object -First 25 | ForEach-Object { Write-Host "  $($_.Line)" }
    Stop-WithError "Full log: $log`nSend the error lines above (and your engine version) so the code can be fixed."
}
Write-Ok "Compiled: $($dll.Name)"

# 6. Install into the project ------------------------------------------------
Write-Step 'Installing into your project'
$pluginsDir = Join-Path $ProjectDir 'Plugins'
$dest = Join-Path $pluginsDir $PluginName
$readOnly = Get-ReadOnlyFiles $dest
if ($readOnly.Count -gt 0) {
    Write-Warn 'These files are read-only (probably submitted in Perforce):'
    $readOnly | Select-Object -First 10 | ForEach-Object { Write-Host "      $($_.FullName)" }
    Stop-WithError "Check out '$dest' in P4V (Check Out, include subfolders), then run this script again. Nothing was changed. The compiled plugin is in: $built"
}
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Folder $built $dest @('Intermediate')
Write-Ok "Installed: $dest"

# LightMobilityTool holds the Python logic the Performance tab uses.
$toolDest = Join-Path $pluginsDir 'LightMobilityTool'
if ($PluginInfo.NeedsLightTool -and (Test-Path $ToolSource)) {
    if (-not (Test-Path $toolDest)) {
        Copy-Folder $ToolSource $toolDest @('__pycache__')
        Write-Ok "Installed: $toolDest (the tab's Python logic)"
    }
    elseif (Test-FoldersDiffer $ToolSource $toolDest) {
        if (Ask-YesNo "    LightMobilityTool in your project is different from this download. Update it?") {
            $toolReadOnly = Get-ReadOnlyFiles $toolDest
            if ($toolReadOnly.Count -gt 0) {
                Write-Warn "Not updated: '$toolDest' is read-only (Perforce). Check it out in P4V and run this script again."
            }
            else {
                Copy-Folder $ToolSource $toolDest @('__pycache__')
                Write-Ok "Updated: $toolDest"
            }
        }
        else {
            Write-Warn 'LightMobilityTool left as it is. The tab needs the current version to work.'
        }
    }
    else {
        Write-Ok 'LightMobilityTool is up to date.'
    }
}

# 7. Done -----------------------------------------------------------------------
Write-Host ''
Write-Host 'DONE.' -ForegroundColor Green
Write-Host 'Next:'
Write-Host '  1. Open your project. If Unreal asks to enable the new plugin, click Yes.'
Write-Host "  2. $($PluginInfo.Menu)"
Write-Host "  3. Perforce: submit Plugins\$PluginName (with Binaries, without Intermediate)"
if ($PluginInfo.NeedsLightTool) {
    Write-Host '     and Plugins\LightMobilityTool if it was added or updated.'
}
Write-Host '  Note: the compiled plugin only works with this engine version; run this again after an engine upgrade.'
exit 0
