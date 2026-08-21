"""เขียนไฟล์ JSON แบบ atomic — เขียนลง .tmp ข้างๆ, fsync, แล้ว os.replace ทับ

ไฟดับ/crash กลางคันไฟล์เดิมยังอยู่ครบ (os.replace atomic ทั้ง Windows/POSIX)
ใช้กับไฟล์ state ทุกตัว: signals/breakouts (ประวัติถาวร track ใน git),
watchlist/auto_watch/job_state — เดิม write_text ทับตรงๆ พังได้ทั้งไฟล์
.tmp ที่ตกค้างจาก crash ระหว่าง replace ถูก gitignore และโดนเขียนทับรอบถัดไป
"""
import json
import os


def write_json_atomic(path, data):
    """เขียน data เป็น JSON ลง path (รูปแบบเดียวกับ write_text เดิมทุก writer)"""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.flush()
        os.fsync(f.fileno())        # ถึง disk จริงก่อน replace — กันไฟล์ใหม่ว่างตอนไฟดับ
    os.replace(tmp, path)
