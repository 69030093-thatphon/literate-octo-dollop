"""
Fisch Auto-Fish Macro (GUI) v5  -  Windows + macOS
- อ่านหน้าจอ + จำลองการกดปุ่ม/เมาส์ (ไม่ inject โค้ดเข้าเกม)
- ติดตั้ง: pip install pillow numpy pynput mss
- รัน:    python fisch_macro.py   (ถ้าเกมไม่รับปุ่ม ให้รันแบบ Run as administrator)
- Hotkey: F6 = เริ่ม/หยุด, F7 = หยุดฉุกเฉิน, F8 = ถ่ายภาพหน้าจอไว้สอบเทียบ
          ลากเมาส์ไปมุมซ้ายบนสุดของจอ = หยุดฉุกเฉิน

v5: ปรับระบบแทร็คให้แม่นและเร็วขึ้น
- ตั้ง timer ของ Windows เป็น 1ms + จับภาพเฉพาะบางแถวของพื้นที่ ลูปเร็วเป็นร้อยเฟรม/วิ
- แก้บั๊กแถบกระโดด: ตอนปลาทับแถบ สีแถบถูกบังจนขาดเป็น 2 ท่อน ตอนนี้ต่อท่อนให้อัตโนมัติ
- ตำแหน่งปลาใช้จุดศูนย์ถ่วงถ่วงน้ำหนักพิกเซล (นิ่งกว่าเดิม) และเลือกก้อนที่ใกล้ตำแหน่งที่คาดไว้
- ประเมินความเร็วปลา/แถบ แล้วคาดการณ์ล่วงหน้าชดเชยดีเลย์ของเกม
- ควบคุมแบบ PID + PWM (กดสลับเร็วตามสัดส่วน) แทน กด/ปล่อย แบบสองจังหวะ
- มีตัวเลือกบันทึก trace เป็น CSV ไว้ดูย้อนหลังว่าบอทเห็นและสั่งอะไร
"""
import csv
import ctypes
import json
import math
import os
import sys
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
from PIL import ImageGrab, Image, ImageDraw, ImageTk
from pynput import keyboard

try:
    import mss
except ImportError:
    mss = None

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

winsound = None
if IS_WIN:
    try:
        import winsound
    except ImportError:
        winsound = None
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # ให้พิกัดตรงกับจอจริง
    except Exception:
        pass
    user32 = ctypes.windll.user32
else:
    user32 = None

if IS_WIN:
    # ------------------------------------------------------------ SendInput (scan code)
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KeyBdInput(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", PUL)]

    class HardwareInput(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short),
                    ("wParamH", ctypes.c_ushort)]

    class MouseInput(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]

    class Input_I(ctypes.Union):
        _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    SCAN = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
            "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "\\": 0x2B, "enter": 0x1C}

    def _send(inp):
        user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))

    def key_event(scan, up=False):
        extra = ctypes.c_ulong(0)
        ii = Input_I()
        ii.ki = KeyBdInput(0, scan, 0x0008 | (0x0002 if up else 0), 0, ctypes.pointer(extra))
        _send(Input(1, ii))

    def tap(name, hold=0.04):
        scan = SCAN.get(name)
        if scan is None:
            return
        key_event(scan, False)
        time.sleep(hold)
        key_event(scan, True)

    def mouse_button(down):
        extra = ctypes.c_ulong(0)
        ii = Input_I()
        ii.mi = MouseInput(0, 0, 0, 0x0002 if down else 0x0004, 0, ctypes.pointer(extra))
        _send(Input(0, ii))

    def cursor_pos():
        p = POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

else:
    # ------------------------------------------------------------ macOS / อื่น ๆ (pynput)
    from pynput import mouse as _pmouse
    _kb = keyboard.Controller()
    _ms = _pmouse.Controller()

    def tap(name, hold=0.04):
        key = keyboard.Key.enter if name == "enter" else name
        _kb.press(key)
        time.sleep(hold)
        _kb.release(key)

    def mouse_button(down):
        if down:
            _ms.press(_pmouse.Button.left)
        else:
            _ms.release(_pmouse.Button.left)

    def cursor_pos():
        x, y = _ms.position
        return int(x), int(y)


def beep():
    try:
        if IS_WIN and winsound:
            winsound.Beep(1200, 60)
        elif IS_MAC:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
    except Exception:
        pass


# ---------------------------------------------------------------- ตั้งค่า
if IS_MAC and getattr(sys, "frozen", False):
    BASE_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FischMacro")
    os.makedirs(BASE_DIR, exist_ok=True)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "fisch_config.json")
TRACE_FILE = os.path.join(BASE_DIR, "fisch_trace.csv")

DEFAULTS = {
    "rod_slot": "1",
    "region": [600, 800, 720, 60],
    "fish_color": [90, 90, 90],
    "bar_color": [255, 255, 255],
    "bar_color2": None,          # สีแถบตอนหลุดจากปลา (น้ำตาล)
    "tolerance": 25,
    "cast_hold": 1.0,
    "bite_timeout": 25,
    "reel_timeout": 40,
    "loop_delay": 2.0,
    "start_delay": 5,
    "kp": 1.0,                   # ความไวในการตามปลา
    "kd": 0.10,                  # กันแกว่ง (ใช้ความเร็วสัมพัทธ์)
    "latency": 0.05,             # ชดเชยดีเลย์ของเกม (วินาที)
    "use_shake": True,
    "nav_each_cycle": True,      # กด \ เปิดตอนรอ Shake และกด \ ปิดตอนเริ่มดึง (ครบคู่ทุกรอบ)
    "equip_on_start": True,      # กดช่องเบ็ดครั้งเดียวตอนเริ่ม (ถ้าถือเบ็ดอยู่แล้วให้ปิด)
    "invert": False,
    "trace": False,              # บันทึก fisch_trace.csv ของมินิเกมล่าสุด
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


# ---------------------------------------------------------------- จับภาพ + ตรวจจับ
class Grabber:
    """ใช้ mss ถ้ามี (เร็ว) ไม่งั้นใช้ ImageGrab. สร้างแยกต่อ thread"""

    def __init__(self):
        self.sct = None
        self.scale = 1.0     # Retina: พิกเซลจริง / พอยท์ของ macOS
        if mss is not None:
            try:
                self.sct = mss.mss()
                if IS_MAC:
                    mon = self.sct.monitors[1]
                    shot = self.sct.grab(mon)
                    self.scale = max(1.0, shot.width / float(mon["width"]))
            except Exception:
                self.sct = None

    def grab(self, region, stride=1):
        """คืน array RGB (int16) ของพื้นที่ โดยเก็บทุก stride แถว"""
        x, y, w, h = region
        if self.sct is not None:
            try:
                k = self.scale
                shot = self.sct.grab({"left": int(round(x / k)), "top": int(round(y / k)),
                                      "width": int(round(w / k)), "height": int(round(h / k))})
                return np.asarray(shot)[::stride, :, 2::-1].astype(np.int16)
            except Exception:
                self.sct = None
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
        return np.asarray(img)[::stride].astype(np.int16)


BAR_GAP = 60   # พิกเซลที่ยอมให้ขาดช่วงในแถบ (ตอนปลา/ไอคอนบังแถบ) แล้วยังนับเป็นแถบเดียวกัน
FISH_GAP = 2


def color_mask(arr, color, tol):
    return np.all(np.abs(arr - np.array(color, dtype=np.int16)) <= tol, axis=2)


def runs_of(mask, gap):
    """แยกคอลัมน์ที่มีสีตรงเป็นก้อนๆ คืนลิสต์ (ซ้าย, ขวา, จุดศูนย์ถ่วง, น้ำหนัก, จำนวนคอลัมน์)"""
    counts = mask.sum(axis=0)
    cols = np.nonzero(counts)[0]
    if cols.size == 0:
        return []
    out = []
    for g in np.split(cols, np.nonzero(np.diff(cols) > gap + 1)[0] + 1):
        w = counts[g]
        out.append((int(g[0]), int(g[-1]), float((g * w).sum() / w.sum()), int(w.sum()), int(g.size)))
    return out


def choose(runs, pred, min_cols=3):
    """เลือกก้อนที่ใช่: ตัดก้อนเล็กทิ้ง แล้วเลือกก้อนที่ใกล้ตำแหน่งที่คาดไว้ (ถ้าไม่มีให้เลือกก้อนใหญ่สุด)"""
    runs = [r for r in runs if r[4] >= min_cols]
    if not runs:
        return None
    max_w = max(r[3] for r in runs)
    cands = [r for r in runs if r[3] >= 0.4 * max_w]
    if pred is None:
        return max(cands, key=lambda r: r[3])
    return min(cands, key=lambda r: abs(r[2] - pred))


def analyze(arr, cfg, tol=None):
    """ใช้กับ Preview/หน้าสอบเทียบ: คืน (ก้อนปลา, ก้อนแถบ, mask ปลา, mask แถบขาว, mask แถบน้ำตาล)"""
    tol = cfg["tolerance"] if tol is None else tol
    fm = color_mask(arr, cfg["fish_color"], tol)
    bm1 = color_mask(arr, cfg["bar_color"], tol)
    bm2 = color_mask(arr, cfg["bar_color2"], tol) if cfg.get("bar_color2") else None
    bm = (bm1 | bm2) if bm2 is not None else bm1
    return choose(runs_of(fm, FISH_GAP), None), choose(runs_of(bm, BAR_GAP), None), fm, bm1, bm2


def measure(arr, cfg, pred_fish=None, pred_bar=None):
    """ใช้ในบอท: ตรวจปลา/แถบ โดยใช้ตำแหน่งที่คาดไว้ช่วยเลือกก้อน"""
    tol = cfg["tolerance"]
    fm = color_mask(arr, cfg["fish_color"], tol)
    bm = color_mask(arr, cfg["bar_color"], tol)
    if cfg.get("bar_color2"):
        bm |= color_mask(arr, cfg["bar_color2"], tol)
    return (choose(runs_of(fm, FISH_GAP), pred_fish),
            choose(runs_of(bm, BAR_GAP), pred_bar))


def centers(f, b):
    fish = f[2] if f else None
    bar = (b[0] + b[1]) / 2 if b else None
    return fish, bar


def row_stride(region):
    return max(1, region[3] // 24)


def detect(cfg, grabber):
    arr = grabber.grab(cfg["region"], row_stride(cfg["region"]))
    f, b = measure(arr, cfg)
    return centers(f, b)


class Track:
    """เก็บตำแหน่งล่าสุด + ความเร็ว (EMA) ไว้คาดการณ์ล่วงหน้า"""
    TAU = 0.05

    def __init__(self):
        self.x = None
        self.v = 0.0
        self.t = 0.0

    def update(self, z, t):
        if self.x is None or t - self.t > 0.3:
            self.x, self.v, self.t = z, 0.0, t
            return
        dt = max(t - self.t, 1e-3)
        a = 1.0 - math.exp(-dt / self.TAU)
        self.v += a * ((z - self.x) / dt - self.v)
        self.x, self.t = z, t

    def fresh(self, now, age=0.15):
        return self.x is not None and now - self.t <= age

    def pos(self, t):
        if self.x is None:
            return None
        return self.x + self.v * min(max(t - self.t, 0.0), 0.12)


# ---------------------------------------------------------------- บอท
class Bot(threading.Thread):
    def __init__(self, cfg, log, on_catch, on_finish):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.log = log
        self.on_catch = on_catch
        self.on_finish = on_finish
        self.stop_event = threading.Event()
        self.holding = False
        self.grabber = None
        self.live = ""

    def stop(self):
        self.stop_event.set()

    def stopped(self):
        return self.stop_event.is_set()

    def check_failsafe(self):
        if cursor_pos() == (0, 0):
            self.log("FAILSAFE: เมาส์อยู่มุมซ้ายบน หยุดทำงาน")
            self.stop()

    def wait(self, sec):
        end = time.time() + sec
        while not self.stopped() and time.time() < end:
            time.sleep(min(0.05, max(0.0, end - time.time())))
            self.check_failsafe()

    def hold(self, state):
        if state != self.holding:
            mouse_button(state)
            self.holding = state

    def cast(self):
        self.live = "เหวี่ยงเบ็ด"
        self.hold(True)
        self.wait(self.cfg["cast_hold"])
        self.hold(False)
        self.log("เหวี่ยงเบ็ด")

    def wait_for_bite(self):
        cfg = self.cfg
        self.live = "รอปลากิน / กด Shake"
        nav = cfg["use_shake"] and cfg["nav_each_cycle"]
        found = False
        if nav:
            self.wait(0.3)
            tap("\\")                      # เปิด UI Navigation
        try:
            start = time.time()
            while not self.stopped() and time.time() - start < cfg["bite_timeout"]:
                if cfg["use_shake"]:
                    tap("enter")
                fish, bar = detect(cfg, self.grabber)
                if fish is not None and bar is not None:
                    found = True
                    break
                self.wait(0.1)
        finally:
            if nav:
                tap("\\")                  # ปิด UI Navigation ให้ครบคู่เสมอ
                self.wait(0.15)
        return found

    def reel(self):
        cfg = self.cfg
        kp, kd, lat = cfg["kp"], cfg["kd"], cfg["latency"]
        region = cfg["region"]
        stride = row_stride(region)
        ft, bt = Track(), Track()
        bar_w = None
        integ, acc = 0.0, 0.5
        trace = []
        t0 = time.perf_counter()
        last_fish_seen = last_ctrl = fps_t = t0
        frames = fps_n = 0
        fps = 0.0
        u = 0.5
        while not self.stopped() and time.perf_counter() - t0 < cfg["reel_timeout"]:
            arr = self.grabber.grab(region, stride)
            now = time.perf_counter()
            frames += 1
            fps_n += 1
            f, b = measure(arr, cfg, ft.pos(now), bt.pos(now))
            if f:
                ft.update(f[2], now)
                last_fish_seen = now
            elif now - last_fish_seen > 0.7:
                break                           # ไม่เห็นปลานาน = มินิเกมจบ
            if b:
                bt.update((b[0] + b[1]) / 2, now)
                w = b[1] - b[0] + 1
                bar_w = w if bar_w is None else 0.9 * bar_w + 0.1 * w

            if now - last_ctrl >= 0.006:        # ส่งคำสั่งกดทุก ~6ms
                dt = now - last_ctrl
                last_ctrl = now
                if ft.fresh(now) and bt.fresh(now):
                    tp = now + lat
                    fp, bp = ft.pos(tp), bt.pos(tp)
                    half = max(8.0, (bar_w or 30.0) / 2)
                    e = (fp - bp) / half                 # +1 = ปลาอยู่ที่ขอบขวาของแถบ
                    ev = (ft.v - bt.v) / half
                    if abs(e) < 0.8:
                        integ = min(0.3, max(-0.3, integ + 0.3 * e * dt))
                    u = min(1.0, max(0.0, 0.5 + kp * e + kd * ev + integ))
                    if cfg["invert"]:
                        u = 1.0 - u
                    acc += u                              # sigma-delta: แปลง u เป็นจังหวะกด/ปล่อย
                    if acc >= 1.0:
                        acc -= 1.0
                        self.hold(True)
                    else:
                        self.hold(False)
                    if cfg["trace"]:
                        trace.append((round(now - t0, 4), round(ft.x, 1), round(bt.x, 1),
                                      round(bar_w or 0, 1), round(u, 3), int(self.holding)))
                    if frames % 8 == 0:
                        self.live = (f"ปลา {fp:.0f}  แถบ {bp:.0f}  กว้าง {bar_w or 0:.0f}  "
                                     f"u={u:.2f}  {fps:.0f} fps")
                elif not bt.fresh(now):
                    self.hold(False)                      # ไม่เห็นแถบ ปล่อยไว้ก่อนกันค้าง

            if fps_n >= 40:
                fps = fps_n / max(now - fps_t, 1e-6)
                fps_t, fps_n = now, 0
            if frames % 25 == 0:
                self.check_failsafe()
            time.sleep(0.001)
        self.hold(False)
        dur = time.perf_counter() - t0
        if cfg["trace"] and trace:
            try:
                with open(TRACE_FILE, "w", newline="", encoding="utf-8") as fh:
                    wr = csv.writer(fh)
                    wr.writerow(["t", "fish_x", "bar_x", "bar_w", "u", "hold"])
                    wr.writerows(trace)
            except Exception as e:
                self.log(f"เขียน trace ไม่ได้: {e}")
        self.live = ""
        return dur, frames / max(dur, 1e-6)

    def run(self):
        try:
            if IS_WIN:
                try:
                    ctypes.windll.winmm.timeBeginPeriod(1)    # ให้ sleep/นาฬิกาละเอียด 1ms
                except Exception:
                    pass
            self.grabber = Grabber()
            self.log("ใช้ mss จับภาพ" if self.grabber.sct else "ไม่พบ mss ใช้ ImageGrab (ช้ากว่า) แนะนำ pip install mss")
            self.log(f"เริ่มใน {self.cfg['start_delay']} วิ  คลิกกลับไปหน้าต่าง Roblox ให้ทัน")
            self.wait(self.cfg["start_delay"])
            if self.cfg["equip_on_start"] and not self.stopped():
                tap(self.cfg["rod_slot"])
                self.log(f"กดช่อง {self.cfg['rod_slot']} ถือเบ็ด (ครั้งเดียว)")
                self.wait(0.8)
            n = 0
            while not self.stopped():
                n += 1
                self.log(f"--- รอบที่ {n} ---")
                self.cast()
                if self.stopped():
                    break
                if self.wait_for_bite():
                    self.log("เจอมินิเกม เริ่มดึง")
                    dur, fps = self.reel()
                    self.on_catch()
                    self.log(f"จบมินิเกม ({dur:.1f} วิ, เฉลี่ย {fps:.0f} fps)")
                elif not self.stopped():
                    self.log("ไม่เจอมินิเกมจนหมดเวลา (เช็คว่าถือเบ็ดอยู่/พื้นที่ถูกไหม)")
                self.live = ""
                self.wait(self.cfg["loop_delay"])
        except Exception as e:
            self.log(f"error: {e}")
        finally:
            try:
                mouse_button(False)
            except Exception:
                pass
            if IS_WIN:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass
            self.live = ""
            self.on_finish()


# ---------------------------------------------------------------- GUI
class App:
    PREVIEW_W = 480
    MAX_SNAPS = 8
    FIELDS = [
        ("ช่องเบ็ด", "rod_slot", str),
        ("กดค้างเหวี่ยง (วิ)", "cast_hold", float),
        ("รอปลากิน (วิ)", "bite_timeout", int),
        ("ดึงปลา สูงสุด (วิ)", "reel_timeout", int),
        ("หน่วงรอบ (วิ)", "loop_delay", float),
        ("หน่วงก่อนเริ่ม (วิ)", "start_delay", int),
        ("tolerance สี", "tolerance", int),
        ("ความไว kp", "kp", float),
        ("กันแกว่ง kd", "kd", float),
        ("ชดเชยดีเลย์ (วิ)", "latency", float),
    ]
    CHECKS = [
        ("กด Shake (Enter)", "use_shake"),
        ("สลับ UI Nav ทุกรอบ (\\)", "nav_each_cycle"),
        ("กดช่องเบ็ดตอนเริ่ม", "equip_on_start"),
        ("กลับทิศการกด", "invert"),
        ("บันทึก trace (ดีบัก)", "trace"),
    ]

    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.bot = None
        self.catches = 0
        self.started_at = None
        self.q = queue.Queue()
        self.photo = None
        self.pgrab = Grabber()
        self.snaps = []
        self.calib_open = False

        root.title("Fisch Macro v5")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        style = ttk.Style()
        style.configure(".", font=("Tahoma", 9))
        style.configure("TNotebook.Tab", padding=(8, 2))

        main = ttk.Frame(root, padding=6)
        main.grid()

        # --- แถบควบคุมบนสุด
        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew")
        self.btn = ttk.Button(top, text="เริ่ม (F6)", width=9, command=self.toggle)
        self.btn.pack(side="left")
        ttk.Button(top, text="บันทึก", width=7, command=self.save).pack(side="left", padx=4)
        self.preview_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Preview", variable=self.preview_var).pack(side="left", padx=4)
        self.stat = ttk.Label(top, text="ปลา 0 | 00:00:00 | หยุด")
        self.stat.pack(side="right")

        # --- Preview
        self.preview_img = tk.Label(main, bg="black", height=3)
        self.preview_img.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.preview_txt = ttk.Label(main, text="", foreground="gray")
        self.preview_txt.grid(row=2, column=0, sticky="w")

        # --- แท็บ
        nb = ttk.Notebook(main)
        nb.grid(row=3, column=0, sticky="ew", pady=(2, 0))

        # แท็บสอบเทียบ
        cal = ttk.Frame(nb, padding=6)
        nb.add(cal, text="สอบเทียบ")
        self.region_lbl = ttk.Label(cal, text="")
        self.region_lbl.grid(row=0, column=0, columnspan=4, sticky="w")
        self.snap_lbl = ttk.Label(cal, text="")
        self.snap_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(cal, text="เปิดหน้าสอบเทียบ", command=self.open_calib).grid(
            row=1, column=2, sticky="ew", padx=(0, 4))
        ttk.Button(cal, text="ล้างภาพ", command=self.clear_snaps).grid(row=1, column=3, sticky="ew")
        self.fish_sw = tk.Label(cal, width=3, relief="solid")
        self.bar_sw = tk.Label(cal, width=3, relief="solid")
        self.bar2_sw = tk.Label(cal, width=3, relief="solid")
        ttk.Label(cal, text="สีปลา").grid(row=2, column=0, sticky="w")
        self.fish_sw.grid(row=2, column=1, padx=(0, 8))
        ttk.Label(cal, text="สีแถบขาว").grid(row=2, column=2, sticky="w")
        self.bar_sw.grid(row=2, column=3, sticky="w")
        ttk.Label(cal, text="สีแถบน้ำตาล").grid(row=3, column=0, sticky="w", pady=2)
        self.bar2_sw.grid(row=3, column=1, padx=(0, 8))
        ttk.Button(cal, text="ล้างสีน้ำตาล", command=self.clear_bar2).grid(
            row=3, column=2, sticky="ew", padx=(0, 4))
        ttk.Button(cal, text="ทดสอบตรวจจับ", command=self.test_detect).grid(row=3, column=3, sticky="ew")
        ttk.Label(cal, foreground="gray", justify="left",
                  text="ระหว่างมินิเกม กด F8 ถ่ายภาพ 2-3 ครั้ง (ตอนแถบขาว/ตอนแถบน้ำตาล)\n"
                       "แล้วกด 'เปิดหน้าสอบเทียบ' เพื่อเลือกพื้นที่และสีบนภาพนิ่ง"
                  ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.refresh_cal()
        self.update_snap_lbl()

        # แท็บตั้งค่า
        st = ttk.Frame(nb, padding=6)
        nb.add(st, text="ตั้งค่า")
        self.vars, self.types = {}, {}
        half = (len(self.FIELDS) + 1) // 2
        for i, (label, key, typ) in enumerate(self.FIELDS):
            col = 0 if i < half else 3
            row = i if i < half else i - half
            ttk.Label(st, text=label).grid(row=row, column=col, sticky="w", pady=1)
            v = tk.StringVar(value=str(self.cfg[key]))
            self.vars[key] = v
            self.types[key] = typ
            ttk.Entry(st, textvariable=v, width=7).grid(row=row, column=col + 1, padx=(4, 12))
        self.bool_vars = {}
        for i, (label, key) in enumerate(self.CHECKS):
            b = tk.BooleanVar(value=bool(self.cfg[key]))
            self.bool_vars[key] = b
            ttk.Checkbutton(st, text=label, variable=b).grid(
                row=half + i // 2, column=0 if i % 2 == 0 else 3, columnspan=3, sticky="w")

        # แท็บ log
        lg = ttk.Frame(nb, padding=4)
        nb.add(lg, text="Log")
        self.logbox = tk.Text(lg, height=7, width=62, state="disabled", font=("Tahoma", 8))
        self.logbox.pack()

        # บรรทัดสถานะล่างสุด
        self.status_lbl = ttk.Label(main, text="พร้อมใช้งาน", foreground="#555")
        self.status_lbl.grid(row=4, column=0, sticky="w", pady=(2, 0))

        self.hk = keyboard.GlobalHotKeys({
            "<f6>": lambda: self.root.after(0, self.toggle),
            "<f7>": lambda: self.root.after(0, self.stop),
            "<f8>": self.snapshot,          # ถ่ายทันทีใน thread ของ hotkey เพื่อให้ไวที่สุด
        })
        self.hk.start()

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()
        self.update_preview()
        self.log("F8 ถ่ายภาพมินิเกม → เปิดหน้าสอบเทียบ → กดเริ่ม (F6) / หยุด (F7)")

    # ---------- ตัวช่วย
    def log(self, msg):
        self.q.put(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def poll(self):
        while not self.q.empty():
            line = self.q.get()
            self.logbox.configure(state="normal")
            self.logbox.insert("end", line + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
            self.status_lbl.config(text=line[11:])
        if self.bot and self.bot.is_alive() and self.started_at:
            s = int(time.time() - self.started_at)
            self.stat.config(text=f"ปลา {self.catches} | {s//3600:02d}:{s%3600//60:02d}:{s%60:02d} | ทำงาน")
        self.root.after(200, self.poll)

    def refresh_cal(self):
        x, y, w, h = self.cfg["region"]
        self.region_lbl.config(text=f"พื้นที่: x={x} y={y} w={w} h={h}")
        self.fish_sw.config(bg=rgb_hex(self.cfg["fish_color"]))
        self.bar_sw.config(bg=rgb_hex(self.cfg["bar_color"]))
        c2 = self.cfg.get("bar_color2")
        self.bar2_sw.config(bg=rgb_hex(c2) if c2 else "#e0e0e0", text="" if c2 else "-")

    def clear_bar2(self):
        self.cfg["bar_color2"] = None
        self.refresh_cal()
        self.log("ล้างสีแถบน้ำตาลแล้ว")

    def cur_tol(self):
        try:
            return int(self.vars["tolerance"].get())
        except ValueError:
            return self.cfg["tolerance"]

    def read_settings(self):
        try:
            for key, typ in self.types.items():
                self.cfg[key] = typ(self.vars[key].get())
            for key, b in self.bool_vars.items():
                self.cfg[key] = b.get()
            return True
        except ValueError:
            messagebox.showerror("ผิดพลาด", "ค่าที่กรอกไม่ถูกต้อง (ตัวเลข/ข้อความ)")
            return False

    def save(self):
        if self.read_settings():
            save_config(self.cfg)
            self.log("บันทึกตั้งค่าแล้ว")

    # ---------- Preview
    def update_preview(self):
        running = bool(self.bot and self.bot.is_alive())
        if running:
            # ระหว่างบอททำงานไม่จับภาพซ้ำ (กันแย่ง CPU) แสดงตัวเลขสดจากบอทแทน
            self.preview_txt.config(text=self.bot.live or "กำลังทำงาน...")
            self.root.after(200, self.update_preview)
            return
        if self.preview_var.get() and not self.calib_open:
            try:
                arr = self.pgrab.grab(self.cfg["region"])
                f, b, fm, bm1, bm2 = analyze(arr, self.cfg, self.cur_tol())
                out = arr.astype(np.uint8).copy()
                out[fm] = (255, 0, 0)
                out[bm1] = (0, 255, 0)
                if bm2 is not None:
                    out[bm2] = (255, 200, 0)
                pil = Image.fromarray(out)
                d = ImageDraw.Draw(pil)
                fc, bc = centers(f, b)
                if fc is not None:
                    d.line([(fc, 0), (fc, pil.height)], fill=(255, 0, 255), width=1)
                if bc is not None:
                    d.line([(bc, 0), (bc, pil.height)], fill=(0, 255, 255), width=1)
                if pil.width > self.PREVIEW_W:
                    pil = pil.resize((self.PREVIEW_W, max(1, int(pil.height * self.PREVIEW_W / pil.width))))
                self.photo = ImageTk.PhotoImage(pil)
                self.preview_img.config(image=self.photo, height=pil.height)
                self.preview_txt.config(
                    text=f"ปลา: {'x=%.0f' % fc if fc is not None else 'ไม่เจอ'}   "
                         f"แถบ: {'x=%.0f' % bc if bc is not None else 'ไม่เจอ'}   "
                         f"(แดง=ปลา เขียว=แถบขาว เหลือง=แถบน้ำตาล)")
            except Exception as e:
                self.preview_txt.config(text=f"preview error: {e}")
        elif not self.preview_var.get():
            self.preview_img.config(image="", height=3)
            self.preview_txt.config(text="")
        self.root.after(150, self.update_preview)

    # ---------- ภาพนิ่งสำหรับสอบเทียบ
    def snapshot(self):
        """ถูกเรียกจาก hotkey F8 (อยู่ใน thread ของ pynput)"""
        if self.calib_open:
            return
        try:
            if IS_MAC and mss is not None:
                with mss.mss() as _s:
                    _shot = _s.grab(_s.monitors[1])
                    img = Image.frombytes("RGB", _shot.size, _shot.bgra, "raw", "BGRX")
            else:
                img = ImageGrab.grab().convert("RGB")  # จอหลัก (พิกัดเริ่มที่ 0,0 เหมือนที่บอทใช้)
        except Exception as e:
            self.log(f"ถ่ายภาพไม่สำเร็จ: {e}")
            return
        self.snaps.append(img)
        if len(self.snaps) > self.MAX_SNAPS:
            self.snaps.pop(0)
        beep()
        self.log(f"ถ่ายภาพแล้ว ({len(self.snaps)} ภาพ)")
        self.root.after(0, self.update_snap_lbl)

    def update_snap_lbl(self):
        self.snap_lbl.config(text=f"ภาพที่ถ่ายไว้: {len(self.snaps)}/{self.MAX_SNAPS}  (F8 = ถ่าย)")

    def clear_snaps(self):
        self.snaps.clear()
        self.update_snap_lbl()
        self.log("ล้างภาพที่ถ่ายไว้แล้ว")

    def open_calib(self):
        if self.calib_open:
            return
        if not self.snaps:
            messagebox.showinfo("ยังไม่มีภาพ", "กด F8 ตอนมินิเกมแสดงอยู่ เพื่อถ่ายภาพไว้ก่อน")
            return
        self.calib_open = True
        self.root.withdraw()
        self.root.after(250, self._calib_window)

    def _calib_window(self):
        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        top.attributes("-topmost", True)
        top.configure(bg="black")
        canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        W, H = top.winfo_screenwidth(), top.winfo_screenheight()
        first = self.snaps[-1]
        sc = min(W / first.width, H / first.height)
        if sc > 0.98:
            sc = 1.0
        S = {"idx": len(self.snaps) - 1, "photo": None, "loupe": None, "drag": None}
        mode = tk.StringVar(value="region")
        overlay = tk.BooleanVar(value=True)

        img_item = canvas.create_image(0, 0, anchor="nw")
        rect_item = canvas.create_rectangle(0, 0, 0, 0, outline="cyan", width=2)
        drag_item = canvas.create_rectangle(0, 0, 0, 0, outline="red", width=2)
        loupe_item = canvas.create_image(W - 10, 10, anchor="ne")
        loupe_txt = canvas.create_text(W - 10, 195, anchor="ne", fill="yellow", font=("Tahoma", 10), text="")

        # ---- แถบเครื่องมือ
        bar = tk.Frame(canvas, bg="#222", padx=6, pady=4)
        row1 = tk.Frame(bar, bg="#222")
        row1.pack()
        hint = tk.Label(bar, bg="#222", fg="yellow", font=("Tahoma", 10))
        hint.pack(anchor="w")

        def rb(text, val):
            r = tk.Radiobutton(row1, text=text, variable=mode, value=val, bg="#222", fg="white",
                               selectcolor="#555", activebackground="#222", activeforeground="white",
                               font=("Tahoma", 10))
            r.pack(side="left")

        def sw():
            l = tk.Label(row1, width=2, relief="solid")
            l.pack(side="left", padx=(0, 8))
            return l

        rb("① ลากพื้นที่", "region")
        rb("② สีปลา", "fish")
        sw_fish = sw()
        rb("③ สีแถบขาว", "bar")
        sw_bar = sw()
        rb("④ สีแถบน้ำตาล", "bar2")
        sw_bar2 = sw()

        tk.Button(row1, text="◀", command=lambda: step(-1)).pack(side="left")
        idx_lbl = tk.Label(row1, bg="#222", fg="white", font=("Tahoma", 10))
        idx_lbl.pack(side="left", padx=4)
        tk.Button(row1, text="▶", command=lambda: step(1)).pack(side="left", padx=(0, 8))
        tk.Label(row1, text="tol", bg="#222", fg="white").pack(side="left")
        spin = tk.Spinbox(row1, from_=0, to=150, width=4, textvariable=self.vars["tolerance"],
                          command=lambda: render())
        spin.pack(side="left", padx=(2, 8))
        spin.bind("<KeyRelease>", lambda e: render())
        tk.Checkbutton(row1, text="ดูผลจับสี", variable=overlay, command=lambda: render(),
                       bg="#222", fg="white", selectcolor="#555", activebackground="#222",
                       activeforeground="white").pack(side="left", padx=(0, 8))
        tk.Button(row1, text="เสร็จ (Esc)", command=lambda: close()).pack(side="left")
        canvas.create_window(W // 2, 6, window=bar, anchor="n")

        hints = {
            "region": "ลากกรอบคลุมเฉพาะแถบแนวนอนที่มีปลากับแถบขาว (ให้บางที่สุด)",
            "fish": "คลิกที่ไอคอนปลา (ดูแว่นขยายมุมขวาบนช่วยเล็ง)",
            "bar": "คลิกที่แถบสีขาว (ใช้ภาพที่แถบเป็นสีขาว)",
            "bar2": "คลิกที่แถบสีน้ำตาล (กด ◀ ▶ ไปภาพที่แถบเป็นสีน้ำตาล)",
        }

        def on_mode(*_):
            hint.config(text=hints[mode.get()] + "     |     ← → เปลี่ยนภาพ   Esc ปิด")

        mode.trace_add("write", on_mode)
        on_mode()

        def sync_sw():
            sw_fish.config(bg=rgb_hex(self.cfg["fish_color"]))
            sw_bar.config(bg=rgb_hex(self.cfg["bar_color"]))
            c2 = self.cfg.get("bar_color2")
            sw_bar2.config(bg=rgb_hex(c2) if c2 else "#555")

        def base():
            return self.snaps[S["idx"]]

        def render():
            b = base()
            shown = b
            if overlay.get():
                x, y, w, h = self.cfg["region"]
                x0, y0 = max(0, x), max(0, y)
                x1, y1 = min(b.width, x + w), min(b.height, y + h)
                if x1 - x0 > 3 and y1 - y0 > 1:
                    crop = b.crop((x0, y0, x1, y1))
                    arr = np.asarray(crop).astype(np.int16)
                    _, _, fm, bm1, bm2 = analyze(arr, self.cfg, self.cur_tol())
                    out = np.array(crop)
                    out[fm] = (255, 0, 0)
                    out[bm1] = (0, 255, 0)
                    if bm2 is not None:
                        out[bm2] = (255, 200, 0)
                    shown = b.copy()
                    shown.paste(Image.fromarray(out), (x0, y0))
            if sc != 1.0:
                shown = shown.resize((int(shown.width * sc), int(shown.height * sc)), Image.NEAREST)
            S["photo"] = ImageTk.PhotoImage(shown)
            canvas.itemconfig(img_item, image=S["photo"])
            x, y, w, h = self.cfg["region"]
            canvas.coords(rect_item, x * sc, y * sc, (x + w) * sc, (y + h) * sc)
            idx_lbl.config(text=f"ภาพ {S['idx'] + 1}/{len(self.snaps)}")
            sync_sw()

        def step(d):
            S["idx"] = (S["idx"] + d) % len(self.snaps)
            render()

        def to_img(e):
            b = base()
            ix = min(max(int(e.x / sc), 0), b.width - 1)
            iy = min(max(int(e.y / sc), 0), b.height - 1)
            return ix, iy

        def on_move(e):
            b = base()
            ix, iy = to_img(e)
            r = 12
            loupe = b.crop((ix - r, iy - r, ix + r + 1, iy + r + 1)).resize((25 * 7, 25 * 7), Image.NEAREST)
            d = ImageDraw.Draw(loupe)
            c = r * 7
            d.rectangle([c, c, c + 6, c + 6], outline=(255, 0, 255))
            S["loupe"] = ImageTk.PhotoImage(loupe)
            canvas.itemconfig(loupe_item, image=S["loupe"])
            px = b.getpixel((ix, iy))[:3]
            canvas.itemconfig(loupe_txt, text=f"{rgb_hex(px)}  RGB{tuple(px)}  ({ix},{iy})")

        def pick(e):
            m = mode.get()
            key = {"fish": "fish_color", "bar": "bar_color", "bar2": "bar_color2"}[m]
            ix, iy = to_img(e)
            px = list(base().getpixel((ix, iy))[:3])
            self.cfg[key] = px
            self.log(f"เก็บสี {key} = {px}")
            nxt = {"fish": "bar", "bar": "bar2"}
            if m in nxt:
                mode.set(nxt[m])
            render()

        def on_press(e):
            if mode.get() == "region":
                S["drag"] = (e.x, e.y)
                canvas.coords(drag_item, e.x, e.y, e.x, e.y)
            else:
                pick(e)

        def on_drag(e):
            if S["drag"]:
                x0, y0 = S["drag"]
                canvas.coords(drag_item, x0, y0, e.x, e.y)
            on_move(e)

        def on_release(e):
            if not S["drag"]:
                return
            x0, y0 = S["drag"]
            S["drag"] = None
            canvas.coords(drag_item, 0, 0, 0, 0)
            l, t = min(x0, e.x), min(y0, e.y)
            w, h = abs(e.x - x0), abs(e.y - y0)
            if w > 5 and h > 2:
                self.cfg["region"] = [int(l / sc), int(t / sc), int(w / sc), int(h / sc)]
                self.log(f"ตั้งพื้นที่: {self.cfg['region']}")
                mode.set("fish")
                render()

        def close(_=None):
            self.calib_open = False
            try:
                save_config(self.cfg)
            except Exception:
                pass
            top.destroy()
            self.root.deiconify()
            self.refresh_cal()
            self.log("สอบเทียบเสร็จ (บันทึกอัตโนมัติแล้ว) ดูผลที่ Preview")

        canvas.bind("<Motion>", on_move)
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        top.bind("<Escape>", close)
        top.bind("<Left>", lambda e: step(-1))
        top.bind("<Right>", lambda e: step(1))
        top.protocol("WM_DELETE_WINDOW", close)
        top.focus_force()
        render()

    def test_detect(self):
        if not self.read_settings():
            return
        fish, bar = detect(self.cfg, self.pgrab)
        self.log(f"ทดสอบ: ปลา x={fish}  แถบ x={bar}  (None = ไม่พบ)")

    # ---------- ควบคุมบอท
    def toggle(self):
        if self.bot and self.bot.is_alive():
            self.stop()
        else:
            self.start()

    def start(self):
        if not self.read_settings():
            return
        self.catches = 0
        self.started_at = time.time()
        self.bot = Bot(self.cfg, self.log, self.add_catch, self.on_finish)
        self.bot.start()
        self.btn.config(text="หยุด (F6)")

    def stop(self):
        if self.bot and self.bot.is_alive():
            self.bot.stop()
            self.log("กำลังหยุด...")

    def add_catch(self):
        self.catches += 1

    def on_finish(self):
        self.root.after(0, self._finished)

    def _finished(self):
        self.btn.config(text="เริ่ม (F6)")
        self.stat.config(text=f"ปลา {self.catches} | หยุด")
        self.log("หยุดการทำงานแล้ว")

    def close(self):
        self.stop()
        self.hk.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
