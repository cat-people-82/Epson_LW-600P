"""Parse a LabelWorks job back into commands and an image (for verification)."""

from __future__ import annotations

import sys

from PIL import Image


def parse(job: bytes):
    """Yield ('cmd', name, params) / ('raster', dots, data) / ('ff',)."""
    i = 0
    while i < len(job):
        b = job[i]
        if b == 0x0C:
            yield ("ff",)
            i += 1
        elif job[i:i + 2] == b"\x1b{":
            n = job[i + 2]
            body = job[i + 3:i + 3 + n]
            cmd, params, chk, end = body[0], body[1:-2], body[-2], body[-1]
            if end != ord("}") or chk != (cmd + sum(params)) & 0xFF:
                raise ValueError(f"bad frame at offset {i}: {body.hex(' ')}")
            yield ("cmd", chr(cmd), bytes(params))
            i += 3 + n
        elif job[i:i + 2] == b"\x1b.":
            dots = job[i + 6] | job[i + 7] << 8
            size = (dots + 7) // 8
            yield ("raster", dots, job[i + 8:i + 8 + size])
            i += 8 + size
        else:
            raise ValueError(f"unexpected byte 0x{b:02x} at offset {i}")


def to_images(job: bytes) -> list[Image.Image]:
    """Render each page as the printer would lay it on tape (rows = lines)."""
    pages, rows, dots = [], [], 0
    for item in parse(job):
        if item[0] == "raster":
            dots, rows = item[1], rows + [item[2]]
        elif item[0] == "ff" and rows:
            img = Image.frombytes("1", (dots, len(rows)), b"".join(rows))
            pages.append(img.point(lambda v: 255 - v))
            rows = []
    return pages


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    job = open(argv[0], "rb").read()
    for item in parse(job):
        if item[0] == "cmd":
            print(f"ESC {{ {item[1]!r} {item[2].hex(' ')}")
    for n, img in enumerate(to_images(job)):
        if len(argv) > 1:
            path = argv[1].replace(".png", f"-{n}.png")
            # Rotate back to reading orientation for human inspection.
            img.convert("L").transpose(Image.Transpose.ROTATE_270).save(path)
            print(f"page {n}: {img.size[0]} dots x {img.size[1]} lines -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
