@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   kanji-tool 一键安全拉取
echo   自动关闭 start.py 本地服务，然后执行 dbtool.py pull
echo ============================================================
echo.

echo [1/2] 关闭正在运行的 start.py 本地服务...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*start.py*' } | ForEach-Object { Write-Host ('  已结束进程 PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo [2/2] 安全拉取（备份后拉取远端，并回填本地数据）...
".\venv\Scripts\python.exe" dbtool.py pull

echo.
echo ============================================================
echo   完成。
echo   如需把本地数据上云到 Render：
echo       venv\Scripts\python.exe dbtool.py publish -m "更新数据库"
echo ============================================================
pause
