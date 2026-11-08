"""
main.py - ตัวเซิร์ฟเวอร์ (FastAPI) รับคำขอ HTTP จากแอปแล้วเรียกฟังก์ชันใน service.py

รัน:      uvicorn main:app --host 0.0.0.0 --port 8000
หรือ:     python main.py
ลองยิง API ผ่านหน้าเว็บ:  http://127.0.0.1:8000/docs   (FastAPI สร้างหน้านี้ให้อัตโนมัติ)
"""
import sys
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database
import service
import sheets
from service import ApiError


@asynccontextmanager
async def lifespan(_app):
    database.init_db()                                  # สร้างตารางถ้ายังไม่มี
    service.set_change_hook(sheets.sync.request)        # ข้อมูลผู้ใช้เปลี่ยน -> ขอซิงค์ Google Sheet
    sheets.sync.start()
    if not sheets.sync.enabled:
        print("[sheets] ปิดอยู่ (ยังไม่ได้ตั้งค่า sheet_webhook_url) ดู README ขั้นตอน Google Sheet")
    yield


app = FastAPI(title="Fisch Macro Auth API", lifespan=lifespan)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    # ทุก error ส่งกลับเป็น JSON รูปแบบเดียวกัน {"detail": "ข้อความ"} ให้แอปอ่านง่าย
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


# ---------------------------------------------------------------- รูปแบบข้อมูลที่รับเข้ามา
class RegisterBody(BaseModel):
    username: str
    password: str
    nickname: str
    birthday: str            # YYYY-MM-DD


class LoginBody(BaseModel):
    username: str
    password: str


class ResetBody(BaseModel):
    username: str = ""       # ถ้าไม่ใส่ จะค้นหาด้วย nickname + birthday
    birthday: str
    nickname: str
    new_password: str


class ChangePwBody(BaseModel):
    old_password: str
    new_password: str


class ActiveBody(BaseModel):
    active: bool


class AdminResetBody(BaseModel):
    new_password: str = ""   # ว่าง = สุ่มให้


# ---------------------------------------------------------------- ตัวช่วยตรวจสิทธิ์ (dependency)
def get_token(authorization: str = Header(default="")) -> str:
    """อ่าน token จากหัว HTTP  Authorization: Bearer <token>"""
    if not authorization.lower().startswith("bearer "):
        raise ApiError(401, "ต้องล็อกอินก่อน")
    return authorization[7:].strip()


def current_user(token: str = Depends(get_token)):
    return service.current_user(token)


def admin_user(user: dict = Depends(current_user)):
    if user["role"] != "admin":
        raise ApiError(403, "เฉพาะผู้ดูแลระบบเท่านั้น")
    return user


# ---------------------------------------------------------------- เส้นทางสาธารณะ (ไม่ต้องล็อกอิน)
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/register", status_code=201)
def register(body: RegisterBody):
    return service.register(body.username, body.password, body.nickname, body.birthday)


@app.post("/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else ""
    return service.login(body.username, body.password, ip)


@app.post("/password/reset")
def password_reset(body: ResetBody):
    return service.reset_password(body.username, body.birthday, body.nickname, body.new_password)


# ---------------------------------------------------------------- ต้องล็อกอิน
@app.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@app.post("/logout")
def logout(token: str = Depends(get_token)):
    service.logout(token)
    return {"ok": True}


@app.post("/change-password")
def change_password(body: ChangePwBody, token: str = Depends(get_token),
                    user: dict = Depends(current_user)):
    return service.change_password(user["id"], token, body.old_password, body.new_password)


# ---------------------------------------------------------------- เฉพาะผู้ดูแล
@app.get("/admin/users")
def admin_users(_admin: dict = Depends(admin_user)):
    return service.list_users()


@app.post("/admin/users/{user_id}/active")
def admin_set_active(user_id: int, body: ActiveBody, admin: dict = Depends(admin_user)):
    return service.set_active(admin["id"], user_id, body.active)


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, body: AdminResetBody, _admin: dict = Depends(admin_user)):
    return service.admin_reset_password(user_id, body.new_password)


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: dict = Depends(admin_user)):
    return service.delete_user(admin["id"], user_id)


@app.post("/admin/sync-sheet")
def admin_sync_sheet(_admin: dict = Depends(admin_user)):
    ok, message = sheets.sync.push_now()
    return {"ok": ok, "message": message, "enabled": sheets.sync.enabled}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
