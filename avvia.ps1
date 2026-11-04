<#
.SYNOPSIS
  Avvia Aetherdeck in locale.

.DESCRIPTION
  Modalita normale: prepara l'ambiente se manca (venv, dipendenze, build del frontend),
  avvia il server su http://127.0.0.1:8090 e apre il browser. Ctrl+C lo arresta.

  Modalita sviluppo (-Dev): backend con ricarica automatica sulla 8090 e Vite sulla
  5173 in una seconda finestra; il browser apre la 5173.

.EXAMPLE
  .\avvia.ps1
.EXAMPLE
  .\avvia.ps1 -Dev
.EXAMPLE
  .\avvia.ps1 -Db C:\percorso\copia.db     # usa un altro database SQLite
.EXAMPLE
  .\avvia.ps1 -Setup                       # reinstalla dipendenze e ricompila il frontend
#>
param(
    [switch]$Dev,
    [string]$Db = "",
    [int]$Port = 8090,
    [switch]$Setup,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Frontend = Join-Path $Root "frontend"
$Dist = Join-Path $Frontend "dist\index.html"

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERRORE: $text" -ForegroundColor Red; exit 1 }

function Test-Port($p) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $p); return $true } catch { return $false } finally { $client.Close() }
}

function Open-WhenReady($url, $p) {
    if ($NoBrowser) { return }
    # Opens the browser in the background as soon as the port answers.
    Start-Job -ScriptBlock {
        param($url, $p)
        for ($i = 0; $i -lt 120; $i++) {
            $c = New-Object System.Net.Sockets.TcpClient
            try { $c.Connect("127.0.0.1", $p); $c.Close(); Start-Process $url; return } catch { Start-Sleep -Milliseconds 500 } finally { $c.Close() }
        }
    } -ArgumentList $url, $p | Out-Null
}

Set-Location $Root

# --- Python -----------------------------------------------------------------
if (-not (Test-Path $Python)) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { Fail "Python 3.11+ non trovato. Installalo e riprova." }
    Step "Creo l'ambiente Python (.venv)"
    & $py.Source -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "creazione del venv non riuscita." }
    $Setup = $true
}
if ($Setup) {
    Step "Installo le dipendenze Python"
    & $Python -m pip install --disable-pip-version-check -q -r (Join-Path $Root "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "installazione delle dipendenze Python non riuscita." }
}

# --- Frontend ---------------------------------------------------------------
$needNode = $Dev -or $Setup -or -not (Test-Path $Dist)
if (-not $needNode) {
    # Rebuild when a source file is newer than the last build.
    $built = (Get-Item $Dist).LastWriteTime
    $newer = Get-ChildItem (Join-Path $Frontend "src"), (Join-Path $Frontend "index.html") -Recurse -File |
        Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1
    if ($newer) { $needNode = $true }
}
if ($needNode) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js 22+ non trovato. Installalo e riprova." }
    if ($Setup -or -not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Step "Installo le dipendenze del frontend"
        Push-Location $Frontend; npm ci --no-audit --no-fund; $code = $LASTEXITCODE; Pop-Location
        if ($code -ne 0) { Fail "npm ci non riuscito." }
    }
    if (-not $Dev) {
        Step "Compilo il frontend"
        Push-Location $Frontend; npm run build; $code = $LASTEXITCODE; Pop-Location
        if ($code -ne 0) { Fail "build del frontend non riuscita." }
    }
}

# --- Database ---------------------------------------------------------------
if ($Db) {
    $full = (Resolve-Path $Db -ErrorAction SilentlyContinue)
    if (-not $full) { Fail "database non trovato: $Db" }
    $env:DATABASE_URL = "sqlite:///" + ($full.Path -replace "\\", "/")
    Step "Database: $($full.Path)"
} else {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Step "Database: data\mtgdeck.db"
}

# --- Server -----------------------------------------------------------------
if (Test-Port $Port) {
    Write-Host "La porta $Port e' gia' in uso: l'app e' probabilmente gia' avviata." -ForegroundColor Yellow
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
    exit 0
}

$uvicorn = @("-m", "uvicorn", "main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "$Port")
if ($Dev) {
    if (Test-Port 5173) { Fail "la porta 5173 e' gia' in uso (un altro Vite?)." }
    Step "Avvio Vite su http://127.0.0.1:5173 in una nuova finestra"
    $env:VITE_API_TARGET = "http://127.0.0.1:$Port"
    Start-Process powershell -WorkingDirectory $Frontend -ArgumentList @(
        "-NoExit", "-Command", "npx vite --host 127.0.0.1 --port 5173 --strictPort"
    ) | Out-Null
    Open-WhenReady "http://127.0.0.1:5173" 5173
    $uvicorn += @("--reload", "--reload-dir", "backend")
} else {
    Open-WhenReady "http://127.0.0.1:$Port" $Port
}

Step "Avvio il server su http://127.0.0.1:$Port (Ctrl+C per arrestarlo)"
& $Python @uvicorn
