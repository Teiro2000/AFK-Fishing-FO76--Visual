import math
import os
import subprocess
import threading
import time

import mss
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AHK_EXE = r"C:\Program Files\AutoHotkey\UX\AutoHotkeyUX.exe"
# EasyFishing.ahk is AutoHotkey v1 syntax, which AutoHotkeyUX.exe would run
# as v2 - so it needs the v1 interpreter directly
AHK_V1_EXE = r"C:\Program Files\AutoHotkey\AutoHotkeyU64.exe"

# All coordinates below are for 1920x1080 and get scaled to the actual
# monitor (game in borderless fullscreen, 16:9 HUD). Values were calibrated
# from real screenshots: the "E) CAST" prompt starts ~100px further left
# than "E) START REELING", and the floating bobber is a small cyan blob.
MONITOR = 1  # mss monitor index (1 = primary)
BASE_HEIGHT = 1080

# Fishing.ba2 draws a pink marker at the top-left corner while in fishing mode
# (5x5 at 1080p, bigger at higher resolutions - so (2, 2) is always inside it)
MARKER_POS = (2, 2)
MARKER_RGB = (0xF7, 0xA0, 0xB5)
MARKER_TOLERANCE = 20

# Left part of the prompt bar - only has white text when it says "E) CAST"
CAST_ZONE = {"left": 580, "top": 1022, "width": 80, "height": 30}

# Water area. Starts below the horizon so the bobber hanging from the rod
# tip (before casting) isn't counted.
WATER_ZONE = {"left": 0, "top": 560, "width": 1920, "height": 440}

POLL = 0.03

# Tunable settings - the GUI exposes these and saves them to settings.json
DEFAULT_SETTINGS = {
    "cast_min_white": 100,      # seen: 392 when showing, 0 otherwise
    "bobber_min_pixels": 5,     # seen: ~30 for a mid-distance bobber, 0 after a bite
    "bite_confirm": 0.2,        # bobber must be gone this long before reeling
    "cast_settle": 4,           # time for the bobber to land after casting
    "no_bobber_timeout": 10,    # bobber never showed up after casting -> reel in and retry
    "max_wait": 30,             # no bite after this long -> reel in and recast
    "minigame_timeout": 60,     # give up waiting for "CAST" after reeling
    "cast_delay": 2,            # pause after "CAST" appears before casting again
    # Pixel positions EasyFishing reads in the mod's corner squares, 0 = work
    # out from the resolution ((2,2) / (7,7) at 1080p)
    "minigame_square1": 0,
    "minigame_square2": 0,
}
# Pixel counts are compared as 1080p-equivalents (divided by scale^2), so
# cast_min_white / bobber_min_pixels work at any resolution

STATE_PAUSED = "paused"        # not in fishing mode
STATE_IDLE = "idle"            # waiting for the "CAST" prompt
STATE_CASTING = "casting"      # cast pressed, bobber landing
STATE_WAITING = "waiting"      # bobber floating, watching for a bite
STATE_REELING = "reeling"      # EasyFishing is playing the minigame


def press_e():
    subprocess.Popen([AHK_EXE, os.path.join(SCRIPT_DIR, "press_e.ahk")])


class Screen:
    # mss handles are per-thread, so create this in the thread that uses it
    def __init__(self):
        self.sct = mss.MSS()
        mon = self.sct.monitors[MONITOR]
        self.offset = (mon["left"], mon["top"])
        self.width, self.height = mon["width"], mon["height"]
        self.scale = self.height / BASE_HEIGHT
        self.area_scale = self.scale ** 2

        # The prompt bar is centred, so scale CAST_ZONE around the middle
        # of the screen (keeps it right on non-16:9 monitors too)
        sc = self.scale
        self.cast_zone = {
            "left": round(self.width / 2 + (CAST_ZONE["left"] - 960) * sc),
            "top": round(CAST_ZONE["top"] * sc),
            "width": round(CAST_ZONE["width"] * sc),
            "height": round(CAST_ZONE["height"] * sc),
        }
        self.water_zone = {
            "left": 0,
            "top": round(WATER_ZONE["top"] * sc),
            "width": self.width,
            "height": round(WATER_ZONE["height"] * sc),
        }

    def describe(self):
        return f"{self.width}x{self.height} (scale {self.scale:.2f}x)"

    def easy_fishing_squares(self, settings):
        # ceil matches EasyFishing's documented values: 7 at 1080p, 10 at 1440p
        square1 = settings["minigame_square1"] or 2
        square2 = settings["minigame_square2"] or math.ceil(7 * self.scale)
        return square1, square2

    def grab(self, zone):
        region = dict(zone)
        region["left"] += self.offset[0]
        region["top"] += self.offset[1]
        # mss returns BGRA
        return np.asarray(self.sct.grab(region))[..., 2::-1].astype(np.int16)

    def in_fishing_mode(self):
        x, y = MARKER_POS
        px = self.grab({"left": x, "top": y, "width": 1, "height": 1})[0, 0]
        return all(abs(int(c) - t) <= MARKER_TOLERANCE for c, t in zip(px, MARKER_RGB))

    def cast_white_pixels(self):
        img = self.grab(self.cast_zone)
        return round((img.min(axis=2) > 200).sum() / self.area_scale)

    def bobber_pixels(self, exclude=None):
        zone = self.water_zone
        img = self.grab(zone)
        if exclude:
            # Blank out an overlay window (e.g. the GUI) so it isn't
            # mistaken for, or hide, the bobber. Rect is in screen coords.
            left, top, right, bottom = exclude
            x0 = max(left - self.offset[0] - zone["left"], 0)
            y0 = max(top - self.offset[1] - zone["top"], 0)
            x1 = right - self.offset[0] - zone["left"]
            y1 = bottom - self.offset[1] - zone["top"]
            if x1 > 0 and y1 > 0:
                img[y0:y1, x0:x1] = 0
        r, g, b = img[..., 0], img[..., 1], img[..., 2]
        cyan = (g > 150) & (b > 150) & (g - r > 40) & (b - r > 40)
        return round(cyan.sum() / self.area_scale)


class Fisher:
    """Runs the fishing loop on a background thread.

    on_log(msg) is called for log lines, and the latest detection values are
    readable from the attributes below - both from the worker thread, so a
    GUI should poll rather than touch widgets from the callback.
    """

    def __init__(self, settings=None, on_log=print):
        self.settings = dict(DEFAULT_SETTINGS, **(settings or {}))
        self.on_log = on_log
        self._stop = threading.Event()
        self._thread = None
        self._easy_fishing = None

        self.state = STATE_IDLE
        self.catches = 0
        self.fishing_mode = False
        self.cast_white = 0
        self.bobber_px = 0
        self.started_at = None
        # Screen rect (left, top, right, bottom) to ignore when looking for
        # the bobber - the GUI sets this to its own window
        self.exclude_rect = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._easy_fishing and self._easy_fishing.poll() is None:
            self._easy_fishing.terminate()
            self.log("Closed EasyFishing")
        self._easy_fishing = None

    def log(self, msg):
        self.on_log(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _press_e(self, reason):
        self.log(f"{reason} - pressing E")
        press_e()

    def _set_state(self, new_state):
        if new_state != self.state:
            self.state = new_state
            self._last_state_change = time.time()
            self.log(f"State: {new_state}")

    def _start_easy_fishing(self, screen):
        square1, square2 = screen.easy_fishing_squares(self.settings)
        if os.path.exists(AHK_V1_EXE):
            tooltip = (round(1650 * screen.scale), round(520 * screen.scale))
            self.log(f"Launching EasyFishing.ahk - squares ({square1},{square1}) / ({square2},{square2})")
            cmd = [AHK_V1_EXE, os.path.join(SCRIPT_DIR, "EasyFishing.ahk"),
                   *map(str, (square1, square1, square2, square2, *tooltip))]
        else:
            # easyFishing.exe is a precompiled build with the 1080p positions
            self.log("AutoHotkey v1 not found - launching easyFishing.exe (1080p only)")
            if (square1, square2) != (2, 7):
                self.log(f"WARNING: this resolution needs squares ({square1},{square1}) / "
                         f"({square2},{square2}) - install AutoHotkey v1 for the minigame to work")
            cmd = [os.path.join(SCRIPT_DIR, "easyFishing.exe")]
        self._easy_fishing = subprocess.Popen(cmd, cwd=SCRIPT_DIR)
        if self._stop.wait(1.5):  # give it time to load and register the F5 hotkey
            return
        self.log("Starting EasyFishing loop (F5)")
        subprocess.Popen([AHK_EXE, os.path.join(SCRIPT_DIR, "press_f5.ahk")])

    def _run(self):
        screen = Screen()
        self.started_at = time.time()
        self._last_state_change = time.time()
        self.state = STATE_IDLE
        self._bobber_seen = False
        self._bobber_gone_since = None
        self._cast_seen_since = None

        self.log(f"Screen: {screen.describe()}")
        self._start_easy_fishing(screen)
        self.log("Watching the screen")
        while not self._stop.is_set():
            self.fishing_mode = screen.in_fishing_mode()
            self.cast_white = screen.cast_white_pixels()
            self.bobber_px = screen.bobber_pixels(self.exclude_rect)
            if self.fishing_mode:
                if self.state == STATE_PAUSED:
                    self._set_state(STATE_IDLE)
                self._tick()
            elif self.state != STATE_PAUSED:
                self.log("Not in fishing mode (no pink marker) - pausing")
                self._set_state(STATE_PAUSED)
            self._stop.wait(POLL)
        self.log("Stopped")

    def _tick(self):
        s = self.settings
        now = time.time()
        elapsed = now - self._last_state_change
        cast_prompt = self.cast_white >= s["cast_min_white"]

        if self.state in (STATE_IDLE, STATE_REELING):
            if cast_prompt:
                if self._cast_seen_since is None:
                    self._cast_seen_since = now
                if now - self._cast_seen_since >= s["cast_delay"]:
                    self._press_e("Casting")
                    self._cast_seen_since = None
                    self._bobber_seen = False
                    self._bobber_gone_since = None
                    self._set_state(STATE_CASTING)
            else:
                self._cast_seen_since = None
                if self.state == STATE_REELING and elapsed >= s["minigame_timeout"]:
                    self.log("Never got back to the CAST prompt - resetting")
                    self._set_state(STATE_IDLE)
            return

        bobber = self.bobber_px >= s["bobber_min_pixels"]

        if self.state == STATE_CASTING:
            if bobber:
                self._bobber_seen = True
            if elapsed >= s["cast_settle"]:
                self._set_state(STATE_WAITING)
            return

        # STATE_WAITING
        if bobber:
            self._bobber_seen = True
            self._bobber_gone_since = None
        elif self._bobber_seen:
            if self._bobber_gone_since is None:
                self._bobber_gone_since = now
            if now - self._bobber_gone_since >= s["bite_confirm"]:
                self.catches += 1
                self._press_e(f"Bite #{self.catches}! Reeling in")
                self._set_state(STATE_REELING)
                return

        if not self._bobber_seen and elapsed >= s["no_bobber_timeout"]:
            self._press_e("Couldn't find the bobber - reeling in to recast")
            self._set_state(STATE_REELING)
        elif elapsed >= s["max_wait"]:
            self._press_e(f"No bite after {s['max_wait']}s - reeling in to recast")
            self._set_state(STATE_REELING)


def main():
    fisher = Fisher()
    fisher.start()
    print("Press Ctrl+C to stop...")
    last_debug = 0.0
    try:
        while fisher.running:
            if time.time() - last_debug >= 1.0:
                print(f"[debug] state={fisher.state} cast_white={fisher.cast_white} "
                      f"bobber_px={fisher.bobber_px}")
                last_debug = time.time()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    fisher.stop()


if __name__ == "__main__":
    main()
