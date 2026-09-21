#!/usr/bin/env python3
"""Reset the ESP32-S3 over the USB Serial/JTAG port and capture its console.

Why not `idf.py monitor`: this needs to be non-interactive and byte-exact.
Resetting through esptool keeps the gap between "chip boots" and "host starts
listening" down to ~1 s, so the 3 s after-boot telemetry cannot be missed.

  python serial_capture.py COM14 out.log 25
"""
import argparse
import subprocess
import sys
import time

import serial


def hard_reset(port: str) -> int:
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32s3", "-p", port,
           "--before", "default_reset", "--after", "hard_reset", "read_mac"]
    print("reset: " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout[-1500:])
    if r.returncode != 0:
        sys.stdout.write(r.stderr[-1500:])
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("out")
    ap.add_argument("seconds", type=float)
    ap.add_argument("--no-reset", action="store_true")
    ap.add_argument("--until", default=None,
                    help="stop as soon as this literal appears in the stream "
                         "(the seconds value then only acts as a safety net)")
    a = ap.parse_args()

    if not a.no_reset:
        hard_reset(a.port)
        time.sleep(1.0)

    ser = None
    last = None
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            ser = serial.Serial(a.port, 115200, timeout=0.2)
            break
        except Exception as exc:                      # port still re-enumerating
            last = exc
            time.sleep(0.5)
    if ser is None:
        print(f"cannot open {a.port}: {last}")
        return 1

    # never leave the modem lines in a pattern that could reset the chip again
    ser.dtr = False
    ser.rts = False

    print(f"capturing up to {a.seconds}s -> {a.out}"
          + (f" (until {a.until!r})" if a.until else ""), flush=True)
    end = time.time() + a.seconds
    total = 0
    seen = b""
    marker = a.until.encode() if a.until else None

    with open(a.out, "wb") as f:
        while time.time() < end:
            data = ser.read(8192)
            if data:
                f.write(data)
                f.flush()
                total += len(data)
                if marker is not None:
                    # keep a short tail so the marker cannot be split across
                    # two reads and missed
                    seen = (seen + data)[-len(marker) - 64:]
                    if marker in seen:
                        print("end marker seen", flush=True)
                        break
    ser.close()
    print(f"captured {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
