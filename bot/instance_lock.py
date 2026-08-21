"""กันบอทรันซ้อน: จอง TCP port บน localhost เป็น lock ระดับเครื่อง

เหตุจริง 2026-08-20: รันมือทดสอบซ้อนกับตัว background → สอง instance แย่ง
getUpdates โดน telegram.error.Conflict 65 ครั้ง — ใช้ socket แทน lockfile
เพราะ process ตาย (crash/kill) แล้ว OS คืน port ให้เอง ไม่มี stale lock ค้าง
"""
import socket

LOCK_PORT = 48962               # port ประจำบอทตัวนี้ (จองเฉพาะบน 127.0.0.1)


def acquire(port=LOCK_PORT):
    """จอง lock — คืน socket (ผู้เรียกถือ reference ไว้ตลอดอายุ process) · None = มีตัวอื่นถืออยู่"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        return None
    sock.listen(1)
    return sock
