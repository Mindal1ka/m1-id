# Налагодження старту uvicorn: пишемо stdout/stderr у файли й читаємо їх.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$py = Join-Path $backend '.venv\Scripts\python.exe'
$out = Join-Path $env:TEMP 'm1id_uvicorn_out.txt'
$err = Join-Path $env:TEMP 'm1id_uvicorn_err.txt'

Remove-Item $out, $err -ErrorAction SilentlyContinue

$b = Start-Process -FilePath $py `
	-ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8080' `
	-WorkingDirectory $backend -PassThru -WindowStyle Hidden `
	-RedirectStandardOutput $out -RedirectStandardError $err

Start-Sleep -Seconds 6
Write-Output "HasExited: $($b.HasExited); ExitCode: $(if ($b.HasExited) { $b.ExitCode } else { '-' })"
try {
	$r = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 3
	Write-Output "HEALTH OK: $($r | ConvertTo-Json -Compress)"
} catch {
	Write-Output "HEALTH FAIL: $($_.Exception.Message)"
}
if (-not $b.HasExited) { Stop-Process -Id $b.Id -Force -ErrorAction SilentlyContinue }

Write-Output '── STDOUT ──'
Get-Content $out -ErrorAction SilentlyContinue
Write-Output '── STDERR ──'
Get-Content $err -ErrorAction SilentlyContinue
