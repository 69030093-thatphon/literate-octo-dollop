// =====================================================================
// โค้ดนี้ "วางใน Google Sheet" (ไม่ได้รันบนเครื่องคุณ)
//   Google Sheet > เมนู ส่วนขยาย (Extensions) > Apps Script > วางโค้ดนี้ทั้งหมด
//   แก้ SECRET ให้เป็นรหัสลับของคุณเอง แล้วกด Deploy > New deployment
//   ประเภท: Web app / Execute as: Me / Who has access: Anyone
//   คัดลอก URL ที่ลงท้ายด้วย /exec ไปใส่ใน backend/settings.json (sheet_webhook_url)
// =====================================================================

const SECRET = "เปลี่ยนเป็นรหัสลับของคุณ";   // ต้องตรงกับ sheet_secret ใน settings.json
const SHEET_NAME = "users";                  // ชื่อแท็บที่จะเขียนข้อมูล (ไม่มีจะสร้างให้)

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRET) {
      return reply({ ok: false, error: "unauthorized" });
    }

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    const cols = data.headers.length;
    const total = data.rows.length + 1;

    sh.clear();

    // บังคับบางคอลัมน์เป็น "ข้อความ" กัน Google Sheets แปลงวันที่/ตัวเลขเอง
    (data.text_columns || []).forEach(function (c) {
      sh.getRange(1, c, total, 1).setNumberFormat("@");
    });

    sh.getRange(1, 1, 1, cols).setValues([data.headers])
      .setFontWeight("bold").setBackground("#e0f2fe");
    if (data.rows.length > 0) {
      sh.getRange(2, 1, data.rows.length, cols).setValues(data.rows);
    }
    sh.setFrozenRows(1);
    sh.getRange(1, cols + 2).setValue("อัปเดตล่าสุด: " + data.synced_at);
    sh.autoResizeColumns(1, cols);

    return reply({ ok: true, count: data.rows.length });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
