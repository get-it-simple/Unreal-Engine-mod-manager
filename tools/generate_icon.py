#!/usr/bin/env python3
"""Generate the application icon: a gamepad inside a gear.

Requires Pillow (a PyInstaller dependency, used only to build this asset).
Run with: python tools/generate_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

BACKGROUND = "#051923"
GOLD = "#D9A521"
BODY = "#0582CA"
ACCENT = "#00A6FB"
ACCENT_DARK = "#006494"
OUTLINE = "#003554"

SIZE = 1024
CENTER = SIZE // 2

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _gear_teeth(draw: ImageDraw.ImageDraw, center: tuple[int, int], root_r: int, tip_r: int, count: int, half_width_deg: float, fill: str) -> None:
    cx, cy = center
    for i in range(count):
        angle = 360.0 / count * i
        a0 = math.radians(angle - half_width_deg)
        a1 = math.radians(angle + half_width_deg)
        points = [
            (cx + root_r * math.cos(a0), cy + root_r * math.sin(a0)),
            (cx + tip_r * math.cos(a0), cy + tip_r * math.sin(a0)),
            (cx + tip_r * math.cos(a1), cy + tip_r * math.sin(a1)),
            (cx + root_r * math.cos(a1), cy + root_r * math.sin(a1)),
        ]
        draw.polygon(points, fill=fill)


def _circle(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, **kwargs) -> None:
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), **kwargs)


def build_icon() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = 32
    draw.rounded_rectangle((margin, margin, SIZE - margin, SIZE - margin), radius=220, fill=BACKGROUND)

    gear_root_r = 400
    gear_tip_r = 460
    _circle(draw, (CENTER, CENTER), gear_root_r, fill=GOLD)
    _gear_teeth(draw, (CENTER, CENTER), gear_root_r, gear_tip_r, count=12, half_width_deg=11, fill=GOLD)
    _circle(draw, (CENTER, CENTER), 330, fill=BACKGROUND)

    body_box = (CENTER - 260, CENTER - 150, CENTER + 260, CENTER + 150)
    draw.rounded_rectangle(body_box, radius=110, fill=BODY, outline=OUTLINE, width=12)

    dpad_cx, dpad_cy = CENTER - 122, CENTER
    draw.rounded_rectangle((dpad_cx - 70, dpad_cy - 22, dpad_cx + 70, dpad_cy + 22), radius=10, fill=OUTLINE)
    draw.rounded_rectangle((dpad_cx - 22, dpad_cy - 70, dpad_cx + 22, dpad_cy + 70), radius=10, fill=OUTLINE)

    for bx, by in ((CENTER + 90, CENTER - 64), (CENTER + 154, CENTER)):
        _circle(draw, (bx, by), 34, fill=ACCENT, outline=ACCENT_DARK, width=6)

    return image


def main() -> None:
    icon = build_icon()
    ASSETS_DIR.mkdir(exist_ok=True)

    png_path = ASSETS_DIR / "icon.png"
    icon.resize((256, 256), Image.LANCZOS).save(png_path)

    ico_path = ASSETS_DIR / "icon.ico"
    icon.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()
