Build FischMacro.exe ด้วย GitHub Actions (ไม่ต้องมีเครื่อง Windows)

1. สมัคร/ล็อกอิน github.com แล้วสร้าง repository ใหม่ (Private ก็ได้)
2. อัปโหลดไฟล์ทั้งหมดในโฟลเดอร์นี้ขึ้นไป รวมโฟลเดอร์ .github ด้วย
   (โฟลเดอร์ขึ้นต้นด้วยจุดจะถูกซ่อนใน Finder: กด Cmd+Shift+. เพื่อให้เห็น)
   วิธีง่ายสุด: ใน repo กด Add file > Upload files แล้วลากทั้งหมดใส่
3. ไปแท็บ Actions > "Build FischMacro.exe" > Run workflow
   (หรือ push ขึ้น branch main มันจะรันเอง)
4. รอประมาณ 2-4 นาที เปิดรอบที่รันเสร็จ เลื่อนลงไปหัวข้อ Artifacts
   แล้วโหลด FischMacro-windows (เป็น zip ข้างในมี FischMacro.exe)

หมายเหตุ: Windows Defender อาจเตือนเพราะ exe ไม่มีลายเซ็นและมีโค้ดจำลองคีย์บอร์ด/เมาส์
