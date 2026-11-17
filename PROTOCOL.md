# Epson LabelWorks LW-600P — recovered protocol

Source: Epson's macOS driver 1.37 (`LabelWorksDriver_1.37.dmg` → `Driver.pkg`),
x86_64 slices of `rastertolw`, `LWUSBPrintClass.plugin` and `LWLib.framework`
(2017 build, symbols intact). The protocol was recovered by static disassembly for
interoperability. Nothing was executed and no printer was attached, so everything
below comes from static analysis. No Epson code or binaries are included in this
repository.

## Why the old driver no longer works

All binaries are Intel-only (x86_64/i386). The kext `LWUSBPrintClass.kext` has
no code: it is an `AppleUSBMergeNub` personality that attaches Epson's
`USB Printing Class` plugin to the printer's interface (VID `0x04B8`,
PID `0x0704` / `0x0705`). The interface itself is a normal USB printer-class
interface, so libusb can drive it directly.

## Command framing (`ESCPCommand::makeCommand`)

```
1B 7B <len> <cmd> <params…> <sum> 7D       len = bytes from cmd to 7D
                                            sum = (cmd + Σparams) & 0xFF
```

| cmd | params | meaning (source) |
|-----|--------|------------------|
| `{` | `00 00 53 54` | start job (`doStartDoc`) |
| `C` | 4 bytes | cut mode: each label `03 01 01 01`, end of job `03 00 01 01`, none `00 00 00 00` (half-cut models use `02 …`) |
| `D` | density+5 | density −3…+3 → 2…8 |
| `G` | — | sent at job start |
| `s` | speed | 0 on LW-600P (no `EPLWPrintSpeed` in PPD) |
| `L` | u32 LE | label length in raster lines (`doStartPage`) |
| `T` | u16 LE | leading blank lines, clamped 10…5300 |
| `@` | — | end job (`doEndDoc`) |
| `+` | 0 / 1 | feed / feed + cut (LWLib `sendTapeFeed*`) |
| `O` `W` `t` | — | only for wide-tape models (flag never set for LW-600P) |

Raster line (`doSendRasterData`): `1B 2E 00 00 00 01 nL nH` + ⌈n/8⌉ bytes,
MSB = first dot, n = tape width in dots (`cupsWidth`). Each page ends with `0C`.

Job order: `{` `C` `D` `G` `s`, then per label/copy `L` `T` rows… `0C`, then `@`.

Driver margin rule (`setRasterInfo`, default path): with P = leading blank rows
and E = last content row, `T = clamp(P, 10, 5300)` and `L = E + min(T, 70)`,
which mirrors the lead margin at the tail, capped at 10 mm.

## Geometry (PPD, 180 dpi)

| tape | page pt | dots | imageable pt |
|------|---------|------|--------------|
| 6 mm | 17 | 43 | 1–15 |
| 9 mm | 25 | 63 | 2–22 |
| 12 mm | 34 | 85 | 3–31 |
| 18 mm | 51 | 128 | 4–46 |
| 24 mm | 68 | 170 | 8–58 |

## USB requests (`USBClassPluginSub`)

| request | bmRequestType / bRequest | notes |
|---------|-------------------------|-------|
| GetPortStatus | `A1 01`, wIndex=iface, len 1 | relay waits for bit `0x10` |
| SoftReset | `21 02`, wIndex=iface | before every job |
| GetLWStatus | `C1 01`, len 8 | byte1 state, byte2 error, byte3 tape code |
| ResetDevice | `41 00`, len 3 | not used here |
| Engage connect/disconnect/status | `C1 02/03/04` | not needed on USB |

Tape codes (status byte 3): 1=6, 2=9, 3=12, 4=18, 5=24, 6=36, 0x0B=4,
0x11/0x12=24/36 cable, 0x21=50, 0x23=100 mm.

## Unverified (needs the real printer)

- Which way a label comes out: the app copies macOS's landscape→portrait
  rotation (90° counter-clockwise). Use `--flip` if text prints upside down.
- `cupsWidth` rounding (18 mm → 128 vs 127 dots).
- Exact meaning of status bytes 1 and 2 beyond "state" and "error".
- Which of PID 0x0704 / 0x0705 is the LW-600P (both are accepted).
