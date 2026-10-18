#!/usr/bin/env python3
"""Generate modern macOS AppIcon.icns for Alt Agent Harness."""

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


def generate_icon(output_icns_path: Path):
    size = 1024
    pixels = bytearray(size * size * 3)

    cx, cy = size / 2.0, size / 2.0
    box_r = 440.0

    def in_squircle(x, y):
        nx = (x - cx) / box_r
        ny = (y - cy) / box_r
        return (abs(nx) ** 4.5 + abs(ny) ** 4.5) <= 1.0

    # Draw 1024x1024 canvas
    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 3
            if in_squircle(x, y):
                # Rich dark-mode backdrop gradient
                t = (x + y) / (2.0 * size)
                r = int(24 * (1 - t) + 12 * t)
                g = int(22 * (1 - t) + 16 * t)
                b = int(48 * (1 - t) + 28 * t)

                # Outer glowing ring
                dist = math.hypot(x - cx, y - cy)
                is_ring = abs(dist - 370) < 12

                # Terminal prompt glyphs: '>' and cursor '_'
                # Arrow '>'
                is_arrow = False
                if 350 <= y <= 512 and abs(x - (320 + (y - 350))) < 32:
                    is_arrow = True
                elif 512 <= y <= 674 and abs(x - (482 - (y - 512))) < 32:
                    is_arrow = True

                # Cursor '_'
                is_cursor = (540 <= x <= 720 and 644 <= y <= 680)

                if is_arrow or is_cursor:
                    # Neon cyan / violet gradient
                    t_glyph = y / size
                    r = int(124 * (1 - t_glyph) + 0 * t_glyph)
                    g = int(111 * (1 - t_glyph) + 210 * t_glyph)
                    b = 255
                elif is_ring:
                    # Subtle glowing accent ring
                    r = min(255, r + 75)
                    g = min(255, g + 65)
                    b = min(255, b + 155)

                pixels[idx] = max(0, min(255, r))
                pixels[idx + 1] = max(0, min(255, g))
                pixels[idx + 2] = max(0, min(255, b))
            else:
                # Black outer margins
                pixels[idx] = 0
                pixels[idx + 1] = 0
                pixels[idx + 2] = 0

    temp_dir = Path("/tmp/alt_agent_icon_build")
    temp_dir.mkdir(parents=True, exist_ok=True)
    ppm_path = temp_dir / "icon_1024.ppm"
    png_path = temp_dir / "icon_1024.png"
    iconset_dir = temp_dir / "AppIcon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)

    with open(ppm_path, "wb") as f:
        f.write(f"P6\n{size} {size}\n255\n".encode("ascii"))
        f.write(pixels)

    subprocess.run(["sips", "-s", "format", "png", str(ppm_path), "--out", str(png_path)], check=True, capture_output=True)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
    ]

    for s, name in sizes:
        subprocess.run(
            ["sips", "-z", str(s), str(s), str(png_path), "--out", str(iconset_dir / name)],
            check=True,
            capture_output=True,
        )

    shutil.copy(png_path, iconset_dir / "icon_512x512@2x.png")

    output_icns_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_icns_path)], check=True)

    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"[icon] Generated {output_icns_path}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("AppIcon.icns")
    generate_icon(out)
