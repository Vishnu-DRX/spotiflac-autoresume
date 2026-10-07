<#
.SYNOPSIS
  Registers the auto-resume watcher as a per-user scheduled task (no admin needed).
.DESCRIPTION
  Runs at every logon, hidden. Safe to re-run: it replaces the existing task.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$src = Join-Path $root 'src'
$taskName = 'SpotiFLAC-AutoResume'

$py = (& python -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path $py)) { throw 'python not found on PATH (need Python 3.11+)' }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'     # windowless interpreter
if (-not (Test-Path $pyw)) { throw "pythonw.exe not found next to $py" }

& $py -c "import sys, pywinauto; assert sys.version_info >= (3, 11)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing dependencies (user scope)...'
    & $py -m pip install --user --quiet 'pywinauto>=0.6.8'
}

$cfg = Join-Path $root 'config.toml'
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $root 'config.example.toml') $cfg
    Write-Host "Created $cfg - check [paths] app_exe before relying on autolaunch."
}

$action   = New-ScheduledTaskAction -Execute $pyw -Argument '-m spotiflac_autoresume run' -WorkingDirectory $src
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
            -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'Resumes the SpotiFLAC queue after a server scheduled break' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started '$taskName'."
Write-Host "Control it with: scripts\autoresume.ps1 status | pause | resume | logs"
Write-Host "Config: $cfg    Log: $(Join-Path $root 'watcher.log')"
