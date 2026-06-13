"""Generatore di icone PNG per la PWA, in pura libreria standard (niente Pillow).

Disegna un'icona "chart-like": sfondo scuro + una linea ascendente verde.
Serve a rendere la PWA installabile su iPhone (apple-touch-icon richiede un PNG).
"""

from __future__ import annotations

import struct
import zlib

_BG = (16, 22, 33)       # sfondo scuro
_LINE = (22, 163, 74)    # verde (trend up)


def _png(width: int, height: int, pixels: bytes) -> bytes:
    """Codifica RGBA grezzo (pixels = righe con filtro 0) in un PNG valido."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(pixels, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def chart_icon(size: int = 192) -> bytes:
    thick = max(2, size // 24)
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # byte di filtro per riga
        for x in range(size):
            # linea ascendente: y_line decresce all'aumentare di x
            y_line = int((size - 1) * (1 - x / (size - 1))) if size > 1 else 0
            on_line = abs(y - y_line) <= thick
            r, g, b = _LINE if on_line else _BG
            rows.extend((r, g, b, 255))
    return _png(size, size, bytes(rows))
