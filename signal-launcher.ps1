# Signal launcher: a small window with Start, Open and Stop buttons. No typing needed.
# Put a Signal icon on your desktop by double-clicking Create-Signal-Shortcut.bat once.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Test-Url($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# Stops only the program that listens on a port, and only if its name matches (never an unrelated program).
function Stop-Port($port, $namePattern) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($p -and ($p.ProcessName -like $namePattern)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

$script:runner = $null

$form = New-Object System.Windows.Forms.Form
$form.Text = "Signal"
$form.Size = New-Object System.Drawing.Size(380, 300)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(20, 22, 26)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = "Signal"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 20, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 14)
$title.AutoSize = $true
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = "Research only. Nothing here places a trade."
$sub.ForeColor = [System.Drawing.Color]::FromArgb(167, 173, 184)
$sub.Location = New-Object System.Drawing.Point(22, 58)
$sub.AutoSize = $true
$form.Controls.Add($sub)

$status = New-Object System.Windows.Forms.Label
$status.Text = "Stopped"
$status.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
$status.Location = New-Object System.Drawing.Point(22, 88)
$status.Size = New-Object System.Drawing.Size(330, 44)
$form.Controls.Add($status)

$real = New-Object System.Windows.Forms.CheckBox
$real.Text = "Use real market data (needs internet)"
$real.Location = New-Object System.Drawing.Point(22, 134)
$real.Size = New-Object System.Drawing.Size(330, 24)
$real.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($real)

function New-Button($text, $x) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Location = New-Object System.Drawing.Point($x, 176)
    $b.Size = New-Object System.Drawing.Size(105, 44)
    $b.FlatStyle = "Flat"
    $b.BackColor = [System.Drawing.Color]::FromArgb(197, 202, 211)
    $b.ForeColor = [System.Drawing.Color]::FromArgb(11, 12, 14)
    $b.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    return $b
}
$btnStart = New-Button "Start" 22
$btnOpen = New-Button "Open" 137
$btnStop = New-Button "Stop" 252
$form.Controls.Add($btnStart)
$form.Controls.Add($btnOpen)
$form.Controls.Add($btnStop)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "First start takes a few minutes. A small window opens and stays minimised: that is Signal working."
$hint.ForeColor = [System.Drawing.Color]::FromArgb(167, 173, 184)
$hint.Location = New-Object System.Drawing.Point(22, 230)
$hint.Size = New-Object System.Drawing.Size(330, 40)
$form.Controls.Add($hint)

$btnStart.Add_Click({
    if (Test-Url "http://127.0.0.1:8081") {
        $status.Text = "Already running. Press Open."
        return
    }
    $script = Join-Path $root "start-windows.ps1"
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $script + '"'), "-SignalOnly")
    if ($real.Checked) { $argList += "-Real" }
    $script:runner = Start-Process powershell -ArgumentList $argList -PassThru -WindowStyle Minimized
    $status.Text = "Starting... first time takes a few minutes."
})

$btnOpen.Add_Click({
    if (Test-Url "http://127.0.0.1:8081") {
        Start-Process "http://localhost:8081"
    } else {
        $status.Text = "Not ready yet. Wait until it says Running."
    }
})

$btnStop.Add_Click({
    Stop-Port 8081 "node*"
    Stop-Port 8000 "python*"
    if ($script:runner -and -not $script:runner.HasExited) {
        & taskkill /PID $script:runner.Id /T /F | Out-Null
    }
    $script:runner = $null
    $status.Text = "Stopped"
})

# Every few seconds, show what is really running.
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 3000
$timer.Add_Tick({
    $back = Test-Url "http://127.0.0.1:8000/api/health"
    $sig = Test-Url "http://127.0.0.1:8081"
    if ($back -and $sig) {
        $status.Text = "Running. Press Open. When Signal asks for a server, type: http://localhost:8000"
    } elseif ($script:runner -and -not $script:runner.HasExited) {
        $status.Text = "Starting... first time takes a few minutes."
    } elseif ($script:runner -and $script:runner.HasExited) {
        $status.Text = "It stopped. Press Start to try again. If it keeps failing, press Start and read the red text in the small window."
        $script:runner = $null
    }
})
$timer.Start()

[void]$form.ShowDialog()
