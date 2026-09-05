#Requires -Version 5.1
<#
.SYNOPSIS
  One command for Windows: install Python + Node deps, start Minecraft, run LLM agents.

.EXAMPLE
  .\run.ps1
  .\run.ps1 --no-docker --host localhost --port 25565
  .\run.ps1 --agents explorer builder
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Command($Name, $Hint) {
    if (-not (Test-Command $Name)) {
        Write-Host "Missing ``$Name``." -ForegroundColor Red
        Write-Host $Hint
        exit 1
    }
}

# ---- uv (Python package runner) -------------------------------------------
if (-not (Test-Command "uv")) {
    Write-Host "Installing uv (Python package runner)…"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Host "uv install failed. See https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Red
        Write-Host $_
        exit 1
    }
    # Fresh install PATH for this session
    $uvBin = Join-Path $env:USERPROFILE ".local\bin"
    $uvCargo = Join-Path $env:USERPROFILE ".cargo\bin"
    if (Test-Path $uvBin) { $env:Path = "$uvBin;$env:Path" }
    if (Test-Path $uvCargo) { $env:Path = "$uvCargo;$env:Path" }
}

Require-Command "uv" "uv install failed. See https://docs.astral.sh/uv/"
Require-Command "node" "Install Node.js 18+ from https://nodejs.org (needed for the Minecraft bot)."
Require-Command "npm" "npm ships with Node.js — reinstall Node from https://nodejs.org"

Write-Host "Installing Python packages…"
& uv sync --extra llm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
& uv run simulatecraft @args
exit $LASTEXITCODE
