import ctypes
import ctypes.wintypes
import json
import os
import queue
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import autoFish as af

SETTINGS_FILE = os.path.join(af.SCRIPT_DIR, "settings.json")

# (key, label, help text) - order shown in the settings panel
SETTING_FIELDS = [
    ("bobber_min_pixels", "Bobber min pixels", "Lower if a far-away bobber isn't detected"),
    ("cast_min_white", "CAST prompt min pixels", "White pixels needed to count as the CAST prompt"),
    ("bite_confirm", "Bite confirm (s)", "Bobber must be gone this long before reeling"),
    ("cast_delay", "Cast delay (s)", "Pause after CAST appears before casting"),
    ("cast_settle", "Cast settle (s)", "Time for the bobber to land after casting"),
    ("max_wait", "Max wait for bite (s)", "Reel in and recast after this long"),
    ("no_bobber_timeout", "No bobber timeout (s)", "Recast if the bobber is never found"),
    ("minigame_timeout", "Minigame timeout (s)", "Give up waiting for CAST after reeling"),
    ("minigame_square1", "Minigame square 1", "0 = auto from resolution (2 at 1080p)"),
    ("minigame_square2", "Minigame square 2", "0 = auto from resolution (7 at 1080p, 10 at 1440p)"),
]

STATE_LABELS = {
    af.STATE_PAUSED: ("Paused - not in fishing mode", "#b58900"),
    af.STATE_IDLE: ("Waiting for CAST prompt", "#268bd2"),
    af.STATE_CASTING: ("Casting...", "#268bd2"),
    # Keep cyan out of the GUI - the bobber detector would count it
    af.STATE_WAITING: ("Waiting for a bite", "#3a9d23"),
    af.STATE_REELING: ("Reeling / minigame", "#d33682"),
}
GOOD, BAD, OFF = "#2e9e44", "#c0392b", "#888888"


def load_settings():
    settings = dict(af.DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
        settings.update({k: v for k, v in saved.items() if k in settings})
    except (OSError, ValueError):
        pass
    return settings


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AFK Fishing FO76 - Visual")
        self.resizable(False, True)
        self.logs = queue.Queue()
        self.fisher = af.Fisher(load_settings(), on_log=self.logs.put)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build()
        self._refresh()
        # Start as the compact overlay; wait until the window exists so its
        # real size is known when placing it in the corner
        self.after(50, self.toggle_on_top)

    # ---------- layout ----------

    def _build(self):
        style = ttk.Style(self)
        style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=8)
        style.configure("State.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Value.TLabel", font=("Consolas", 11))

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        self.start_btn = ttk.Button(top, text="▶  Start", style="Big.TButton",
                                    command=self.toggle)
        self.start_btn.pack(side="left")
        self.on_top = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Always on top", variable=self.on_top,
                        command=self.toggle_on_top).pack(side="right", padx=(16, 0))

        # Status
        status = ttk.LabelFrame(root, text="Status", padding=10)
        status.pack(fill="x", pady=(12, 0))
        self.status_frame = status
        # Fixed widths so the window doesn't resize (and drift off the
        # bottom of the screen in overlay mode) as the text changes
        self.state_lbl = ttk.Label(status, text="Stopped", style="State.TLabel",
                                   foreground=OFF, width=26)
        self.state_lbl.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.indicators = {}
        for row, (key, label) in enumerate([
                ("mode", "Fishing mode"), ("cast", "CAST prompt"),
                ("bobber", "Bobber"), ("bites", "Bites"), ("runtime", "Running for")], 1):
            dot = tk.Canvas(status, width=12, height=12, highlightthickness=0)
            dot.create_oval(2, 2, 11, 11, fill=OFF, outline="", tags="dot")
            dot.grid(row=row, column=0, padx=(0, 6))
            ttk.Label(status, text=label).grid(row=row, column=1, sticky="w")
            val = ttk.Label(status, text="-", style="Value.TLabel", width=20)
            val.grid(row=row, column=2, sticky="w", padx=(16, 0))
            self.indicators[key] = (dot, val)
        status.columnconfigure(2, weight=1)

        # Settings
        settings = ttk.LabelFrame(root, text="Settings", padding=10)
        settings.pack(fill="x", pady=(12, 0))
        self.settings_frame = settings
        self.setting_vars = {}
        for row, (key, label, tip) in enumerate(SETTING_FIELDS):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=1)
            var = tk.StringVar(value=str(self.fisher.settings[key]))
            entry = ttk.Entry(settings, textvariable=var, width=7, justify="right")
            entry.grid(row=row, column=1, padx=8)
            ttk.Label(settings, text=tip, foreground="#777").grid(row=row, column=2, sticky="w")
            self.setting_vars[key] = (var, entry)
        btns = ttk.Frame(settings)
        btns.grid(row=len(SETTING_FIELDS), column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="Apply & save", command=self.save_settings).pack(side="left")
        ttk.Button(btns, text="Reset defaults", command=self.reset_settings).pack(side="left", padx=6)
        self.settings_msg = ttk.Label(btns, text="")
        self.settings_msg.pack(side="left", padx=6)

        # Log
        logf = ttk.LabelFrame(root, text="Log", padding=6)
        logf.pack(fill="both", expand=True, pady=(12, 0))
        self.log_frame = logf
        self.log_box = ScrolledText(logf, height=10, width=70, state="disabled",
                                    font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)

        self.hint = ttk.Label(root, foreground="#777",
                              text="Enter fishing mode in-game (1920x1080, borderless), then press Start.")
        self.hint.pack(anchor="w", pady=(8, 0))

    def toggle_on_top(self):
        """Always on top = compact overlay in the bottom-left corner of the
        game, showing only the controls and status."""
        on_top = self.on_top.get()
        self.attributes("-topmost", on_top)
        if on_top:
            self.normal_pos = (self.winfo_x(), self.winfo_y())
            for w in (self.settings_frame, self.log_frame, self.hint):
                w.pack_forget()
            self.geometry("")  # shrink to fit what's left
            self.update_idletasks()
            with af.mss.MSS() as sct:
                mon = sct.monitors[af.MONITOR]
            _, top, _, bottom = self._window_rect()
            x = mon["left"]
            y = mon["top"] + mon["height"] - (bottom - top)
            self.geometry(f"+{x}+{y}")
        else:
            self.settings_frame.pack(fill="x", pady=(12, 0))
            self.log_frame.pack(fill="both", expand=True, pady=(12, 0))
            self.hint.pack(anchor="w", pady=(8, 0))
            self.geometry("")
            x, y = getattr(self, "normal_pos", (100, 100))
            self.geometry(f"+{x}+{y}")

    def _window_rect(self):
        # Outer window rect incl. title bar, in the same physical pixels
        # mss uses (importing mss makes the process DPI aware)
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(int(self.wm_frame(), 16), ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    # ---------- actions ----------

    def toggle(self):
        if self.fisher.running:
            self.fisher.stop()
        else:
            if not self.save_settings():
                return
            self.fisher.catches = 0
            self.fisher.start()

    def save_settings(self):
        new = {}
        for key, (var, entry) in self.setting_vars.items():
            try:
                value = float(var.get())
                if value < 0:
                    raise ValueError
            except ValueError:
                entry.focus_set()
                self.settings_msg.config(text=f"Invalid value: {key}", foreground=BAD)
                return False
            default = af.DEFAULT_SETTINGS[key]
            new[key] = int(value) if isinstance(default, int) else value
        self.fisher.settings.update(new)
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(new, f, indent=2)
            self.settings_msg.config(text="Saved", foreground=GOOD)
        except OSError as e:
            self.settings_msg.config(text=f"Applied, couldn't save: {e}", foreground=BAD)
        self.after(2500, lambda: self.settings_msg.config(text=""))
        return True

    def reset_settings(self):
        for key, (var, _) in self.setting_vars.items():
            var.set(str(af.DEFAULT_SETTINGS[key]))
        self.save_settings()

    def on_close(self):
        if self.fisher.running:
            self.fisher.stop()
        self.destroy()

    # ---------- live updates ----------

    def _set(self, key, text, color):
        dot, val = self.indicators[key]
        dot.itemconfig("dot", fill=color)
        val.config(text=text)

    def _refresh(self):
        while not self.logs.empty():
            self.log_box.config(state="normal")
            self.log_box.insert("end", self.logs.get() + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        f = self.fisher
        s = f.settings
        # Tell the detector where this window is so it doesn't read its
        # own pixels as (or lose the bobber behind) the GUI
        f.exclude_rect = self._window_rect() if self.state() == "normal" else None
        if f.running:
            self.start_btn.config(text="■  Stop")
            text, color = STATE_LABELS.get(f.state, (f.state, OFF))
            self.state_lbl.config(text=text, foreground=color)
            self._set("mode", "Yes" if f.fishing_mode else "No",
                      GOOD if f.fishing_mode else BAD)
            cast = f.cast_white >= s["cast_min_white"]
            self._set("cast", f"{'Visible' if cast else 'Hidden':8} {f.cast_white} / {s['cast_min_white']}",
                      GOOD if cast else OFF)
            bobber = f.bobber_px >= s["bobber_min_pixels"]
            self._set("bobber", f"{'Floating' if bobber else 'Not seen':8} {f.bobber_px} / {s['bobber_min_pixels']}",
                      GOOD if bobber else OFF)
            self._set("bites", str(f.catches), GOOD if f.catches else OFF)
            secs = int(time.time() - f.started_at) if f.started_at else 0
            self._set("runtime", time.strftime("%H:%M:%S", time.gmtime(secs)), GOOD)
        else:
            self.start_btn.config(text="▶  Start")
            self.state_lbl.config(text="Stopped", foreground=OFF)
            for key in ("mode", "cast", "bobber", "runtime"):
                self._set(key, "-", OFF)
        self.after(150, self._refresh)


if __name__ == "__main__":
    App().mainloop()
