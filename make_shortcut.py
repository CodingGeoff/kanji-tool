# -*- coding: utf-8 -*-
"""创建桌面快捷方式：日语汉字学习工具"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, 'venv', 'Scripts', 'python.exe')
START = os.path.join(ROOT, 'start.py')
ICON = os.path.join(ROOT, 'kanji.ico')
SHORTCUT_NAME = '日语汉字学习工具.lnk'

# 桌面路径
desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
shortcut_path = os.path.join(desktop, SHORTCUT_NAME)

# PowerShell 创建 .lnk 快捷方式
ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path.replace(chr(92), chr(92)+chr(92))}")
$Shortcut.TargetPath = "{PYTHON.replace(chr(92), chr(92)+chr(92))}"
$Shortcut.Arguments = '"{START.replace(chr(92), chr(92)+chr(92))}"'
$Shortcut.WorkingDirectory = "{ROOT.replace(chr(92), chr(92)+chr(92))}"
$Shortcut.IconLocation = "{ICON.replace(chr(92), chr(92)+chr(92))}"
$Shortcut.Description = "日语汉字学习工具 Japanese Kanji Learning Tool"
$Shortcut.Save()
Write-Host "OK"
'''

result = subprocess.run(
    ['powershell', '-NoProfile', '-Command', ps_script],
    capture_output=True, text=True
)

if 'OK' in result.stdout:
    print(f'[OK] 桌面快捷方式已创建: {shortcut_path}')
else:
    print(f'✗ 创建失败: {result.stderr}')
    sys.exit(1)
