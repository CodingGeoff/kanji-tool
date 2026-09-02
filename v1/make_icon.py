# -*- coding: utf-8 -*-
"""生成桌面图标 kanji.ico（红色印章风 + 汉字「漢」）"""
from PIL import Image, ImageDraw, ImageFont
import os

size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角红色背景（印章风）
radius = 56
d.rounded_rectangle([8, 8, size - 8, size - 8], radius=radius, fill=(200, 42, 42, 255))

# 内层细线框（印章双线装饰）
d.rounded_rectangle([22, 22, size - 22, size - 22], radius=radius - 14,
                    outline=(255, 255, 255, 255), width=5)

font_path = None
for p in ['C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/msyh.ttc',
          'C:/Windows/Fonts/msyhbd.ttc']:
    if os.path.exists(p):
        font_path = p
        break

font = ImageFont.truetype(font_path, 150)
text = '漢'
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 10),
       text, font=font, fill=(255, 255, 255, 255))

# 底部小字
font_s = ImageFont.truetype(font_path, 40)
sub = '語'
sb = d.textbbox((0, 0), sub, font=font_s)
sw, sh = sb[2] - sb[0], sb[3] - sb[1]
d.text(((size - sw) / 2 - sb[0], size - 78), sub, font=font_s,
       fill=(255, 220, 180, 255))

# 保存多尺寸 ico
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.ico')
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('saved', out)
