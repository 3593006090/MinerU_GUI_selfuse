"""生成应用图标 assets/icon.ico（构建机使用，需 Pillow）。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "icon.ico"
SIZE = 256


def gradient() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE))
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = int(0x5B + (0x8F - 0x5B) * t)
        g = int(0x4C + (0x7B - 0x4C) * t)
        b = int(0xF5 + (0xFF - 0xF5) * t)
        d.line([(0, y), (SIZE, y)], fill=(r, g, b))
    return img


def main() -> None:
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=58, fill=255)
    base.paste(gradient(), (0, 0), mask)

    d = ImageDraw.Draw(base)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 150)
    bbox = d.textbbox((0, 0), "M", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1] - 4), "M",
           font=font, fill=(255, 255, 255, 255))
    base.save(OUT, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("icon ->", OUT)


if __name__ == "__main__":
    main()
