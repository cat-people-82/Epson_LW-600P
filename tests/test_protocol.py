"""Byte-level expectations taken directly from the rastertolw 1.37 disassembly."""

import pytest
from PIL import Image

from lw600p import label, protocol as p
from lw600p.transport import Status


# --- command framing (ESCPCommand::makeCommand) --------------------------

def test_start_job_matches_hardcoded_checksum():
    # makeCommand '{': 07 7b 00 00 53 54, checksum = '{' - 0x59 = 0x22
    assert p.cmd_start_job() == bytes.fromhex("1b7b077b000053542 27d".replace(" ", ""))


@pytest.mark.parametrize("mode, params", [
    (p.CutMode.EACH_LABEL, "03010101"),   # 0x01010103 little-endian
    (p.CutMode.END_OF_JOB, "03000101"),   # 0x01010003
    (p.CutMode.NONE, "00000000"),
])
def test_cut_command(mode, params):
    body = bytes.fromhex("43" + params)
    chk = sum(body) & 0xFF
    assert p.cmd_cut(mode) == b"\x1b{\x07" + body + bytes([chk]) + b"}"


def test_density_offset_by_five():
    assert p.cmd_density(0) == bytes.fromhex("1b7b04440549" + "7d")
    assert p.cmd_density(-3)[4] == 2 and p.cmd_density(3)[4] == 8
    with pytest.raises(ValueError):
        p.cmd_density(4)


def test_parameterless_commands_repeat_cmd_as_checksum():
    assert p.cmd_g() == bytes.fromhex("1b7b0347477d")
    assert p.cmd_end_job() == bytes.fromhex("1b7b0340407d")


def test_length_and_margin_little_endian():
    assert p.cmd_length(0x1234) == bytes.fromhex("1b7b074c341200009 27d".replace(" ", ""))
    assert p.cmd_lead_margin(300) == bytes.fromhex("1b7b05542c01817d")


def test_feed_commands_from_lwlib():
    assert p.cmd_feed(cut=False) == bytes.fromhex("1b7b042b002b7d")
    assert p.cmd_feed(cut=True) == bytes.fromhex("1b7b042b012c7d")


def test_raster_line_header():
    line = p.raster_line(b"\xff" * 16, 128)
    assert line[:8] == bytes.fromhex("1b2e000000018000")
    assert len(line) == 8 + 16
    with pytest.raises(ValueError):
        p.raster_line(b"\x00", 128)


# --- job ordering (doStartDoc / doStartPage / doEndPage / doEndDoc) -----

def test_job_order_and_copies():
    page = p.Page(dots=8, rows=[b"\x00"] * 30, lead=12)
    job = p.build_job([page], copies=2)
    head = (p.cmd_start_job() + p.cmd_cut(p.CutMode.EACH_LABEL)
            + p.cmd_density(0) + p.cmd_g() + p.cmd_speed(0))
    assert job.startswith(head)
    assert job.endswith(b"\x0c" + p.cmd_end_job())
    assert job.count(p.cmd_length(30)) == 2
    assert job.count(b"\x1b.") == 60


def test_lead_margin_clamped_to_driver_minimum():
    page = p.Page(dots=8, rows=[b"\x00"] * 20, lead=0)
    assert p.cmd_lead_margin(10) in p.page_commands(page)


# --- geometry from the PPD ----------------------------------------------

@pytest.mark.parametrize("mm, dots", [(6, 43), (9, 63), (12, 85), (18, 128), (24, 170)])
def test_tape_dots(mm, dots):
    assert label.TAPES[mm].dots == dots


def test_layout_rotation_and_bits():
    tape = label.TAPES[18]
    art = Image.new("1", (5, 4), 1)
    art.putpixel((4, 0), 0)          # rightmost column, top row of the text
    page, _ = label.layout(art, tape, margin_mm=0)
    lead, trail = label.choose_length(5, 0, None)
    assert len(page.rows) == lead + 5 + trail
    # Rotated CCW: the label's right end is the first inked row.
    first_ink = next(i for i, r in enumerate(page.rows) if any(r))
    assert first_ink == trail
    first, last = tape.printable
    top_dot = first + ((last - first) - 4) // 2
    row = page.rows[first_ink]
    assert row[top_dot // 8] & (0x80 >> (top_dot % 8))


def test_status_decoding():
    st = Status(bytes([0, 0, 0, 4, 0, 0, 0, 0]))
    assert st.tape == "18mm" and st.tape_mm == 18 and st.error == 0
