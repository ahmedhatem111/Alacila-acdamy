#!/usr/bin/env python3
"""أوامر إدارة سريعة:
  python manage.py stats                    عدد الطلاب لكل سنة/تخصص
  python manage.py list                     قائمة الحسابات
  python manage.py export users.csv         تصدير الحسابات CSV (من غير كلمات المرور)
  python manage.py reset-password EMAIL     تغيير كلمة مرور طالب (وتسجيل خروجه من كل الأجهزة)
  python manage.py delete EMAIL             حذف حساب وكل بياناته
"""
import csv
import getpass
import sys
import time

from werkzeug.security import generate_password_hash

import app as site

LABEL = {"year1": "السنة الأولى", "year2": "السنة الثانية", "cs": "علوم الحاسب", "ai": "الذكاء الاصطناعي", "is": "نظم المعلومات"}
fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def main(argv):
    if not argv:
        print(__doc__); return 1
    db = site.connect()
    cmd = argv[0]
    if cmd == "stats":
        print("إجمالي الحسابات:", db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        for r in db.execute("SELECT major, COUNT(*) n FROM users GROUP BY major ORDER BY n DESC"):
            print(f"  {LABEL.get(r['major'], r['major'])}: {r['n']}")
    elif cmd == "list":
        for r in db.execute("SELECT * FROM users ORDER BY id"):
            print(f"{r['id']:>4}  {r['email']:<36} {r['name']:<24} {LABEL[r['major']]:<18} سجّل: {fmt(r['created_at'])}")
    elif cmd == "export" and len(argv) > 1:
        with open(argv[1], "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["id", "name", "email", "major", "created_at", "last_login"])
            for r in db.execute("SELECT * FROM users ORDER BY id"):
                w.writerow([r["id"], r["name"], r["email"], LABEL[r["major"]], fmt(r["created_at"]), fmt(r["last_login"])])
        print("تم:", argv[1])
    elif cmd == "reset-password" and len(argv) > 1:
        pw = getpass.getpass("كلمة المرور الجديدة (8 أحرف على الأقل): ")
        if len(pw) < 8:
            print("قصيرة جدًا"); return 1
        cur = db.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE email = ?",
                         (generate_password_hash(pw), argv[1].lower()))
        db.commit(); print("تم" if cur.rowcount else "الإيميل غير موجود")
    elif cmd == "delete" and len(argv) > 1:
        cur = db.execute("DELETE FROM users WHERE email = ?", (argv[1].lower(),))
        db.commit(); print("تم الحذف" if cur.rowcount else "الإيميل غير موجود")
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
