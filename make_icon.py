# -*- coding: utf-8 -*-
"""生成 netcheck 的自定义图标（.ico + 预览 png）"""
from PIL import Image, ImageDraw

S = 1024          # 先画大图再缩小，边缘更平滑
BG = (15, 34, 51, 255)          # 深蓝底 #0F2233
G1 = (46, 204, 113, 255)        # 亮绿 #2ECC71
G2 = (39, 174, 96, 255)         # 中绿 #27AE60
G3 = (30, 132, 73, 255)         # 深绿 #1E8449


def rr(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 底板：圆角方形
    m = int(S * 0.03)
    rr(d, (m, m, S - m, S - m), int(S * 0.22), BG)

    # 底部一条"网线"横杠（呼应网络主题）
    bar_h = int(S * 0.055)
    bar_y = int(S * 0.775)
    d.rounded_rectangle((int(S * 0.16), bar_y, int(S * 0.84), bar_y + bar_h),
                        radius=bar_h // 2, fill=(255, 255, 255, 70))

    # 雷达/信号弧：从右下角发散的同心弧
    cx, cy = int(S * 0.30), int(S * 0.66)
    for r, w, col in ((int(S * 0.30), int(S * 0.085), G3),
                      (int(S * 0.215), int(S * 0.085), G2),
                      (int(S * 0.13), int(S * 0.085), G1)):
        d.arc((cx - r, cy - r, cx + r, cy + r), start=-82, end=2,
              fill=col, width=w)

    # 弧心：信号源圆点
    dr = int(S * 0.055)
    d.ellipse((cx - dr, cy - dr, cx + dr, cy + dr), fill=G1)

    # 右上角：一个"端口/TCP"小方块（白色描边），表示端口检测
    bx0, by0 = int(S * 0.60), int(S * 0.17)
    bx1, by1 = int(S * 0.84), int(S * 0.41)
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=int(S * 0.045),
                        outline=(255, 255, 255, 235), width=int(S * 0.032))
    # 里面三根短线，像端口插槽
    for i in range(3):
        y = by0 + (by1 - by0) * (0.30 + i * 0.20)
        x2 = bx0 + (bx1 - bx0) * (0.34 if i % 2 else 0.66)
        d.line((bx0 + (bx1 - bx0) * 0.26, y, x2, y),
               fill=(255, 255, 255, 210), width=int(S * 0.022))

    img.save("icon_preview.png")
    img.resize((256, 256), Image.LANCZOS).save(
        "netcheck.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    # 各个尺寸的预览拼一张图，方便检查小尺寸下的辨识度
    sheet = Image.new("RGBA", (16 + 32 + 48 + 64 + 128 + 20 * 5, 148), (240, 240, 240, 255))
    x = 10
    for sz in (16, 32, 48, 64, 128):
        ic = img.resize((sz, sz), Image.LANCZOS)
        sheet.paste(ic, (x, 10), ic)
        x += sz + 20
    sheet.save("icon_sizes.png")
    print("icon generated")


if __name__ == "__main__":
    main()
