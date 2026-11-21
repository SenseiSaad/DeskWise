<#
.SYNOPSIS
  Deskwise — One-Command Local Setup for Windows (PowerShell 5.1+ / PowerShell 7+)

.EXAMPLE
  .\scripts\start_local.ps1                  # Default --no-ai (retrieval-only, zero keys)
  .\scripts\start_local.ps1 -Doctor          # Run environment doctor checks
  .\scripts\start_local.ps1 -Ai gemini       # Configure Gemini (key saved to gitignored .env)
  .\scripts\start_local.ps1 -Stop            # Stop containers
  .\scripts\start_local.ps1 -Reset           # Stop + wipe local demo volumes
#>
[CmdletBinding()]
param(
  [switch]$Doctor,
  [switch]$Stop,
  [switch]$Reset,
  [switch]$NoAi,
  [ValidateSet("", "gemini", "openai", "ollama")]
  [string]$Ai = "",
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function New-RandomSecret {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return ([Convert]::ToBase64String($bytes) -replace '\+', '-' -replace '/', '_' -replace '=', '')
}

function New-DemoPassword {
  $bytes = New-Object byte[] 6
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $hex = ([BitConverter]::ToString($bytes) -replace '-', '').ToLower()
  return "DeskDemo!${hex}9A"
}

function Get-EnvVal([string]$FilePath, [string]$Key, [string]$Default) {
  if (Test-Path $FilePath) {
    $line = Get-Content $FilePath | Where-Object { $_ -match "^${Key}=" } | Select-Object -Last 1
    if ($line) {
      $val = $line.Substring($Key.Length + 1).Trim()
      if ($val) { return $val }
    }
  }
  return $Default
}

function Set-EnvVal([string]$FilePath, [string]$Key, [string]$Value) {
  $lines = if (Test-Path $FilePath) { @(Get-Content $FilePath) } else { @() }
  $found = $false
  $out = foreach ($l in $lines) {
    if ($l -match "^${Key}=") {
      $found = $true
      "${Key}=${Value}"
    } else {
      $l
    }
  }
  if (-not $found) { $out += "${Key}=${Value}" }
  Set-Content -Path $FilePath -Value $out -Encoding UTF8
}

function Test-PortInUse([int]$Port) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $conns)
  } catch {
    return $false
  }
}

function Invoke-Doctor {
  $failed = $false
  Write-Host "=== Deskwise Local Environment Doctor (Windows) ==="

  if (Get-Command docker -ErrorAction SilentlyContinue) {
    $ver = (& docker --version) 2>$null
    Write-Host "[PASS] Docker CLI installed ($ver)"
  } else {
    Write-Host "[FAIL] Docker is not installed." -ForegroundColor Red
    Write-Host "       Fix: Install Docker Desktop for Windows: https://docs.docker.com/desktop/install/windows-install/"
    $failed = $true
  }

  & docker info *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[PASS] Docker daemon is running (no Administrator prompt required)"
  } else {
    Write-Host "[FAIL] Docker daemon is not running." -ForegroundColor Red
    Write-Host "       Fix: Open Docker Desktop and wait until the engine reports Running."
    $failed = $true
  }

  & docker compose version *> $null
  if ($LASTEXITCODE -eq 0) {
    $cver = (& docker compose version --short) 2>$null
    Write-Host "[PASS] Docker Compose v2 available ($cver)"
  } else {
    Write-Host "[FAIL] Docker Compose v2 plugin not available." -ForegroundColor Red
    Write-Host "       Fix: Update Docker Desktop: https://docs.docker.com/compose/install/"
    $failed = $true
  }

  $stackRunning = (& docker compose ps -q) 2>$null
  $apiPort = [int](Get-EnvVal (Join-Path $Root ".env") "API_PORT" "8000")
  $webPort = [int](Get-EnvVal (Join-Path $Root ".env") "WEB_PORT" "3000")
  foreach ($p in @($apiPort, $webPort)) {
    if ($stackRunning) {
      Write-Host "[PASS] Port $p (Deskwise stack already running)"
    } elseif (Test-PortInUse $p) {
      Write-Host "[FAIL] Port $p is already in use by another application." -ForegroundColor Red
      Write-Host "       Fix: Stop the conflicting process or change API_PORT/WEB_PORT in .env."
      $failed = $true
    } else {
      Write-Host "[PASS] Port $p is free"
    }
  }

  $drive = (Get-Item $Root).PSDrive
  $freeGb = [math]::Round($drive.Free / 1GB, 1)
  if ($freeGb -ge 2) {
    Write-Host "[PASS] Disk space OK (${freeGb} GB free)"
  } else {
    Write-Host "[FAIL] Low disk space (${freeGb} GB free; recommend >= 2 GB)" -ForegroundColor Red
    $failed = $true
  }

  $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
  if ($ramGb -ge 2) {
    Write-Host "[PASS] System RAM OK (${ramGb} GB total)"
  } else {
    Write-Host "[WARN] System RAM is ${ramGb} GB (recommend >= 2 GB)" -ForegroundColor Yellow
  }

  if ($failed) {
    Write-Host "=== Doctor found issues above. Fix them and re-run. ===" -ForegroundColor Red
    exit 1
  }
  Write-Host "=== Doctor passed! Ready to launch Deskwise. ===" -ForegroundColor Green
}

if ($Doctor) { Invoke-Doctor; exit 0 }
if ($Stop) { & docker compose down; Write-Host "[deskwise] Stopped local Deskwise stack."; exit 0 }
if ($Reset) {
  & docker compose down -v --remove-orphans
  Remove-Item -ErrorAction SilentlyContinue (Join-Path $Root ".dev-logs\demo-credentials.txt")
  Write-Host "[deskwise] Reset complete."
  exit 0
}

Invoke-Doctor

$envPath = Join-Path $Root ".env"
if (-not (Test-Path $envPath)) {
  Copy-Item (Join-Path $Root ".env.example") $envPath
  Write-Host "[deskwise] Created gitignored .env from .env.example"
}
if (-not (Get-EnvVal $envPath "SECRET_KEY" "")) {
  Set-EnvVal $envPath "SECRET_KEY" (New-RandomSecret)
  Write-Host "[deskwise] Generated fresh local SECRET_KEY in .env"
}
if (-not (Get-EnvVal $envPath "LLM_KEY_ENCRYPTION_KEY" "")) {
  Set-EnvVal $envPath "LLM_KEY_ENCRYPTION_KEY" (New-RandomSecret)
  Write-Host "[deskwise] Generated fresh local LLM_KEY_ENCRYPTION_KEY in .env"
}

$aiMode = if ($Ai -and -not $NoAi) { $Ai } else { "none" }
switch ($aiMode) {
  "none" { Set-EnvVal $envPath "LLM_PROVIDER" "fake" }
  "ollama" { Set-EnvVal $envPath "LLM_PROVIDER" "ollama" }
  "gemini" {
    Set-EnvVal $envPath "LLM_PROVIDER" "gemini"
    if (-not (Get-EnvVal $envPath "GEMINI_API_KEY" "")) {
      $sec = Read-Host "Enter Google Gemini API key (saved only in local gitignored .env)" -AsSecureString
      $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
      $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
      if ($plain) { Set-EnvVal $envPath "GEMINI_API_KEY" $plain }
    }
  }
  "openai" {
    Set-EnvVal $envPath "LLM_PROVIDER" "openai"
    if (-not (Get-EnvVal $envPath "OPENAI_API_KEY" "")) {
      $sec = Read-Host "Enter OpenAI API key (saved only in local gitignored .env)" -AsSecureString
      $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
      $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
      if ($plain) { Set-EnvVal $envPath "OPENAI_API_KEY" $plain }
    }
  }
}

$apiPort = Get-EnvVal $envPath "API_PORT" "8000"
$webPort = Get-EnvVal $envPath "WEB_PORT" "3000"

Write-Host "[deskwise] Building and starting Docker containers..."
& docker compose up -d --build --wait

Write-Host "[deskwise] Running migrations & seeding demo personas..."
& docker compose exec -T api python manage.py migrate --noinput
& docker compose exec -T api python manage.py seed_plans

$logDir = Join-Path $Root ".dev-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$credsFile = Join-Path $logDir "demo-credentials.txt"
$demoPass = ""
if (Test-Path $credsFile) {
  $pline = Get-Content $credsFile | Where-Object { $_ -match "^Password:" } | Select-Object -First 1
  if ($pline) { $demoPass = ($pline -split '\s+')[1] }
}
if (-not $demoPass) { $demoPass = New-DemoPassword }

& docker compose exec -T api python manage.py seed_demo_personas --password $demoPass

@"
Password: $demoPass
Admin:    admin@demo.deskwise.local
Finance:  finance@demo.deskwise.local
Employee: employee@demo.deskwise.local
Viewer:   viewer@demo.deskwise.local
"@ | Set-Content -Path $credsFile -Encoding UTF8

Write-Host ""
Write-Host "========================================================================"
Write-Host "  Deskwise is LIVE locally!"
Write-Host "  Web App:    http://localhost:$webPort"
Write-Host "  API Health: http://localhost:$apiPort/api/health"
Write-Host "  Password for all demo personas: $demoPass"
Write-Host "    Admin:            admin@demo.deskwise.local     (Confidential)"
Write-Host "    Finance Manager:  finance@demo.deskwise.local   (Internal / Finance)"
Write-Host "    General Employee: employee@demo.deskwise.local  (Internal / Engineering)"
Write-Host "    Viewer:           viewer@demo.deskwise.local    (Standard / HR)"
Write-Host "  Stop anytime:  .\scripts\start_local.ps1 -Stop"
Write-Host "  Wipe & reset:  .\scripts\start_local.ps1 -Reset"
Write-Host "========================================================================"

if (-not $NoBrowser -and $env:CI -ne "true") {
  Start-Process "http://localhost:$webPort"
}
