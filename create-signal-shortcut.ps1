# Puts a "Signal" icon on your desktop. Run it once by double-clicking Create-Signal-Shortcut.bat.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Signal.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"" + (Join-Path $root "signal-launcher.ps1") + "`""
$s.WorkingDirectory = $root
$s.IconLocation = (Join-Path $env:WINDIR "System32\shell32.dll") + ",13"
$s.Description = "Start Signal"
$s.Save()
Write-Host ""
Write-Host "Done. A Signal icon is now on your desktop: $lnk" -ForegroundColor Green
Write-Host "Double-click it, press Start, wait for Running, then press Open."
Start-Sleep -Seconds 6
