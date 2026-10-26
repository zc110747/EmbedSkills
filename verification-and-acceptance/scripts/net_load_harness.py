#!/usr/bin/env python3
"""net_load_harness.py -- stdlib-only skeleton for driving a TCP service at scale.

Why a shared skeleton: every acceptance script (e2e / launcher / load) must agree on
"what a client is" and "how a pass is counted". If each script rolls its own, one of
them will eventually call a behaviour PASS while another calls it FAIL -- and then
nobody trusts either.

Copy this file next to your verify_*.py scripts (or paste the parts you need) and
extend it. It intentionally contains no service-specific logic.

Design rules baked in (see the accompanying SKILL.md):
  * stdlib only                     -- an acceptance script must not need an install step
  * read raw bytes over real sockets -- never infer behaviour from a log line
  * subprocess stdout uses errors="replace" -- a non-UTF-8 byte must not kill the reader
  * every assertion is preceded by "wait until it should hold"  (never sleep-and-hope)
  * counters are read from a NEW line, tracked against a recorded baseline
  * failures are recorded and the run continues -- one run yields the whole picture
  * process exit is asserted WITH A TIMEOUT (it catches "shutdown hangs")

Typical use:

    server = ServerProcess([argv0, "--port", "0", "--console", "--stats", "0"])
    server.start()
    host, port = server.wait_endpoint()          # parsed from the startup banner

    clients, errors, seconds = connect_many(host, port, 1000, simultaneous=True)
    wait_for_member_count(server, 1000)          # DISCIPLINE A: wait before asserting

    clients[999].send(b"probe")                  # the LAST accepted client: the one
                                                 # that used to be silently ignored
    for c in clients[1:]:
        wait_until(lambda c=c: c.received() == b"probe", 5.0)

    mine = server.stats()                        # DISCIPLINE B: parse the NEW stats line
    checks.eq(int(mine["packets_out"]), 1 * (1000 - 1), "packets_out == senders*(N-1)")

    for c in clients:
        c.close()
    checks.eq(server.stop(timeout=20.0), 0, "graceful shutdown exits 0")
    raise SystemExit(checks.report())
"""

from __future__ import annotations

import re
import socket
import subprocess
import threading
import time

# --------------------------------------------------------------------------------------
# tiny check harness
# --------------------------------------------------------------------------------------


class Checks:
    """Records PASS/FAIL; never aborts early, so one run reports everything."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.passed = 0
        self.failures: list[str] = []

    def check(self, ok: bool, what: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  PASS  {what}")
        else:
            msg = f"{what}" + (f"   ({detail})" if detail else "")
            self.failures.append(msg)
            print(f"  FAIL  {msg}")
        return bool(ok)

    def eq(self, actual, expected, what: str) -> bool:
        if actual == expected:
            return self.check(True, what)
        return self.check(False, what, f"got {actual!r}, expected {expected!r}")

    def report(self) -> int:
        total = self.passed + len(self.failures)
        if self.failures:
            print(f"\n{self.title}: FAIL ({len(self.failures)}/{total} failed)")
            for f in self.failures:
                print(f"  - {f}")
            return 1
        print(f"\n{self.title}: PASS ({total} checks)")
        return 0


def first_difference(a: bytes, b: bytes) -> str:
    """Compact mismatch hint -- NEVER dump a 32 kB payload into the failure message,
    or the one FAIL that matters gets buried in scrollback."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return f"differ at offset {i}: 0x{a[i]:02x} != 0x{b[i]:02x}; {len(a)} vs {len(b)} bytes"
    if len(a) != len(b):
        return f"prefix identical, lengths differ: {len(a)} vs {len(b)} bytes"
    return "identical"


# --------------------------------------------------------------------------------------
# waiting
# --------------------------------------------------------------------------------------


def wait_until(pred, timeout: float = 10.0, interval: float = 0.02) -> bool:
    """Poll `pred` until true or timeout. Returns the final truth value."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if pred():
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


# --------------------------------------------------------------------------------------
# server under test
# --------------------------------------------------------------------------------------

_ENDPOINT_RE = re.compile(r"([0-9]{1,3}(?:\.[0-9]{1,3}){3}):(\d+)\s*$")
_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\S+)")


class ServerProcess:
    """Runs the real service and gives the test a snapshot of its console output.

    The reader runs on its own thread so assertion code never blocks on readline(),
    and it decodes with errors="replace": a single non-UTF-8 byte on the service's
    error path would otherwise kill the reader thread silently (symptom: "the log
    stops at line N and the exit code is never observable").
    """

    def __init__(self, argv: list[str], cwd: str | None = None,
                 env: dict | None = None, decode_errors: str = "replace") -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.decode_errors = decode_errors
        self.proc: subprocess.Popen | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------------
    def start(self) -> "ServerProcess":
        self.proc = subprocess.Popen(
            self.argv, cwd=self.cwd, env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors=self.decode_errors, bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        return self

    def _pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:               # blocks only on this thread
            with self._lock:
                self._lines.append(line.rstrip("\n"))

    # -- output ------------------------------------------------------------------
    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def lines_since(self, baseline: int) -> list[str]:
        return self.snapshot()[baseline:]

    def console(self, cmd: str) -> None:
        """Send one console command (needs the service's --console for a piped stdin)."""
        if self.proc is not None and self.proc.stdin is not None:
            self.proc.stdin.write(cmd.rstrip("\n") + "\n")
            self.proc.stdin.flush()

    def wait_line(self, pred, timeout: float = 10.0) -> str | None:
        found: list[str] = []

        def probe() -> bool:
            for line in self.snapshot():
                if pred(line):
                    found.append(line)
                    return True
            return False

        return found[0] if wait_until(probe, timeout) else None

    def wait_new_line(self, baseline: int, pred, timeout: float = 10.0) -> str | None:
        """Wait for a line arriving AFTER `baseline` line count.

        DISCIPLINE B: "a line exists" is satisfied instantly by the PREVIOUS round's
        output sitting in the buffer -- you then read stale counters and conclude the
        service did nothing.
        """
        found: list[str] = []

        def probe() -> bool:
            for line in self.lines_since(baseline):
                if pred(line):
                    found.append(line)
                    return True
            return False

        return found[0] if wait_until(probe, timeout) else None

    def wait_endpoint(self, timeout: float = 15.0) -> tuple[str, int]:
        """Parse host:port from the startup banner (requires the service to print the
        REAL bound port -- essential when it was started with --port 0)."""
        hit: list[tuple[str, int]] = []

        def probe() -> bool:
            for line in self.snapshot():
                m = _ENDPOINT_RE.search(line)
                if m:
                    hit.append((m.group(1), int(m.group(2))))
                    return True
            return False

        if not wait_until(probe, timeout):
            raise TimeoutError(f"no endpoint in banner; output so far:\n" +
                               "\n".join(self.snapshot()[-20:]))
        return hit[0]

    # -- counters ----------------------------------------------------------------
    def stats(self, cmd: str = "stats", prefix: str = "[stats]",
              timeout: float = 15.0) -> dict:
        """Ask for a stats line and parse the NEW one into {key: value}.

        Records the baseline BEFORE sending the command, so the answer can never be
        a stale line already in the buffer.
        """
        baseline = len(self.snapshot())
        self.console(cmd)
        line = self.wait_new_line(baseline, lambda l: l.startswith(prefix), timeout)
        if line is None:
            raise TimeoutError(f"no '{prefix}' line within {timeout}s")
        return {k: v for k, v in _KV_RE.findall(line)}

    def wait_for_counter(self, key: str, value, timeout: float = 20.0) -> bool:
        """DISCIPLINE A: wait until a counter reaches the value you are about to assert.

        A burst of N connects finishing at the kernel does NOT mean the service has
        accept()ed them; sampling now reads an intermediate value (e.g. online=973/1000)
        that looks exactly like data loss.
        """
        def probe() -> bool:
            try:
                return str(self.stats().get(key)) == str(value)
            except TimeoutError:
                return False

        return wait_until(probe, timeout)

    # -- shutdown ----------------------------------------------------------------
    def stop(self, quit_cmd: str = "quit", timeout: float = 20.0) -> int | None:
        """Graceful shutdown, asserted WITH A TIMEOUT. Returns the exit code or None."""
        try:
            self.console(quit_cmd)
        except Exception:
            pass
        assert self.proc is not None
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
            return None

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)


# --------------------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------------------


class Client:
    """One real TCP client that RECORDS PACKET BOUNDARIES.

    `packets()` gives what actually came out of each recv() -- keep them separate from
    `received()`, because "two packets were coalesced" is a kernel fact while "the bytes
    are right" is a service fact. Mixing the two assertions yields a conclusion about
    the kernel, not about the service.
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0,
                 recv_size: int = 65536) -> None:
        self.host, self.port = host, port
        self.recv_size = recv_size
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.2)
        self._packets: list[bytes] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self.sock.recv(self.recv_size)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                self._packets.append(chunk)

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def packets(self) -> list[bytes]:
        with self._lock:
            return list(self._packets)

    def received(self) -> bytes:
        return b"".join(self.packets())

    def hit_once(self, tag: bytes) -> int:
        """How many packets EQUAL `tag` exactly.

        DISCIPLINE C: do NOT test `tag in received()`. TCP may coalesce two sends, and
        the tag then still appears as a substring without ever being a standalone packet.
        Counting exact packet hits distinguishes "arrived as one whole packet" from
        "spilled into a merged one".
        """
        return sum(1 for p in self.packets() if p == tag)

    def was_split(self, tag: bytes) -> bool:
        """True if the tag appears but never as a whole packet (i.e. it was fragmented
        or merged with a neighbour)."""
        if tag not in self.received():
            return False
        if self.hit_once(tag):
            return False
        return any(tag in p for p in self.packets() if tag != p)

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def connect_many(host: str, port: int, count: int, simultaneous: bool = True,
                 timeout: float = 60.0) -> tuple[list[Client], list[str], float]:
    """Connect `count` clients. simultaneous=True uses one thread per client, which is
    what actually exercises the kernel's pending-accept queue (a serial connect loop
    drains the queue as it goes and hides a too-small backlog).

    Returns (clients, errors, elapsed_seconds).
    """
    clients: list[Client] = []
    errors: list[str] = []
    lock = threading.Lock()
    started = time.monotonic()

    if not simultaneous:
        for _ in range(count):
            try:
                clients.append(Client(host, port, timeout=timeout))
            except OSError as e:
                errors.append(str(e))
        return clients, errors, time.monotonic() - started

    threads: list[threading.Thread] = []

    def one() -> None:
        try:
            c = Client(host, port, timeout=timeout)
        except OSError as e:
            with lock:
                errors.append(str(e))
            return
        with lock:
            clients.append(c)

    for _ in range(count):
        t = threading.Thread(target=one)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=timeout)
    return clients, errors, time.monotonic() - started


def close_all(clients: list[Client]) -> None:
    for c in clients:
        c.close()


# --------------------------------------------------------------------------------------
# optional self-check so the skeleton itself can be smoke-tested
# --------------------------------------------------------------------------------------


def _selftest() -> int:
    checks = Checks("net_load_harness selftest")
    checks.eq(first_difference(b"abc", b"axc"), "differ at offset 1: 0x62 != 0x78; 3 vs 3 bytes",
              "first_difference reports offset and bytes")
    checks.check(wait_until(lambda: True, 0.1), "wait_until returns immediately on true")
    checks.check(not wait_until(lambda: False, 0.05), "wait_until times out on false")

    # one real loopback socket pair to prove Client records packet boundaries
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()

    def serve() -> None:
        conn, _ = srv.accept()
        conn.sendall(b"one")
        conn.sendall(b"two")
        time.sleep(0.2)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    with Client(host, port) as c:
        ok = wait_until(lambda: c.received() == b"onetwo", 3.0)
        checks.check(ok, "Client receives both payloads")
        # Two back-to-back sendall() calls on loopback FREQUENTLY arrive coalesced in a
        # single recv(). That is exactly why "arrived as one whole packet" must be a
        # counting test (hit_once) and NOT a substring test (tag in received()).
        packets = c.packets()
        checks.check(len(packets) == 2 or packets == [b"onetwo"],
                     "either two separate packets or one coalesced packet",
                     f"packets={packets!r}")
        if c.hit_once(b"one") == 0:
            checks.check(c.was_split(b"one"),
                         "a coalesced tag is detected as NOT a whole packet")
            checks.check(b"one" in c.received(),
                         "yet a substring test would have wrongly said it arrived")
        else:
            checks.eq(c.hit_once(b"one"), 1,
                      "hit_once counts a whole packet exactly once")
    srv.close()
    return checks.report()


if __name__ == "__main__":
    raise SystemExit(_selftest())
