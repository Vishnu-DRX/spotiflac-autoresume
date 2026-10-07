<#
.SYNOPSIS
  Day-to-day control of the watcher.
.EXAMPLE
  .\autoresume.ps1 status
#>
param([Parameter(Mandatory)]
      [ValidateSet('status','pause','resume','start','stop','restart','logs','resume-now')]
      [string]$Cmd)

$root = Split-Path $PSScriptRoot -Parent
$taskName = 'SpotiFLAC-AutoResume'
$flag = Join-Path $root 'PAUSE'

function Get-Watcher {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*spotiflac_autoresume*run*' }
}
function Invoke-Cli([string]$sub) {
    $env:PYTHONPATH = Join-Path $root 'src'
    python -m spotiflac_autoresume $sub
}

switch ($Cmd) {
    'pause'   { New-Item -ItemType File -Force $flag | Out-Null
                Write-Host 'Paused: watcher stays up but takes no action. Run "resume" to continue.' }
    'resume'  { Remove-Item $flag -ErrorAction SilentlyContinue; Write-Host 'Resumed: watcher is active.' }
    'start'   { Start-ScheduledTask -TaskName $taskName; Write-Host 'Started.' }
    'stop'    { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
                Get-Watcher | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
                Write-Host 'Stopped (starts again at next logon, or run "start").' }
    'restart' { & $PSCommandPath stop; Start-Sleep 1; & $PSCommandPath start }
    'logs'    { Get-Content (Join-Path $root 'watcher.log') -Tail 40 }
    'resume-now' { Invoke-Cli 'resume-now' }
    'status'  {
        $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Write-Host ("scheduled task : " + $(if ($t) { $t.State } else { 'NOT INSTALLED' }))
        Write-Host ("watcher process: " + $(if (Get-Watcher) { 'running' } else { 'not running' }))
        Invoke-Cli 'status'
    }
}
