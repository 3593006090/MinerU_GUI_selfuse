param(
    [ValidateSet('webui', 'console', 'api', 'all')]
    [string]$Target = 'webui'
)

$ErrorActionPreference = 'SilentlyContinue'

$portMap = @{ webui = 7860; console = 7861; api = 8000 }

$patterns = @{
    webui   = @('webui --server-name', 'mineru-kit-gradio-api')
    console = @('webapp\server.py')
    api     = @('mineru.kit.main api-server --host 127.0.0.1 --port 8000')
}

$targets = if ($Target -eq 'all') { @('webui', 'console', 'api') } else { @($Target) }

function Stop-ByPort($port) {
    $owners = @(Get-NetTCPConnection -LocalPort $port -State Listen |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($procId in $owners) {
        if ($procId -and $procId -ne 0) {
            Write-Host "  killing pid $procId on port $port"
            taskkill /PID $procId /T /F 2>$null | Out-Null
        }
    }
}

function Stop-ByPattern($needles) {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.Name -match 'python|mineru' } |
        Where-Object {
            $cmd = $_.CommandLine
            $hit = $false
            foreach ($n in $needles) { if ($cmd -like "*$n*") { $hit = $true } }
            $hit
        } |
        ForEach-Object {
            Write-Host "  killing leftover pid $($_.ProcessId)"
            taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null
        }
}

foreach ($t in $targets) {
    Write-Host "Stopping $t ..."
    Stop-ByPort $portMap[$t]
    Stop-ByPattern $patterns[$t]
    Start-Sleep -Milliseconds 600
    $still = Get-NetTCPConnection -LocalPort $portMap[$t] -State Listen
    if ($still) {
        Write-Host "  [WARN] port $($portMap[$t]) is still in use, retry or kill manually"
    } else {
        Write-Host "  stopped, port $($portMap[$t]) is free"
    }
}
