"""
view_database.py - โปรแกรมเปิดดูฐานข้อมูล SQLite (app.db) แบบหน้าต่าง GUI
ใช้สำหรับพรีเซนต์ให้อาจารย์เห็นโครงสร้างตาราง ข้อมูลผู้ใช้ แฮชรหัสผ่าน และประวัติการล็อกอิน
"""
import os
import sqlite3
import sys
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

# ตั้งค่า encoding ใน Windows console
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

from paths import app_dir

BASE_DIR = app_dir()
DB_PATH = os.path.join(BASE_DIR, "app.db")

import database

BG = "#0f172a"
PANEL = "#1e293b"
PANEL2 = "#334155"
LINE = "#475569"
FG = "#e2e8f0"
MUTED = "#94a3b8"
ACCENT = "#22d3ee"
GREEN = "#22c55e"
DARK = "#0b1220"
FONT = ("Tahoma", 9)
FONT_B = ("Tahoma", 9, "bold")


class DatabaseViewer:
    def __init__(self, root):
        self.root = root
        root.title("ฐานข้อมูลระบบสมาชิก (SQLite: app.db) - สำหรับพรีเซนต์อาจารย์")
        root.geometry("980x620")
        root.minsize(800, 500)
        root.configure(bg=BG)

        self.setup_style()

        # Header
        head = ttk.Frame(root, style="Head.TFrame", padding=(14, 10))
        head.pack(fill="x")
        ttk.Label(head, text="ฐานข้อมูล SQLite (app.db)", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"  [ไฟล์: {DB_PATH}]", style="HeadMuted.TLabel").pack(side="left", pady=(3, 0))

        btn_refresh = ttk.Button(head, text="🔄 รีเฟรชข้อมูล", style="Accent.TButton", command=self.refresh_all)
        btn_refresh.pack(side="right")

        # Status banner
        self.status_var = tk.StringVar(value="กำลังตรวจสอบฐานข้อมูล...")
        status_bar = ttk.Frame(root, padding=(14, 4))
        status_bar.pack(fill="x")
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")

        # Tabs
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=12, pady=8)

        # Tab 1: ตาราง users
        self.build_users_tab()

        # Tab 2: ตาราง login_logs
        self.build_logs_tab()

        # Tab 3: ตาราง sessions
        self.build_sessions_tab()

        # Tab 4: SQL Query Console
        self.build_sql_tab()

        self.refresh_all()

    def setup_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, font=FONT, fieldbackground=PANEL2,
                    bordercolor=LINE, focuscolor=BG, troughcolor=PANEL)
        s.configure("TFrame", background=BG)
        s.configure("Head.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Title.TLabel", background=PANEL, foreground=ACCENT, font=("Tahoma", 14, "bold"))
        s.configure("HeadMuted.TLabel", background=PANEL, foreground=MUTED, font=("Tahoma", 9))
        s.configure("Accent.TButton", background=ACCENT, foreground=BG, font=FONT_B, relief="flat", padding=(10, 4))
        s.map("Accent.TButton", background=[("active", "#67e8f9")])
        s.configure("TButton", background=PANEL2, foreground=FG, relief="flat", padding=(8, 4))
        s.map("TButton", background=[("active", LINE)])
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 5), font=FONT_B)
        s.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", ACCENT)])
        s.configure("Treeview", background=DARK, fieldbackground=DARK, foreground=FG, rowheight=24)
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])
        s.configure("Treeview.Heading", background=PANEL2, foreground=FG, relief="flat", font=FONT_B)
        s.map("Treeview.Heading", background=[("active", LINE)])

    def get_conn(self):
        database.init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------- Tab 1: ตาราง users
    def build_users_tab(self):
        t = ttk.Frame(self.nb, padding=10)
        self.nb.add(t, text=" ตาราง users (ผู้ใช้งาน) ")

        desc = ("ตารางหลักที่เก็บข้อมูลผู้ใช้: id (PK), username, nickname, birthday, role, active, "
                "และ password_hash (แฮชด้วย PBKDF2 200,000 รอบ + salt ไม่เก็บรหัสจริง)")
        ttk.Label(t, text=desc, style="Muted.TLabel", wraplength=940).pack(anchor="w", pady=(0, 6))

        cols = [
            ("id", "ID", 45),
            ("username", "ชื่อผู้ใช้", 110),
            ("nickname", "ชื่อเล่น", 90),
            ("birthday", "วันเกิด", 90),
            ("role", "สิทธิ์", 70),
            ("active", "สถานะ", 65),
            ("created_at", "วันที่สมัคร", 130),
            ("last_login", "ล็อกอินล่าสุด", 130),
            ("password_hash", "Password Hash (PBKDF2)", 240),
        ]
        self.users_tree = ttk.Treeview(t, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width in cols:
            self.users_tree.heading(key, text=title)
            self.users_tree.column(key, width=width, anchor="w")

        sc_y = ttk.Scrollbar(t, orient="vertical", command=self.users_tree.yview)
        sc_x = ttk.Scrollbar(t, orient="horizontal", command=self.users_tree.xview)
        self.users_tree.configure(yscrollcommand=sc_y.set, xscrollcommand=sc_x.set)

        sc_y.pack(side="right", fill="y")
        sc_x.pack(side="bottom", fill="x")
        self.users_tree.pack(fill="both", expand=True)

    # ------------------------------------------------------------- Tab 2: ตาราง login_logs
    def build_logs_tab(self):
        t = ttk.Frame(self.nb, padding=10)
        self.nb.add(t, text=" ตาราง login_logs (ประวัติล็อกอิน) ")

        desc = "บันทึกประวัติการพยายามล็อกอินทุกครั้ง (สำเร็จหรือไม่, IP, เวลา) ใช้ตรวจสอบความปลอดภัยและ Audit"
        ttk.Label(t, text=desc, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        cols = [
            ("id", "ID", 60),
            ("username", "ชื่อผู้ใช้ที่พยายามล็อกอิน", 180),
            ("ok", "ผลลัพธ์", 120),
            ("ip", "IP Address", 140),
            ("at", "วันเวลา", 180),
        ]
        self.logs_tree = ttk.Treeview(t, columns=[c[0] for c in cols], show="headings")
        for key, title, width in cols:
            self.logs_tree.heading(key, text=title)
            self.logs_tree.column(key, width=width, anchor="w")

        sc_y = ttk.Scrollbar(t, orient="vertical", command=self.logs_tree.yview)
        self.logs_tree.configure(yscrollcommand=sc_y.set)
        sc_y.pack(side="right", fill="y")
        self.logs_tree.pack(fill="both", expand=True)

    # ------------------------------------------------------------- Tab 3: ตาราง sessions
    def build_sessions_tab(self):
        t = ttk.Frame(self.nb, padding=10)
        self.nb.add(t, text=" ตาราง sessions (โทเคนที่กำลังออนไลน์) ")

        desc = "เก็บโทเคนเซสชันของผู้ใช้ที่ล็อกอินอยู่ (เก็บเฉพาะค่า SHA-256 Hash ของโทเคน) มีวันหมดอายุ 12 ชม."
        ttk.Label(t, text=desc, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        cols = [
            ("user_id", "User ID", 80),
            ("username", "ชื่อผู้ใช้", 140),
            ("token_hash", "Token Hash (SHA-256)", 320),
            ("expires_at", "หมดอายุเมื่อ", 160),
            ("created_at", "สร้างเมื่อ", 160),
        ]
        self.sessions_tree = ttk.Treeview(t, columns=[c[0] for c in cols], show="headings")
        for key, title, width in cols:
            self.sessions_tree.heading(key, text=title)
            self.sessions_tree.column(key, width=width, anchor="w")

        sc_y = ttk.Scrollbar(t, orient="vertical", command=self.sessions_tree.yview)
        self.sessions_tree.configure(yscrollcommand=sc_y.set)
        sc_y.pack(side="right", fill="y")
        self.sessions_tree.pack(fill="both", expand=True)

    # ------------------------------------------------------------- Tab 4: SQL Query Console
    def build_sql_tab(self):
        t = ttk.Frame(self.nb, padding=10)
        self.nb.add(t, text=" ⚡ รันคำสั่ง SQL สด (Query Console) ")

        ttk.Label(t, text="พิมพ์คำสั่ง SQL เช่น: SELECT id, username, nickname, birthday, role FROM users;",
                  style="Muted.TLabel").pack(anchor="w")

        box_frame = ttk.Frame(t)
        box_frame.pack(fill="x", pady=(6, 4))
        self.sql_entry = tk.Text(box_frame, height=3, bg=DARK, fg=FG, insertbackground=FG,
                                 font=("Consolas", 10), padx=8, pady=6)
        self.sql_entry.pack(side="left", fill="x", expand=True)
        self.sql_entry.insert("1.0", "SELECT id, username, nickname, birthday, role, active FROM users;")

        btn_run = ttk.Button(box_frame, text="▶ รัน SQL", style="Accent.TButton", command=self.run_custom_sql)
        btn_run.pack(side="left", padx=(8, 0), fill="y")

        self.sql_tree_frame = ttk.Frame(t)
        self.sql_tree_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.sql_tree = None

    def run_custom_sql(self):
        query = self.sql_entry.get("1.0", "end").strip()
        if not query:
            return
        conn = self.get_conn()
        if not conn:
            messagebox.showerror("ไม่พบฐานข้อมูล", "ยังไม่มีไฟล์ app.db ให้เปิด backend ก่อน")
            return
        try:
            with conn:
                cur = conn.execute(query)
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description] if cur.description else []

            # เคลียร์และสร้าง treeview ใหม่ตามคอลัมน์ที่ query คืนมา
            for w in self.sql_tree_frame.winfo_children():
                w.destroy()

            if not cols:
                ttk.Label(self.sql_tree_frame, text=f"คำสั่งทำงานสำเร็จ (แถวที่ได้รับผลกระทบ: {cur.rowcount})",
                          foreground=GREEN, font=FONT_B).pack(pady=20)
                return

            tree = ttk.Treeview(self.sql_tree_frame, columns=cols, show="headings")
            for col in cols:
                tree.heading(col, text=col)
                tree.column(col, width=120, anchor="w")

            for r in rows:
                tree.insert("", "end", values=[str(val) if val is not None else "NULL" for val in r])

            sc_y = ttk.Scrollbar(self.sql_tree_frame, orient="vertical", command=tree.yview)
            sc_x = ttk.Scrollbar(self.sql_tree_frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=sc_y.set, xscrollcommand=sc_x.set)
            sc_y.pack(side="right", fill="y")
            sc_x.pack(side="bottom", fill="x")
            tree.pack(fill="both", expand=True)

        except Exception as e:
            messagebox.showerror("SQL Error", str(e))

    # ------------------------------------------------------------- โหลดข้อมูล
    @staticmethod
    def fmt_ts(ts):
        if not ts:
            return "-"
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)

    def refresh_all(self):
        conn = self.get_conn()
        if not conn:
            self.status_var.set("❌ ยังไม่พบไฟล์ app.db (ให้เปิด start_backend.bat ก่อนอย่างน้อย 1 ครั้ง)")
            return

        try:
            with conn:
                # 1. users
                u_rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
                self.users_tree.delete(*self.users_tree.get_children())
                for r in u_rows:
                    self.users_tree.insert("", "end", values=(
                        r["id"], r["username"], r["nickname"], r["birthday"],
                        "ผู้ดูแล (admin)" if r["role"] == "admin" else "ผู้ใช้ทั่วไป",
                        "ใช้งานได้" if r["active"] else "ถูกระงับ",
                        self.fmt_ts(r["created_at"]),
                        self.fmt_ts(r["last_login"]),
                        r["password_hash"],
                    ))

                # 2. logs
                l_rows = conn.execute("SELECT * FROM login_logs ORDER BY id DESC LIMIT 100").fetchall()
                self.logs_tree.delete(*self.logs_tree.get_children())
                for r in l_rows:
                    self.logs_tree.insert("", "end", values=(
                        r["id"], r["username"],
                        "สำเร็จ ✅" if r["ok"] else "ไม่สำเร็จ ❌",
                        r["ip"] or "-",
                        self.fmt_ts(r["at"]),
                    ))

                # 3. sessions
                s_rows = conn.execute(
                    "SELECT s.token_hash, s.user_id, s.expires_at, s.created_at, u.username "
                    "FROM sessions s LEFT JOIN users u ON u.id = s.user_id ORDER BY s.created_at DESC"
                ).fetchall()
                self.sessions_tree.delete(*self.sessions_tree.get_children())
                for r in s_rows:
                    self.sessions_tree.insert("", "end", values=(
                        r["user_id"], r["username"] or "-",
                        r["token_hash"],
                        self.fmt_ts(r["expires_at"]),
                        self.fmt_ts(r["created_at"]),
                    ))

                self.status_var.set(f"✅ เชื่อมต่อฐานข้อมูลสำเร็จ | ผู้ใช้ทั้งหมด: {len(u_rows)} คน | ล็อกอินล่าสุด: {len(l_rows)} ครั้ง | เซสชันที่ทำงานอยู่: {len(s_rows)}")

        except Exception as e:
            self.status_var.set(f"⚠️ เกิดข้อผิดพลาดในการอ่านข้อมูล: {e}")


def main():
    root = tk.Tk()
    app = DatabaseViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
