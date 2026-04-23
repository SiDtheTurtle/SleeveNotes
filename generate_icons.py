"""Generate static/icon-192.png and static/icon-512.png using stdlib only."""
import struct, zlib, math

BG     = (245, 240, 232, 255)   # #F5F0E8 cream
RECORD = (26,  26,  26,  255)   # #1A1A1A dark vinyl
LABEL  = (184, 150, 46,  255)   # #B8962E gold

def make_png(size):
    cx = cy = size / 2
    r_outer = size * 0.44          # record — leaves a small margin
    r_inner = r_outer * 0.28       # gold label area (mirrors SVG proportions)

    rows = []
    for y in range(size):
        row = bytearray([0])       # filter byte: None
        for x in range(size):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            row.extend(LABEL if d <= r_inner else RECORD if d <= r_outer else BG)
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
        + chunk(b'IEND', b'')
    )

for size, path in [(192, 'static/icon-192.png'), (512, 'static/icon-512.png')]:
    with open(path, 'wb') as f:
        f.write(make_png(size))
    print(f'Generated {path}')
