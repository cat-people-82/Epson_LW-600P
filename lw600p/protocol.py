"""Epson LabelWorks wire protocol, as recovered from rastertolw 1.37.

Every control command is framed as::

    ESC '{' <len> <cmd> <params...> <checksum> '}'

where ``len`` counts the bytes from ``cmd`` through the closing ``'}'`` and
``checksum`` is the low byte of ``cmd + sum(params)``
(ESCPCommand::makeCommand @ 0x100003530).

Raster data uses the standard ESC/P "print raster graphics" command, one
line across the tape per command (ESCPCommand::doSendRasterData @ 0x100003230)::

    ESC '.' 00 00 00 01 <nL> <nH> <ceil(n/8) bytes, MSB = first dot>
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

ESC = 0x1B
FORM_FEED = 0x0C

# Leading-margin clamp and trailing-margin cap from ESCPCommand::setRasterInfo
# (@ 0x1000038e0): 10 dots minimum, 5300 maximum, trailing capped at
# 10mm worth of dots (int(res * 10 / 25.4) == 70 at 180 dpi).
MIN_LEAD_DOTS = 10
MAX_LEAD_DOTS = 5300


def frame(cmd: int, params: Sequence[int] = ()) -> bytes:
    """Wrap one command in the ESC { ... } envelope with its checksum."""
    for p in params:
        if not 0 <= p <= 0xFF:
            raise ValueError(f"parameter byte out of range: {p}")
    checksum = (cmd + sum(params)) & 0xFF
    body = bytes([cmd, *params, checksum, ord("}")])
    return bytes([ESC, ord("{"), len(body)]) + body


class CutMode(Enum):
    """Cut behaviour, mapped to the 4 parameter bytes of command 'C'.

    Values come from UIParams::setUIParam (EPLWTapeCut / EPLWHalfCut). The
    LW-600P PPD has no half-cut option, so only full-cut modes are exposed.
    """

    EACH_LABEL = (0x03, 0x01, 0x01, 0x01)  # "EachPage"
    END_OF_JOB = (0x03, 0x00, 0x01, 0x01)  # "EachJob"
    NONE = (0x00, 0x00, 0x00, 0x00)        # "None"


def cmd_start_job() -> bytes:
    """'{' with fixed params 00 00 'S' 'T' — opens the session."""
    return frame(ord("{"), (0x00, 0x00, ord("S"), ord("T")))


def cmd_cut(mode: CutMode) -> bytes:
    return frame(ord("C"), mode.value)


def cmd_density(density: int) -> bytes:
    """Print density -3..+3 (PPD EPLWDensity); sent as density + 5."""
    if not -3 <= density <= 3:
        raise ValueError("density must be between -3 and +3")
    return frame(ord("D"), (density + 5,))


def cmd_g() -> bytes:
    """Parameterless 'G' sent at job start (purpose not named in the binary)."""
    return frame(ord("G"))


def cmd_speed(speed: int = 0) -> bytes:
    """'s' print speed; 0 when the PPD has no EPLWPrintSpeed (LW-600P)."""
    return frame(ord("s"), (speed & 0xFF,))


def cmd_length(lines: int) -> bytes:
    """'L' total label length in raster lines, 32-bit little endian."""
    return frame(ord("L"), tuple(lines.to_bytes(4, "little")))


def cmd_lead_margin(dots: int) -> bytes:
    """'T' leading blank margin in raster lines, 16-bit little endian."""
    return frame(ord("T"), tuple(dots.to_bytes(2, "little")))


def cmd_end_job() -> bytes:
    return frame(ord("@"))


def cmd_feed(cut: bool) -> bytes:
    """'+' tape feed (param 0) or feed-and-cut (param 1), from LWLib."""
    return frame(ord("+"), (1 if cut else 0,))


def raster_line(row: bytes, dots: int) -> bytes:
    """One ESC . raster line of ``dots`` pixels (row is packed MSB-first)."""
    expected = (dots + 7) // 8
    if len(row) != expected:
        raise ValueError(f"row has {len(row)} bytes, expected {expected}")
    return bytes([ESC, ord("."), 0, 0, 0, 1, dots & 0xFF, dots >> 8]) + row


@dataclass(frozen=True)
class Page:
    """A fully laid-out label: rows run along the tape, dots across it.

    ``lead`` is the number of blank rows before the first printed row; the
    rows list already contains those blank rows plus any trailing margin.
    """

    dots: int
    rows: Sequence[bytes]
    lead: int


def page_commands(page: Page) -> bytes:
    """Per-label header + raster + form feed (doStartPage/doEndPage)."""
    lead = max(MIN_LEAD_DOTS, min(page.lead, MAX_LEAD_DOTS))
    out = bytearray()
    out += cmd_length(len(page.rows))
    out += cmd_lead_margin(lead)
    for row in page.rows:
        out += raster_line(row, page.dots)
    out.append(FORM_FEED)
    return bytes(out)


def build_job(
    pages: Iterable[Page],
    *,
    cut: CutMode = CutMode.EACH_LABEL,
    density: int = 0,
    copies: int = 1,
) -> bytes:
    """Assemble a complete print job, byte-for-byte in the driver's order."""
    out = bytearray()
    out += cmd_start_job()
    out += cmd_cut(cut)
    out += cmd_density(density)
    out += cmd_g()
    out += cmd_speed(0)
    for page in pages:
        body = page_commands(page)
        for _ in range(copies):
            out += body
    out += cmd_end_job()
    return bytes(out)
