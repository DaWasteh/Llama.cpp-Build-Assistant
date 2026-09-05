"""Prepare platform icon files from icon.png for PyInstaller builds."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build_assets"
SOURCE = ROOT / "icon.png"


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing icon source: {SOURCE}")

    BUILD_DIR.mkdir(exist_ok=True)
    image = Image.open(SOURCE).convert("RGBA")

    image.save(BUILD_DIR / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(BUILD_DIR / "icon.icns")
    image.save(BUILD_DIR / "icon.png")


if __name__ == "__main__":
    main()
