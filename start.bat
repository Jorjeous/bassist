@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   My Assistant - Startup
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check Python version
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

:: Create venv if missing
if not exist ".venv\Scripts\python.exe" (
    echo [..] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

:: Install / update dependencies
echo [..] Installing dependencies...
.venv\Scripts\pip.exe install -q -e . 2>&1 | findstr /v "already satisfied"
if errorlevel 1 (
    echo [NOTE] Some dependency output above may be warnings, continuing...
)
echo [OK] Dependencies ready

:: Check .env
if not exist ".env" (
    echo.
    echo [WARNING] No .env file found.
    if exist ".env.example" (
        echo          Copying .env.example to .env -- edit it with your tokens.
        copy .env.example .env >nul
    ) else (
        echo          Create a .env file with your DISCORD_TOKEN and other settings.
    )
    echo.
)

:: Check Ollama
where ollama >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Ollama not found in PATH. The assistant needs Ollama running locally.
    echo          Install from https://ollama.com
)

:: Parse argument (default: discord)
set TRANSPORT=discord
if /i "%~1"=="telegram" set TRANSPORT=telegram
if /i "%~1"=="cli" set TRANSPORT=cli

echo.
echo [>>] Starting assistant (transport: %TRANSPORT%)...
echo     Press Ctrl+C to stop.
echo.

.venv\Scripts\python.exe -m src.app --transport %TRANSPORT%

pause
