"""
security.py - จัดการแฮชรหัสผ่านและการสร้าง token สำหรับเซสชัน
- แฮชรหัสผ่านด้วย PBKDF2-HMAC-SHA256 (200,000 รอบ) พร้อม salt สุ่ม
- สร้างและแฮช session token
"""
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """แปลงรหัสผ่านเป็นค่าแฮช พร้อมสุ่ม salt เก็บในรูปแบบ: pbkdf2_sha256$iterations$salt_hex$hash_hex"""
    salt = secrets.token_bytes(SALT_BYTES)
    pw_bytes = password.encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", pw_bytes, salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """ตรวจว่ารหัสผ่านตรงกับแฮชที่บันทึกไว้หรือไม่"""
    try:
        parts = hashed.split("$")
        if len(parts) == 4 and parts[0] == ALGORITHM:
            _, iters_str, salt_hex, key_hex = parts
            iters = int(iters_str)
            salt = bytes.fromhex(salt_hex)
            expected_key = bytes.fromhex(key_hex)
            actual_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
            return hmac.compare_digest(actual_key, expected_key)
        if ":" in hashed:
            salt_hex, key_hex = hashed.split(":", 1)
            salt = bytes.fromhex(salt_hex)
            actual_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
            return hmac.compare_digest(actual_key, bytes.fromhex(key_hex))
        return False
    except Exception:
        return False


# ค่า Dummy Hash สำหรับป้องกัน Timing Attack ตอนที่หาชื่อผู้ใช้ไม่พบ
DUMMY_HASH = hash_password("dummy_password_for_timing_safety")


def new_token() -> str:
    """สร้าง token สุ่มสำหรับเซสชัน (ความยาว 32 bytes สุ่ม แบบ URL-safe)"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """แฮช token ด้วย SHA-256 เพื่อเก็บลงฐานข้อมูล (ไม่เก็บ token จริง)"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
