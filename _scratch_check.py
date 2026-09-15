# -*- coding: utf-8 -*-
"""临时自检脚本（用完即删）：确认课本表已建好。"""
import db

with db.get_conn() as c:
    names = [r['name'] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print('tables:', names)
print('book tables:', [n for n in names if n.startswith('book')])