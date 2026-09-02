# -*- coding: utf-8 -*-
"""生成桌面图标 kanji.ico（日式印章风，优雅配色）"""
from PIL import Image, ImageDraw, ImageFont
import os, math

SIZE = 512
MARGIN = 16
CORNER = 80

# ---------- 基础画布 ----------
img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 渐变背景：从深朱红到正红
for y in range(SIZE):
    t = y / SIZE
    r = int(180 + 55 * t)
    g = int(30 + 10 * t)
    b = int(30 + 10 * t)
    d.line([(MARGIN, y), (SIZE - MARGIN, y)], fill=(r, g, b, 255))

# 圆角遮罩
mask = Image.new('L', (SIZE, SIZE), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN],
                      radius=CORNER, fill=255)
img.putalpha(mask)

# ---------- 内层装饰框（双线印章风）----------
inner = 36
d.rounded_rectangle([inner, inner, SIZE - inner, SIZE - inner],
                     radius=CORNER - 16, outline=(255, 240, 220, 180), width=4)
inner2 = 44
d.rounded_rectangle([inner2, inner2, SIZE - inner2, SIZE - inner2],
                     radius=CORNER - 20, outline=(255, 240, 220, 100), width=2)

# ---------- 字体 ----------
font_path = None
for p in ['C:/Windows/Fonts/msyhbd.ttc', 'C:/Windows/Fonts/simhei.ttf',
          'C:/Windows/Fonts/msyh.ttc']:
    if os.path.exists(p):
        font_path = p
        break
if not font_path:
    raise RuntimeError('找不到中文字体')

# ---------- 主字「漢」----------
font_main = ImageFont.truetype(font_path, 260)
text = '漢'
bbox = d.textbbox((0, 0), text, font=font_main)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
x = (SIZE - tw) / 2 - bbox[0]
y = (SIZE - th) / 2 - bbox[1] - 30

# 文字阴影
d.text((x + 4, y + 4), text, font=font_main, fill=(80, 10, 10, 120))
# 文字本体
d.text((x, y), text, font=font_main, fill=(255, 250, 240, 255))

# ---------- 底部小字「語学」----------
font_sub = ImageFont.truetype(font_path, 62)
sub_text = '語学'
sb = d.textbbox((0, 0), sub_text, font=font_sub)
sw, sh = sb[2] - sb[0], sb[3] - sb[1]
sx = (SIZE - sw) / 2 - sb[0]
sy = SIZE - 108
d.text((sx, sy), sub_text, font=font_sub, fill=(255, 230, 190, 220))

# ---------- 顶部小装饰线 ----------
line_y = 58
line_w = 80
cx = SIZE // 2
d.line([(cx - line_w, line_y), (cx + line_w, line_y)],
       fill=(255, 230, 190, 140), width=2)
# 中心小菱形
d菱 = [
    (cx, line_y - 8),
    (cx + 8, line_y),
    (cx, line_y + 8),
    (cx - 8, line_y),
]
d.polygon(d菱, fill=(255, 230, 190, 200))

# ---------- 保存 ----------
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.ico')
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                     (64, 64), (128, 128), (256, 256), (512, 512)])
print(f'[OK] 图标已生成: {out}')
