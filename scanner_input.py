"""Read PROPixx DIN edges directly; the device buffers pulses between polls."""
import struct
import sys
from importlib.metadata import PackageNotFoundError, version
from time import perf_counter, sleep


# Classic DIN records contain four timestamp words and one input word.
BASE = 12_000_000
FRAME_BYTES = 10
FRAMES = 10_000
BUFFER_BYTES = FRAME_BYTES * FRAMES


class ScannerInput:
    def __init__(self, trigger_bit=4, trigger_level=0, button_level=0):
        try:
            from pypixxlib import _libdpx as dpx
        except (ImportError, OSError) as exc:
            raise RuntimeError(f"Cannot load pypixxlib in {sys.executable}: {exc}") from exc

        self.dpx = dpx
        try:
            self.package_version = version("pypixxlib")
        except PackageNotFoundError:
            self.package_version = "unknown"
        self.log_backend = "PROPixxCtrl classic DIN buffer"
        self.trigger_bit = trigger_bit
        self.trigger_level = trigger_level
        self.button_level = button_level
        self.log_configured = False
        self.sync = None
        self.max_pending = 0
        dpx.DPxOpen()
        try:
            if not dpx.DPxSelectDevice("PROPixxCtrl"):
                raise RuntimeError("PROPixx controller not found. Check its connection.")
            self.update()
        except Exception:
            dpx.DPxClose()
            raise

    def check_error(self, operation):
        status = self.dpx.DPxGetError()
        if status == 0 or getattr(status, "name", status) in ("DPX_SUCCESS", b"DPX_SUCCESS"):
            return
        raise RuntimeError(f"VPixx {operation} failed ({status}).")

    def call(self, name, *args):
        result = getattr(self.dpx, name)(*args)
        self.check_error(name)
        return result

    def update(self):
        """Bracket a hardware clock read with host times for an approximate mapping."""
        before = perf_counter()
        self.call("DPxUpdateRegCache")
        device = self.call("DPxGetTime")
        after = perf_counter()
        self.sync = dict(device_time_s=float(device), host_before_s=before, host_after_s=after)

    def arm(self, *, monitor_all=False):
        """Ignore old pulses and a line already active when the run becomes ready."""
        self.call("DPxDisableDinLogEvents")
        self.call("DPxUpdateRegCache")
        if self.call("DPxIsDoutDinLoopback"):
            raise RuntimeError("Controller DIN loopback is enabled.")
        if not monitor_all and self.call("DPxGetDinDataDir") & (1 << self.trigger_bit):
            raise RuntimeError("Scanner DIN is configured as an output.")
        if self.call("DPxGetRamSize") < BASE + BUFFER_BYTES:
            raise RuntimeError("Controller RAM is too small for the configured DIN buffer.")
        self.call("DPxSetDinBuff", BASE, BUFFER_BYTES)
        self.log_configured = True
        self.call("DPxEnableDinLogTimetags")
        self.call("DPxEnableDinStabilize")
        self.call("DPxDisableDinDebounce")
        # A small even read of the inactive buffer distinguishes wrapper units.
        # A length of two returns either two bytes or two 16-bit words.
        probe_size = len(self.ram_bytes(BASE, 2))
        if probe_size not in (2, 4):
            raise RuntimeError(f"Unexpected DPxReadRam probe size {probe_size} bytes.")
        self.bytes_per_unit = probe_size // 2
        self.call("DPxEnableDinLogEvents")
        self.update()
        if not self.call("DPxIsDinLogEvents"):
            raise RuntimeError("The VPixx digital input log did not start.")
        self.read_offset = 0
        self.armed_time = self.sync["device_time_s"]
        self.previous = int(self.call("DPxGetDinValue"))

    def ram_bytes(self, address, length):
        """Normalise the wrapper's byte or uint16 buffer to little-endian bytes."""
        result = self.call("DPxReadRam", address, length)
        try:
            view = memoryview(result)
        except TypeError:
            # Some wrappers return a list of NumPy/ctypes byte or word scalars.
            if len(result):
                try:
                    element_size = memoryview(result[0]).itemsize
                except TypeError:
                    element_size = None
                if element_size == 1:
                    return bytes(result)
                if element_size == 2:
                    return struct.pack(f"<{len(result)}H", *result)
            raise RuntimeError(
                f"DPxReadRam returned {type(result).__name__} without a byte/word "
                "element type. Send the installed DPxReadRam source to check its units."
            ) from None
        if view.ndim == 1 and view.itemsize == 1:
            return view.tobytes()
        if view.ndim == 1 and view.itemsize == 2:
            return struct.pack(f"<{len(view)}H", *result)
        raise RuntimeError(f"Unexpected DPxReadRam buffer format {view.format}.")

    def read(self, *, monitor_all=False):
        self.update()
        if not self.call("DPxIsDinLogEvents"):
            raise RuntimeError("VPixx digital input logging stopped unexpectedly.")
        offset = int(self.call("DPxGetDinBuffWriteAddr")) - BASE
        if not 0 <= offset <= BUFFER_BYTES or offset % FRAME_BYTES:
            raise RuntimeError(f"Unexpected Classic DIN buffer write offset {offset}.")
        pending = ((offset - self.read_offset) % BUFFER_BYTES) // FRAME_BYTES
        self.max_pending = max(self.max_pending, pending)
        if pending >= 0.9 * FRAMES:
            raise RuntimeError("VPixx input buffer nearly full; check for noisy inputs.")
        rows = []
        while pending:
            # Limit USB transfer size and split reads at the circular-buffer boundary.
            count = min(pending, (BUFFER_BYTES - self.read_offset) // FRAME_BYTES, 4000)
            byte_count = count * FRAME_BYTES
            address = BASE + self.read_offset
            length = byte_count // self.bytes_per_unit
            prefix = 0
            if length % 2:
                # Some word-count wrappers also require an even word count.
                # Read one neighbouring word, always inside the allocated ring.
                if self.read_offset + byte_count == BUFFER_BYTES:
                    prefix = 2
                    address -= prefix
                length += 1
            data = self.ram_bytes(address, length)
            if len(data) != length * self.bytes_per_unit:
                raise RuntimeError("Incomplete Classic DIN RAM transfer.")
            for ticks, value in struct.iter_unpack("<QH", data[prefix:prefix + byte_count]):
                rows.append((ticks / 1e9, value))
            self.read_offset = (self.read_offset + count * FRAME_BYTES) % BUFFER_BYTES
            pending -= count
        detected = perf_counter()
        events = []
        channels = range(16) if monitor_all else sorted(set(range(4)) | {self.trigger_bit})
        for device_time, raw in rows:
            # previous already represents the state at armed_time.
            if device_time <= self.armed_time:
                continue
            raw = int(raw)
            changed = self.previous ^ raw
            for bit in channels:
                if not changed & (1 << bit):
                    continue
                level = (raw >> bit) & 1
                if monitor_all:
                    kind = "rising" if level else "falling"
                    key = f"DIN{bit}"
                elif bit == self.trigger_bit:
                    kind = "trigger" if level == self.trigger_level else "trigger_release"
                    key = "scanner"
                else:
                    kind = "boxpress" if level == self.button_level else "boxrelease"
                    key = ("red", "yellow", "green", "blue")[bit]
                events.append(dict(device_time_s=float(device_time), host_detected_s=detected,
                                   kind=kind, key=key, raw_din=raw))
            self.previous = raw
        return events

    def close(self):
        try:
            if self.log_configured:
                self.dpx.DPxDisableDinLogEvents()
                self.dpx.DPxUpdateRegCache()
        finally:
            self.dpx.DPxClose()



def monitor():
    """Inspect the scanner cable and button box before loading PsychoPy."""
    print(f"Python {sys.version.split()[0]} at {sys.executable}", flush=True)
    scanner = ScannerInput()
    try:
        print(f"Controller selected. pypixxlib {scanner.package_version}, "
              f"{scanner.log_backend}", flush=True)
        scanner.arm(monitor_all=True)
        print(f"READY. Initial DIN = 0x{scanner.previous & 0xffff:04x}. "
              "Send several scanner pulses, then press each button. Ctrl+C exits.", flush=True)
        while True:
            for event in scanner.read(monitor_all=True):
                print(f"{event['device_time_s']:.6f}  {event['key']}  "
                      f"{event['kind']}  0x{event['raw_din']:04x}", flush=True)
            sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        scanner.close()


if __name__ == "__main__":
    monitor()
