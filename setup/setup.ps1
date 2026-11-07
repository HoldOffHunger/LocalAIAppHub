<#
  App Hub setup: checks what this PC has, picks models that fit its graphics card and its free disk space,
  and downloads them. Safe to run again: anything already downloaded is skipped.

    powershell -ExecutionPolicy Bypass -File setup\setup.ps1 -DryRun      # just show the plan
    powershell -ExecutionPolicy Bypass -File setup\setup.ps1              # do it
    ... -ModelsDir D:\AIModels        keep the models somewhere else (default: the hub's ModelFiles folder)
    ... -BudgetGB 40                  spend at most this much disk on models
    ... -NoImages / -NoVoice          skip the picture or the speech models
    ... -InstallMissing               install Python 3.12 and Ollama with winget if they're missing
#>
param(
    [string]$ModelsDir = "",
    [double]$BudgetGB = 0,
    [switch]$NoImages,
    [switch]$NoVoice,
    [switch]$InstallMissing,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Hub = Split-Path -Parent $PSScriptRoot
$Plan = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "models.json") | ConvertFrom-Json
$DefaultModels = Join-Path $Hub "ModelFiles"
if (-not $ModelsDir) { $ModelsDir = if ($env:AI_MODELS) { $env:AI_MODELS } else { $DefaultModels } }
$ModelsDir = [System.IO.Path]::GetFullPath($ModelsDir)

function Say($text) { Write-Host $text }
function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Have($command) { [bool](Get-Command $command -ErrorAction SilentlyContinue) }

# --- What this PC has ---------------------------------------------------------------------------------------------
Step "This PC"
$python = ""
if (Have "py") { try { & py -3.12 --version *> $null; if ($LASTEXITCODE -eq 0) { $python = "py -3.12" } } catch {} }
if (-not $python -and (Have "python")) {
    $version = (& python --version 2>&1) -replace "Python ", ""
    if ([version]($version -replace "[^\d.]", "") -ge [version]"3.10") { $python = "python" }
}
$ollama = Have "ollama"
if ($InstallMissing -and -not $DryRun) {
    if (-not $python) { winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements; $python = "py -3.12" }
    if (-not $ollama) { winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements; $ollama = $true
                        $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama" }
}
Say ("Python:  " + $(if ($python) { $python } else { "MISSING (winget install Python.Python.3.12, or run with -InstallMissing)" }))
Say ("Ollama:  " + $(if ($ollama) { "yes" } else { "MISSING (winget install Ollama.Ollama, or run with -InstallMissing)" }))

$vram = 0; $gpu = "no NVIDIA card found (models will run on the processor, slowly)"
if (Have "nvidia-smi") {
    $line = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
    if ($line) { $parts = $line -split ","; $gpu = $parts[0].Trim(); $vram = [math]::Round([double]$parts[1].Trim() / 1024, 1) }
}
Say "Graphics: $gpu$(if ($vram) { ", $vram GB" })"

foreach ($drive in [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq "Fixed" }) {
    Say ("Drive {0}  {1:N0} GB free of {2:N0} GB" -f $drive.Name, ($drive.AvailableFreeSpace / 1GB), ($drive.TotalSize / 1GB))
}
$free = ([System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($ModelsDir))).AvailableFreeSpace / 1GB
$budget = [math]::Max(0, [math]::Min($free - $Plan.reserve_gb, $free * $Plan.largest_share_of_free_space))
if ($BudgetGB -gt 0) { $budget = [math]::Min($BudgetGB, $free - 5) }
Say ("Models go in {0} ({1:N0} GB free there; budget {2:N0} GB)" -f $ModelsDir, $free, $budget)

# --- Where Ollama keeps its models ----------------------------------------------------------------------------------
$ollamaHome = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if (-not $ollamaHome) { $ollamaHome = $env:OLLAMA_MODELS }
$movingOllama = -not $ollamaHome
if ($movingOllama) { $ollamaHome = Join-Path $ModelsDir "ollama\models" }
Say "Ollama's models: $ollamaHome$(if ($movingOllama) { ' (will be set)' })"

# --- The plan -------------------------------------------------------------------------------------------------------
Step "The plan"
$pulled = @()
if ($ollama) { try { $pulled = (& ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split "\s+")[0] }) } catch {} }
$tier = $Plan.chat_tiers | Where-Object { $vram -ge $_.min_vram } | Select-Object -Last 1
$chat = @(); $spent = 0
foreach ($model in $tier.models) {
    if ($pulled -contains $model.name) { Say "  have    $($model.name)"; $chat += $model.name; continue }
    if ($spent + $model.gb -le $budget) { $chat += $model.name; $spent += $model.gb; Say ("  get     {0,-14} {1,5:N1} GB  {2}" -f $model.name, $model.gb, $model.why) }
    else { Say ("  skip    {0,-14} {1,5:N1} GB  (doesn't fit the budget)" -f $model.name, $model.gb) }
}
$haveVoice = (@($Plan.voice | Where-Object { -not (Test-Path (Join-Path $ModelsDir $_.to)) }).Count -eq 0) -and (Test-Path (Join-Path $ModelsDir ($Plan.whisper.to + "\model.bin")))
$voice = (-not $NoVoice) -and ($haveVoice -or ($spent + 0.9 -le $budget))
if ($voice -and $haveVoice) { Say "  have    speech models (Kokoro voice, Whisper ears)" }
elseif ($voice) { $spent += 0.9; Say "  get     speech models (Kokoro voice, Whisper ears)    0.9 GB" }
elseif (-not $NoVoice) { Say "  skip    speech models (doesn't fit the budget)" }
$imageGB = ($Plan.images.files | Measure-Object -Property gb -Sum).Sum
$haveImages = @($Plan.images.files | Where-Object { -not (Test-Path (Join-Path $ModelsDir $_.to)) }).Count -eq 0
$images = (-not $NoImages) -and ($vram -ge $Plan.images.min_vram) -and ($haveImages -or ($spent + $imageGB -le $budget))
if ($images -and $haveImages) { Say "  have    picture model FLUX.2 klein 4B" }
elseif ($images) { $spent += $imageGB; Say ("  get     picture model FLUX.2 klein 4B             {0,5:N1} GB" -f $imageGB) }
elseif (-not $NoImages) { Say "  skip    picture model (needs an NVIDIA card with $($Plan.images.min_vram)+ GB and $([math]::Round($imageGB)) GB of budget)" }
Say ("  total about {0:N1} GB to download" -f $spent)

if ($DryRun) { Say ""; Say "Dry run: nothing downloaded."; exit 0 }
if (-not $python -or -not $ollama) { Say ""; Say "Install what's missing first (see above), then run this again."; exit 1 }

# --- Settings -------------------------------------------------------------------------------------------------------
New-Item -ItemType Directory -Force $ModelsDir | Out-Null
if ($ModelsDir -ne [System.IO.Path]::GetFullPath($DefaultModels)) {
    [Environment]::SetEnvironmentVariable("AI_MODELS", $ModelsDir, "User"); $env:AI_MODELS = $ModelsDir
    Say "Set AI_MODELS=$ModelsDir for this user."
}
if ($movingOllama) {
    New-Item -ItemType Directory -Force $ollamaHome | Out-Null
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ollamaHome, "User"); $env:OLLAMA_MODELS = $ollamaHome
    Say "Set OLLAMA_MODELS=$ollamaHome for this user; restarting Ollama so it uses it."
    Get-Process "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}
$ollamaApp = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null }
catch {
    if (Test-Path $ollamaApp) { Start-Process $ollamaApp } else { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
    Start-Sleep -Seconds 5
}

# --- Chat models ----------------------------------------------------------------------------------------------------
Step "Chat models"
foreach ($name in $chat) {
    if ($pulled -contains $name) { continue }
    & ollama pull $name
    if ($LASTEXITCODE -ne 0) { Say "Couldn't pull $name; carrying on." }
}
$chatSettings = Join-Path $Hub "local-chat\data\settings.json"
if ($chat.Count -and -not (Test-Path $chatSettings)) {
    New-Item -ItemType Directory -Force (Split-Path $chatSettings) | Out-Null
    [System.IO.File]::WriteAllText($chatSettings, (@{ model = $chat[0] } | ConvertTo-Json))
    Say "Chat's default model: $($chat[0])"
}

function Fetch($url, $to) {
    $target = Join-Path $ModelsDir $to
    if (Test-Path $target) { Say "  have $to"; return }
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Say "  getting $to"
    & curl.exe -L --fail --retry 3 -C - -o "$target.part" $url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $url" }
    Move-Item "$target.part" $target
}

# --- Voice ----------------------------------------------------------------------------------------------------------
if ($voice) {
    Step "Voice"
    $voiceDir = Join-Path $Hub "Voice"
    $venvPython = Join-Path $voiceDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        if ($python -eq "py -3.12") { & py -3.12 -m venv (Join-Path $voiceDir ".venv") } else { & python -m venv (Join-Path $voiceDir ".venv") }
    }
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -r (Join-Path $voiceDir "requirements.txt")
    foreach ($file in $Plan.voice) { Fetch $file.url $file.to }
    $whisper = Join-Path $ModelsDir $Plan.whisper.to
    if (-not (Test-Path (Join-Path $whisper "model.bin"))) {
        Say "  getting Whisper $($Plan.whisper.name)"
        & $venvPython -c "import sys; from faster_whisper import download_model; download_model(sys.argv[1], output_dir=sys.argv[2])" $Plan.whisper.name $whisper
    } else { Say "  have $($Plan.whisper.to)" }
}

# --- Images ---------------------------------------------------------------------------------------------------------
if ($images) {
    Step "Images"
    foreach ($file in $Plan.images.files) { Fetch $file.url $file.to }
    $candidates = @(
        (Join-Path $Hub "ComfyUI"),
        (Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"),
        (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "ComfyUI")
    )
    $found = $null
    foreach ($base in $candidates) {
        foreach ($py in @((Join-Path $base ".venv\Scripts\python.exe"), (Join-Path (Split-Path $base) "python_embeded\python.exe"))) {
            if ((Test-Path $py) -and (Test-Path (Join-Path $base "main.py"))) { $found = @{ python = $py; main = (Join-Path $base "main.py") }; break }
        }
        if ($found) { break }
    }
    $imageSettings = Join-Path $Hub "ImageGen\data\settings.json"
    if ($found) {
        $settings = if (Test-Path $imageSettings) { Get-Content -Raw $imageSettings | ConvertFrom-Json } else { [pscustomobject]@{} }
        $settings | Add-Member -Force comfy_python $found.python
        $settings | Add-Member -Force comfy_main $found.main
        $settings | Add-Member -Force models_folder (Join-Path $ModelsDir "comfyui")
        New-Item -ItemType Directory -Force (Split-Path $imageSettings) | Out-Null
        [System.IO.File]::WriteAllText($imageSettings, ($settings | ConvertTo-Json))
        Say "  Images will use the ComfyUI at $(Split-Path $found.main)"
    } else {
        Say "  The picture model is downloaded, but there's no ComfyUI yet. See SETUP.md, 'Images needs ComfyUI'."
    }
}

Step "Done"
Say "Double-click start.bat to open the App Hub at http://127.0.0.1:8700"
