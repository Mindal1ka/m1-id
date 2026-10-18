# M1 ID: перевірка зв'язки бекенд(8080) ↔ фронтенд(5173).
# Запуск з папки m1-id:  powershell -ExecutionPolicy Bypass -File scripts\dev_check.ps1
$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $PSScriptRoot
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$py       = Join-Path $backend '.venv\Scripts\python.exe'

function Wait-Url($url, $seconds) {
	for ($i = 0; $i -lt ($seconds * 2); $i++) {
		try {
			$r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
			if ($r.StatusCode -lt 500) { return $true }
		} catch { }
		Start-Sleep -Milliseconds 500
	}
	return $false
}

function Kill-Tree($proc) {
	if (-not $proc -or $proc.HasExited) { return }
	Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.Id)" |
		ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
	Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

Write-Output '── [1/2] Backend ──'
$b = Start-Process -FilePath $py `
	-ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8080' `
	-WorkingDirectory $backend -PassThru -WindowStyle Hidden
try {
	if (Wait-Url 'http://127.0.0.1:8080/api/health' 20) {
		$h = Invoke-RestMethod 'http://127.0.0.1:8080/api/health'
		$s = (Invoke-RestMethod 'http://127.0.0.1:8080/api/system/spec/stats').data
		Write-Output ("BACKEND OK · {0} v{1}" -f $h.data.service, $h.data.version)
		Write-Output ("SPEC · ops={0} paths={1} schemas={2} tags={3}" -f `
			$s.operations, $s.paths, $s.schemas, $s.tags)
	} else {
		Write-Output 'BACKEND FAILED: /api/health не відповів за 20 с'
	}

	Write-Output '── [2/2] Frontend ──'
	$f = Start-Process -FilePath 'npm.cmd' `
		-ArgumentList 'run', 'dev', '--', '--port', '5173', '--strictPort' `
		-WorkingDirectory $frontend -PassThru -WindowStyle Hidden
	try {
		if (Wait-Url 'http://localhost:5173/' 40) {
			Start-Sleep -Seconds 2   # дати vite доробити оптимізацію залежностей
			$html = (Invoke-WebRequest 'http://localhost:5173/' -UseBasicParsing).Content
			if ($html -match 'manifest\.webmanifest') {
				Write-Output 'FRONTEND OK · shell + PWA-маніфест віддаються, проксі /api налаштовано'
			} else {
				Write-Output 'FRONTEND відповідає, але маніфест PWA в HTML не знайдено'
			}
		} else {
			Write-Output 'FRONTEND FAILED: :5173 не піднявся за 40 с'
		}
	} finally {
		Kill-Tree $f
	}
} finally {
	Kill-Tree $b
}
Write-Output '── Готово, процеси зупинено ──'
