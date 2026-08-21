"""กันบอทรันซ้อน (bot/instance_lock.py) — จอง port localhost เป็น lock

เหตุจริง 2026-08-20: สอง instance แย่ง getUpdates → telegram.error.Conflict 65 ครั้ง
lock แบบ socket: process ตาย (crash/kill) OS คืน port เอง ไม่มี stale lockfile
"""
from bot import instance_lock

TEST_PORT = 48963               # คนละ port กับ LOCK_PORT จริง — กันชนบอทที่รันอยู่


def test_acquire_returns_lock():
    lock = instance_lock.acquire(port=TEST_PORT)
    try:
        assert lock is not None
    finally:
        lock.close()


def test_second_acquire_fails_while_held():
    first = instance_lock.acquire(port=TEST_PORT)
    try:
        assert instance_lock.acquire(port=TEST_PORT) is None
    finally:
        first.close()


def test_reacquire_after_release():
    first = instance_lock.acquire(port=TEST_PORT)
    first.close()
    second = instance_lock.acquire(port=TEST_PORT)
    try:
        assert second is not None
    finally:
        second.close()
