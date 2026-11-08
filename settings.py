"""
settings.py - โหลดค่าตั้งค่าการเชื่อมต่อ Google Sheet จาก settings.json หรือ Environment Variables
"""
import json
import os

from paths import app_dir

BASE_DIR = app_dir()
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

SHEET_WEBHOOK_URL = os.environ.get("SHEET_WEBHOOK_URL", "")
SHEET_SECRET = os.environ.get("SHEET_SECRET", "")

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            SHEET_WEBHOOK_URL = data.get("sheet_webhook_url", SHEET_WEBHOOK_URL)
            SHEET_SECRET = data.get("sheet_secret", SHEET_SECRET)
    except Exception as e:
        print(f"[settings] ไม่สามารถอ่านไฟล์ {SETTINGS_FILE}: {e}")
