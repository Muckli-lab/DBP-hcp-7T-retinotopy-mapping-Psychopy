"""Read PROPixx DIN edges directly; the device buffers pulses between polls."""
from time import perf_counter


class ScannerInput:
    def __init__(self, trigger_bit=4, trigger_level=0, button_level=0):
        from pypixxlib import _libdpx as dpx

        self.dpx = dpx
        self.trigger_bit = trigger_bit
        self.trigger_level = trigger_level
        self.button_level = button_level
        self.status = None
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

    def update(self):
        """Bracket a hardware clock read with host times for an approximate mapping."""
        before = perf_counter()
        self.dpx.DPxUpdateRegCache()
        device = self.dpx.DPxGetTime()
        after = perf_counter()
        error = self.dpx.DPxGetError()
        if error:
            raise RuntimeError(f"VPixx error {error}; check the controller connection.")
        self.sync = dict(device_time_s=float(device), host_before_s=before, host_after_s=after)

    def arm(self):
        """Ignore old pulses and a line already active when the run becomes ready."""
        dpx = self.dpx
        dpx.DPxStopDinLog()
        dpx.DPxUpdateRegCache()
        self.status = dpx.DPxSetDinLog(numBuffFrames=10000)
        if self.status is None:
            raise RuntimeError("Could not configure the VPixx digital input log.")
        # The original 30-ms debounce can suppress scanner TTL edges.
        # SetDinLog's short input stabilization filter is retained.
        dpx.DPxDisableDinDebounce()
        dpx.DPxStartDinLog()
        self.update()
        dpx.DPxGetDinStatus(self.status)
        if not self.status["logRunning"]:
            raise RuntimeError("The VPixx digital input log did not start.")
        if self.status["doutDinLoopback"] or self.status["dataDirection"] & (1 << self.trigger_bit):
            raise RuntimeError("Scanner DIN is not configured as an external input.")
        self.armed_time = self.sync["device_time_s"]
        self.previous = int(dpx.DPxGetDinValue())

    def read(self):
        self.update()
        self.dpx.DPxGetDinStatus(self.status)
        if not self.status["logRunning"]:
            raise RuntimeError("VPixx digital input logging stopped unexpectedly.")
        pending = self.status["newLogFrames"]
        self.max_pending = max(self.max_pending, pending)
        if pending >= .9 * self.status["numBufferFrames"]:
            raise RuntimeError("VPixx input buffer nearly full; check for noisy inputs.")
        rows = self.dpx.DPxReadDinLog(self.status) if pending else []
        error = self.dpx.DPxGetError()
        if error:
            raise RuntimeError(f"VPixx input read failed (error {error}).")
        if self.status.get("underflow"):
            raise RuntimeError("VPixx input log underflow; timing data are unreliable.")
        detected = perf_counter()
        events = []
        channels = sorted(set(range(4)) | {self.trigger_bit})
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
                if bit == self.trigger_bit:
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
            if self.status is not None:
                self.dpx.DPxStopDinLog()
                self.dpx.DPxUpdateRegCache()
        finally:
            self.dpx.DPxClose()
