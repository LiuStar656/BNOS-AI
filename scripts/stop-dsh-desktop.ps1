# Stop the DSH Desktop launched from dsh_desktop.
# Kills only the DSH Desktop electron + node host processes (filtered by path),
# leaving unrelated Electron apps (e.g. the IDE) untouched.
$ErrorActionPreference = 'SilentlyContinue'

$electron = Get-CimInstance Win32_Process -Filter "name='electron.exe'" |
    Where-Object { $_.ExecutablePath -like '*\dsh_desktop\*' }
$electron | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    Write-Host "Stopped electron pid $($_.ProcessId)"
}

$nodes = Get-CimInstance Win32_Process -Filter "name='node.exe'" |
    Where-Object { $_.CommandLine -like '*dsh-plugin-desktop*bin.js*' }
$nodes | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    Write-Host "Stopped node host pid $($_.ProcessId)"
}

if (-not $electron -and -not $nodes) {
    Write-Host 'No DSH Desktop processes found (nothing to stop).'
}
