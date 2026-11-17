"""Render text or images into LW-600P raster pages.

Geometry comes from the original "EPSON LW-600P" PPD: page width (points)
per tape and the imageable band across it, at 180 dpi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .protocol import MAX_LEAD_DOTS, MIN_LEAD_DOTS, Page

DPI = 180
TRAIL_CAP_DOTS = int(DPI * 10 / 25.4)  # 70: trailing margin cap used by the driver


def pt_to_dots(points: float) -> int:
    return int(math.floor(points * DPI / 72 + 0.5))


def mm_to_dots(mm: float) -> int:
    return int(round(mm * DPI / 25.4))


@dataclass(frozen=True)
class Tape:
    width_mm: int
    page_pt: float      # *PageSize width
    left_pt: float      # *ImageableArea llx
    right_pt: float     # *ImageableArea urx
    status_code: int    # tape-width code reported in status byte 3

    @property
    def dots(self) -> int:
        return pt_to_dots(self.page_pt)

    @property
    def printable(self) -> tuple[int, int]:
        """(first, last+1) dot indices of the imageable band."""
        return pt_to_dots(self.left_pt), pt_to_dots(self.right_pt)


TAPES = {
    6: Tape(6, 17.0, 1.0, 15.0, 0x01),
    9: Tape(9, 25.0, 2.0, 22.0, 0x02),
    12: Tape(12, 34.0, 3.0, 31.0, 0x03),
    18: Tape(18, 51.0, 4.0, 46.0, 0x04),
    24: Tape(24, 68.0, 8.0, 58.0, 0x05),
}

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    for candidate in ([path] if path else []) + list(FONT_CANDIDATES):
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


FONT_DIRS = ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
             "/Library/Fonts", str(Path.home() / "Library/Fonts"))


def list_fonts() -> dict[str, str]:
    """Map "Family Style" display names to font file paths (first face only)."""
    fonts: dict[str, str] = {}
    for folder in FONT_DIRS:
        for path in sorted(Path(folder).glob("*")):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                family, style = ImageFont.truetype(str(path), 12).getname()
            except OSError:
                continue
            if family.startswith("."):
                continue  # hidden system UI fonts
            name = family if style in ("Regular", "Normal", None) else f"{family} {style}"
            fonts.setdefault(name, str(path))
    return dict(sorted(fonts.items(), key=lambda kv: kv[0].lower()))


def pt_size_to_dots(points: float) -> int:
    return max(1, round(points * DPI / 72))


def _text_box(lines, font, size, align, bold):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = probe.multiline_textbbox((0, 0), "\n".join(lines), font=font,
                                    spacing=size // 8, align=align,
                                    stroke_width=1 if bold else 0)
    # Pillow returns float boxes for multi-line text; snap outward.
    return (math.floor(bbox[0]), math.floor(bbox[1]),
            math.ceil(bbox[2]), math.ceil(bbox[3]))


def render_text(text: str, band_dots: int, font_path: Optional[str] = None,
                bold: bool = False, align: str = "center",
                size_pt: Optional[float] = None) -> Image.Image:
    """Render (multi-line) text as a 1-bit image exactly ``band_dots`` tall.

    With ``size_pt`` None the largest font that fits the band is used;
    otherwise the text is set at that point size and must fit the band.
    """
    lines = text.split("\\n") if "\\n" in text else text.splitlines() or [""]
    if size_pt is not None:
        size = pt_size_to_dots(size_pt)
        font = load_font(font_path, size)
        bbox = _text_box(lines, font, size, align, bold)
        if bbox[3] - bbox[1] > band_dots:
            max_mm = band_dots * 25.4 / DPI
            raise ValueError(f"{size_pt:g}pt text is too tall for this tape "
                             f"(printable height {max_mm:.1f}mm)")
    else:
        lo, hi, best = 4, band_dots * 2, None
        while lo <= hi:
            size = (lo + hi) // 2
            font = load_font(font_path, size)
            bbox = _text_box(lines, font, size, align, bold)
            if bbox[3] - bbox[1] <= band_dots:
                best, lo = (font, bbox, size), size + 1
            else:
                hi = size - 1
        if best is None:
            raise ValueError("text cannot fit on this tape")
        font, bbox, size = best
    width = bbox[2] - bbox[0]
    img = Image.new("L", (max(width, 1), band_dots), 255)
    y_off = (band_dots - (bbox[3] - bbox[1])) // 2 - bbox[1]
    ImageDraw.Draw(img).multiline_text(
        (-bbox[0], y_off), "\n".join(lines), font=font, fill=0,
        spacing=size // 8, align=align, stroke_width=1 if bold else 0,
        stroke_fill=0)
    return img.point(lambda v: 0 if v < 128 else 255, mode="1")


def load_image(path: str, band_dots: int, dither: bool = True) -> Image.Image:
    """Scale an image to the printable band height and binarise it."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img).convert("L")
    scale = band_dots / img.height
    img = img.resize((max(1, round(img.width * scale)), band_dots),
                     Image.Resampling.LANCZOS)
    if dither:
        return img.convert("1")  # Floyd–Steinberg, like the driver's "Errordiff"
    return img.point(lambda v: 0 if v < 128 else 255, mode="1")


def choose_length(content_dots: int, margin_dots: int,
                  length_dots: Optional[int]) -> tuple[int, int]:
    """Decide (lead, trail) blank rows around ``content_dots`` of artwork.

    ``length_dots`` is None for an auto-length label, otherwise the total
    label length the user asked for.

    Constraints recovered from the driver:
      * lead below MIN_LEAD_DOTS (10) is reported to the printer as 10
      * the driver's own trailing margin mirrors the lead, capped at 70 dots
    """
    if length_dots is None:
        lead = max(MIN_LEAD_DOTS, min(margin_dots, MAX_LEAD_DOTS))
        trail = min(lead, TRAIL_CAP_DOTS)
        return lead, trail

    # TODO(you): fixed-length labels. Return (lead, trail) so that
    #   lead + content_dots + trail == length_dots
    # Decide what happens when the artwork is longer than the requested
    # length, and how the content is positioned (centred? left-aligned at
    # margin_dots?). Keep lead within [MIN_LEAD_DOTS, MAX_LEAD_DOTS].
    raise NotImplementedError("fixed --length labels: see choose_length()")


def layout(art: Image.Image, tape: Tape, *, margin_mm: float = 3.0,
           length_mm: Optional[float] = None, mirror: bool = False,
           flip: bool = False) -> tuple[Page, Image.Image]:
    """Place landscape artwork on the tape and convert it to raster rows.

    ``art`` is a 1-bit image as it should read on the label (width runs
    along the tape, height is the printable band). Returns the Page plus
    the full landscape preview image.
    """
    first, last = tape.printable
    band = last - first
    if art.height > band:
        raise ValueError(f"artwork is {art.height} dots tall, band is {band}")

    lead, trail = choose_length(
        art.width, mm_to_dots(margin_mm),
        mm_to_dots(length_mm) if length_mm else None)

    canvas = Image.new("1", (lead + art.width + trail, tape.dots), 1)
    canvas.paste(art, (lead, first + (band - art.height) // 2))

    # The driver prints portrait CUPS pages; a landscape label reaches it
    # rotated 90° counter-clockwise, so raster row 0 is the label's right
    # end and dot 0 is the top edge of the text. ``flip`` turns it 180°.
    portrait = canvas.transpose(
        Image.Transpose.ROTATE_270 if flip else Image.Transpose.ROTATE_90)
    if mirror:
        portrait = ImageOps.mirror(portrait)

    # PIL "1" images: 0 = black. Printer bits: 1 = dot.
    packed = ImageOps.invert(portrait.convert("L")).convert(
        "1", dither=Image.Dither.NONE).tobytes()
    stride = (tape.dots + 7) // 8
    rows = [packed[i * stride:(i + 1) * stride] for i in range(portrait.height)]
    page_lead = trail if not flip else lead  # blank rows before first ink row
    return Page(dots=tape.dots, rows=rows, lead=page_lead), canvas
