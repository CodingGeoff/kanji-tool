@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  日语注音 API —— 一键启动（双击即可）
echo ============================================
echo.
echo [1/2] 启动本地注音服务...
start "kanji-api" /min ".\venv\Scripts\python.exe" furigana_api.py
timeout /t 3 /nobreak >nul

echo [2/2] 启动 Cloudflare 隧道，正在申请网址...
echo.
echo  ★ 拿到网址后，把下面这行发给面试官即可测试：
echo.
echo     https://XXXX.trycloudflare.com
echo.
echo ============================================
echo  隧道日志（网址会出现在下面）：
echo ============================================
echo.

.\cloudflared.exe tunnel --url http://localhost:5000

echo.
echo 隧道已断开（窗口被关闭或 cloudflared 退出）。
pause
