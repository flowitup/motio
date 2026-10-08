<#
.SYNOPSIS
  Runs the Motio engine in the background on this Windows PC (home server), reachable only over Tailscale.

.DESCRIPTION
  Installs a Task Scheduler task that starts the engine installed by the Motio MSI at every log on and restarts it
  when it stops. The engine listens on this PC's Tailscale address only, keeps all data in -DataDir (put it on the
  big drive) and needs the token below. A Windows Firewall rule lets only Tailscale addresses reach the port.
  Runbook: docs/WINDOWS_SERVER.md. Not tested on a real Windows PC yet.

  Run it in an elevated PowerShell (Run as administrator), as the Windows user who will stay logged in: that user's
  browser cookies are the ones the engine will see.

.EXAMPLE
  .\motio-server.ps1 -DataDir D:\Motio\data -KeepAwake     # install (or update) and start
  .\motio-server.ps1 -Status                               # task state + /api/health
  .\motio-server.ps1 -Uninstall                            # remove the task and the firewall rule (data stays)
#>
[CmdletBinding()]
param(
  [string]$DataDir = "D:\Motio\data",
  [int]$Port = 8765,
  [string]$BindAddress,   # default: this PC's Tailscale IPv4 (tailscale ip -4)
  [string]$Exe,           # default: motio-engine.exe inside the installed Motio
  [string]$Token,         # default: the token from the last run, else a new random one
  [switch]$KeepAwake,     # never sleep or hibernate while plugged in
  [switch]$Status,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "Motio engine"
$RuleName = "Motio engine (Tailscale)"
$StateDir = Join-Path $env:LOCALAPPDATA "MotioServer"
$Launcher = Join-Path $StateDir "run-engine.ps1"
$User = "$env:USERDOMAIN\$env:USERNAME"
$TokenFile = Join-Path $StateDir "token.txt"

function Get-TailscaleIp {
  $ts = Get-Command tailscale -ErrorAction SilentlyContinue
  if (-not $ts) {
    $p = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
    if (Test-Path $p) { $ts = $p }
  }
  if (-not $ts) { return $null }
  $ip = & $ts ip -4 2>$null | Select-Object -First 1
  if ($ip -match '^\d+\.\d+\.\d+\.\d+$') { return $ip }
  return $null
}

function Find-Engine {
  $roots = @((Join-Path $env:ProgramFiles "Motio"), (Join-Path $env:LOCALAPPDATA "Motio"),
             (Join-Path $env:LOCALAPPDATA "Programs\Motio")) | Where-Object { Test-Path $_ }
  foreach ($r in $roots) {
    $f = Get-ChildItem -Path $r -Filter "motio-engine.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($f) { return $f.FullName }
  }
  return $null
}

function Stop-Engine {   # only the headless server engine, not one started by the desktop app
  Get-CimInstance Win32_Process -Filter "Name = 'motio-engine.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*--headless*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Status) {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if (-not $t) { throw "The task '$TaskName' is not installed. Run this script without -Status first." }
  Write-Host "Task: $($t.State)"
  $addr = if ($BindAddress) { $BindAddress } else { Get-TailscaleIp }
  $tok = if (Test-Path $TokenFile) { (Get-Content $TokenFile -Raw).Trim() } else { "" }
  $h = Invoke-RestMethod -Uri "http://${addr}:$Port/api/health" -Headers @{ Authorization = "Bearer $tok" } -TimeoutSec 10
  Write-Host "Engine $($h.version) on $($h.platform.system) - data $($h.data_dir) - ASR $($h.providers.asr.engine)"
  if ($h.disk) { Write-Host ("Disk: {0:N0} GB free of {1:N0} GB" -f ($h.disk.free / 1e9), ($h.disk.total / 1e9)) }
  return
}

if (-not (Test-Admin)) { throw "Run this script in an elevated PowerShell (Run as administrator)." }

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Stop-Engine
  Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
  Write-Host "Removed the task and the firewall rule. $DataDir and $StateDir are untouched."
  return
}

if (-not $Exe) { $Exe = Find-Engine }
if (-not $Exe -or -not (Test-Path $Exe)) {
  throw "motio-engine.exe not found. Install the Motio MSI first, or pass -Exe <path to motio-engine.exe>."
}
if (-not $BindAddress) { $BindAddress = Get-TailscaleIp }
if (-not $BindAddress) {
  throw "No Tailscale address found. Install Tailscale, sign in, then run again (or pass -BindAddress)."
}

New-Item -ItemType Directory -Force -Path $StateDir, $DataDir | Out-Null
$HfDir = Join-Path (Split-Path $DataDir -Parent) "hf"   # Whisper models (~1.6 GB) stay off the C: drive too
New-Item -ItemType Directory -Force -Path $HfDir | Out-Null

if (-not $Token -and (Test-Path $TokenFile)) { $Token = (Get-Content $TokenFile -Raw).Trim() }
if (-not $Token) {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $Token = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

# The launcher sets the environment itself, so it does not depend on when the user variables were last read.
$LogOut = Join-Path (Split-Path $DataDir -Parent) "engine.out.log"
$LogErr = Join-Path (Split-Path $DataDir -Parent) "engine.err.log"
@"
`$env:MOTIO_DATA  = '$DataDir'
`$env:HF_HOME     = '$HfDir'
`$env:MOTIO_TOKEN = '$Token'
foreach (`$f in '$LogOut', '$LogErr') { if (Test-Path `$f) { Move-Item `$f "`$f.prev" -Force } }
`$p = Start-Process -FilePath '$Exe' -ArgumentList 'engine', '--host', '$BindAddress', '--port', '$Port', '--headless' ``
  -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput '$LogOut' -RedirectStandardError '$LogErr'
exit `$p.ExitCode
"@ | Set-Content -Path $Launcher -Encoding UTF8
Set-Content -Path $TokenFile -Value $Token -Encoding ASCII
foreach ($f in $Launcher, $TokenFile) {   # the token is inside: this user only
  & icacls $f /inheritance:r /grant:r "${User}:(F)" | Out-Null
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Stop-Engine
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
  -Settings $settings -Description "Motio engine (home server, Tailscale only)" | Out-Null

Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
  -RemoteAddress "100.64.0.0/10" -Profile Any | Out-Null   # Tailscale's address range only

if ($KeepAwake) {
  powercfg /change standby-timeout-ac 0
  powercfg /change hibernate-timeout-ac 0
}

Start-ScheduledTask -TaskName $TaskName
$url = "http://${BindAddress}:$Port"
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
  Start-Sleep -Seconds 2
  try {
    Invoke-RestMethod -Uri "$url/api/health" -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 5 | Out-Null
    $ok = $true
  } catch { }
}

Write-Host ""
if ($ok) { Write-Host "The Motio engine is running." } else {
  Write-Host "The engine did not answer within a minute. Look at $LogErr, then run: .\motio-server.ps1 -Status"
}
Write-Host "On the Mac: Settings > Engine > Remote engine"
Write-Host "  URL:   $url"
Write-Host "  Token: $Token"
Write-Host "Data: $DataDir (logs next to it). Enter the API keys once in the app: Settings."
