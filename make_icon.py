#!/usr/bin/env python3
"""
Tao file icon.ico cho app 3GPP Search
Chay 1 lan: python make_icon.py
Yeu cau: pip install Pillow
"""

def make_icon():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        import subprocess, sys
        print("Dang cai Pillow...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "--quiet"])
        from PIL import Image, ImageDraw, ImageFont

    from pathlib import Path

    sizes = [256, 128, 64, 48, 32, 16]
    frames = []

    for size in sizes:
        img  = Image.new("RGBA", (size, size), (0,0,0,0))
        draw = ImageDraw.Draw(img)

        # Background circle - dark navy
        pad = size // 12
        draw.ellipse([pad, pad, size-pad, size-pad],
                     fill=(31, 78, 121, 255))

        # "3G" text
        text = "3G"
        font_size = int(size * 0.38)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        # Center text
        bbox = draw.textbbox((0,0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) // 2 - bbox[0]
        ty = (size - th) // 2 - bbox[1] - int(size * 0.03)
        draw.text((tx, ty), text, fill=(79, 142, 247, 255), font=font)

        frames.append(img)

    out = Path(__file__).parent / "icon.ico"
    frames[0].save(out, format="ICO", sizes=[(s,s) for s in sizes],
                   append_images=frames[1:])
    print(f"Da tao: {out}")

if __name__ == "__main__":
    make_icon()
