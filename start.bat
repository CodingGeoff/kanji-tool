@echo off
chcp 65001 >nul 2>&1
title 日语汉字学习工具
cd /d "%~dp0"

echo ======================================
echo    日语汉字学习工具
echo    Japanese Kanji Learning Tool
echo ======================================
echo.

:: 延迟打开浏览器（等待服务启动）
start "" python -c "import time,webbrowser;time.sleep(2);webbrowser.open('http://127.0.0.1:5000')"

:: 启动 Flask 服务（端口冲突自动递增，见 app.py）
python app.py

pause
