# ============================================================================
# Cyber Minecraft AI - Windows installer (PowerShell 5.1+ / PowerShell 7+)
#
#   git clone https://github.com/cyberdrivepro/cyber-minecraft-ai.git
#   cd cyber-minecraft-ai
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\install.ps1
#
# Supports Windows 10/11 and Windows Server. Optional: install Java 21 via
# winget (Adoptium Temurin). Creates a virtualenv, installs dependencies,
# prepares .env and the database, and can register a startup shortcut.
# ============================================================================
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$LogFile = Join-Path $RepoRoot "install.log"
Start-Transcript -Path $LogFile -Append | Out-Null

function Write-Info($msg)  { Write-Host "[install] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[ok] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }

Write-Info "Cyber Minecraft AI installer starting in $RepoRoot"

# ---------------------------------------------------------------- detect OS
$osVersion = [System.Environment]::OSVersion.Version
Write-Info ("Detected Windows {0}.{1} ({2})" -f $osVersion.Major, $osVersion.Minor,
    ($(if ([System.Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" })))
$ramMb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
Write-Info "RAM: $ramMb MB"

# ---------------------------------------------------------------- python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Info "Python not found. Installing via winget (Python 3.12)..."
        winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $python = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $python) {
        Write-Warn2 "Python 3.9+ is required. Install it from https://www.python.org/downloads/ and re-run this script."
        Stop-Transcript | Out-Null
        exit 1
    }
}
$pyVer = & python --version
Write-Ok "Python found: $pyVer"

# ---------------------------------------------------------------- java (optional)
$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Java 21 is required for real Minecraft server hosting and Fabric builds. Install Adoptium Temurin 21 via winget? [y/N]"
        if ($answer -eq "y" -or $answer -eq "Y") {
            winget install --id EclipseAdoptium.Temurin.21.JDK --accept-source-agreements --accept-package-agreements
            Write-Ok "Java 21 installed (open a NEW terminal so PATH refreshes)"
        } else {
            Write-Warn2 "Skipping Java — the platform will run in embedded-console mode"
        }
    } else {
        Write-Warn2 "winget not available; install Java 21 from https://adoptium.net"
    }
} else {
    Write-Ok ("Java found: " + ((java -version 2>&1 | Select-Object -First 1)))
}

# ---------------------------------------------------------------- venv + deps
Write-Info "Creating virtual environment (.venv)..."
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\pip.exe" install -r requirements.txt
Write-Ok "Python dependencies installed"

# ---------------------------------------------------------------- .env
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $token = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    (Get-Content ".env") -replace "^ADMIN_TOKEN=.*", "ADMIN_TOKEN=$token" | Set-Content ".env"
    Write-Ok ".env created with a generated ADMIN_TOKEN"
} else {
    Write-Ok "Existing .env preserved (upgrade-safe)"
}

# ---------------------------------------------------------------- database
Write-Info "Initializing database..."
& ".venv\Scripts\python.exe" -c "from storage.database import init_db; init_db(); print('database ready')"
Write-Ok "Database initialized"

# ---------------------------------------------------------------- startup shortcut (optional)
$answer = Read-Host "Create a desktop shortcut to start the platform? [y/N]"
if ($answer -eq "y" -or $answer -eq "Y") {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath("Desktop"), "Cyber Minecraft AI.lnk"))
    $sc.TargetPath = (Join-Path $RepoRoot ".venv\Scripts\pythonw.exe")
    $sc.Arguments = "main.py"
    $sc.WorkingDirectory = $RepoRoot
    $sc.Save()
    Write-Ok "Desktop shortcut created"
}

Write-Host ""
Write-Host "============================================================"
Write-Host " Installation complete!"
Write-Host " Start:     .venv\Scripts\python.exe main.py"
Write-Host " Dashboard: http://127.0.0.1:7860"
Write-Host " CLI:       .venv\Scripts\python.exe scripts\cyber-minecraft-ai doctor"
Write-Host " Logs:      $LogFile"
Write-Host "============================================================"
Stop-Transcript | Out-Null
