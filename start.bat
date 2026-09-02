@echo off
chcp 65001 >nul 2>&1
title Japanese Kanji Learning Tool
cd /d "%~dp0"

if not exist kanji.ico (
    venv\Scripts\python.exe make_icon.py
)

venv\Scripts\python.exe start.py

pause
