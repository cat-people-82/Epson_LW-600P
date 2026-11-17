import pytest

from lw600p import design, label, protocol
from lw600p.decode import parse


def test_render_text_job_is_valid_and_matches_tape():
    out = design.render(design.LabelSpec(text="Shelf 3", tape_mm=12, copies=2))
    assert out.page.dots == label.TAPES[12].dots
    cmds = [i[1] for i in parse(out.job) if i[0] == "cmd"]  # checksums verified
    assert cmds == ["{", "C", "D", "G", "s", "L", "T", "L", "T", "@"]


def test_fixed_point_size_too_tall_is_rejected():
    with pytest.raises(ValueError, match="too tall"):
        design.render(design.LabelSpec(text="Big", tape_mm=6, size_pt=72))


def test_alignment_changes_layout_not_size():
    left = label.render_text("a\nlonger", 100, align="left", size_pt=10)
    right = label.render_text("a\nlonger", 100, align="right", size_pt=10)
    assert left.size == right.size and left.tobytes() != right.tobytes()


def test_empty_text_is_reported():
    with pytest.raises(ValueError):
        design.render(design.LabelSpec(text="   "))


def test_spec_round_trip_ignores_unknown_keys():
    spec = design.LabelSpec(text="x", cut="end", density=-2)
    data = spec.to_dict() | {"future_option": 1}
    assert design.LabelSpec.from_dict(data) == spec


def test_cut_modes_map_to_protocol():
    out = design.render(design.LabelSpec(text="x", cut="none"))
    assert protocol.cmd_cut(protocol.CutMode.NONE) in out.job
