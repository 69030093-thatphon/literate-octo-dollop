"""
database.py - เชื่อมต่อและสร้างตารางฐานข้อมูล (SQLite)

SQLite = ฐานข้อมูลที่เก็บเป็นไฟล์เดียว (app.db) ไม่ต้องติดตั้งเซิร์ฟเวอร์ฐานข้อมูลเพิ่ม
เหมาะกับโปรเจกต์เรียนรู้ ภาษา SQL ที่ใช้ตรงนี้ใช้ได้เกือบเหมือนกันกับ MySQL / PostgreSQL
เปิดดูข้อมูลในไฟล์ app.db ได้ด้วยโปรแกรมฟรี "DB Browser for SQLite"
"""
import os
import sqlite3
from contextlib import contextmanager

from paths import app_dir

DB_PATH = os.environ.get("FISCH_DB", os.path.join(app_dir(), "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,      -- เลขประจำตัว (int) เพิ่มเองทีละ 1
    username           TEXT    NOT NULL UNIQUE COLLATE NOCASE,  -- ชื่อผู้ใช้ ห้ามซ้ำ (ไม่สนตัวพิมพ์ใหญ่เล็ก)
    password_hash      TEXT    NOT NULL,                        -- แฮชของรหัสผ่าน (ไม่ใช่รหัสจริง)
    nickname           TEXT    NOT NULL,                        -- ชื่อเล่น / ชื่อ (ข้อความ)
    birthday           TEXT    NOT NULL,                        -- วันเกิด เก็บเป็น 'YYYY-MM-DD'
    role               TEXT    NOT NULL DEFAULT 'user',         -- 'admin' หรือ 'user'
    active             INTEGER NOT NULL DEFAULT 1,              -- 1 = ใช้งานได้, 0 = ถูกระงับ
    failed_count       INTEGER NOT NULL DEFAULT 0,              -- ใส่รหัสผ่านผิดติดกันกี่ครั้ง
    locked_until       REAL    NOT NULL DEFAULT 0,              -- ล็อกการล็อกอินถึงเวลาไหน (epoch วินาที)
    reset_failed_count INTEGER NOT NULL DEFAULT 0,              -- ยืนยันตัวตนตอนลืมรหัสผิดกี่ครั้ง
    reset_locked_until REAL    NOT NULL DEFAULT 0,
    created_at         REAL    NOT NULL,                        -- เวลาที่สมัคร
    last_login         REAL                                     -- เวลาที่ล็อกอินล่าสุด
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,                                -- แฮชของ token (ไม่เก็บ token จริง)
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL    NOT NULL,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS login_logs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ok       INTEGER NOT NULL,                                  -- 1 = สำเร็จ, 0 = ไม่สำเร็จ
    ip       TEXT,
    at       REAL    NOT NULL
);
"""


@contextmanager
def db():
    """ใช้แบบ  with db() as c:  -> ถ้าจบปกติ commit ให้เอง ถ้า error จะ rollback"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row            # อ่านคอลัมน์ด้วยชื่อได้ เช่น row["username"]
    conn.execute("PRAGMA foreign_keys = ON")   # ให้ ON DELETE CASCADE ทำงาน
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(SCHEMA)
