"""
test_service.py - ชุดทดสอบอัตโนมัติสำหรับ service.py และ database.py
ทดสอบ: สมัคร, ล็อกอิน, เปลี่ยนรหัส, ลืมรหัส, แอดมินระงับ/ลบ, และการ export ไปยัง Google Sheet
"""
import os
import sys

# ใช้ฐานข้อมูลทดสอบในหน่วยความจำหรือไฟล์ชั่วคราว
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_app.db")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
os.environ["FISCH_DB"] = TEST_DB

import database
import service
from service import ApiError


def run_tests():
    print("เริ่มการทดสอบ...")
    database.init_db()

    # 1. ทดสอบสมัครสมาชิกคนแรก (ต้องได้ role = admin)
    u1 = service.register("admin_user", "password123", "นายแอดมิน", "1995-05-15")
    assert u1["username"] == "admin_user"
    assert u1["role"] == "admin", f"Expected admin, got {u1['role']}"
    print("[PASS] สมัครสมาชิกคนแรกเป็น admin")

    # 2. ทดสอบสมัครซ้ำ (ต้องได้ 409)
    try:
        service.register("admin_user", "password123", "แอดมินอีกคน", "1995-05-15")
        assert False, "ควรแจ้งว่า username ซ้ำ"
    except ApiError as e:
        assert e.status == 409
    print("[PASS] ป้องกันชื่อผู้ใช้ซ้ำ")

    # 3. ทดสอบสมัครคนที่สอง (ต้องได้ role = user)
    u2 = service.register("regular_user", "pass45678", "น้องยูสเซอร์", "2000-01-01")
    assert u2["role"] == "user"
    print("[PASS] สมัครสมาชิกคนที่สองเป็น user")

    # 4. ทดสอบล็อกอินรหัสผิด
    try:
        service.login("regular_user", "wrong_password")
        assert False, "ควรล็อกอินไม่ผ่าน"
    except ApiError as e:
        assert e.status == 401
    print("[PASS] ปฏิเสธรหัสผ่านผิด")

    # 5. ทดสอบล็อกอินสำเร็จ
    login_res = service.login("regular_user", "pass45678")
    assert "token" in login_res
    token = login_res["token"]
    print("[PASS] ล็อกอินสำเร็จและได้ token")

    # 6. ทดสอบ current_user ด้วย token
    me = service.current_user(token)
    assert me["username"] == "regular_user"
    print("[PASS] ดึงข้อมูลผู้ใช้ปัจจุบัน (current_user) สำเร็จ")

    # 7. ทดสอบส่งออกแถวสำหรับ Google Sheet
    headers, rows = service.export_users_rows()
    assert headers == service.SHEET_HEADERS
    assert len(rows) == 2
    # ตรวจสอบว่าไม่มีรหัสผ่านหลุดไปใน Sheet
    for r in rows:
        assert "password123" not in r
        assert "pass45678" not in r
    print("[PASS] export_users_rows ปลอดภัยและถูกต้อง")

    # 8. ทดสอบระงับผู้ใช้โดย admin
    service.set_active(u1["id"], u2["id"], False)
    try:
        service.current_user(token)
        assert False, "บัญชีถูกระงับต้องเข้าใช้งานไม่ได้"
    except ApiError as e:
        assert e.status == 403
    print("[PASS] ระงับบัญชีผู้ใช้สำเร็จ")

    # ปลดระงับ
    service.set_active(u1["id"], u2["id"], True)
    me_again = service.current_user(token)
    assert me_again["username"] == "regular_user"
    print("[PASS] ปลดระงับสำเร็จ")

    # 9. ทดสอบลืมรหัสผ่านด้วย nickname + birthday (ไม่ใส่ username)
    service.reset_password(username="", birthday="2000-01-01", nickname="น้องยูสเซอร์", new_password="new_password_999")
    # ลองล็อกอินด้วยรหัสผ่านใหม่
    res_new = service.login("regular_user", "new_password_999")
    assert "token" in res_new
    print("[PASS] ลืมรหัสผ่านด้วย nickname + birthday สำเร็จ (ไม่ต้องใส่ username)")

    # 10. ทดสอบลืมรหัสผ่านด้วย nickname + birthday + username
    service.reset_password(username="admin_user", birthday="1995-05-15", nickname="นายแอดมิน", new_password="admin_new_pass")
    res_admin = service.login("admin_user", "admin_new_pass")
    assert "token" in res_admin
    print("[PASS] ลืมรหัสผ่านด้วย username + nickname + birthday สำเร็จ")

    # ทำความสะอาดไฟล์ db ทดสอบ
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except Exception:
            pass

    print("\nผ่านทุกการทดสอบ!")


if __name__ == "__main__":
    run_tests()
