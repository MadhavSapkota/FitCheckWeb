"""Regenerate the original, lightweight SVG screenshot placeholders. No dependencies."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = '''<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640" viewBox="0 0 360 640">
<rect width="360" height="640" fill="#faf9f6"/>
<rect x="138" y="10" width="84" height="18" rx="9" fill="#19191b"/>
<g font-family="Arial,Helvetica,sans-serif" fill="#19191b">
<text x="24" y="65" font-size="22" font-weight="700" letter-spacing="-1">fitcheck</text>
<text x="309" y="63" font-size="20">✦</text>
<text x="24" y="112" font-size="11" fill="#66616d" letter-spacing="1">{kicker}</text>
<text x="24" y="151" font-size="28" font-weight="700" letter-spacing="-1">{headline}</text>
{body}
<path d="M0 581h360" stroke="#deddd8"/>
<text x="35" y="610" font-size="12">Fit check</text><text x="151" y="610" font-size="12" fill="#66616d">Explore</text><text x="263" y="610" font-size="12" fill="#66616d">Closet</text>
<rect x="52" y="622" width="256" height="17" rx="4" fill="#19191b"/>
<text x="180" y="634" fill="#fff" font-size="9" text-anchor="middle" letter-spacing="1">SCREENSHOT PLACEHOLDER</text>
</g></svg>'''

upload = '''<rect x="24" y="181" width="312" height="283" rx="17" fill="#ece7f4" stroke="#b3a4cb" stroke-dasharray="6 6"/>
<circle cx="180" cy="290" r="47" fill="#d0c2e9"/>
<g fill="none" stroke="#50425f" stroke-width="2.5"><rect x="154" y="274" width="52" height="34" rx="5"/><path d="m163 274 5-8h23l6 8"/><circle cx="180" cy="291" r="10"/></g>
<text x="180" y="365" font-size="17" text-anchor="middle" font-weight="700">A mirror moment.</text>
<text x="180" y="391" font-size="12" fill="#66616d" text-anchor="middle">Your outfit photo goes here.</text>
<rect x="24" y="487" width="312" height="51" rx="10" fill="#19191b"/>
<text x="180" y="519" fill="#fff" text-anchor="middle" font-size="14">Upload your outfit  ↗</text>'''

feedback = '''<rect x="24" y="178" width="312" height="183" rx="17" fill="#e3edce"/>
<text x="180" y="217" font-size="10" text-anchor="middle" letter-spacing="1">EXAMPLE STYLE SCORE</text>
<text x="172" y="291" font-size="68" font-weight="700" text-anchor="middle" letter-spacing="-4">8.8</text>
<text x="248" y="291" font-size="17">/10</text>
<text x="180" y="330" font-size="12" text-anchor="middle">A fresh take on your everyday fit.</text>
<text x="24" y="403" font-size="18" font-weight="700">The little details</text>
<rect x="24" y="423" width="312" height="111" rx="12" fill="#eee9f6"/>
<text x="42" y="454" font-size="13" font-weight="700">✦  Try a little color</text>
<text x="42" y="482" font-size="12" fill="#66616d">An accent accessory can bring</text>
<text x="42" y="502" font-size="12" fill="#66616d">your whole outfit together.</text>'''

closet = '''<text x="24" y="183" font-size="12" fill="#66616d">Good outfits deserve a repeat.</text>'''
for x, y, color, label, garment in [
    (24, 211, '#e5ddf3', 'Everyday energy', 'shirt'),
    (188, 211, '#e4edce', 'Weekend ready', 'pants'),
    (24, 387, '#f2e1d6', 'A little color', 'shirt'),
    (188, 387, '#dce8ed', 'The go-to', 'shirt'),
]:
    closet += f'<rect x="{x}" y="{y}" width="148" height="155" rx="12" fill="{color}"/>'
    if garment == 'shirt':
        closet += f'<g transform="translate({x},{y})"><path d="m47 23-24 20 17 22 12-10v53h46V55l12 10 17-22-24-20-15-5c0 16-23 16-23 0Z" fill="#faf9f6" stroke="#716879" stroke-width="1.5"/></g>'
    else:
        closet += f'<g transform="translate({x},{y})"><path d="M49 20h51l10 91-34 2-4-57-7 57-30-2Z" fill="#63606b" stroke="#38353e" stroke-width="1.5"/></g>'
    closet += f'<text x="{x+12}" y="{y+139}" font-size="11">{label}</text>'

for name, kicker, headline, body in [
    ('upload', 'YOUR NEXT GREAT FIT', 'Let’s see the look.', upload),
    ('feedback', 'YOUR FIT CHECK', 'The fit is fitting.', feedback),
    ('closet', 'YOUR DIGITAL CLOSET', 'Keep the good ones.', closet),
]:
    (ROOT / 'assets' / f'screenshot-{name}.svg').write_text(BASE.format(kicker=kicker, headline=headline, body=body))
print('Created three SVG screenshot placeholders.')
