"""
paths.py - หาโฟลเดอร์สำหรับเก็บไฟล์ข้อมูล (app.db, settings.json, fisch_client.json ฯลฯ)

- รันด้วย python ตามปกติ  -> โฟลเดอร์ของซอร์สโค้ด
- รันเป็น .exe (PyInstaller) -> โฟลเดอร์เดียวกับไฟล์ .exe
  (ถ้าใช้ __file__ ตอนเป็น exe แบบ onefile จะชี้ไปโฟลเดอร์ temp ที่ถูกลบทิ้งทุกครั้ง ข้อมูลจะหาย)
"""
import os
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
