# Interactive control menu for the SpotiFLAC auto-resume watcher. Double-click ..\menu.bat to open.
# (ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 without a BOM.)
$root = Split-Path $PSScriptRoot -Parent
$ctl  = Join-Path $PSScriptRoot 'autoresume.ps1'
$env:PYTHONPATH = Join-Path $root 'src'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$taskName = 'SpotiFLAC-AutoResume'

function Invoke-Py([string]$sub) { python -m spotiflac_autoresume $sub }

function Show-Header {
    Clear-Host
    Write-Host ''
    Write-Host '  SpotiFLAC Auto-Resume' -ForegroundColor Cyan
    Write-Host '  ---------------------'
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        Write-Host '  NOT INSTALLED - run scripts\install.ps1 first' -ForegroundColor Red
    }
    $lines = @(Invoke-Py 'status')
    $verdict = $lines | Select-Object -First 1
    $color = 'Green'
    if ($verdict -match 'NOT RUNNING') { $color = 'Red' } elseif ($verdict -match 'PAUSED') { $color = 'Yellow' }
    Write-Host ("  " + $verdict) -ForegroundColor $color
    foreach ($l in ($lines | Where-Object { $_ -match '^(Doing|Queue|Sync)' })) { Write-Host ("  " + $l) }
    Write-Host ''
}

function Show-Menu {
    Write-Host '   1  Live status (auto-refreshing)'
    Write-Host '   2  Pause automation'
    Write-Host '   3  Resume automation'
    Write-Host '   4  Press Resume / Retry in SpotiFLAC now'
    Write-Host '   5  Sync configured playlists now'
    Write-Host '   6  Show recent log'
    Write-Host '   C  View configuration'
    Write-Host '   7  Edit config (restarts watcher after)'
    Write-Host '   8  Start watcher'
    Write-Host '   9  Stop watcher'
    Write-Host '   R  Restart watcher'
    Write-Host '   U  Uninstall...'
    Write-Host '   Q  Quit'
    Write-Host ''
}

function Pause-Menu { Write-Host ''; Read-Host '  Press Enter to return to the menu' | Out-Null }

while ($true) {
    Show-Header
    Show-Menu
    $choice = (Read-Host '  Choose').Trim().ToUpper()
    Write-Host ''
    switch ($choice) {
        '1' { Invoke-Py 'watch' }
        '2' { & $ctl pause; Pause-Menu }
        '3' { & $ctl resume; Pause-Menu }
        '4' { & $ctl resume-now; Pause-Menu }
        '5' { Invoke-Py 'sync-now'; Pause-Menu }
        '6' { & $ctl logs; Pause-Menu }
        'C' { Invoke-Py 'config'; Pause-Menu }
        '7' {
            Start-Process notepad.exe -ArgumentList (Join-Path $root 'config.toml') -Wait
            & $ctl restart
            Pause-Menu
        }
        '8' { & $ctl start; Pause-Menu }
        '9' { & $ctl stop; Pause-Menu }
        'R' { & $ctl restart; Pause-Menu }
        'U' {
            $a = Read-Host '  Type YES to remove the scheduled task (SpotiFLAC and your music are untouched)'
            if ($a -ceq 'YES') { & (Join-Path $PSScriptRoot 'uninstall.ps1'); Pause-Menu; exit }
            Write-Host '  Cancelled.'; Pause-Menu
        }
        'Q' { exit }
        default { Write-Host '  Not an option.' -ForegroundColor Yellow; Start-Sleep 1 }
    }
}
