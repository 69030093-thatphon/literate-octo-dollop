"""
sheets.py - ส่งข้อมูลผู้ใช้ทั้งหมดไปแสดงใน Google Sheet

วิธีทำงาน:
  backend --(HTTP POST + JSON)--> Google Apps Script (Web app) --> เขียนลงชีต

ทำไมใช้ Apps Script: ไม่ต้องสร้าง Service Account / ไฟล์กุญแจ ตั้งค่าง่าย เหมาะกับโปรเจกต์เรียนรู้
(ถ้าต้องการแบบทางการ ใช้ไลบรารี gspread + Service Account ก็ได้ ดูใน README)

ทุกครั้งที่ข้อมูลผู้ใช้เปลี่ยน (สมัคร / ล็อกอิน / ระงับ / ลบ / รีเซ็ตรหัส) จะ "ขอซิงค์"
แล้วรอ 2 วินาทีรวมคำขอที่มาถี่ๆ ให้เป็นครั้งเดียว ก่อนส่งข้อมูลทั้งตารางไปเขียนทับในชีต

หมายเหตุความเป็นส่วนตัว: ส่งเฉพาะ id, ชื่อผู้ใช้, ชื่อเล่น, วันเกิด, สิทธิ์, สถานะ, เวลา
ไม่ส่งรหัสผ่าน/แฮช เด็ดขาด
"""
import sys
import threading
import time
from datetime import datetime

if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

import requests

import service
import settings

DEBOUNCE_SECS = 2.0


class SheetSync:
    def __init__(self):
        self._event = threading.Event()
        self._started = False
        self.last_status = "ยังไม่เคยซิงค์"

    @property
    def enabled(self):
        return bool(settings.SHEET_WEBHOOK_URL)

    def start(self):
        """เรียกตอนเปิดเซิร์ฟเวอร์ จะเริ่ม thread เบื้องหลัง และซิงค์ครั้งแรกทันที"""
        if self._started or not self.enabled:
            return
        self._started = True
        threading.Thread(target=self._loop, daemon=True).start()
        self.request()

    def request(self):
        """ขอซิงค์ (ไม่รอผล) ใช้เป็น hook เมื่อข้อมูลผู้ใช้เปลี่ยน"""
        if self.enabled:
            self._event.set()

    def _loop(self):
        while True:
            self._event.wait()
            time.sleep(DEBOUNCE_SECS)     # รวมคำขอที่มาถี่ๆ
            self._event.clear()
            self.push_now()

    def push_now(self):
        """ส่งข้อมูลทั้งตารางไปที่ Google Sheet ทันที คืน (สำเร็จไหม, ข้อความ)"""
        if not self.enabled:
            return False, "ยังไม่ได้ตั้งค่า sheet_webhook_url ใน settings.json"
        headers, rows = service.export_users_rows()
        stamp = datetime.now(service.TZ).strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "secret": settings.SHEET_SECRET,
            "headers": headers,
            "rows": rows,
            "text_columns": service.SHEET_TEXT_COLUMNS,
            "synced_at": stamp,
        }
        try:
            r = requests.post(settings.SHEET_WEBHOOK_URL, json=payload, timeout=30)
            try:
                data = r.json()
            except ValueError:
                data = None
            if r.status_code == 200 and isinstance(data, dict) and data.get("ok"):
                ok, msg = True, f"ซิงค์สำเร็จ {len(rows)} แถว"
            elif data is None:
                ok, msg = False, ("Google ตอบกลับไม่ใช่ JSON: ตรวจว่า Deploy เป็น 'Anyone' "
                                  "และใช้ URL ที่ลงท้ายด้วย /exec")
            else:
                ok, msg = False, f"Apps Script ตอบ: {data.get('error', data)}"
        except requests.exceptions.RequestException as e:
            ok, msg = False, f"เรียก Google ไม่สำเร็จ ({e.__class__.__name__})"
        self.last_status = f"[{stamp}] {msg}"
        print("[sheets]", self.last_status)
        return ok, msg


sync = SheetSync()
