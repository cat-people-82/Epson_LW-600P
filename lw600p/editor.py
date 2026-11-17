"""LW-600P Label Editor — a small desktop replacement for Epson Label Editor Lite."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageTk

from . import design, label, protocol

APP_NAME = "LW-600P Label Editor"
SETTINGS = Path.home() / "Library/Application Support/lw600p/settings.json"
SIZES = ["Auto", "6", "8", "10", "12", "14", "18", "24", "36", "48", "72"]
CUT_LABELS = {"each": "Cut each label", "end": "Cut at end of job",
              "none": "Don't cut"}
TAPE_COLOUR = (250, 248, 240)
BAND_COLOUR = (180, 205, 235)
CUT_COLOUR = (220, 60, 60)


class Editor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.spec = self._load_settings()
        self.fonts: dict[str, str] = {}
        self.rendered: Optional[design.Rendered] = None
        self._photo = None
        self._pending = None
        self._busy = False

        root.title(APP_NAME)
        root.minsize(760, 520)
        self._build_ui()
        self._apply_spec_to_widgets()
        self.schedule_preview()

        threading.Thread(target=self._load_fonts, daemon=True).start()
        self.root.after(300, lambda: self.printer_task(
            self._task_status, self._on_status, busy_text=None))
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<Command-p>", lambda e: self.print_label())
        root.bind("<Command-s>", lambda e: self.save_job())

    # ------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 3}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # Preview ----------------------------------------------------------
        prev = ttk.LabelFrame(outer, text="Preview", padding=6)
        prev.pack(fill="x")
        self.canvas = tk.Canvas(prev, height=190, highlightthickness=0,
                                background="#e6e6e6")
        self.canvas.pack(fill="x", expand=True)
        self.hscroll = ttk.Scrollbar(prev, orient="horizontal",
                                     command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hscroll.set)
        self.hscroll.pack(fill="x")
        self.canvas.bind("<Configure>", lambda e: self._draw_preview())
        self.info = ttk.Label(prev, text="", foreground="#555")
        self.info.pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(10, 0))

        # Content ----------------------------------------------------------
        content = ttk.LabelFrame(body, text="Label", padding=8)
        content.pack(side="left", fill="both", expand=True)
        self.text = tk.Text(content, height=5, width=34, wrap="none",
                            font=("Helvetica", 15), undo=True)
        self.text.pack(fill="both", expand=True)
        self.text.bind("<<Modified>>", self._on_text_modified)

        imgrow = ttk.Frame(content)
        imgrow.pack(fill="x", pady=(6, 0))
        ttk.Button(imgrow, text="Use Image…", command=self.choose_image).pack(side="left")
        self.clear_img = ttk.Button(imgrow, text="Back to Text",
                                    command=self.clear_image)
        self.clear_img.pack(side="left", padx=6)
        self.dither = tk.BooleanVar()
        self.dither_box = ttk.Checkbutton(imgrow, text="Dither photo",
                                          variable=self.dither,
                                          command=self.schedule_preview)
        self.dither_box.pack(side="left")
        self.img_label = ttk.Label(content, text="", foreground="#555")
        self.img_label.pack(anchor="w")

        # Settings ---------------------------------------------------------
        opts = ttk.LabelFrame(body, text="Settings", padding=8)
        opts.pack(side="left", fill="y", padx=(10, 0))
        grid = lambda w, r, c, **kw: w.grid(row=r, column=c, sticky="w", **pad, **kw)

        grid(ttk.Label(opts, text="Font"), 0, 0)
        self.font_var = tk.StringVar()
        self.font_box = ttk.Combobox(opts, textvariable=self.font_var, width=26,
                                     state="readonly", values=["Loading fonts…"])
        grid(self.font_box, 0, 1, columnspan=3)
        self.font_box.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview())

        grid(ttk.Label(opts, text="Size (pt)"), 1, 0)
        self.size_var = tk.StringVar()
        size_box = ttk.Combobox(opts, textvariable=self.size_var, width=6,
                                values=SIZES)
        grid(size_box, 1, 1)
        self.bold = tk.BooleanVar()
        grid(ttk.Checkbutton(opts, text="Bold", variable=self.bold,
                             command=self.schedule_preview), 1, 2)

        grid(ttk.Label(opts, text="Align"), 2, 0)
        self.align = tk.StringVar()
        arow = ttk.Frame(opts)
        grid(arow, 2, 1, columnspan=3)
        for value in ("left", "center", "right"):
            ttk.Radiobutton(arow, text=value.title(), value=value,
                            variable=self.align,
                            command=self.schedule_preview).pack(side="left")

        ttk.Separator(opts).grid(row=3, column=0, columnspan=4, sticky="ew", pady=6)

        grid(ttk.Label(opts, text="Tape"), 4, 0)
        self.tape = tk.StringVar()
        grid(ttk.Combobox(opts, textvariable=self.tape, width=6, state="readonly",
                          values=[f"{mm} mm" for mm in label.TAPES]), 4, 1)
        grid(ttk.Button(opts, text="Detect", command=self.detect_tape), 4, 2)

        grid(ttk.Label(opts, text="Length"), 5, 0)
        self.length_mode = tk.StringVar()
        lrow = ttk.Frame(opts)
        grid(lrow, 5, 1, columnspan=3)
        ttk.Radiobutton(lrow, text="Auto", value="auto", variable=self.length_mode,
                        command=self._length_mode_changed).pack(side="left")
        ttk.Radiobutton(lrow, text="Fixed", value="fixed", variable=self.length_mode,
                        command=self._length_mode_changed).pack(side="left")
        self.length = tk.StringVar()
        self.length_box = ttk.Spinbox(lrow, from_=10, to=1000, increment=5,
                                      width=6, textvariable=self.length)
        self.length_box.pack(side="left", padx=(4, 2))
        ttk.Label(lrow, text="mm").pack(side="left")

        grid(ttk.Label(opts, text="Margins"), 6, 0)
        mrow = ttk.Frame(opts)
        grid(mrow, 6, 1, columnspan=3)
        self.margin = tk.StringVar()
        ttk.Spinbox(mrow, from_=0, to=50, increment=1, width=6,
                    textvariable=self.margin).pack(side="left")
        ttk.Label(mrow, text="mm each end").pack(side="left", padx=4)

        ttk.Separator(opts).grid(row=7, column=0, columnspan=4, sticky="ew", pady=6)

        grid(ttk.Label(opts, text="Copies"), 8, 0)
        self.copies = tk.StringVar()
        grid(ttk.Spinbox(opts, from_=1, to=99, width=6, textvariable=self.copies), 8, 1)

        grid(ttk.Label(opts, text="Cut"), 9, 0)
        self.cut = tk.StringVar()
        grid(ttk.Combobox(opts, textvariable=self.cut, width=18, state="readonly",
                          values=list(CUT_LABELS.values())), 9, 1, columnspan=3)

        grid(ttk.Label(opts, text="Density"), 10, 0)
        self.density = tk.StringVar()
        grid(ttk.Spinbox(opts, from_=-3, to=3, width=6,
                         textvariable=self.density), 10, 1)

        self.mirror = tk.BooleanVar()
        self.flip = tk.BooleanVar()
        grid(ttk.Checkbutton(opts, text="Mirror", variable=self.mirror,
                             command=self.schedule_preview), 11, 1)
        grid(ttk.Checkbutton(opts, text="Rotate 180°", variable=self.flip,
                             command=self.schedule_preview), 11, 2, columnspan=2)

        for var in (self.size_var, self.tape, self.length, self.margin,
                    self.copies, self.cut, self.density):
            var.trace_add("write", lambda *_: self.schedule_preview())

        # Action bar -------------------------------------------------------
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 0))
        self.action_buttons = [
            ttk.Button(bar, text="Feed", command=lambda: self.feed(False)),
            ttk.Button(bar, text="Feed && Cut", command=lambda: self.feed(True)),
            ttk.Button(bar, text="Save Job…", command=self.save_job),
            ttk.Button(bar, text="Export PNG…", command=self.export_png),
        ]
        for b in self.action_buttons:
            b.pack(side="left", padx=(0, 6))
        self.print_btn = ttk.Button(bar, text="Print", command=self.print_label,
                                    default="active")
        self.print_btn.pack(side="right")
        self.action_buttons.append(self.print_btn)
        self.status = ttk.Label(bar, text="Looking for printer…")
        self.status.pack(side="right", padx=10)

    # ------------------------------------------------------ spec <-> widgets
    def _apply_spec_to_widgets(self) -> None:
        s = self.spec
        self.text.delete("1.0", "end")
        self.text.insert("1.0", s.text)
        self.text.edit_modified(False)
        self.size_var.set("Auto" if s.size_pt is None else f"{s.size_pt:g}")
        self.bold.set(s.bold)
        self.align.set(s.align)
        self.tape.set(f"{s.tape_mm} mm")
        self.length_mode.set("auto" if s.length_mm is None else "fixed")
        self.length.set(f"{s.length_mm or 50:g}")
        self.margin.set(f"{s.margin_mm:g}")
        self.copies.set(str(s.copies))
        self.cut.set(CUT_LABELS[s.cut])
        self.density.set(str(s.density))
        self.mirror.set(s.mirror)
        self.flip.set(s.flip)
        self.dither.set(s.dither)
        self.font_var.set(Path(s.font_path).stem if s.font_path else "Helvetica")
        self._length_mode_changed(preview=False)
        self._image_mode_changed()

    def _read_spec(self) -> design.LabelSpec:
        def num(var, kind, default):
            try:
                return kind(var.get())
            except ValueError:
                return default

        size = self.size_var.get().strip()
        cut = next(k for k, v in CUT_LABELS.items() if v == self.cut.get())
        return design.LabelSpec(
            text=self.text.get("1.0", "end-1c"),
            image_path=self.spec.image_path,
            tape_mm=int(self.tape.get().split()[0]),
            font_path=self.fonts.get(self.font_var.get(), self.spec.font_path),
            size_pt=None if size.lower() in ("", "auto") else num(self.size_var, float, None),
            bold=self.bold.get(),
            align=self.align.get(),
            margin_mm=max(0.0, num(self.margin, float, 3.0)),
            length_mm=(num(self.length, float, None)
                       if self.length_mode.get() == "fixed" else None),
            copies=min(99, max(1, num(self.copies, int, 1))),
            density=min(3, max(-3, num(self.density, int, 0))),
            cut=cut,
            dither=self.dither.get(),
            mirror=self.mirror.get(),
            flip=self.flip.get(),
        )

    # -------------------------------------------------------------- preview
    def schedule_preview(self) -> None:
        if self._pending:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(120, self._update_preview)

    def _update_preview(self) -> None:
        self._pending = None
        self.spec = self._read_spec()
        try:
            self.rendered = design.render(self.spec)
            r = self.rendered
            self.info.configure(foreground="#555", text=(
                f"{r.tape.width_mm} mm tape  ·  {r.length_mm:.1f} mm long  ·  "
                f"{self.spec.copies} cop{'y' if self.spec.copies == 1 else 'ies'}"))
        except NotImplementedError:
            self.rendered = None
            self.info.configure(foreground="#b03030", text=(
                "Fixed length isn't implemented yet — fill in choose_length() "
                "in lw600p/label.py"))
        except (ValueError, OSError) as exc:
            self.rendered = None
            self.info.configure(foreground="#b03030", text=str(exc))
        self._draw_preview()

    def _draw_preview(self) -> None:
        c = self.canvas
        c.delete("all")
        width, height = max(c.winfo_width(), 100), int(c["height"])
        if not self.rendered:
            c.create_text(width // 2, height // 2, text="No preview",
                          fill="#888", font=("Helvetica", 14))
            return
        img = self._tape_picture(self.rendered)
        zoom = min(3.0, (height - 30) / img.height)
        zoom = max(0.2, min(zoom, (width - 40) / img.width)
                   if img.width * zoom > width - 40 else zoom)
        size = (max(1, int(img.width * zoom)), max(1, int(img.height * zoom)))
        resample = Image.Resampling.NEAREST if zoom >= 1 else Image.Resampling.BOX
        self._photo = ImageTk.PhotoImage(img.resize(size, resample))
        x = max(20, (width - size[0]) // 2)
        c.create_image(x, (height - size[1]) // 2, anchor="nw", image=self._photo)
        c.configure(scrollregion=(0, 0, max(width, size[0] + 40), height))

    @staticmethod
    def _tape_picture(r: design.Rendered) -> Image.Image:
        """Landscape preview on a tape-coloured strip with band and cut marks."""
        art = r.preview.convert("L")
        pic = Image.new("RGB", art.size, TAPE_COLOUR)
        pic.paste((0, 0, 0), mask=art.point(lambda v: 255 - v))
        draw = ImageDraw.Draw(pic)
        first, last = r.tape.printable
        for y in (first - 1, last):
            for x in range(0, pic.width, 6):
                draw.line([(x, y), (x + 2, y)], fill=BAND_COLOUR)
        for x in (0, pic.width - 1):
            draw.line([(x, 0), (x, pic.height)], fill=CUT_COLOUR)
        return pic

    # --------------------------------------------------------------- events
    def _on_text_modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.schedule_preview()

    def _length_mode_changed(self, preview: bool = True) -> None:
        fixed = self.length_mode.get() == "fixed"
        self.length_box.configure(state="normal" if fixed else "disabled")
        if preview:
            self.schedule_preview()

    def _image_mode_changed(self) -> None:
        has_img = bool(self.spec.image_path)
        self.text.configure(state="disabled" if has_img else "normal",
                            foreground="#999" if has_img else "black")
        self.clear_img.configure(state="normal" if has_img else "disabled")
        self.dither_box.configure(state="normal" if has_img else "disabled")
        self.img_label.configure(
            text=f"Image: {Path(self.spec.image_path).name}" if has_img else "")

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff"),
                       ("All files", "*")])
        if path:
            self.spec.image_path = path
            self._image_mode_changed()
            self.schedule_preview()

    def clear_image(self) -> None:
        self.spec.image_path = None
        self._image_mode_changed()
        self.schedule_preview()

    def _load_fonts(self) -> None:
        fonts = label.list_fonts()
        self.root.after(0, self._fonts_loaded, fonts)

    def _fonts_loaded(self, fonts: dict[str, str]) -> None:
        self.fonts = fonts
        self.font_box.configure(values=list(fonts))
        by_path = {v: k for k, v in fonts.items()}
        current = by_path.get(self.spec.font_path or "")
        if not current:
            current = "Helvetica" if "Helvetica" in fonts else next(iter(fonts), "")
        self.font_var.set(current)
        self.schedule_preview()

    # ------------------------------------------------------- printer access
    def printer_task(self, work: Callable, done: Callable,
                     busy_text: Optional[str] = "Working…") -> None:
        """Run ``work(printer)`` on a thread; call ``done(result, error)``."""
        if self._busy:
            return
        self._busy = True
        for b in self.action_buttons:
            b.state(["disabled"])
        if busy_text:
            self.status.configure(text=busy_text, foreground="black")

        def runner():
            from .transport import LabelPrinter
            printer = None
            try:
                printer = LabelPrinter()
                result, error = work(printer), None
            except Exception as exc:  # reported in the status bar
                result, error = None, exc
            finally:
                if printer:
                    try:
                        printer.close()
                    except Exception:
                        pass
            self.root.after(0, finish, result, error)

        def finish(result, error):
            self._busy = False
            for b in self.action_buttons:
                b.state(["!disabled"])
            if error:
                self.status.configure(text=self._error_text(error),
                                      foreground="#b03030")
            done(result, error)

        threading.Thread(target=runner, daemon=True).start()

    @staticmethod
    def _error_text(exc: Exception) -> str:
        if type(exc).__name__ == "PrinterNotFound":
            return "Printer not found — connect it by USB and switch it on"
        if type(exc).__name__ == "NoBackendError":
            return "libusb missing — run: brew install libusb"
        return f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _task_status(printer):
        return printer.status()

    def _on_status(self, st, error) -> None:
        if error:
            return
        self.status.configure(text=f"Printer ready · {st.tape} tape",
                              foreground="#2a7a2a")
        if st.error:
            self.status.configure(text=f"Printer error {st.error}",
                                  foreground="#b03030")

    def detect_tape(self) -> None:
        def done(st, error):
            if error:
                return
            self._on_status(st, None)
            if st.tape_mm in label.TAPES:
                self.tape.set(f"{st.tape_mm} mm")
        self.printer_task(self._task_status, done, "Checking tape…")

    def feed(self, cut: bool) -> None:
        def work(printer):
            printer.soft_reset()
            printer.wait_ready()
            printer.write(protocol.cmd_feed(cut=cut))
        self.printer_task(work, lambda r, e: e or self.status.configure(
            text="Fed and cut" if cut else "Fed", foreground="#2a7a2a"),
            "Feeding…")

    def print_label(self) -> None:
        self._update_preview()
        if not self.rendered:
            messagebox.showwarning(APP_NAME, self.info.cget("text"))
            return
        rendered = self.rendered

        def checked(st, error):
            if error:
                return
            if st.tape_mm and st.tape_mm != rendered.tape.width_mm:
                if not messagebox.askyesno(APP_NAME, (
                        f"The printer has {st.tape} tape loaded, but this label "
                        f"is set up for {rendered.tape.width_mm} mm.\n\nPrint anyway?")):
                    self.status.configure(text="Print cancelled", foreground="black")
                    return
            self.printer_task(send, printed, "Printing…")

        def send(printer):
            before = printer.send_job(rendered.job)
            return printer.wait_idle(before.state)

        def printed(st, error):
            if not error:
                self.status.configure(text="Printed", foreground="#2a7a2a")
                self._save_settings()

        self.printer_task(self._task_status, checked, "Checking printer…")

    def save_job(self) -> None:
        self._update_preview()
        if not self.rendered:
            return
        path = filedialog.asksaveasfilename(
            title="Save printer job", defaultextension=".bin",
            initialfile="label.bin", filetypes=[("Printer job", "*.bin")])
        if path:
            Path(path).write_bytes(self.rendered.job)
            self.status.configure(text=f"Saved {Path(path).name}", foreground="black")

    def export_png(self) -> None:
        self._update_preview()
        if not self.rendered:
            return
        path = filedialog.asksaveasfilename(
            title="Export preview", defaultextension=".png",
            initialfile="label.png", filetypes=[("PNG image", "*.png")])
        if path:
            self.rendered.preview.save(path)
            self.status.configure(text=f"Exported {Path(path).name}", foreground="black")

    # ------------------------------------------------------------- settings
    @staticmethod
    def _load_settings() -> design.LabelSpec:
        try:
            return design.LabelSpec.from_dict(json.loads(SETTINGS.read_text()))
        except (OSError, ValueError, TypeError):
            return design.LabelSpec(text="Hello")

    def _save_settings(self) -> None:
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(self._read_spec().to_dict(), indent=2))
        except OSError:
            pass

    def _on_close(self) -> None:
        self._save_settings()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Editor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
