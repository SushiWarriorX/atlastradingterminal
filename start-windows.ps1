# ATLAS: one-step start for Windows. Double-click start-windows.bat (or run this file in PowerShell).
#   start-windows.bat          practice mode: synthetic DEMO data, no keys, nothing real
#   start-windows.bat -Real    real data (Yahoo, Coinbase, FRED, RSS). Needs internet.
#   .\start-windows.bat -IbkrPort 4001   real data AND read-only IBKR prices through IB Gateway (live: 4001, paper: 4002; TWS: 7496 / 7497).
#                                        Connects by itself and reconnects after Gateway's daily logout. It can only read: it never places orders.
# Optional: copy local-settings.example.ps1 to local-settings.ps1 and put your keys there (that file is never uploaded to GitHub).
# Every start first checks GitHub and updates to the latest version by itself (add -NoUpdate to skip that). Your own changes are never overwritten.
# First run installs everything (a few minutes). Later runs start in seconds.
# To stop ATLAS, close the two black windows it opens.
#   start-signal-windows.bat   only the Signal phone app (in your browser) plus the backend it needs. Same as: .\start-windows.ps1 -SignalOnly
param([switch]$Real, [int]$IbkrPort = 0, [switch]$SignalOnly, [switch]$NoUpdate)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "atlas\backend"
$web = Join-Path $root "atlas\web"

function Stop-WithProblem($message) {
    Write-Host ""
    Write-Host "PROBLEM: $message" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close this window"
    exit 1
}

function Start-Window($script) {
    # -EncodedCommand avoids every quoting problem with paths that contain spaces.
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($script))
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded) | Out-Null
}

function Test-Url($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# 0. Update to the latest version from GitHub, then carry on.
# Skipped with -NoUpdate, when git is missing, when GitHub cannot be reached, or when you have changes of your own in this folder. Nothing of yours is ever overwritten.
function Update-Atlas {
    if ($NoUpdate -or $env:ATLAS_NO_UPDATE -or $env:ATLAS_UPDATED) { return @() }
    if (-not (Get-Command git -ErrorAction SilentlyContinue) -or -not (Test-Path (Join-Path $root ".git"))) {
        Write-Host "Update check skipped (git is not installed, or this folder is not a git checkout)." -ForegroundColor DarkGray
        return @()
    }
    Push-Location $root
    try {
        $branch = ((& git rev-parse --abbrev-ref HEAD 2>$null) | Select-Object -First 1)
        if (-not $branch -or $branch -eq "HEAD") {
            Write-Host "Update check skipped (no branch is checked out)." -ForegroundColor DarkGray
            return @()
        }
        Write-Host "Checking GitHub for a newer version..."
        & git fetch origin $branch 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not reach GitHub, so starting the version you have." -ForegroundColor Yellow
            return @()
        }
        # npm rewrites its lock files by itself. Those are not your changes, so they are reset before updating.
        & git checkout -- atlas/mobile/package-lock.json atlas/web/package-lock.json 2>$null | Out-Null
        $before = ((& git rev-parse HEAD 2>$null) | Select-Object -First 1)
        $remote = ((& git rev-parse "origin/$branch" 2>$null) | Select-Object -First 1)
        if (-not $remote -or $before -eq $remote) {
            Write-Host "You already have the latest version." -ForegroundColor Green
            return @()
        }
        & git merge-base --is-ancestor $remote $before 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "You already have the latest version." -ForegroundColor Green
            return @()
        }
        $dirty = (& git status --porcelain --untracked-files=no 2>$null)
        if ($dirty) {
            Write-Host "A newer version exists, but you have changes of your own in this folder, so it was not updated. Starting the version you have." -ForegroundColor Yellow
            Write-Host "To update: ask Claude, or run  git stash  then start again." -ForegroundColor Yellow
            return @()
        }
        & git merge --ff-only "origin/$branch" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not update automatically, so starting the version you have." -ForegroundColor Yellow
            return @()
        }
        $after = ((& git rev-parse HEAD 2>$null) | Select-Object -First 1)
        $files = @(& git diff --name-only $before $after 2>$null)
        $count = @(& git rev-list "$before..$after" 2>$null).Count
        Write-Host "Updated to the latest version ($count new change(s))." -ForegroundColor Green
        foreach ($line in @(& git log --oneline -5 "$before..$after" 2>$null)) { Write-Host "  $line" -ForegroundColor DarkGray }
        return $files
    } catch {
        Write-Host "The update check failed ($($_.Exception.Message)), so starting the version you have." -ForegroundColor Yellow
        return @()
    } finally {
        Pop-Location
    }
}
$changedFiles = @(Update-Atlas)
if ($changedFiles -contains "start-windows.ps1") {
    # The start script itself changed, so run the new copy (once) instead of carrying on with the old one.
    Write-Host "The start script was updated; restarting it..." -ForegroundColor Yellow
    $env:ATLAS_UPDATED = "1"
    $relaunch = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    if ($Real) { $relaunch += "-Real" }
    if ($IbkrPort -gt 0) { $relaunch += @("-IbkrPort", "$IbkrPort") }
    if ($SignalOnly) { $relaunch += "-SignalOnly" }
    & powershell @relaunch
    exit $LASTEXITCODE
}
$backendChanged = ($changedFiles -contains "atlas/backend/pyproject.toml")
$webChanged = (($changedFiles -contains "atlas/web/package.json") -or ($changedFiles -contains "atlas/web/package-lock.json"))

if ($IbkrPort -gt 0) { $Real = $true }      # IBKR prices only make sense with real data

Write-Host "ATLAS starting..." -ForegroundColor Cyan
if ($Real) { Write-Host "Mode: REAL data" -ForegroundColor Yellow } else { Write-Host "Mode: practice (synthetic DEMO data)" -ForegroundColor Green }

# Private settings (keys): optional file next to this script, ignored by git
$localSettings = Join-Path $root "local-settings.ps1"
if (Test-Path $localSettings) {
    . $localSettings
    Write-Host "Loaded your private settings from local-settings.ps1"
}
if ($Real -and -not $env:ATLAS_SEC_CONTACT) {
    Write-Host "Note: the Company deep-dive and Discover need an email for SEC filings. Without it they show empty. Fix: add this line to local-settings.ps1 (next to this script):  `$env:ATLAS_SEC_CONTACT = 'you@example.com'" -ForegroundColor Yellow
}
# Let the browser version of Signal (http://localhost:8081) talk to this backend. Harmless if you do not use it.
if (-not $env:ATLAS_CORS_ORIGINS) { $env:ATLAS_CORS_ORIGINS = "http://localhost:8081,http://127.0.0.1:8081" }
if ($IbkrPort -gt 0) {
    $env:IBKR_ENABLED = "1"
    $env:IBKR_MODE = "readonly"
    $env:IBKR_PORT = "$IbkrPort"
    $env:ATLAS_IBKR_DATA = "1"
    $env:IBKR_AUTOCONNECT = "1"
    Write-Host "IBKR: read-only on port $IbkrPort. IB Gateway must be open and logged in." -ForegroundColor Yellow
}

# 1. Python 3.11 or newer
$pyVersion = ""
try { $pyVersion = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null) } catch { $pyVersion = "" }
if (-not $pyVersion -or $pyVersion -notmatch '^\d+\.\d+$') {
    Stop-WithProblem "Python was not found. Install Python 3.12 from https://www.python.org/downloads/ and tick 'Add python.exe to PATH' in the installer, then run this again."
}
if ([version]$pyVersion -lt [version]"3.11") {
    Stop-WithProblem "Python $pyVersion is too old. ATLAS needs 3.11 or newer. Install Python 3.12 from https://www.python.org/downloads/ and run this again."
}

# 2. Node 18 or newer
$nodeVersion = ""
try { $nodeVersion = (& node --version 2>$null) } catch { $nodeVersion = "" }
if (-not ($nodeVersion -match '^v(\d+)\.')) {
    Stop-WithProblem "Node.js was not found. Install the LTS version from https://nodejs.org/ and run this again."
}
if ([int]$Matches[1] -lt 18) {
    Stop-WithProblem "Node.js $nodeVersion is too old. ATLAS needs version 18 or newer. Install the LTS version from https://nodejs.org/ and run this again."
}

# 3. Backend: virtual environment and packages (first run only)
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating the Python environment..."
    & python -m venv (Join-Path $backend ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Stop-WithProblem "Could not create the Python environment." }
}
$marker = Join-Path $backend ".venv\atlas-installed"
if ($backendChanged -and (Test-Path $marker)) { Remove-Item $marker -Force }      # the backend's package list changed: install again
if (-not (Test-Path $marker)) {
    Write-Host "Installing backend packages. First run only; this takes a few minutes..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e $backend
    if ($LASTEXITCODE -ne 0) { Stop-WithProblem "Installing the backend packages failed. Copy the red text above and send it to Claude." }
    New-Item -ItemType File -Path $marker | Out-Null
}

# 4. Frontend packages (first run only)
$mobile = Join-Path $root "atlas\mobile"
if ($SignalOnly) {
    Write-Host "Checking the Signal app packages (fast when nothing changed)..."
    Push-Location $mobile
    & npm install --no-audit --no-fund
    $npmCode = $LASTEXITCODE
    Pop-Location
    if ($npmCode -ne 0) { Stop-WithProblem "Installing the Signal app packages failed. Copy the red text above and send it to Claude." }
}
elseif ((-not (Test-Path (Join-Path $web "node_modules"))) -or $webChanged) {
    Write-Host "Installing frontend packages. First run only; this takes a few minutes..."
    Push-Location $web
    & npm install
    $npmCode = $LASTEXITCODE
    Pop-Location
    if ($npmCode -ne 0) { Stop-WithProblem "Installing the frontend packages failed. Copy the red text above and send it to Claude." }
}

# 5. Start both programs, each in its own window
# An old backend would keep its old settings (for example the wrong IBKR port), so it is stopped first. Only a Python process is ever stopped.
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -like "python*") {
        Write-Host "Stopping the ATLAS backend that was already running, so it restarts with the current settings..." -ForegroundColor Yellow
        Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 20; $i++) {
            if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 500
        }
    } else {
        Stop-WithProblem "Port 8000 is being used by another program ($($owner.ProcessName)), not by ATLAS. Close that program and run this again."
    }
}
$b = $backend.Replace("'", "''")
$p = $venvPython.Replace("'", "''")
$demoLine = if ($Real) { "Remove-Item Env:ATLAS_DEMO -ErrorAction SilentlyContinue" } else { "`$env:ATLAS_DEMO = '1'" }
Start-Window ("`$Host.UI.RawUI.WindowTitle = 'ATLAS backend (close this window to stop it)'; Set-Location '$b'; $demoLine; & '$p' -m atlas_api")
if ($SignalOnly) {
    # no ATLAS terminal screen needed
} elseif (Test-Url "http://127.0.0.1:5173") {
    Write-Host "A screen is already running on port 5173: using it." -ForegroundColor Yellow
} else {
    $w = $web.Replace("'", "''")
    Start-Window ("`$Host.UI.RawUI.WindowTitle = 'ATLAS screen (close this window to stop it)'; Set-Location '$w'; npm run dev")
}

# 6. Wait until both answer, then open the browser
Write-Host "Waiting for ATLAS to start (up to 2 minutes)..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    if ((Test-Url "http://127.0.0.1:8000/api/health") -and ($SignalOnly -or (Test-Url "http://127.0.0.1:5173"))) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Stop-WithProblem "ATLAS did not start within 2 minutes. Look at the two black windows it opened: the last red lines there say what went wrong. Send them to Claude."
}
if ($SignalOnly) {
    Write-Host ""
    Write-Host "The backend is running. Starting Signal now. When it asks for a server address, type: http://localhost:8000" -ForegroundColor Green
    Write-Host "Signal opens in your browser (usually http://localhost:8081). To stop: press Ctrl+C here, then close the black ATLAS backend window." -ForegroundColor Green
    Set-Location $mobile
    $env:EXPO_NO_TELEMETRY = "1"
    & npx --no-install expo start --web --clear
    if ($LASTEXITCODE -ne 0) { Stop-WithProblem "Signal did not start. Copy the red text above and send it to Claude." }
    exit 0
}
Start-Process "http://127.0.0.1:5173"
Write-Host ""
Write-Host "ATLAS is open in your browser: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "Press / in the page to type a command, for example: BTC, AAPL, HELP"
Write-Host "To stop ATLAS, close the two black windows it opened. You can close this one now."
Start-Sleep -Seconds 8
