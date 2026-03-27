param(
    [ValidateSet("discord", "telegram", "cli")]
    [string]$Transport = "discord"
)

Set-Location $PSScriptRoot

if ($IsWindows -or ($env:OS -eq "Windows_NT")) {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    $pip    = Join-Path $PSScriptRoot ".venv\Scripts\pip.exe"
} else {
    $python = Join-Path $PSScriptRoot ".venv/bin/python"
    $pip    = Join-Path $PSScriptRoot ".venv/bin/pip"
}

if (-not (Test-Path $python)) {
    Write-Host "[..] Creating virtual environment..." -ForegroundColor Yellow
    if ($IsWindows -or ($env:OS -eq "Windows_NT")) {
        python -m venv .venv
    } else {
        python3 -m venv .venv
    }
    if (-not (Test-Path $python)) {
        throw "Failed to create virtual environment."
    }
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
}

Write-Host "[..] Installing dependencies..." -ForegroundColor Yellow
& $pip install -q -e . 2>&1 | Out-Null
Write-Host "[OK] Dependencies ready" -ForegroundColor Green

if (-not (Test-Path ".env")) {
    Write-Host "[WARNING] No .env file. Copy .env.example and fill in your tokens." -ForegroundColor Red
}

Write-Host ""
Write-Host "[>>] Starting assistant (transport: $Transport)..." -ForegroundColor Cyan
& $python -m src.app --transport $Transport
