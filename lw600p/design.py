"""One label description → preview image + printer job, shared by CLI and editor."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Optional

from PIL import Image

from . import label, protocol

CUT_MODES = {"each": protocol.CutMode.EACH_LABEL,
             "end": protocol.CutMode.END_OF_JOB,
             "none": protocol.CutMode.NONE}


@dataclass
class LabelSpec:
    text: str = ""
    image_path: Optional[str] = None
    tape_mm: int = 18
    font_path: Optional[str] = None
    size_pt: Optional[float] = None      # None = fit the tape
    bold: bool = False
    align: str = "center"
    margin_mm: float = 3.0
    length_mm: Optional[float] = None    # None = fit the content
    copies: int = 1
    density: int = 0
    cut: str = "each"
    dither: bool = True
    mirror: bool = False
    flip: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LabelSpec":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class Rendered:
    page: protocol.Page
    preview: Image.Image
    job: bytes
    tape: label.Tape

    @property
    def length_mm(self) -> float:
        return len(self.page.rows) * 25.4 / label.DPI


def render(spec: LabelSpec) -> Rendered:
    tape = label.TAPES[spec.tape_mm]
    first, last = tape.printable
    band = last - first
    if spec.image_path:
        art = label.load_image(spec.image_path, band, dither=spec.dither)
    else:
        if not spec.text.strip():
            raise ValueError("type some text or choose an image")
        art = label.render_text(spec.text, band, spec.font_path, spec.bold,
                                spec.align, spec.size_pt)
    page, preview = label.layout(art, tape, margin_mm=spec.margin_mm,
                                 length_mm=spec.length_mm, mirror=spec.mirror,
                                 flip=spec.flip)
    job = protocol.build_job([page], cut=CUT_MODES[spec.cut],
                             density=spec.density, copies=spec.copies)
    return Rendered(page, preview, job, tape)
