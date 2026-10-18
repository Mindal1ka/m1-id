param([string]$Server = "uvicorn", [int]$Port = 8126, [int]$VU = 60)

$py = ".venv\Scripts\python.exe"
if ($Server -eq "granian") {
    $args = @("-m", "granian", "--interface", "asgi",
              "scripts.loadtest_server:app",
              "--host", "127.0.0.1", "--port", "$Port",
              "--log-level", "warning")
} else {
    $args = @("-m", "uvicorn", "scripts.loadtest_server:app",
              "--host", "127.0.0.1", "--port", "$Port",
              "--log-level", "warning")
}

if (Test-Path _server_stats.txt) { Remove-Item _server_stats.txt }

$p = Start-Process -FilePath $py -ArgumentList $args -NoNewWindow -PassThru `
        -RedirectStandardOutput "_srv_out.log" -RedirectStandardError "_srv_err.log"

$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($h.ok) { $ok = $true; break }
    } catch {}
}
if (-not $ok) {
    Write-Host "[$Server] СЕРВЕР НЕ ПІДНЯВСЯ"
    Get-Content _srv_err.log -ErrorAction SilentlyContinue | Select-Object -Last 15
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "[$Server] сервер піднято, ганяємо клієнт ($VU VU)..."

& $py scripts\loadtest_client.py $VU $Port
$clientExit = $LASTEXITCODE

Start-Sleep -Seconds 6  # дати флашеру записати останні метрики
taskkill /PID $p.Id /T /F 2>$null | Out-Null

Write-Host "=== СЕРВЕРНИЙ ЧАС ($Server) ==="
Get-Content _server_stats.txt -ErrorAction SilentlyContinue
Remove-Item _srv_out.log, _srv_err.log -ErrorAction SilentlyContinue
exit $clientExit
