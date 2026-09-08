#Requires -Version 5.1
<#
.SYNOPSIS
  SimulateCraft one-line installer for Windows.

.EXAMPLE
  irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex

  # If raw.githubusercontent.com fails (occasional 503), use:
  irm https://cdn.jsdelivr.net/gh/DanyalAbbas/SimulateCraft@main/install.ps1 | iex

  $env:OPENROUTER_API_KEY = "sk-or-..."
  irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex

  $env:SIMULATECRAFT_SKIP_RUN = "1"
  irm https://raw.githubusercontent.com/DanyalAbbas/SimulateCraft/main/install.ps1 | iex
#>
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:SIMULATECRAFT_REPO) { $env:SIMULATECRAFT_REPO } else { "https://github.com/DanyalAbbas/SimulateCraft.git" }
$TargetDir = if ($env:SIMULATECRAFT_DIR) { $env:SIMULATECRAFT_DIR } else { Join-Path $HOME "SimulateCraft" }
$Branch = if ($env:SIMULATECRAFT_BRANCH) { $env:SIMULATECRAFT_BRANCH } else { "main" }

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Test-Command $Name)) {
        Write-Host "Missing '$Name'." -ForegroundColor Red
        Write-Host $Hint
        exit 1
    }
}

function Test-EnvValueSet([string]$Key) {
    $raw = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $false }
    return [bool]($raw -match "(?m)^$Key=.+")
}

Write-Host "==> SimulateCraft installer"
Write-Host "    Target: $TargetDir"

Require-Command "git" "Install Git for Windows: https://git-scm.com/download/win"
Require-Command "node" "Install Node.js 18+ from https://nodejs.org"
Require-Command "npm" "npm ships with Node.js — reinstall from https://nodejs.org"

try {
    $nodeMajor = [int](& node -p "process.versions.node.split('.')[0]")
} catch {
    $nodeMajor = 0
}
if ($nodeMajor -lt 18) {
    Write-Host "Node.js 18+ required (found $(node -v))." -ForegroundColor Red
    Write-Host "Install from https://nodejs.org and re-run."
    exit 1
}

if (-not (Test-Command "uv")) {
    Write-Host "==> Installing uv…"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uvCandidates = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE ".cargo\bin"),
        (Join-Path $env:LOCALAPPDATA "uv\bin")
    )
    foreach ($bin in $uvCandidates) {
        if (Test-Path $bin) { $env:Path = "$bin;$env:Path" }
    }
}
Require-Command "uv" "uv install failed. See https://docs.astral.sh/uv/getting-started/installation/"

if (Test-Path (Join-Path $TargetDir ".git")) {
    Write-Host "==> Updating existing clone…"
    git -C $TargetDir fetch origin
    git -C $TargetDir checkout $Branch
    git -C $TargetDir pull --ff-only origin $Branch 2>$null
} elseif (Test-Path $TargetDir) {
    Write-Host "Refusing to overwrite non-git path: $TargetDir" -ForegroundColor Red
    Write-Host "Set `$env:SIMULATECRAFT_DIR to a new folder and retry."
    exit 1
} else {
    Write-Host "==> Cloning SimulateCraft…"
    git clone --branch $Branch --depth 1 $RepoUrl $TargetDir
}

Set-Location $TargetDir

$envFile = Join-Path $TargetDir ".env"
$envExample = Join-Path $TargetDir ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    } else {
        New-Item -ItemType File -Path $envFile | Out-Null
    }
}

function Set-EnvKv([string]$Key, [string]$Value) {
    $content = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
    if ($null -eq $content) { $content = "" }
    if ($content -match "(?m)^$Key=") {
        $content = [regex]::Replace($content, "(?m)^$Key=.*$", "$Key=$Value")
    } else {
        $content = $content.TrimEnd() + "`r`n$Key=$Value`r`n"
    }
    Set-Content -Path $envFile -Value $content -NoNewline
}

if ($env:OPENROUTER_API_KEY) {
    Set-EnvKv "OPENROUTER_API_KEY" $env:OPENROUTER_API_KEY
    Write-Host "==> Wrote OPENROUTER_API_KEY into .env"
}
if ($env:OPENAI_BASE_URL) {
    Set-EnvKv "OPENAI_BASE_URL" $env:OPENAI_BASE_URL
    Write-Host "==> Wrote OPENAI_BASE_URL into .env"
}
if ($env:OPENAI_API_KEY) {
    Set-EnvKv "OPENAI_API_KEY" $env:OPENAI_API_KEY
    Write-Host "==> Wrote OPENAI_API_KEY into .env"
}
if ($env:SIMULATECRAFT_MODEL) {
    Set-EnvKv "SIMULATECRAFT_MODEL" $env:SIMULATECRAFT_MODEL
    Write-Host "==> Wrote SIMULATECRAFT_MODEL into .env"
}
if ($env:GROQ_API_KEY) {
    Set-EnvKv "GROQ_API_KEY" $env:GROQ_API_KEY
    Write-Host "==> Wrote GROQ_API_KEY into .env"
}

$hasProvider = (Test-EnvValueSet "OPENROUTER_API_KEY") -or
    (Test-EnvValueSet "OPENAI_BASE_URL") -or
    (Test-EnvValueSet "GROQ_API_KEY") -or
    (Test-EnvValueSet "SIMULATECRAFT_MODEL")

if ($env:SIMULATECRAFT_SKIP_RUN -eq "1") {
    Write-Host "==> Setup complete (skip run). Next:"
    Write-Host "    1. Edit $envFile with OpenRouter / 9Router / your API"
    Write-Host "    2. cd `"$TargetDir`"; .\run.ps1"
    exit 0
}

if (-not $hasProvider -and $env:SIMULATECRAFT_FORCE_RUN -ne "1") {
    Write-Host ""
    Write-Host "==> Repo ready at $TargetDir"
    Write-Host "No LLM provider configured yet (blank keys in .env do not count)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Edit .env, then launch:"
    Write-Host "    Prefer OpenRouter:  OPENROUTER_API_KEY=sk-or-..."
    Write-Host "    Or 9Router / own API:"
    Write-Host "      OPENAI_BASE_URL=http://localhost:20128/v1"
    Write-Host "      OPENAI_API_KEY=..."
    Write-Host "      SIMULATECRAFT_MODEL=oc/mimo-v2.5-free"
    Write-Host "    Docs: https://danyalabbas.github.io/SimulateCraft/llm-providers/"
    Write-Host ""
    Write-Host "    cd `"$TargetDir`"; .\run.ps1"
    Write-Host "    (or double-click run.cmd)"
    Write-Host ""
    Write-Host "(Docker Desktop needed for the bundled Minecraft 1.21.4 server.)"
    exit 0
}

$extra = @()
if ($env:SIMULATECRAFT_NO_DOCKER -eq "1") {
    $extra += "--no-docker"
}

Write-Host "==> Launching SimulateCraft…"
& .\run.ps1 @extra
exit $LASTEXITCODE
