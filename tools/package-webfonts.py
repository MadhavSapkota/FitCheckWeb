"""Losslessly package supplied TrueType font tables into standard WOFF containers.

Usage: python3 tools/package-webfonts.py /path/to/Inter-font-directory
"""
from pathlib import Path
import struct
import sys
import zlib

root = Path(__file__).resolve().parents[1]
font_dir = Path(sys.argv[1])
for weight in ['Regular', 'SemiBold']:
    original = (font_dir / f'Inter-{weight}.ttf').read_bytes()
    count = struct.unpack_from('>H', original, 4)[0]
    tables = []
    for index in range(count):
        tag, checksum, offset, length = struct.unpack_from('>4sIII', original, 12 + index * 16)
        raw = original[offset:offset + length]
        compressed = zlib.compress(raw, 9)
        tables.append({'tag': tag, 'checksum': checksum, 'raw': raw, 'source_offset': offset,
                       'packed': compressed if len(compressed) < length else raw})
    offset = 44 + 20 * count
    chunks = []
    for table in sorted(tables, key=lambda item: item['source_offset']):
        table['offset'] = offset
        data = table['packed']
        padded = data + b'\0' * ((-len(data)) % 4)
        chunks.append(padded)
        offset += len(padded)
    sfnt_size = 12 + 16 * count + sum((len(item['raw']) + 3) & ~3 for item in tables)
    header = struct.pack('>4sIIHHIHHIIIII', b'wOFF', struct.unpack_from('>I', original)[0],
                         offset, count, 0, sfnt_size, 4, 1, 0, 0, 0, 0, 0)
    directory = b''.join(struct.pack('>4sIIII', item['tag'], item['offset'],
                                    len(item['packed']), len(item['raw']), item['checksum'])
                         for item in tables)
    output = header + directory + b''.join(chunks)
    assert len(output) == offset
    # Check every decompressed table against the original source.
    for index, table in enumerate(tables):
        tag, start, packed_size, raw_size, checksum = struct.unpack_from('>4sIIII', output, 44 + 20 * index)
        data = output[start:start + packed_size]
        recovered = zlib.decompress(data) if packed_size < raw_size else data
        assert recovered == table['raw'] and checksum == table['checksum']
    path = root / 'assets/fonts' / f'inter-{weight.lower()}.woff'
    path.write_bytes(output)
    print(f'{path.name}: {len(output):,} bytes; all {count} font tables verified losslessly.')
