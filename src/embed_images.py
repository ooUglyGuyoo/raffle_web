#!/usr/bin/env python3
"""Crop logos from sponsor wall, optimize prize images, embed all as base64 into raffle.html."""
import base64, io, json, os, re
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "img")                       # 仓库内 src/img
HTML = os.path.join(HERE, "..", "index.html")         # 仓库根 index.html

def b64img(im, fmt="JPEG", quality=82):
    buf = io.BytesIO()
    im.save(buf, fmt, quality=quality)
    data = base64.b64encode(buf.getvalue()).decode()
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{data}"

def fit(im, maxw, maxh):
    im.thumbnail((maxw, maxh), Image.LANCZOS)
    return im

def to_rgb(im, bg=(255, 255, 255)):
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bgim = Image.new("RGBA", im.size, bg + (255,))
        bgim.alpha_composite(im)
        im = bgim.convert("RGB")
    else:
        im = im.convert("RGB")
    return im

# ---------- 1) logos ----------
# 京东: 用官方反白透明版(白色logo,专为深色背景设计)
jd_white = Image.open(os.path.join(SRC, "logos", "jd-white.png")).convert("RGBA")

# 其他三个: 从赞助商墙图裁剪 -> 去白底
wall = Image.open(os.path.join(SRC, "logos", "sponsor-wall.png")).convert("RGB")
tiles = {
    "csl":         (332, 782, 527, 849),
    "Shokz韶音":    (110, 872, 305, 939),
    "香港科技大学图书馆": (775, 555, 971, 621),
}

def white_to_alpha(im):
    im = im.convert("RGBA")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a:
                m = min(r, g, b)
                px[x, y] = (r, g, b, int(a * (255 - m) / 255))
    return im

def trim_alpha(im, pad=4):
    bbox = im.getbbox()
    if bbox:
        l, t, r, b = bbox
        l = max(0, l - pad); t = max(0, t - pad)
        r = min(im.width, r + pad); b = min(im.height, b + pad)
        im = im.crop((l, t, r, b))
    return im

def round_corners(im, radius=50):
    """裁掉墙图圆角残留(白色/杂色角块)"""
    from PIL import ImageChops, ImageDraw, ImageFilter
    im = im.convert("RGBA")
    # 先腐蚀 2px 清掉抗锯齿毛边
    im = im.filter(ImageFilter.MinFilter(3))
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    im.putalpha(ImageChops.multiply(im.split()[3], mask))
    return trim_alpha(im)

logos = {}
# 京东直接使用反白版
jd = trim_alpha(jd_white)
jd.thumbnail((1000, 140), Image.LANCZOS)
logos["京东港澳"] = b64img(jd, "PNG")
print(f"logo 京东港澳: {jd.size}")

for key, (x0, y0, x1, y1) in tiles.items():
    pad = 0   # 严格贴白块边缘裁,避免带入墙图紫底
    tile = wall.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    tile = tile.resize((tile.width * 2, tile.height * 2), Image.LANCZOS)
    tile = white_to_alpha(tile)
    px = tile.load()
    if key in ("Shokz韶音", "香港科技大学图书馆"):  # 反白为纯白剪影
        for y in range(tile.height):
            for x in range(tile.width):
                r, g, b, a = px[x, y]
                if a:
                    px[x, y] = (255, 255, 255, a)
    tile = trim_alpha(tile)
    tile = round_corners(tile)
    tile.thumbnail((1000, 140), Image.LANCZOS)
    logos[key] = b64img(tile, "PNG")
    tile.save(f"/tmp/logo_proc_{key}.png")   # 供检查
    print(f"logo {key}: {tile.size}")

# ---------- 2) prize images ----------
prize_map = [
    ("抽湿机",                          "prizes/dehumidifier.jpg",       (400, 300)),
    ("手持除螨吸尘仪",                    "prizes/mite-vacuum.jpg",        (400, 300)),
    ("肩颈按摩仪",                        "prizes/massager.jpg",           (400, 300)),
    ("小米手环",                          "prizes/xiaomi-band.jpg",        (400, 300)),
    ("csl 留学生专属 5G 月费计划\n全年免费", "prizes/csl-5g-plan.png",        (400, 300)),
    ("华为手表",                          "prizes/huawei-watch.jpg",       (400, 300)),
    ("蓝牙音响",                          "prizes/speaker.jpg",            (400, 300)),
    ("Shokz 韶音 OpenRun Pro2",          "prizes/shokz-openrun-pro2.jpg", (400, 300)),
    ("Shokz 韶音 OpenFit2",              "prizes/shokz-openfit2.jpg",     (400, 300)),
    ("三合一充电线",                       "prizes/charging-cable.png",    (400, 300)),
    ("科大图书馆擦镜布",                   "prizes/lens-cloth.png",         (400, 300)),
]
prizes = {}
for name, path, box in prize_map:
    p = os.path.join(SRC, path)
    im = to_rgb(fit(Image.open(p), *box))
    prizes[name] = b64img(im, "JPEG", 80)
    print(f"prize {name!r}: {im.size} {len(prizes[name])//1024}KB")

# ---------- 3) inject (idempotent) ----------
import re
html = open(HTML).read()
html = re.sub(r'const (?:PRIZE_IMG|LOGO_IMG) = .*?;\n', '', html, flags=re.S)
prize_js = "const PRIZE_IMG = " + json.dumps(prizes, ensure_ascii=False) + ";\n"
logo_js = "const LOGO_IMG = " + json.dumps(logos, ensure_ascii=False) + ";\n"
marker = "/* ================= 图片素材(注入) ================= */"
assert marker in html
html = html.replace(marker, marker + "\n" + prize_js + logo_js)
open(HTML, "w").write(html)
print("INJECTED. final size:", os.path.getsize(HTML), "bytes")
