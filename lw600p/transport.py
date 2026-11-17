"""USB transport for the LW-600P, replacing LWUSBPrintClass.plugin + kext.

Control requests are those issued by USBClassPluginSub in the original
plugin; bulk OUT carries the print job.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

EPSON_VID = 0x04B8
# PIDs bound by LWUSBPrintClass.kext (personalities PID704 / PID705).
KNOWN_PIDS = (0x0704, 0x0705)

TAPE_CODES = {
    0x01: "6mm", 0x02: "9mm", 0x03: "12mm", 0x04: "18mm", 0x05: "24mm",
    0x06: "36mm", 0x0B: "4mm", 0x11: "24mm cable", 0x12: "36mm cable",
    0x21: "50mm", 0x23: "100mm",
}


@dataclass(frozen=True)
class Status:
    raw: bytes

    @property
    def state(self) -> int:
        """Byte 1: the relay loop waits on this while a job runs."""
        return self.raw[1]

    @property
    def error(self) -> int:
        """Byte 2: error code (driver strings are named ERROR_%05d)."""
        return self.raw[2]

    @property
    def tape_code(self) -> int:
        return self.raw[3]

    @property
    def tape(self) -> str:
        return TAPE_CODES.get(self.tape_code, f"unknown (0x{self.tape_code:02x})")

    @property
    def tape_mm(self) -> Optional[int]:
        name = TAPE_CODES.get(self.tape_code, "")
        return int(name[:-2]) if name.endswith("mm") else None

    def describe(self) -> str:
        err = "none" if self.error == 0 else f"ERROR_{self.error:05d}"
        return (f"tape={self.tape} state=0x{self.state:02x} error={err} "
                f"raw={self.raw.hex(' ')}")


class PrinterNotFound(RuntimeError):
    pass


class LabelPrinter:
    STATUS_LEN = 8  # RasterPrint::getStatusLength default (no EPLWStatusLength)

    def __init__(self, pid: Optional[int] = None, timeout_ms: int = 5000):
        import usb.core
        import usb.util

        self._usb = usb
        matcher = (lambda d: d.idProduct == pid) if pid else (
            lambda d: d.idProduct in KNOWN_PIDS)
        dev = usb.core.find(idVendor=EPSON_VID, custom_match=matcher)
        if dev is None:
            raise PrinterNotFound(
                "No Epson LabelWorks printer found on USB "
                f"(vendor 0x{EPSON_VID:04x}, products "
                f"{', '.join(hex(p) for p in KNOWN_PIDS)}). Is it switched on "
                "and connected by cable?")
        self.dev = dev
        self.timeout = timeout_ms
        try:
            dev.set_configuration()
        except usb.core.USBError:
            pass  # already configured
        cfg = dev.get_active_configuration()
        self.intf = cfg[(0, 0)]
        self.iface = self.intf.bInterfaceNumber
        try:
            if dev.is_kernel_driver_active(self.iface):
                dev.detach_kernel_driver(self.iface)
        except (NotImplementedError, usb.core.USBError):
            pass
        usb.util.claim_interface(dev, self.iface)
        out = usb.util.ENDPOINT_OUT
        self.ep_out = usb.util.find_descriptor(
            self.intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == out)
        if self.ep_out is None:
            raise RuntimeError("printer interface has no bulk OUT endpoint")

    # --- printer-class requests (USB Printer Class 1.1) ---------------
    def port_status(self) -> int:
        """GET_PORT_STATUS (A1 01); bit 0x10 = selected / online."""
        return self.dev.ctrl_transfer(0xA1, 0x01, 0, self.iface, 1,
                                      self.timeout)[0]

    def soft_reset(self) -> None:
        """SOFT_RESET (21 02), sent before every job by the original relay."""
        self.dev.ctrl_transfer(0x21, 0x02, 0, self.iface, None, self.timeout)

    # --- Epson vendor request -----------------------------------------
    def status(self) -> Status:
        """Vendor request C1 01 (GetLWStatusSub), 8 bytes on the LW-600P."""
        data = self.dev.ctrl_transfer(0xC1, 0x01, 0, 0, self.STATUS_LEN,
                                      self.timeout)
        return Status(bytes(data))

    # --- job flow -------------------------------------------------------
    def wait_ready(self, timeout_s: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not self.port_status() & 0x10:
            if time.monotonic() > deadline:
                raise TimeoutError("printer did not report ready (select)")
            time.sleep(0.05)

    def write(self, data: bytes, chunk: int = 4096) -> None:
        for i in range(0, len(data), chunk):
            self.ep_out.write(data[i:i + chunk], self.timeout)

    def send_job(self, job: bytes) -> Status:
        """Mirror KJRelay: reset, wait for select, check status, send."""
        self.soft_reset()
        self.wait_ready()
        before = self.status()
        if before.error:
            raise RuntimeError(f"printer reports an error: {before.describe()}")
        self.write(job)
        return before

    def wait_idle(self, idle_state: int, timeout_s: float = 60.0) -> Status:
        """Poll status until byte 1 returns to its pre-job value."""
        deadline = time.monotonic() + timeout_s
        time.sleep(0.5)
        while True:
            st = self.status()
            if st.error:
                raise RuntimeError(f"printer error: {st.describe()}")
            if st.state == idle_state or time.monotonic() > deadline:
                return st
            time.sleep(0.5)

    def close(self) -> None:
        self._usb.util.release_interface(self.dev, self.iface)
        self._usb.util.dispose_resources(self.dev)
