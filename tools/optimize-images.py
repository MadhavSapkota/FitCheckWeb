"""Build responsive WebP copies without changing the supplied originals.
Requires Pillow; run with python3.13 tools/optimize-images.py.
"""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'assets' / 'responsive'
OUTPUT.mkdir(exist_ok=True)
for source in sorted((ROOT / 'assets').glob('*.webp')):
    if not source.name.startswith(('fitcheck-look-', 'hero-background-')):
        continue
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        for width in (360, 720):
            if image.width <= width:
                continue
            resized = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
            resized.save(OUTPUT / f'{source.stem}-{width}.webp', 'WEBP', quality=85, method=6)
print('Responsive images generated. Original photos remain intact.')
