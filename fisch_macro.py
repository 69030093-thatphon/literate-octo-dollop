"""
Fisch Auto-Fishing Macro (GUI) v9  -  Windows เท่านั้น
v8: ต้องล็อกอินก่อนใช้งาน โดยบัญชีเก็บในฐานข้อมูลฝั่งเซิร์ฟเวอร์ (backend: FastAPI + SQLite)
    แอปคุยกับ backend ผ่าน HTTP เท่านั้น (ไม่ต่อฐานข้อมูลตรง)
    สมัครสมาชิก (ชื่อผู้ใช้/รหัสผ่าน/ชื่อเล่น/วันเกิด) · ลืมรหัสผ่าน · ผู้ดูแลดู ID/รีเซ็ตรหัส/ซิงค์ Google Sheet
    ต้องเปิด backend ก่อน (ดู README.md)  ติดตั้งเพิ่ม: pip install requests
- อ่านหน้าจอ + จำลองการกดปุ่ม/เมาส์ (ไม่ inject โค้ดเข้าเกม)
- ติดตั้ง: pip install pillow numpy pynput mss requests
- รัน:    python fisch_macro.py   (ถ้าเกมไม่รับปุ่ม ให้รันแบบ Run as administrator)
- Hotkey: F6 = เริ่ม/หยุด, F7 = หยุดฉุกเฉิน, F8 = ถ่ายภาพหน้าจอไว้สอบเทียบ
          ลากเมาส์ไปมุมซ้ายบนสุดของจอ = หยุดฉุกเฉิน
"""
import csv
import ctypes
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import date
from tkinter import ttk, messagebox, simpledialog

import numpy as np
import requests
from PIL import ImageGrab, Image, ImageDraw, ImageTk
from pynput import keyboard

try:
    import mss
except ImportError:
    mss = None

try:
    import winsound
except ImportError:
    winsound = None

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # ให้พิกัดตรงกับจอจริง
except Exception:
    pass

user32 = ctypes.windll.user32

# ---------------------------------------------------------------- SendInput (scan code)
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


# ---------------------------------------------------------------- ตั้งค่า
from paths import app_dir

BASE_DIR = app_dir()
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
        if mss is not None:
            try:
                self.sct = mss.mss()
            except Exception:
                self.sct = None

    def grab(self, region, stride=1):
        """คืน array RGB (int16) ของพื้นที่ โดยเก็บทุก stride แถว"""
        x, y, w, h = region
        if self.sct is not None:
            try:
                shot = self.sct.grab({"left": x, "top": y, "width": w, "height": h})
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
        self.phase = "idle"      # idle / start / cast / wait / reel / rest
        self.cycle = 0

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
        self.phase = "cast"
        self.live = "เหวี่ยงเบ็ด"
        self.hold(True)
        self.wait(self.cfg["cast_hold"])
        self.hold(False)
        self.log("เหวี่ยงเบ็ด")

    def wait_for_bite(self):
        cfg = self.cfg
        self.phase = "wait"
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
        self.phase = "reel"
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
            try:
                ctypes.windll.winmm.timeBeginPeriod(1)    # ให้ sleep/นาฬิกาละเอียด 1ms
            except Exception:
                pass
            self.grabber = Grabber()
            self.log("ใช้ mss จับภาพ" if self.grabber.sct else "ไม่พบ mss ใช้ ImageGrab (ช้ากว่า) แนะนำ pip install mss")
            self.log(f"เริ่มใน {self.cfg['start_delay']} วิ  คลิกกลับไปหน้าต่าง Roblox ให้ทัน")
            self.phase = "start"
            self.live = "นับถอยหลัง... คลิกกลับไปหน้าเกม"
            self.wait(self.cfg["start_delay"])
            if self.cfg["equip_on_start"] and not self.stopped():
                tap(self.cfg["rod_slot"])
                self.log(f"กดช่อง {self.cfg['rod_slot']} ถือเบ็ด (ครั้งเดียว)")
                self.wait(0.8)
            while not self.stopped():
                self.cycle += 1
                self.log(f"--- รอบที่ {self.cycle} ---")
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
                self.phase = "rest"
                self.live = "พักก่อนเหวี่ยงรอบถัดไป"
                self.wait(self.cfg["loop_delay"])
        except Exception as e:
            self.log(f"error: {e}")
        finally:
            try:
                mouse_button(False)
            except Exception:
                pass
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
            self.phase = "idle"
            self.live = ""
            self.on_finish()


# ---------------------------------------------------------------- ธีม
BG = "#0f172a"        # พื้นหลังหลัก
PANEL = "#1e293b"     # แผง/header
PANEL2 = "#334155"    # ช่องกรอก/ปุ่มรอง
LINE = "#475569"      # เส้นขอบ
FG = "#e2e8f0"
MUTED = "#94a3b8"
ACCENT = "#22d3ee"    # ฟ้าทะเล
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
DARK = "#0b1220"
FONT_NAME = "Segoe UI" if sys.platform == "win32" else "Tahoma"
FONT = (FONT_NAME, 9)
FONT_B = (FONT_NAME, 9, "bold")

PHASES = {
    "idle": ("หยุด", "#64748b"),
    "start": ("เตรียมเริ่ม", AMBER),
    "cast": ("เหวี่ยงเบ็ด", ACCENT),
    "wait": ("รอปลากิน", AMBER),
    "reel": ("กำลังดึงปลา", GREEN),
    "rest": ("พักรอบ", ACCENT),
}

FIELD_INFO = {
    "rod_slot": ("ช่องเบ็ด (1-9)", str, "เลขช่อง hotbar ที่ใส่เบ็ดไว้ในเกม"),
    "cast_hold": ("กดค้างเหวี่ยง (วิ)", float, "เวลากดเมาส์ค้างตอนเหวี่ยง ยิ่งนานยิ่งเหวี่ยงไกล"),
    "bite_timeout": ("รอปลากิน (วิ)", int, "รอปลากินนานสุดกี่วินาที เกินแล้วเหวี่ยงใหม่"),
    "reel_timeout": ("ดึงปลา สูงสุด (วิ)", int, "เวลาดึงปลาสูงสุดต่อ 1 ตัว กันบอทค้างในมินิเกม"),
    "loop_delay": ("พักระหว่างรอบ (วิ)", float, "พักก่อนเหวี่ยงรอบใหม่ ให้ป๊อปอัปปลาที่ได้หายก่อน"),
    "start_delay": ("นับถอยหลังเริ่ม (วิ)", int, "เวลาหลังกดเริ่ม ให้คลิกกลับไปหน้าต่างเกมให้ทัน"),
    "tolerance": ("ความคลาดเคลื่อนสี", int, "ยอมให้สีต่างจากที่เก็บไว้ได้เท่าไร\nน้อย = เข้มงวด / มาก = หลวมแต่จับสีผิดได้"),
    "kp": ("ความไว (kp)", float, "ความไวในการตามปลา\nตามไม่ทันให้เพิ่ม / แถบแกว่งไปมาให้ลด"),
    "kd": ("กันแกว่ง (kd)", float, "ถ้าแถบพุ่งเลยปลาบ่อยให้เพิ่มทีละ 0.03"),
    "latency": ("ชดเชยดีเลย์ (วิ)", float, "แถบตามหลังปลาตลอดให้เพิ่ม / พุ่งเลยปลาตลอดให้ลด"),
}
GROUP_TIMING = ["rod_slot", "cast_hold", "bite_timeout", "reel_timeout", "loop_delay", "start_delay"]
GROUP_TRACK = ["tolerance", "kp", "kd", "latency"]
CHECK_INFO = [
    ("กด Shake (Enter รัว)", "use_shake", "กด Enter รัวเพื่อกดปุ่ม Shake อัตโนมัติ"),
    ("สลับ UI Nav ทุกรอบ (\\)", "nav_each_cycle", "กด \\ เปิด UI Navigation ตอนรอ Shake และปิดตอนเริ่มดึง ครบคู่ทุกรอบ"),
    ("กดช่องเบ็ดตอนเริ่ม", "equip_on_start", "กดช่องเบ็ดครั้งเดียวตอนเริ่ม\nถ้าถือเบ็ดอยู่แล้วให้ปิด ไม่งั้นจะเก็บเบ็ด"),
    ("กลับทิศการกด", "invert", "ถ้าแถบวิ่งหนีปลาตลอดไม่ว่าปรับอะไร ให้ติ๊กอันนี้"),
    ("บันทึก trace (ดีบัก)", "trace", "บันทึกข้อมูลทุกเฟรมเป็น fisch_trace.csv ไว้ส่งให้วิเคราะห์"),
]


class Tip:
    """tooltip เมื่อเอาเมาส์ชี้"""

    def __init__(self, widget, text):
        self.w, self.text, self.tw = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _=None):
        if self.tw:
            return
        x = self.w.winfo_rootx() + 14
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tw = tw = tk.Toplevel(self.w)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#fef9c3", fg="#1f2937", justify="left", font=FONT,
                 padx=8, pady=4, relief="solid", bd=1, wraplength=280).pack()

    def hide(self, _=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


# ---------------------------------------------------------------- ระบบล็อกอิน (คุยกับ backend ผ่าน HTTP)
CLIENT_CFG_FILE = os.path.join(BASE_DIR, "fisch_client.json")
DEFAULT_SERVER = "http://127.0.0.1:8000"
HEARTBEAT_SECS = 60      # ถามเซิร์ฟเวอร์ทุกกี่วินาทีว่าบัญชียังใช้ได้ไหม (ถูกระงับ/ลบ/หมดอายุ = ออกจากระบบ)
OFFLINE_GRACE = 5        # ต่อเซิร์ฟเวอร์ไม่ได้ติดกันกี่ครั้ง ถึงจะบังคับออกจากระบบ


def load_client_cfg():
    cfg = {"server": DEFAULT_SERVER, "last_user": ""}
    try:
        with open(CLIENT_CFG_FILE, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_client_cfg(cfg):
    try:
        with open(CLIENT_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class ClientError(Exception):
    """error จากการเรียกเซิร์ฟเวอร์ status = รหัส HTTP (0 = ต่อเซิร์ฟเวอร์ไม่ได้)"""

    def __init__(self, message, status=0):
        super().__init__(message)
        self.message = message
        self.status = status


class ApiClient:
    """ตัวกลางคุยกับ backend ทุกอย่างผ่านคลาสนี้ (แอปไม่ต่อฐานข้อมูลตรงๆ)"""

    def __init__(self, base_url):
        self.base = base_url.strip().rstrip("/")
        self.token = None
        self.http = requests.Session()

    def _call(self, method, path, body=None, auth=True, timeout=8):
        headers = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"     # แนบ token ทุกครั้งที่ต้องล็อกอิน
        try:
            r = self.http.request(method, self.base + path, json=body, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException:
            raise ClientError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ ตรวจที่อยู่เซิร์ฟเวอร์ และว่าเปิด backend อยู่", 0) from None
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            if not isinstance(detail, str):
                detail = ("ข้อมูลที่ส่งไปไม่ครบ/ไม่ถูกต้อง" if r.status_code == 422
                          else f"เซิร์ฟเวอร์ตอบผิดปกติ ({r.status_code})")
            raise ClientError(detail, r.status_code)
        return data

    # --- สาธารณะ
    def health(self):
        return self._call("GET", "/health", auth=False, timeout=5)

    def register(self, username, password, nickname, birthday):
        return self._call("POST", "/register", {"username": username, "password": password,
                                                "nickname": nickname, "birthday": birthday}, auth=False)

    def login(self, username, password):
        d = self._call("POST", "/login", {"username": username, "password": password}, auth=False)
        self.token = d["token"]
        return d

    def reset_password(self, username, birthday, nickname, new_password):
        return self._call("POST", "/password/reset", {"username": username, "birthday": birthday,
                                                      "nickname": nickname, "new_password": new_password},
                          auth=False)

    # --- ต้องล็อกอิน
    def me(self):
        return self._call("GET", "/me")

    def logout(self):
        try:
            self._call("POST", "/logout", timeout=4)
        finally:
            self.token = None

    def change_password(self, old, new):
        return self._call("POST", "/change-password", {"old_password": old, "new_password": new})

    # --- ผู้ดูแล
    def admin_users(self):
        return self._call("GET", "/admin/users")

    def admin_set_active(self, uid, active):
        return self._call("POST", f"/admin/users/{uid}/active", {"active": active})

    def admin_reset_password(self, uid, new_password=""):
        return self._call("POST", f"/admin/users/{uid}/reset-password", {"new_password": new_password})

    def admin_delete(self, uid):
        return self._call("DELETE", f"/admin/users/{uid}")

    def admin_sync_sheet(self):
        return self._call("POST", "/admin/sync-sheet", timeout=45)


def run_bg(widget, fn, on_ok, on_err):
    """รัน fn (เรียกเซิร์ฟเวอร์) ใน thread แยก ไม่ให้หน้าต่างค้าง แล้วเรียก on_ok/on_err กลับใน thread ของ Tk"""
    box = {}

    def work():
        try:
            box["ok"] = fn()
        except ClientError as e:
            box["err"] = e
        except Exception as e:
            box["err"] = ClientError(f"เกิดข้อผิดพลาด: {e}", 0)

    t = threading.Thread(target=work, daemon=True)
    t.start()

    def check():
        try:
            if t.is_alive():
                widget.after(60, check)
            elif "err" in box:
                on_err(box["err"])
            else:
                on_ok(box.get("ok"))
        except tk.TclError:
            pass                      # หน้าต่างถูกปิดไปแล้ว

    widget.after(60, check)


class DateField(ttk.Frame):
    """Universal Date of Birth selector (Day / Month / Year)"""
    MONTHS = [
        "Jan (01)", "Feb (02)", "Mar (03)", "Apr (04)",
        "May (05)", "Jun (06)", "Jul (07)", "Aug (08)",
        "Sep (09)", "Oct (10)", "Nov (11)", "Dec (12)"
    ]

    def __init__(self, parent):
        super().__init__(parent)
        this_year = date.today().year
        self.d = ttk.Combobox(self, width=4, state="readonly", values=[f"{i:02d}" for i in range(1, 32)])
        self.m = ttk.Combobox(self, width=9, state="readonly", values=self.MONTHS)
        self.y = ttk.Combobox(self, width=6, state="readonly",
                              values=[str(i) for i in range(this_year, 1949, -1)])
        for w in (self.d, self.m, self.y):
            w.pack(side="left", padx=(0, 4))
        ttk.Label(self, text="(DD / MM / YYYY)", style="Muted.TLabel").pack(side="left", padx=(2, 0))

    def get(self):
        try:
            return date(int(self.y.get()), self.MONTHS.index(self.m.get()) + 1, int(self.d.get())).isoformat()
        except (ValueError, TypeError):
            return None

    def clear(self):
        for w in (self.d, self.m, self.y):
            w.set("")


class LoginWindow:
    """Authentication Window: Sign In / Create Account / Forgot Password"""

    def __init__(self):
        self.ccfg = load_client_cfg()
        self.result = None
        self.busy = False
        self.buttons, self.pw_entries = [], []
        self.root = tk.Tk()
        self.root.title("Fisch Client — Authentication")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        App.setup_style()
        s = ttk.Style()
        s.configure("Card.TFrame", background="#131c2e")
        s.configure("LTitle.TLabel", foreground=ACCENT, font=(FONT_NAME, 19, "bold"), background="#131c2e")
        s.configure("LSub.TLabel", foreground=MUTED, font=(FONT_NAME, 9), background="#131c2e")
        s.configure("LField.TLabel", foreground="#cbd5e1", font=(FONT_NAME, 9, "bold"))
        s.configure("LHint.TLabel", foreground="#64748b", font=(FONT_NAME, 8))
        self.show_var = tk.BooleanVar(value=False)
        self.remember_var = tk.BooleanVar(value=True)
        self.build()
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(10, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry(f"+{x}+{y}")

    # ---------- UI Components
    def field(self, parent, label, hint="", show=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(7, 2))
        ttk.Label(row, text=label, style="LField.TLabel").pack(side="left")
        if hint:
            ttk.Label(row, text=f" · {hint}", style="LHint.TLabel").pack(side="left")
        e = ttk.Entry(parent, width=34, show=show)
        e.pack(fill="x")
        if show:
            self.pw_entries.append(e)
        return e

    def msg_label(self, parent):
        lbl = ttk.Label(parent, text="", wraplength=310, justify="left", font=(FONT_NAME, 8))
        lbl.pack(anchor="w", pady=(8, 0))
        return lbl

    def action_btn(self, parent, text, cmd):
        b = ttk.Button(parent, text=text, style="Accent.TButton", command=cmd)
        b.pack(fill="x", pady=(10, 0))
        self.buttons.append(b)
        return b

    def show_check(self, parent):
        ttk.Checkbutton(parent, text="Show password", variable=self.show_var,
                        command=self.toggle_show).pack(anchor="w", pady=(6, 0))

    def date_label(self, parent, text, hint=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(7, 2))
        ttk.Label(row, text=text, style="LField.TLabel").pack(side="left")
        if hint:
            ttk.Label(row, text=f" · {hint}", style="LHint.TLabel").pack(side="left")

    def build(self):
        # Elevated container card
        card_outer = tk.Frame(self.root, bg="#131c2e", highlightthickness=1, highlightbackground=LINE, padx=26, pady=20)
        card_outer.pack(padx=14, pady=14)

        ttk.Label(card_outer, text="FISCH CLIENT", style="LTitle.TLabel").pack()
        ttk.Label(card_outer, text="Authentication & Secure Account Portal", style="LSub.TLabel").pack(pady=(2, 8))

        self.nb = ttk.Notebook(card_outer)
        self.nb.pack(fill="x")

        # --- Tab 1: Sign In
        t1 = ttk.Frame(self.nb, padding=12)
        self.nb.add(t1, text="  Sign In  ")
        self.l_user = self.field(t1, "Username", "ชื่อผู้ใช้")
        self.l_pw = self.field(t1, "Password", "รหัสผ่าน", "•")
        row = ttk.Frame(t1)
        row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(row, text="Show password", variable=self.show_var, command=self.toggle_show).pack(side="left")
        ttk.Checkbutton(row, text="Remember me", variable=self.remember_var).pack(side="right")
        self.l_err = self.msg_label(t1)
        self.action_btn(t1, "Sign In  ➜", self.do_login)

        # --- Tab 2: Register (Create Account)
        t2 = ttk.Frame(self.nb, padding=12)
        self.nb.add(t2, text="  Register  ")
        self.r_user = self.field(t2, "Username", "a-z, 0-9, 3-20 chars")
        self.r_pw = self.field(t2, "Password", "min. 6 characters", "•")
        self.r_pw2 = self.field(t2, "Confirm Password", "ยืนยันรหัสผ่าน", "•")
        self.r_nick = self.field(t2, "Nickname", "ชื่อเล่น / Display Name")
        self.date_label(t2, "Date of Birth", "วันเกิด")
        self.r_bday = DateField(t2)
        self.r_bday.pack(anchor="w")
        self.show_check(t2)
        self.r_err = self.msg_label(t2)
        self.action_btn(t2, "Create Account  ➜", self.do_register)

        # --- Tab 3: Forgot Password
        t3 = ttk.Frame(self.nb, padding=12)
        self.nb.add(t3, text="  Forgot Password  ")
        ttk.Label(t3, text="Verify your registered nickname and birthdate to reset your password.",
                  style="LSub.TLabel", wraplength=310, justify="left").pack(anchor="w", pady=(0, 4))
        self.f_nick = self.field(t3, "Nickname", "ชื่อเล่นที่ใช้ตอนสมัคร")
        self.date_label(t3, "Date of Birth", "วันเกิด")
        self.f_bday = DateField(t3)
        self.f_bday.pack(anchor="w")
        self.f_user = self.field(t3, "Username", "Optional / ถ้าจำได้")
        self.f_pw = self.field(t3, "New Password", "รหัสผ่านใหม่", "•")
        self.f_pw2 = self.field(t3, "Confirm New Password", "ยืนยันรหัสผ่านใหม่", "•")
        self.show_check(t3)
        self.f_err = self.msg_label(t3)
        self.action_btn(t3, "Reset Password  ➜", self.do_reset)

        # --- Server connection section
        srv = ttk.Frame(card_outer)
        srv.pack(fill="x", pady=(12, 0))
        ttk.Label(srv, text="Backend Server Connection", style="LField.TLabel").pack(anchor="w")
        row_s = ttk.Frame(srv)
        row_s.pack(fill="x", pady=(3, 0))
        self.e_srv = ttk.Entry(row_s, width=28)
        self.e_srv.pack(side="left", fill="x", expand=True)
        self.e_srv.insert(0, self.ccfg.get("server", DEFAULT_SERVER))
        self.t_btn = ttk.Button(row_s, text="Ping / Test", command=self.do_test)
        self.t_btn.pack(side="left", padx=(6, 0))
        self.buttons.append(self.t_btn)
        self.srv_lbl = ttk.Label(srv, text="", style="LHint.TLabel")
        self.srv_lbl.pack(anchor="w", pady=(3, 0))

        last = self.ccfg.get("last_user", "")
        if last:
            self.l_user.insert(0, last)
            self.l_pw.focus_set()
        else:
            self.l_user.focus_set()
        self.root.bind("<Return>", self.on_enter)

    # ---------- Helpers
    def toggle_show(self):
        ch = "" if self.show_var.get() else "•"
        for e in self.pw_entries:
            e.config(show=ch)

    def say(self, label, text, kind="err"):
        prefix = {"ok": "✓ ", "err": "✕ ", "info": "● "}.get(kind, "")
        color = {"err": RED, "ok": GREEN, "info": ACCENT}.get(kind, MUTED)
        label.config(text=f"{prefix}{text}" if text else "", foreground=color)

    def set_busy(self, busy):
        self.busy = busy
        for b in self.buttons:
            b.config(state="disabled" if busy else "normal")

    def get_api(self, label):
        url = self.e_srv.get().strip()
        if not url:
            self.say(label, "Please enter server address.")
            return None
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
            self.e_srv.delete(0, "end")
            self.e_srv.insert(0, url)
        return ApiClient(url)

    def on_enter(self, _=None):
        if not self.busy:
            (self.do_login, self.do_register, self.do_reset)[self.nb.index("current")]()

    def finish(self, api, info):
        save_client_cfg({"server": api.base,
                         "last_user": info["username"] if self.remember_var.get() else ""})
        self.result = (api, info)
        self.root.destroy()

    # ---------- Actions
    def do_test(self):
        api = self.get_api(self.srv_lbl)
        if not api:
            return
        self.say(self.srv_lbl, "Testing server connection...", "info")
        self.set_busy(True)

        def ok(_):
            self.set_busy(False)
            self.say(self.srv_lbl, "Connected to backend server successfully.", "ok")

        def err(e):
            self.set_busy(False)
            self.say(self.srv_lbl, e.message, "err")

        run_bg(self.root, api.health, ok, err)

    def do_login(self):
        user, pw = self.l_user.get().strip(), self.l_pw.get()
        if not user or not pw:
            self.say(self.l_err, "Please enter your username and password.")
            return
        api = self.get_api(self.l_err)
        if not api:
            return
        self.say(self.l_err, "Signing in...", "info")
        self.set_busy(True)

        def ok(info):
            self.set_busy(False)
            self.finish(api, info)

        def err(e):
            self.set_busy(False)
            self.l_pw.delete(0, "end")
            self.say(self.l_err, e.message, "err")

        run_bg(self.root, lambda: api.login(user, pw), ok, err)

    def do_register(self):
        user, pw, pw2 = self.r_user.get().strip(), self.r_pw.get(), self.r_pw2.get()
        nick, bday = self.r_nick.get().strip(), self.r_bday.get()
        if not (user and pw and nick):
            self.say(self.r_err, "Please fill in all required fields.")
            return
        if pw != pw2:
            self.say(self.r_err, "Passwords do not match.")
            return
        if bday is None:
            self.say(self.r_err, "Please select a valid date of birth.")
            return
        api = self.get_api(self.r_err)
        if not api:
            return
        self.say(self.r_err, "Creating account...", "info")
        self.set_busy(True)

        def work():
            api.register(user, pw, nick, bday)
            return api.login(user, pw)

        def ok(info):
            self.set_busy(False)
            self.finish(api, info)

        def err(e):
            self.set_busy(False)
            self.say(self.r_err, e.message, "err")

        run_bg(self.root, work, ok, err)

    def do_reset(self):
        user, nick, bday = self.f_user.get().strip(), self.f_nick.get().strip(), self.f_bday.get()
        pw, pw2 = self.f_pw.get(), self.f_pw2.get()
        if not (nick and pw):
            self.say(self.f_err, "Please enter your nickname and new password.")
            return
        if bday is None:
            self.say(self.f_err, "Please select a valid date of birth.")
            return
        if pw != pw2:
            self.say(self.f_err, "New passwords do not match.")
            return
        api = self.get_api(self.f_err)
        if not api:
            return
        self.say(self.f_err, "Verifying credentials...", "info")
        self.set_busy(True)

        def ok(_):
            self.set_busy(False)
            for e in (self.f_nick, self.f_pw, self.f_pw2):
                e.delete(0, "end")
            self.f_bday.clear()
            self.say(self.f_err, "")
            self.l_user.delete(0, "end")
            self.l_user.insert(0, user or nick)
            self.l_pw.delete(0, "end")
            self.nb.select(0)
            self.say(self.l_err, "Password reset successful! Sign in with your new password.", "ok")
            self.l_pw.focus_set()

        def err(e):
            self.set_busy(False)
            self.say(self.f_err, e.message, "err")

        run_bg(self.root, lambda: api.reset_password(user, bday, nick, pw), ok, err)

    def run(self):
        self.root.mainloop()
        return self.result


class AccountDialog:
    """บัญชีของฉัน: ดู ID / เปลี่ยนรหัสผ่าน / (ผู้ดูแล) จัดการผู้ใช้ทั้งหมดและซิงค์ Google Sheet"""

    def __init__(self, parent, api, info, log):
        self.api, self.info, self.log = api, info, log
        self.uid = info.get("id")
        self.user = info.get("username", "")
        self.rows = {}
        is_admin = info.get("role") == "admin"
        top = self.top = tk.Toplevel(parent)
        top.title("บัญชีผู้ใช้")
        top.configure(bg=BG)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        top.transient(parent)
        body = ttk.Frame(top, padding=14)
        body.pack()

        def section(title):
            lf = ttk.LabelFrame(body, text=f" {title} ", padding=10)
            lf.pack(fill="x", pady=(0, 8))
            return lf

        def entry(parent_, label, show=""):
            row = ttk.Frame(parent_)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=18).pack(side="left")
            e = ttk.Entry(row, width=26, show=show)
            e.pack(side="left")
            return e

        ttk.Label(body, style="Accent.TLabel",
                  text=(f"ID: {self.uid}    ชื่อผู้ใช้: {self.user}    ชื่อเล่น: {info.get('nickname', '')}    "
                        f"({'ผู้ดูแล' if is_admin else 'ผู้ใช้ทั่วไป'})")).pack(anchor="w", pady=(0, 8))

        s1 = section("เปลี่ยนรหัสผ่าน")
        self.e_old = entry(s1, "รหัสผ่านเดิม", "•")
        self.e_new = entry(s1, "รหัสผ่านใหม่", "•")
        self.e_new2 = entry(s1, "ยืนยันรหัสผ่านใหม่", "•")
        ttk.Button(s1, text="เปลี่ยนรหัสผ่าน", command=self.change_pw).pack(fill="x", pady=(6, 0))
        self.msg1 = ttk.Label(s1, text="", wraplength=500, justify="left")
        self.msg1.pack(anchor="w", pady=(4, 0))

        if is_admin:
            s2 = section("ผู้ใช้ทั้งหมด (ผู้ดูแลเท่านั้น)")
            cols = (("id", "ID", 40), ("user", "ชื่อผู้ใช้", 95), ("nick", "ชื่อเล่น", 85),
                    ("bday", "วันเกิด", 80), ("role", "สิทธิ์", 55), ("status", "สถานะ", 55),
                    ("last", "ล็อกอินล่าสุด", 125))
            self.tree = ttk.Treeview(s2, columns=[c[0] for c in cols], show="headings",
                                     height=7, selectmode="browse")
            for key, title, width in cols:
                self.tree.heading(key, text=title)
                self.tree.column(key, width=width, anchor="w")
            self.tree.pack(fill="x")
            btns = ttk.Frame(s2)
            btns.pack(fill="x", pady=(8, 0))
            for i in range(3):
                btns.columnconfigure(i, weight=1)
            ttk.Button(btns, text="ระงับ / เปิดใช้งาน", command=self.toggle_active).grid(
                row=0, column=0, sticky="ew", padx=(0, 4))
            ttk.Button(btns, text="รีเซ็ตรหัสผ่าน", command=self.admin_reset).grid(
                row=0, column=1, sticky="ew", padx=(0, 4))
            ttk.Button(btns, text="ลบผู้ใช้", command=self.delete_user).grid(row=0, column=2, sticky="ew")
            ttk.Button(btns, text="รีเฟรช", command=self.reload).grid(
                row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
            ttk.Button(btns, text="ซิงค์ไป Google Sheet", style="Accent.TButton",
                       command=self.sync_sheet).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(4, 0))
            self.msg2 = ttk.Label(s2, text="", wraplength=500, justify="left")
            self.msg2.pack(anchor="w", pady=(6, 0))
            self.reload()

        ttk.Button(body, text="ปิด", command=top.destroy).pack(fill="x")

    @staticmethod
    def say(label, text, ok=False):
        label.config(text=text, foreground=GREEN if ok else RED)

    # ---------- เปลี่ยนรหัสผ่านของตัวเอง
    def change_pw(self):
        old, new, new2 = self.e_old.get(), self.e_new.get(), self.e_new2.get()
        if new != new2:
            self.say(self.msg1, "รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน")
            return

        def ok(_):
            for e in (self.e_old, self.e_new, self.e_new2):
                e.delete(0, "end")
            self.say(self.msg1, "เปลี่ยนรหัสผ่านแล้ว", ok=True)
            self.log("เปลี่ยนรหัสผ่านสำเร็จ")

        run_bg(self.top, lambda: self.api.change_password(old, new), ok,
               lambda e: self.say(self.msg1, e.message))

    # ---------- ผู้ดูแล
    def reload(self):
        run_bg(self.top, self.api.admin_users, self.fill, lambda e: self.say(self.msg2, e.message))

    def fill(self, users):
        self.rows = {u["id"]: u for u in users}
        self.tree.delete(*self.tree.get_children())
        for u in users:
            self.tree.insert("", "end", iid=str(u["id"]), values=(
                u["id"], u["username"], u["nickname"], u["birthday"],
                "ผู้ดูแล" if u["role"] == "admin" else "ผู้ใช้",
                "ใช้งาน" if u["active"] else "ระงับ", u["last_login"] or "-"))
        self.say(self.msg2, f"ผู้ใช้ทั้งหมด {len(users)} คน", ok=True)

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            self.say(self.msg2, "เลือกผู้ใช้ในตารางก่อน")
            return None
        return self.rows.get(int(sel[0]))

    def after_action(self, text):
        self.say(self.msg2, text, ok=True)
        self.reload()

    def toggle_active(self):
        u = self.selected()
        if not u:
            return
        run_bg(self.top, lambda: self.api.admin_set_active(u["id"], not u["active"]),
               lambda _: self.after_action(f"{'ระงับ' if u['active'] else 'เปิดใช้งาน'} {u['username']} แล้ว"),
               lambda e: self.say(self.msg2, e.message))

    def admin_reset(self):
        u = self.selected()
        if not u:
            return
        pw = simpledialog.askstring(
            "รีเซ็ตรหัสผ่าน", f"ตั้งรหัสผ่านใหม่ให้ {u['username']} (อย่างน้อย 6 ตัว)\nเว้นว่าง = ให้ระบบสุ่มให้",
            parent=self.top)
        if pw is None:
            return                                   # กดยกเลิก

        def ok(d):
            messagebox.showinfo("รีเซ็ตรหัสผ่านแล้ว",
                                f"รหัสผ่านใหม่ของ {u['username']} คือ\n\n{d['new_password']}\n\n"
                                "แจ้งผู้ใช้ แล้วให้เปลี่ยนรหัสเองหลังเข้าสู่ระบบ", parent=self.top)
            self.after_action(f"รีเซ็ตรหัสผ่านของ {u['username']} แล้ว")

        run_bg(self.top, lambda: self.api.admin_reset_password(u["id"], pw), ok,
               lambda e: self.say(self.msg2, e.message))

    def delete_user(self):
        u = self.selected()
        if not u:
            return
        if not messagebox.askyesno("ลบผู้ใช้", f"ลบผู้ใช้ '{u['username']}' (ID {u['id']}) ถาวรใช่หรือไม่?",
                                   parent=self.top):
            return
        run_bg(self.top, lambda: self.api.admin_delete(u["id"]),
               lambda _: self.after_action(f"ลบ {u['username']} แล้ว"),
               lambda e: self.say(self.msg2, e.message))

    def sync_sheet(self):
        self.say(self.msg2, "กำลังซิงค์ไป Google Sheet...", ok=True)
        run_bg(self.top, self.api.admin_sync_sheet,
               lambda d: self.say(self.msg2, d["message"], ok=d["ok"]),
               lambda e: self.say(self.msg2, e.message))


# ---------------------------------------------------------------- GUI
class App:
    PREVIEW_W = 480
    MAX_SNAPS = 8

    def __init__(self, root, api=None, info=None):
        self.root = root
        self.api = api
        self.info = info or {}
        self.user = self.info.get("username", "")
        self.role = self.info.get("role", "user")
        self.uid = self.info.get("id", "-")
        self.nickname = self.info.get("nickname", "")
        self.logout_requested = False
        self.kicked = None                     # ข้อความ ถ้าถูกบังคับออกจากระบบ (โดย heartbeat)
        self.hb_stop = threading.Event()
        self.cfg = load_config()
        self.bot = None
        self.catches = 0
        self.started_at = None
        self.q = queue.Queue()
        self.photo = None
        self.pgrab = Grabber()
        self.snaps = []
        self.calib_open = False
        self.vars, self.types, self.bool_vars = {}, {}, {}

        root.title("Fisch Macro")
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)
        self.setup_style()

        main = ttk.Frame(root, padding=8)
        main.grid()

        # ===== Header: ชื่อ + สถิติ + ป้ายสถานะ
        head = ttk.Frame(main, style="Head.TFrame", padding=(12, 8))
        head.grid(row=0, column=0, sticky="ew")
        self.head_title = ttk.Label(head, text="Fisch Macro", style="Title.TLabel")
        self.head_title.pack(side="left")
        ttk.Label(head, text=" v9", style="HeadMuted.TLabel").pack(side="left", pady=(5, 0))
        self.chip = tk.Label(head, text="●  หยุด", bg="#64748b", fg="white", font=FONT_B, padx=10, pady=3)
        self.chip.pack(side="right")
        stats = ttk.Frame(head, style="Head.TFrame")
        stats.pack(side="right", padx=14)

        def stat(cap):
            f = ttk.Frame(stats, style="Head.TFrame")
            f.pack(side="left", padx=9)
            v = ttk.Label(f, text="0", style="Stat.TLabel")
            v.pack()
            ttk.Label(f, text=cap, style="HeadMuted.TLabel").pack()
            return v

        self.st_fish = stat("ปลา")
        self.st_time = stat("เวลา")
        self.st_cycle = stat("รอบ")
        self.st_time.config(text="00:00:00")

        # ===== แถวปุ่มควบคุม
        ctl = ttk.Frame(main)
        ctl.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        self.btn = ttk.Button(ctl, text="▶  เริ่ม (F6)", style="Go.TButton", width=14, command=self.toggle)
        self.btn.pack(side="left")
        ttk.Button(ctl, text="บันทึก", command=self.save).pack(side="left", padx=6)
        self.preview_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Preview", variable=self.preview_var).pack(side="left", padx=6)
        ttk.Button(ctl, text="ออกจากระบบ", command=self.logout).pack(side="right")
        ttk.Button(ctl, text="บัญชี", command=self.open_account).pack(side="right", padx=6)
        ttk.Label(ctl, text=f"{self.nickname or self.user}  (ID {self.uid})", style="Muted.TLabel").pack(side="right", padx=(0, 4))

        # ===== Preview
        pv = ttk.LabelFrame(main, text=" Preview ", padding=6)
        pv.grid(row=2, column=0, sticky="ew")
        self.preview_img = tk.Label(pv, bg=DARK, fg=MUTED, font=FONT, text="(เปิด Preview เพื่อดูภาพ)",
                                    width=64, height=3)
        self.preview_img.pack(fill="x")
        self.preview_txt = ttk.Label(pv, text="", style="Muted.TLabel")
        self.preview_txt.pack(anchor="w", pady=(4, 0))

        # ===== แท็บ
        nb = ttk.Notebook(main)
        nb.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.build_calib_tab(nb)
        self.build_settings_tab(nb)
        self.build_log_tab(nb)

        # ===== แถบสถานะล่างสุด
        sb = ttk.Frame(main, style="Head.TFrame", padding=(10, 3))
        sb.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.status_lbl = ttk.Label(sb, text="พร้อมใช้งาน", style="Status.TLabel")
        self.status_lbl.pack(side="left")
        ttk.Label(sb, text="F7 หยุดฉุกเฉิน · F8 ถ่ายภาพ", style="Status.TLabel").pack(side="right")

        self.hk = keyboard.GlobalHotKeys({
            "<f6>": lambda: self.root.after(0, self.toggle),
            "<f7>": lambda: self.root.after(0, self.stop),
            "<f8>": self.snapshot,          # ถ่ายทันทีใน thread ของ hotkey เพื่อให้ไวที่สุด
        })
        self.hk.start()
        if self.api is not None:
            threading.Thread(target=self.heartbeat, daemon=True).start()

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_cal()
        self.update_snap_lbl()
        self.poll()
        self.update_preview()
        self.log("F8 ถ่ายภาพมินิเกม → เปิดหน้าสอบเทียบ → กดเริ่ม (F6)")

    # ---------- ธีม
    @staticmethod
    def setup_style():
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, font=FONT, fieldbackground=PANEL2,
                    bordercolor=LINE, focuscolor=BG, troughcolor=PANEL)
        s.configure("TFrame", background=BG)
        s.configure("Head.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Accent.TLabel", foreground=ACCENT, font=FONT_B)
        s.configure("Title.TLabel", background=PANEL, foreground=ACCENT, font=(FONT_NAME, 14, "bold"))
        s.configure("HeadMuted.TLabel", background=PANEL, foreground=MUTED, font=(FONT_NAME, 8))
        s.configure("Stat.TLabel", background=PANEL, foreground=FG, font=(FONT_NAME, 12, "bold"))
        s.configure("Status.TLabel", background=PANEL, foreground=MUTED)
        s.configure("Num.TLabel", background=ACCENT, foreground=BG, font=FONT_B, padding=(7, 1))

        def button(name, bg, hover, fg=FG):
            s.configure(name, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg,
                        darkcolor=bg, focuscolor=bg, padding=(12, 5), relief="flat", font=FONT_B)
            s.map(name, background=[("active", hover), ("pressed", hover), ("disabled", PANEL)],
                  bordercolor=[("active", hover)], lightcolor=[("active", hover)],
                  darkcolor=[("active", hover)], foreground=[("disabled", MUTED)])

        button("TButton", PANEL2, LINE)
        button("Go.TButton", "#16a34a", "#22c55e", "white")
        button("Stop.TButton", "#dc2626", "#ef4444", "white")
        button("Accent.TButton", ACCENT, "#67e8f9", BG)

        s.configure("TLabelframe", background=BG, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, relief="solid")
        s.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=FONT_B)
        s.configure("TEntry", fieldbackground=PANEL2, foreground=FG, insertcolor=FG,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=3)
        s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])
        s.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG,
                    upperbordercolor=LINE, lowerbordercolor=LINE)
        s.map("TCheckbutton", background=[("active", BG)], foreground=[("active", ACCENT)],
              indicatorcolor=[("selected", ACCENT), ("!selected", PANEL2)])
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 2, 0, 0))
        s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 5), borderwidth=0,
                    font=FONT_B)
        s.map("TNotebook.Tab", background=[("selected", PANEL2), ("active", PANEL2)],
              foreground=[("selected", ACCENT), ("active", FG)])
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG,
                    arrowcolor=FG, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                    selectbackground=PANEL2, selectforeground=FG, padding=3)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", PANEL2)], selectforeground=[("readonly", FG)],
              bordercolor=[("focus", ACCENT)])
        s.configure("Treeview", background=DARK, fieldbackground=DARK, foreground=FG,
                    borderwidth=0, rowheight=22)
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])
        s.configure("Treeview.Heading", background=PANEL2, foreground=FG, relief="flat", font=FONT_B)
        s.map("Treeview.Heading", background=[("active", LINE)])
        root = tk._default_root
        if root is not None:                       # ทำให้รายการ dropdown ของ Combobox เป็นธีมมืดด้วย
            root.option_add("*TCombobox*Listbox.background", DARK)
            root.option_add("*TCombobox*Listbox.foreground", FG)
            root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
            root.option_add("*TCombobox*Listbox.selectForeground", BG)

    # ---------- แท็บสอบเทียบ
    def make_chip(self, parent, title):
        f = tk.Frame(parent, bg=PANEL2, padx=7, pady=4)
        f.pack(side="left", padx=(0, 6))
        sw = tk.Label(f, width=2, bg="#000", highlightthickness=1, highlightbackground=LINE)
        sw.pack(side="left")
        tk.Label(f, text=title, bg=PANEL2, fg=FG, font=FONT).pack(side="left", padx=(6, 4))
        hx = tk.Label(f, text="", bg=PANEL2, fg=MUTED, font=("Consolas", 8))
        hx.pack(side="left")
        return sw, hx

    def build_calib_tab(self, nb):
        cal = ttk.Frame(nb, padding=10)
        nb.add(cal, text="  สอบเทียบ  ")
        cal.columnconfigure(1, weight=1)

        def step(r, num, text):
            ttk.Label(cal, text=num, style="Num.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 8), pady=5)
            ttk.Label(cal, text=text, justify="left").grid(row=r, column=1, sticky="w", pady=3)

        step(0, "1", "ตอนมินิเกมโผล่ กด F8 ถ่ายภาพ 2-3 ครั้ง\n(ตอนแถบเป็นสีขาว และตอนเป็นสีน้ำตาล)")
        self.snap_lbl = ttk.Label(cal, style="Accent.TLabel")
        self.snap_lbl.grid(row=0, column=2, padx=8)
        ttk.Button(cal, text="ล้างภาพ", command=self.clear_snaps).grid(row=0, column=3)

        step(1, "2", "เปิดหน้าสอบเทียบ แล้วลากเลือกพื้นที่\nและคลิกเลือกสีบนภาพนิ่ง")
        ttk.Button(cal, text="เปิดหน้าสอบเทียบ", style="Accent.TButton", command=self.open_calib).grid(
            row=1, column=2, columnspan=2, sticky="ew", padx=(8, 0))

        step(2, "3", "ดูผลที่ช่อง Preview ด้านบน แล้วลองทดสอบ")
        ttk.Button(cal, text="ทดสอบตรวจจับ", command=self.test_detect).grid(
            row=2, column=2, columnspan=2, sticky="ew", padx=(8, 0))

        chips = ttk.Frame(cal)
        chips.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.fish_sw, self.fish_hx = self.make_chip(chips, "ปลา")
        self.bar_sw, self.bar_hx = self.make_chip(chips, "แถบขาว")
        self.bar2_sw, self.bar2_hx = self.make_chip(chips, "แถบน้ำตาล")
        ttk.Button(chips, text="ล้างสีน้ำตาล", command=self.clear_bar2).pack(side="left")

        self.region_lbl = ttk.Label(cal, style="Muted.TLabel")
        self.region_lbl.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))

    # ---------- แท็บตั้งค่า
    def add_field(self, parent, row, key):
        label, typ, tip = FIELD_INFO[key]
        lb = ttk.Label(parent, text=label)
        lb.grid(row=row, column=0, sticky="w", pady=2)
        v = tk.StringVar(value=str(self.cfg[key]))
        self.vars[key], self.types[key] = v, typ
        en = ttk.Entry(parent, textvariable=v, width=8)
        en.grid(row=row, column=1, padx=(10, 0), pady=2)
        Tip(lb, tip)
        Tip(en, tip)

    def build_settings_tab(self, nb):
        st = ttk.Frame(nb, padding=10)
        nb.add(st, text="  ตั้งค่า  ")

        g1 = ttk.LabelFrame(st, text=" เหวี่ยงและเวลา ", padding=8)
        g1.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for i, k in enumerate(GROUP_TIMING):
            self.add_field(g1, i, k)

        g2 = ttk.LabelFrame(st, text=" การตามปลา ", padding=8)
        g2.grid(row=0, column=1, sticky="nsew")
        for i, k in enumerate(GROUP_TRACK):
            self.add_field(g2, i, k)
        ttk.Button(g2, text="รีเซ็ตเป็นค่าเริ่มต้น", command=self.reset_defaults).grid(
            row=len(GROUP_TRACK), column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Label(g2, text="เอาเมาส์ชี้ช่องต่างๆ เพื่ออ่านคำอธิบาย", style="Muted.TLabel").grid(
            row=len(GROUP_TRACK) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        g3 = ttk.LabelFrame(st, text=" ตัวเลือก ", padding=8)
        g3.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for i, (label, key, tip) in enumerate(CHECK_INFO):
            b = tk.BooleanVar(value=bool(self.cfg[key]))
            self.bool_vars[key] = b
            cb = ttk.Checkbutton(g3, text=label, variable=b)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 22), pady=1)
            Tip(cb, tip)

    # ---------- แท็บ Log
    def build_log_tab(self, nb):
        lg = ttk.Frame(nb, padding=6)
        nb.add(lg, text="  Log  ")
        self.logbox = tk.Text(lg, height=9, width=64, state="disabled", font=("Tahoma", 9), bg=DARK, fg=FG,
                              relief="flat", padx=8, pady=6, insertbackground=FG, highlightthickness=0)
        self.logbox.pack(fill="both", expand=True)
        for tag, color in (("err", RED), ("ok", GREEN), ("warn", AMBER), ("info", ACCENT), ("dim", MUTED)):
            self.logbox.tag_config(tag, foreground=color)

    # ---------- ตัวช่วย
    def log(self, msg):
        self.q.put(f"[{time.strftime('%H:%M:%S')}] {msg}")

    @staticmethod
    def log_tag(line):
        low = line.lower()
        if "error" in low or "ไม่ได้" in line or "ไม่สำเร็จ" in line:
            return "err"
        if "failsafe" in low or "ไม่เจอ" in line or "หมดเวลา" in line or "ไม่พบ" in line:
            return "warn"
        if "จบมินิเกม" in line or "บันทึก" in line or "เสร็จ" in line or "ถ่ายภาพแล้ว" in line:
            return "ok"
        if "รอบที่" in line:
            return "info"
        return "dim"

    def poll(self):
        if self.kicked:                           # ถูกระงับ/ลบ/หมดอายุ/ขาดการเชื่อมต่อ -> ออกจากระบบ
            msg, self.kicked = self.kicked, None
            self.stop()
            messagebox.showwarning("ออกจากระบบ", msg)
            self.logout_requested = True
            self.close()
            return
        while not self.q.empty():
            line = self.q.get()
            self.logbox.configure(state="normal")
            self.logbox.insert("end", line + "\n", self.log_tag(line))
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
            self.status_lbl.config(text=line[11:])
        running = bool(self.bot and self.bot.is_alive())
        text, color = PHASES[self.bot.phase if running else "idle"]
        self.chip.config(text=f"●  {text}", bg=color, fg=BG if color in (AMBER, ACCENT, GREEN) else "white")
        self.st_fish.config(text=str(self.catches))
        if running:
            s = int(time.time() - self.started_at)
            self.st_time.config(text=f"{s//3600:02d}:{s%3600//60:02d}:{s%60:02d}")
            self.st_cycle.config(text=str(self.bot.cycle))
        self.root.after(200, self.poll)

    def refresh_cal(self):
        x, y, w, h = self.cfg["region"]
        self.region_lbl.config(text=f"พื้นที่จับภาพ:  x={x}  y={y}  กว้าง={w}  สูง={h}")
        for sw, hx, key in ((self.fish_sw, self.fish_hx, "fish_color"),
                            (self.bar_sw, self.bar_hx, "bar_color"),
                            (self.bar2_sw, self.bar2_hx, "bar_color2")):
            c = self.cfg.get(key)
            sw.config(bg=rgb_hex(c) if c else "#000")
            hx.config(text=rgb_hex(c) if c else "ยังไม่ได้เลือก")

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

    def reset_defaults(self):
        for key, var in self.vars.items():
            var.set(str(DEFAULTS[key]))
        for key, b in self.bool_vars.items():
            b.set(bool(DEFAULTS[key]))
        self.log("รีเซ็ตค่าเป็นค่าเริ่มต้นแล้ว (กดบันทึกเพื่อยืนยัน)")

    # ---------- Preview
    def update_preview(self):
        running = bool(self.bot and self.bot.is_alive())
        if running:
            # ระหว่างบอททำงานไม่จับภาพซ้ำ (กันแย่ง CPU) แสดงตัวเลขสดจากบอทแทน
            self.preview_txt.config(text=self.bot.live or "กำลังทำงาน...", foreground=ACCENT)
            self.root.after(200, self.update_preview)
            return
        self.preview_txt.config(foreground=MUTED)
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
                self.preview_img.config(image=self.photo, text="", width=pil.width, height=pil.height)
                self.preview_txt.config(
                    text=f"ปลา: {'x=%.0f' % fc if fc is not None else 'ไม่เจอ'}   "
                         f"แถบ: {'x=%.0f' % bc if bc is not None else 'ไม่เจอ'}   "
                         f"(แดง=ปลา  เขียว=แถบขาว  เหลือง=แถบน้ำตาล)")
            except Exception as e:
                self.preview_txt.config(text=f"preview error: {e}")
        elif not self.preview_var.get():
            self.preview_img.config(image="", text="(เปิด Preview เพื่อดูภาพ)", width=64, height=3)
            self.preview_txt.config(text="")
        self.root.after(150, self.update_preview)

    # ---------- ภาพนิ่งสำหรับสอบเทียบ
    def snapshot(self):
        """ถูกเรียกจาก hotkey F8 (อยู่ใน thread ของ pynput)"""
        if self.calib_open:
            return
        try:
            img = ImageGrab.grab().convert("RGB")      # จอหลัก (พิกัดเริ่มที่ 0,0 เหมือนที่บอทใช้)
        except Exception as e:
            self.log(f"ถ่ายภาพไม่สำเร็จ: {e}")
            return
        self.snaps.append(img)
        if len(self.snaps) > self.MAX_SNAPS:
            self.snaps.pop(0)
        if winsound:
            try:
                winsound.Beep(1200, 60)
            except Exception:
                pass
        self.log(f"ถ่ายภาพแล้ว ({len(self.snaps)} ภาพ)")
        self.root.after(0, self.update_snap_lbl)

    def update_snap_lbl(self):
        self.snap_lbl.config(text=f"ภาพ {len(self.snaps)}/{self.MAX_SNAPS}")

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
        rect_item = canvas.create_rectangle(0, 0, 0, 0, outline=ACCENT, width=2)
        drag_item = canvas.create_rectangle(0, 0, 0, 0, outline=RED, width=2)
        loupe_item = canvas.create_image(W - 10, 10, anchor="ne")
        loupe_txt = canvas.create_text(W - 10, 195, anchor="ne", fill=AMBER, font=("Tahoma", 10), text="")

        # ---- แถบเครื่องมือ
        bar = tk.Frame(canvas, bg=PANEL, padx=10, pady=6, highlightthickness=1, highlightbackground=ACCENT)
        row1 = tk.Frame(bar, bg=PANEL)
        row1.pack()
        hint = tk.Label(bar, bg=PANEL, fg=AMBER, font=("Tahoma", 10))
        hint.pack(anchor="w", pady=(4, 0))

        def rb(text, val):
            tk.Radiobutton(row1, text=text, variable=mode, value=val, bg=PANEL, fg=FG,
                           selectcolor=PANEL2, activebackground=PANEL, activeforeground=ACCENT,
                           font=("Tahoma", 10, "bold"), highlightthickness=0).pack(side="left")

        def sw():
            l = tk.Label(row1, width=2, relief="solid", bd=1)
            l.pack(side="left", padx=(0, 10))
            return l

        def tbtn(text, cmd, **kw):
            b = tk.Button(row1, text=text, command=cmd, bg=PANEL2, fg=FG, activebackground=LINE,
                          activeforeground=FG, relief="flat", padx=8, **kw)
            b.pack(side="left")
            return b

        rb("① ลากพื้นที่", "region")
        rb("② สีปลา", "fish")
        sw_fish = sw()
        rb("③ สีแถบขาว", "bar")
        sw_bar = sw()
        rb("④ สีแถบน้ำตาล", "bar2")
        sw_bar2 = sw()

        tbtn("◀", lambda: step(-1))
        idx_lbl = tk.Label(row1, bg=PANEL, fg=FG, font=("Tahoma", 10))
        idx_lbl.pack(side="left", padx=6)
        tbtn("▶", lambda: step(1)).pack_configure(padx=(0, 10))
        tk.Label(row1, text="tol", bg=PANEL, fg=MUTED).pack(side="left")
        spin = tk.Spinbox(row1, from_=0, to=150, width=4, textvariable=self.vars["tolerance"],
                          command=lambda: render(), bg=PANEL2, fg=FG, buttonbackground=PANEL2,
                          insertbackground=FG, relief="flat")
        spin.pack(side="left", padx=(3, 10))
        spin.bind("<KeyRelease>", lambda e: render())
        tk.Checkbutton(row1, text="ดูผลจับสี", variable=overlay, command=lambda: render(),
                       bg=PANEL, fg=FG, selectcolor=PANEL2, activebackground=PANEL,
                       activeforeground=ACCENT, highlightthickness=0).pack(side="left", padx=(0, 10))
        done = tk.Button(row1, text="เสร็จ (Esc)", command=lambda: close(), bg="#16a34a", fg="white",
                         activebackground=GREEN, activeforeground="white", relief="flat", padx=10,
                         font=("Tahoma", 9, "bold"))
        done.pack(side="left")
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
            sw_bar2.config(bg=rgb_hex(c2) if c2 else PANEL2)

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
        self.st_cycle.config(text="0")
        self.st_time.config(text="00:00:00")
        self.bot = Bot(self.cfg, self.log, self.add_catch, self.on_finish)
        self.bot.start()
        self.btn.config(text="■  หยุด (F6)", style="Stop.TButton")

    def stop(self):
        if self.bot and self.bot.is_alive():
            self.bot.stop()
            self.log("กำลังหยุด...")

    def add_catch(self):
        self.catches += 1

    def on_finish(self):
        try:
            self.root.after(0, self._finished)
        except Exception:
            pass                       # หน้าต่างถูกปิดไปแล้ว (ออกจากระบบ/ปิดโปรแกรม)

    def _finished(self):
        self.btn.config(text="▶  เริ่ม (F6)", style="Go.TButton")
        self.log("หยุดการทำงานแล้ว")

    # ---------- บัญชี / เซิร์ฟเวอร์
    def heartbeat(self):
        """thread เบื้องหลัง: ถามเซิร์ฟเวอร์เป็นระยะว่าบัญชียังใช้งานได้ไหม"""
        fails = 0
        while not self.hb_stop.wait(HEARTBEAT_SECS):
            try:
                self.api.me()
                fails = 0
            except ClientError as e:
                if e.status in (401, 403):            # หมดอายุ / ถูกลบ / ถูกระงับ
                    self.kicked = e.message
                    return
                fails += 1                            # ต่อเซิร์ฟเวอร์ไม่ได้ชั่วคราว ให้โอกาสหลายครั้ง
                self.log(f"เช็คบัญชีกับเซิร์ฟเวอร์ไม่ได้ ({fails}/{OFFLINE_GRACE})")
                if fails >= OFFLINE_GRACE:
                    self.kicked = "ขาดการเชื่อมต่อเซิร์ฟเวอร์นานเกินไป กรุณาเข้าสู่ระบบใหม่"
                    return

    def open_account(self):
        AccountDialog(self.root, self.api, self.info, self.log)

    def logout(self):
        if self.bot and self.bot.is_alive():
            if not messagebox.askyesno("ออกจากระบบ", "บอทกำลังทำงานอยู่ ต้องการหยุดและออกจากระบบหรือไม่?"):
                return
        self.logout_requested = True
        api = self.api
        if api is not None:
            def bye():
                try:
                    api.logout()                      # บอกเซิร์ฟเวอร์ให้ยกเลิก token
                except Exception:
                    pass
            threading.Thread(target=bye, daemon=True).start()
        self.close()

    def close(self):
        self.hb_stop.set()
        self.stop()
        try:
            self.hk.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    """ต้องล็อกอินผ่านเซิร์ฟเวอร์ก่อนถึงจะเปิดหน้าต่างหลักได้ ออกจากระบบแล้วกลับมาหน้าล็อกอินอีกครั้ง"""
    while True:
        login = LoginWindow().run()
        if not login:
            break                                     # ปิดหน้าล็อกอิน = ออกจากโปรแกรม
        api, info = login
        root = tk.Tk()
        app = App(root, api, info)
        root.mainloop()
        if not app.logout_requested:
            break


if __name__ == "__main__":
    main()