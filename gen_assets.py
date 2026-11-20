"""Generate Orbs application icons from the supplied transparent logo."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

OUT = Path(__file__).resolve().parent / "web" / "assets"
SOURCE = OUT / "orbs-logo.png"
if not SOURCE.exists():
    raise FileNotFoundError(f"Logo source not found: {SOURCE}")

with Image.open(SOURCE) as image:
    logo = image.convert("RGBA").resize((512, 512), Image.Resampling.LANCZOS)

logo.save(OUT / "icon.png")
logo.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon-256.png")
logo.save(OUT / "orbs.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"Orbs icons generated from {SOURCE}")
