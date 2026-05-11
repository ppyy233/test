# QwenKB V1.0 - Windows Service Manager
# Usage: PowerShell -ExecutionPolicy Bypass -File install_service.ps1

$ErrorActionPreference = "Stop"
$ServiceName = "QwenKB-MCP"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe  = "D:\anaconda\envs\qwen-kb\python.exe"
$ServerScript = Join-Path $ScriptDir "mcp_server.py"
$NssmDir = Join-Path $ScriptDir "nssm"
$NssmExe = Join-Path $NssmDir "nssm.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  QwenKB V1.0 - Windows Service Manager" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Choose operation:"
Write-Host "  [1] Install & Start"
Write-Host "  [2] Stop & Remove"
Write-Host "  [3] Start"
Write-Host "  [4] Stop"
Write-Host "  [5] Status"
Write-Host ""
$choice = Read-Host "Enter number (1-5)"

function Ensure-Nssm {
    if (-not (Test-Path $NssmExe)) {
        Write-Host "nssm not found, downloading..." -ForegroundColor Yellow
        $zipPath = Join-Path $ScriptDir "nssm.zip"
        $nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"

        if (-not (Test-Path $NssmDir)) {
            New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
        }

        try {
            Invoke-WebRequest -Uri $nssmUrl -OutFile $zipPath -ErrorAction Stop
            Expand-Archive -Path $zipPath -DestinationPath $NssmDir -Force
            Remove-Item $zipPath -Force
        } catch {
            Write-Host "Failed to download nssm:" -ForegroundColor Red
            Write-Host "  $nssmUrl" -ForegroundColor Red
            Write-Host "  Please download manually and extract nssm.exe to: $NssmDir" -ForegroundColor Red
            exit 1
        }

        $exe = Get-ChildItem -Path $NssmDir -Recurse -Filter "nssm.exe" | Select-Object -First 1
        if ($exe) {
            $script:NssmExe = $exe.FullName
        } else {
            Write-Host "nssm.exe not found after extraction. Please place it manually in: $NssmDir" -ForegroundColor Red
            exit 1
        }
    }
}

function Show-Status {
    Ensure-Nssm
    & $NssmExe status $ServiceName
}

switch ($choice) {
    "1" {
        Ensure-Nssm
        Write-Host "Installing service: $ServiceName" -ForegroundColor Green
        Write-Host "  Python: $PythonExe" -ForegroundColor Gray
        Write-Host "  Script: $ServerScript" -ForegroundColor Gray
        Write-Host "  Work Dir: $ScriptDir" -ForegroundColor Gray

        & $NssmExe install $ServiceName $PythonExe $ServerScript 2>&1
        & $NssmExe set $ServiceName AppDirectory $ScriptDir 2>&1
        & $NssmExe set $ServiceName DisplayName "QwenKB MCP Server" 2>&1
        & $NssmExe set $ServiceName Description "QwenKB Knowledge Base MCP Server" 2>&1
        & $NssmExe set $ServiceName Start SERVICE_AUTO_START 2>&1
        & $NssmExe set $ServiceName AppStdout (Join-Path $ScriptDir "service_stdout.log") 2>&1
        & $NssmExe set $ServiceName AppStderr (Join-Path $ScriptDir "service_stderr.log") 2>&1

        Write-Host "Service installed." -ForegroundColor Green
        Write-Host "Starting..." -ForegroundColor Gray
        & $NssmExe start $ServiceName 2>&1
        Start-Sleep -Seconds 2
        Show-Status
    }

    "2" {
        Ensure-Nssm
        Write-Host "Stopping and removing: $ServiceName" -ForegroundColor Yellow
        & $NssmExe stop $ServiceName 2>&1
        Start-Sleep -Seconds 1
        & $NssmExe remove $ServiceName confirm 2>&1
        Write-Host "Service removed." -ForegroundColor Green
    }

    "3" {
        Ensure-Nssm
        & $NssmExe start $ServiceName 2>&1
        Show-Status
    }

    "4" {
        Ensure-Nssm
        & $NssmExe stop $ServiceName 2>&1
        Show-Status
    }

    "5" {
        Show-Status
    }

    default {
        Write-Host "Invalid choice. Enter 1-5." -ForegroundColor Red
    }
}
