<#
.SYNOPSIS
  Removes the scheduled task and stops the watcher.
.DESCRIPTION
  SpotiFLAC, its queue and your music are never touched.
  -Purge also deletes this whole project folder (config, logs, scripts).
#>
param([switch]$Purge)
$root = Split-Path $PSScriptRoot -Parent
$taskName = 'SpotiFLAC-AutoResume'

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task '$taskName'."
} else {
    Write-Host "Task '$taskName' was not installed."
}

# stop any watcher process still running
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*spotiflac_autoresume*run*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ($Purge) {
    Set-Location $env:USERPROFILE
    Remove-Item -Recurse -Force $root
    Write-Host 'Project folder deleted.'
} else {
    Write-Host "Kept $root (config + logs). Re-run scripts\install.ps1 any time to bring it back."
}
