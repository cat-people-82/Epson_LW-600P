"""lw600p — print labels on an Epson LabelWorks LW-600P without the old driver."""

from __future__ import annotations

import argparse
import sys

from . import design, label, protocol


def _tape_arg(value: str) -> int:
    mm = int(value.lower().removesuffix("mm"))
    if mm not in label.TAPES:
        raise argparse.ArgumentTypeError(
            f"tape must be one of {', '.join(map(str, label.TAPES))} mm")
    return mm


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lw600p", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("print", help="print a text or image label")
    src = pr.add_mutually_exclusive_group(required=True)
    src.add_argument("text", nargs="?", help="label text (use \\n for a new line)")
    src.add_argument("--image", help="print an image file instead of text")
    pr.add_argument("--tape", type=_tape_arg, default=None,
                    help="tape width in mm (default: detect from printer, else 18)")
    pr.add_argument("--font", help="path to a .ttf/.ttc font")
    pr.add_argument("--bold", action="store_true")
    pr.add_argument("--size", type=float, metavar="PT",
                    help="font size in points (default: fit the tape)")
    pr.add_argument("--align", choices=("left", "center", "right"),
                    default="center", help="alignment of multi-line text")
    pr.add_argument("--margin", type=float, default=3.0, metavar="MM",
                    help="blank margin at each end (default 3mm)")
    pr.add_argument("--length", type=float, metavar="MM",
                    help="fixed label length in mm (default: fit content)")
    pr.add_argument("--copies", type=int, default=1)
    pr.add_argument("--density", type=int, default=0, choices=range(-3, 4),
                    metavar="-3..3")
    pr.add_argument("--cut", choices=("each", "end", "none"), default="each",
                    help="cut after each label, at the end of the job, or never")
    pr.add_argument("--threshold", action="store_true",
                    help="threshold images instead of error-diffusion dithering")
    pr.add_argument("--mirror", action="store_true")
    pr.add_argument("--flip", action="store_true",
                    help="rotate output 180° (if labels come out upside down)")
    pr.add_argument("--preview", metavar="PNG", help="save a preview image")
    pr.add_argument("--output", metavar="FILE",
                    help="write the raw job to FILE instead of the printer")
    pr.add_argument("--pid", type=lambda s: int(s, 0), help="override USB product id")

    st = sub.add_parser("status", help="show printer status")
    st.add_argument("--pid", type=lambda s: int(s, 0))

    fd = sub.add_parser("feed", help="feed tape (optionally cut)")
    fd.add_argument("--cut", action="store_true")
    fd.add_argument("--pid", type=lambda s: int(s, 0))
    return p


def _open(pid):
    from .transport import LabelPrinter
    return LabelPrinter(pid=pid)


def cmd_print(args) -> int:
    spec = design.LabelSpec(
        text=args.text or "", image_path=args.image, tape_mm=args.tape or 18,
        font_path=args.font, size_pt=args.size, bold=args.bold,
        align=args.align, margin_mm=args.margin, length_mm=args.length,
        copies=args.copies, density=args.density, cut=args.cut,
        dither=not args.threshold, mirror=args.mirror, flip=args.flip)
    printer = None if args.output else _open(args.pid)
    try:
        if printer:
            st = printer.status()
            print(f"Printer: {st.describe()}")
            if args.tape is None and st.tape_mm in label.TAPES:
                spec.tape_mm = st.tape_mm
            elif args.tape and st.tape_mm and st.tape_mm != args.tape:
                print(f"warning: --tape {args.tape}mm but printer has "
                      f"{st.tape} loaded", file=sys.stderr)
        out = design.render(spec)
        if args.preview:
            out.preview.save(args.preview)
            print(f"Preview written to {args.preview}")
        print(f"Label: {out.tape.width_mm}mm tape, {out.length_mm:.1f}mm long, "
              f"{len(out.page.rows)} lines x {out.page.dots} dots, "
              f"{len(out.job)} bytes")
        if args.output:
            with open(args.output, "wb") as fh:
                fh.write(out.job)
            print(f"Job written to {args.output}")
            return 0
        before = printer.send_job(out.job)
        after = printer.wait_idle(before.state)
        print(f"Done: {after.describe()}")
    finally:
        if printer:
            printer.close()
    return 0


def cmd_status(args) -> int:
    printer = _open(args.pid)
    try:
        print(printer.status().describe())
        print(f"port status: 0x{printer.port_status():02x}")
    finally:
        printer.close()
    return 0


def cmd_feed(args) -> int:
    printer = _open(args.pid)
    try:
        printer.soft_reset()
        printer.wait_ready()
        printer.write(protocol.cmd_feed(cut=args.cut))
    finally:
        printer.close()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"print": cmd_print, "status": cmd_status,
                "feed": cmd_feed}[args.command](args)
    except Exception as exc:  # surface a readable message, not a traceback
        name = type(exc).__name__
        print(f"error: {exc}" if name in ("PrinterNotFound", "ValueError",
                                          "NotImplementedError")
              else f"error ({name}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
