#!/usr/bin/env python3
"""
أهلية أكاديمي — السيرفر (Flask + SQLite)

- يقدّم ملفات الموقع من مجلد public/
- يحفظ الحسابات والتقدّم والجدول وطلبات التيمز في قاعدة بيانات SQLite
- يحمي الصفحات والملفات: لازم المستخدم يكون مسجّل دخول (والتحقق على السيرفر مش في المتصفح)

التشغيل محليًا:   python app.py
التشغيل الفعلي:   gunicorn -w 3 -b 127.0.0.1:8000 app:app
"""
import os
import re
import sqlite3
import secrets
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import (Flask, abort, g, jsonify, make_response, redirect, request,
                   send_from_directory, session)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join

BASE = Path(__file__).resolve().parent
PUBLIC = BASE / "public"
INSTANCE = Path(os.environ.get("INSTANCE_DIR", BASE / "instance"))
INSTANCE.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("DATABASE", str(INSTANCE / "ahlia.db"))

# ───────────────────────── الإعدادات ─────────────────────────
MAJORS = ("year1", "year2", "cs", "ai", "is")


def access_for(major):
    """الصفحات/الملفات اللي مسموح للطالب يفتحها.
    حاليًا: كل طالب يفتح سنته أو تخصصه بس.
    لو عايز طالب التخصص يشوف السنة الأولى والتانية كمان، غيّر السطر ده مثلًا إلى:
        return [major] if major in ("year1", "year2") else ["year1", "year2", major]
    """
    return [major]


# لو عايز تقصر التسجيل على إيميلات الجامعة: ALLOWED_EMAIL_DOMAINS="ahlia.edu.eg,student.ahlia.edu.eg"
ALLOWED_DOMAINS = [d.strip().lower() for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]

PROTECTED_PAGES = {"welcome", "courses", "course", "staff", "year1", "year2", "cs", "ai", "is",
                   "schedule", "movies", "teams", "certificate", "mylearning", "paths"}
GATED_GROUPS = set(MAJORS)  # صفحات/مجلدات ملفات مقصورة على أصحابها
ALLOWED_EXT = {".html", ".js", ".css", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
               ".ico", ".webmanifest", ".woff", ".woff2", ".txt"}


def load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    f = INSTANCE / "secret.key"
    if f.exists():
        return f.read_text().strip()
    key = secrets.token_hex(32)
    f.write_text(key)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return key


app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=load_secret(),
    SESSION_COOKIE_NAME="ahlia_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("HTTPS", "0") == "1",  # فعّلها (HTTPS=1) أول ما الموقع يشتغل على https
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=256 * 1024,
    JSON_AS_ASCII=False,
)
if os.environ.get("TRUST_PROXY") == "1":  # لو وراء nginx / Render / Railway ...
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ───────────────────────── قاعدة البيانات ─────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  name            TEXT    NOT NULL,
  email           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  major           TEXT    NOT NULL CHECK (major IN ('year1','year2','cs','ai','is')),
  password_hash   TEXT    NOT NULL,
  session_version INTEGER NOT NULL DEFAULT 0,
  created_at      INTEGER NOT NULL,
  last_login      INTEGER
);
CREATE TABLE IF NOT EXISTS enrollments (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id  TEXT    NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, course_id)
);
CREATE TABLE IF NOT EXISTS lecture_progress (
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id TEXT    NOT NULL,
  lecture   INTEGER NOT NULL,
  done_at   INTEGER NOT NULL,
  PRIMARY KEY (user_id, course_id, lecture)
);
CREATE TABLE IF NOT EXISTS course_progress (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id  TEXT    NOT NULL,
  data       TEXT    NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, course_id)
);
CREATE TABLE IF NOT EXISTS schedule_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT    NOT NULL,
  kind       TEXT    NOT NULL,
  day        INTEGER NOT NULL CHECK (day BETWEEN 0 AND 6),
  time       TEXT    NOT NULL,
  place      TEXT    NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedule_user ON schedule_items(user_id);
CREATE TABLE IF NOT EXISTS team_posts (
  id          TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type        TEXT    NOT NULL CHECK (type IN ('need','have')),
  subject     TEXT    NOT NULL,
  role        TEXT    NOT NULL,
  year        TEXT    NOT NULL DEFAULT '',
  count       INTEGER NOT NULL DEFAULT 1,
  description TEXT    NOT NULL DEFAULT '',
  contact     TEXT    NOT NULL,
  closed      INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON team_posts(created_at);
CREATE TABLE IF NOT EXISTS login_attempts (
  key TEXT    NOT NULL,
  ts  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts ON login_attempts(key, ts);
"""


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def init_db():
    db = connect()
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    db.commit()
    db.close()


init_db()


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ───────────────────────── أدوات مساعدة ─────────────────────────
def now():
    return int(time.time())


def err(msg, code=400):
    return jsonify(ok=False, error=msg), code


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def clean(value, max_len):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
COURSE_RE = re.compile(r"^[\w.\-]{1,80}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
KINDS = ("محاضرة", "سكشن", "تسليم", "امتحان")
DUMMY_HASH = generate_password_hash("not-a-real-password")


def public_user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"],
            "major": row["major"], "access": access_for(row["major"])}


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or row["session_version"] != session.get("sv"):
        session.clear()
        return None
    return row


def login_user(row):
    session.clear()  # نمنع session fixation
    session.permanent = True
    session["uid"] = row["id"]
    session["sv"] = row["session_version"]


def state_for(uid):
    db = get_db()
    enrolled = [r["course_id"] for r in db.execute(
        "SELECT course_id FROM enrollments WHERE user_id = ? ORDER BY created_at", (uid,))]
    done = {}
    for r in db.execute("SELECT course_id, lecture FROM lecture_progress WHERE user_id = ? ORDER BY lecture", (uid,)):
        done.setdefault(r["course_id"], []).append(r["lecture"])
    return {"enrolled": enrolled, "done": done}


def session_payload(row):
    return {"ok": True, "user": public_user(row), "state": state_for(row["id"])}


def client_ip():
    return request.remote_addr or "?"


def too_many(checks, window):
    """checks = [(key, limit), ...] — هل المفتاح عدّى الحد خلال window ثانية؟"""
    db = get_db()
    t = now()
    db.execute("DELETE FROM login_attempts WHERE ts < ?", (t - 86400,))
    for key, limit in checks:
        n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key = ? AND ts > ?", (key, t - window)).fetchone()[0]
        if n >= limit:
            return True
    return False


def record_attempt(key):
    get_db().execute("INSERT INTO login_attempts (key, ts) VALUES (?, ?)", (key, now()))
    get_db().commit()


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return err("سجّل دخولك أولاً", 401)
        g.user = user
        return fn(*a, **kw)
    return wrapper


# ───────────────────────── حماية CSRF + رؤوس الأمان ─────────────────────────
@app.before_request
def csrf_guard():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        if request.headers.get("X-Requested-With") != "ahlia":
            return err("طلب غير صالح", 400)
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return err("طلب غير صالح", 403)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ───────────────────────── الحسابات ─────────────────────────
@app.post("/api/register")
def api_register():
    data = body()
    ip = client_ip()
    if too_many([(f"reg:{ip}", 15)], 3600):
        return err("محاولات كتير، جرّب بعد شوية", 429)
    record_attempt(f"reg:{ip}")

    name = clean(data.get("name"), 80)
    email = clean(data.get("email"), 254).lower()
    major = data.get("major")
    password = data.get("password")
    if len(name) < 3:
        return err("اكتب اسمك الكامل")
    if not EMAIL_RE.match(email):
        return err("اكتب بريداً إلكترونياً صحيحاً")
    if ALLOWED_DOMAINS and email.rsplit("@", 1)[-1] not in ALLOWED_DOMAINS:
        return err("التسجيل متاح فقط بالبريد الجامعي (" + "، ".join("@" + d for d in ALLOWED_DOMAINS) + ")")
    if major not in MAJORS:
        return err("اختر سنتك الدراسية أو تخصصك")
    if not isinstance(password, str) or not (8 <= len(password) <= 128):
        return err("كلمة المرور لازم تكون 8 أحرف على الأقل")

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, major, password_hash, created_at, last_login) VALUES (?,?,?,?,?,?)",
            (name, email, major, generate_password_hash(password), now(), now()))
        db.commit()
    except sqlite3.IntegrityError:
        return err("هذا البريد مسجل من قبل، سجّل دخولك", 409)
    row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    login_user(row)
    return jsonify(session_payload(row)), 201


@app.post("/api/login")
def api_login():
    data = body()
    email = clean(data.get("email"), 254).lower()
    password = data.get("password")
    ip = client_ip()
    if too_many([(f"login-ip:{ip}", 40), (f"login-email:{email}", 8)], 900):
        return err("محاولات دخول كتير، استنى 15 دقيقة وجرّب تاني", 429)
    if not EMAIL_RE.match(email) or not isinstance(password, str) or not password:
        return err("البريد أو كلمة المرور غير صحيحة", 401)

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # نفس الزمن تقريبًا سواء الإيميل موجود أو لا
    ok = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
    if not (row and ok):
        record_attempt(f"login-ip:{ip}")
        record_attempt(f"login-email:{email}")
        return err("البريد أو كلمة المرور غير صحيحة", 401)

    db.execute("DELETE FROM login_attempts WHERE key = ?", (f"login-email:{email}",))
    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now(), row["id"]))
    db.commit()
    login_user(row)
    return jsonify(session_payload(row))


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login_required
def api_me():
    return jsonify(session_payload(g.user))


# ───────────────────────── الاشتراك والتقدّم ─────────────────────────
@app.put("/api/enroll")
@login_required
def api_enroll():
    data = body()
    course = data.get("course")
    if not isinstance(course, str) or not COURSE_RE.match(course):
        return err("كورس غير صالح")
    db = get_db()
    if data.get("on"):
        db.execute("INSERT OR IGNORE INTO enrollments (user_id, course_id, created_at) VALUES (?,?,?)",
                   (g.user["id"], course, now()))
    else:
        db.execute("DELETE FROM enrollments WHERE user_id = ? AND course_id = ?", (g.user["id"], course))
    db.commit()
    return jsonify(ok=True)


@app.put("/api/lecture")
@login_required
def api_lecture():
    data = body()
    course, idx = data.get("course"), data.get("index")
    if not isinstance(course, str) or not COURSE_RE.match(course):
        return err("كورس غير صالح")
    if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < 500):
        return err("محاضرة غير صالحة")
    db = get_db()
    if data.get("done"):
        db.execute("INSERT OR IGNORE INTO lecture_progress (user_id, course_id, lecture, done_at) VALUES (?,?,?,?)",
                   (g.user["id"], course, idx, now()))
    else:
        db.execute("DELETE FROM lecture_progress WHERE user_id = ? AND course_id = ? AND lecture = ?",
                   (g.user["id"], course, idx))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/course-progress", methods=["GET", "POST"])
@login_required
def api_course_progress():
    """تقدّم مشغّل الكورس (course.html): الموضع، المحاضرات المكتملة، نتيجة الاختبار ..."""
    import json
    db = get_db()
    if request.method == "GET":
        course = request.args.get("course", "")
        if not COURSE_RE.match(course):
            return err("كورس غير صالح")
        row = db.execute("SELECT data FROM course_progress WHERE user_id = ? AND course_id = ?",
                         (g.user["id"], course)).fetchone()
        return jsonify(json.loads(row["data"]) if row else {})
    data = body()
    course, progress = data.get("course"), data.get("progress")
    if not isinstance(course, str) or not COURSE_RE.match(course) or not isinstance(progress, dict):
        return err("بيانات غير صالحة")
    raw = json.dumps(progress, ensure_ascii=False)
    if len(raw) > 65536:
        return err("البيانات كبيرة جدًا", 413)
    db.execute("""INSERT INTO course_progress (user_id, course_id, data, updated_at) VALUES (?,?,?,?)
                  ON CONFLICT(user_id, course_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
               (g.user["id"], course, raw, now()))
    db.commit()
    return jsonify(ok=True)


# ───────────────────────── الجدول ─────────────────────────
def schedule_row(r):
    return {"id": r["id"], "title": r["title"], "kind": r["kind"], "day": r["day"], "time": r["time"], "place": r["place"]}


@app.get("/api/schedule")
@login_required
def api_schedule_list():
    rows = get_db().execute("SELECT * FROM schedule_items WHERE user_id = ? ORDER BY day, time", (g.user["id"],))
    return jsonify([schedule_row(r) for r in rows])


@app.post("/api/schedule")
@login_required
def api_schedule_add():
    data = body()
    title, place = clean(data.get("title"), 120), clean(data.get("place"), 80)
    kind, day, time_ = data.get("kind"), data.get("day"), data.get("time") or "09:00"
    if len(title) < 2:
        return err("اكتب عنوان الموعد")
    if kind not in KINDS:
        return err("نوع الموعد غير صالح")
    if not isinstance(day, int) or isinstance(day, bool) or not (0 <= day <= 6):
        return err("اليوم غير صالح")
    if not isinstance(time_, str) or not TIME_RE.match(time_):
        return err("الوقت غير صالح")
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM schedule_items WHERE user_id = ?", (g.user["id"],)).fetchone()[0] >= 300:
        return err("وصلت للحد الأقصى من المواعيد", 429)
    cur = db.execute("INSERT INTO schedule_items (user_id, title, kind, day, time, place, created_at) VALUES (?,?,?,?,?,?,?)",
                     (g.user["id"], title, kind, day, time_, place, now()))
    db.commit()
    row = db.execute("SELECT * FROM schedule_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(schedule_row(row)), 201


@app.delete("/api/schedule/<int:item_id>")
@login_required
def api_schedule_delete(item_id):
    db = get_db()
    db.execute("DELETE FROM schedule_items WHERE id = ? AND user_id = ?", (item_id, g.user["id"]))
    db.commit()
    return jsonify(ok=True)


# ───────────────────────── طلبات التيمز (مشتركة بين كل الطلاب) ─────────────────────────
def post_row(r):
    return {"id": r["id"], "uid": str(r["user_id"]), "name": r["name"], "at": r["created_at"] * 1000,
            "closed": bool(r["closed"]), "type": r["type"], "subject": r["subject"], "role": r["role"],
            "year": r["year"], "count": r["count"], "desc": r["description"], "contact": r["contact"]}


POST_SELECT = "SELECT p.*, u.name AS name FROM team_posts p JOIN users u ON u.id = p.user_id"


@app.get("/api/teams")
@login_required
def api_teams_list():
    rows = get_db().execute(POST_SELECT + " ORDER BY p.created_at DESC LIMIT 500")
    return jsonify([post_row(r) for r in rows])


@app.post("/api/teams")
@login_required
def api_teams_add():
    data = body()
    type_ = data.get("type")
    subject, role = clean(data.get("subject"), 120), clean(data.get("role"), 120)
    contact, year = clean(data.get("contact"), 200), clean(data.get("year"), 30)
    desc = str(data.get("desc") or "").strip()[:600]
    try:
        count = max(1, min(20, int(data.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    if type_ not in ("need", "have") or not subject or not role or not contact:
        return err("املأ الحقول المطلوبة.")
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM team_posts WHERE user_id = ? AND closed = 0", (g.user["id"],)).fetchone()[0] >= 10:
        return err("عندك 10 طلبات مفتوحة، اقفل بعضها الأول", 429)
    pid = secrets.token_urlsafe(6)
    db.execute("""INSERT INTO team_posts (id, user_id, type, subject, role, year, count, description, contact, created_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
               (pid, g.user["id"], type_, subject, role, year, count, desc, contact, now()))
    db.commit()
    row = db.execute(POST_SELECT + " WHERE p.id = ?", (pid,)).fetchone()
    return jsonify(post_row(row)), 201


@app.patch("/api/teams/<pid>")
@login_required
def api_teams_close(pid):
    db = get_db()
    cur = db.execute("UPDATE team_posts SET closed = 1 WHERE id = ? AND user_id = ?", (pid, g.user["id"]))
    db.commit()
    return jsonify(ok=True) if cur.rowcount else err("غير موجود", 404)


@app.delete("/api/teams/<pid>")
@login_required
def api_teams_delete(pid):
    db = get_db()
    db.execute("DELETE FROM team_posts WHERE id = ? AND user_id = ?", (pid, g.user["id"]))
    db.commit()
    return jsonify(ok=True)


@app.get("/healthz")
def healthz():
    get_db().execute("SELECT 1")
    return "ok"


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return err("غير موجود", 404)
    return make_response(
        '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>الصفحة غير موجودة</title><body style="font-family:Cairo,Tahoma,sans-serif;background:#050a2a;color:#fff;'
        'display:grid;place-items:center;min-height:100vh;margin:0;text-align:center"><div><h1>٤٠٤</h1>'
        '<p>الصفحة اللي بتدوّر عليها مش موجودة.</p><p><a style="color:#8fb0ff" href="/index.html">الرجوع للرئيسية</a></p></div></body></html>',
        404)


@app.errorhandler(405)
def bad_method(_e):
    return err("طريقة الطلب غير مسموحة", 405)


@app.errorhandler(413)
def too_large(_e):
    return err("البيانات كبيرة جدًا", 413)


# ───────────────────────── تقديم الموقع (مع الحماية) ─────────────────────────
@app.get("/", defaults={"path": "index.html"})
@app.get("/<path:path>")
def site(path):
    if path.startswith("api/") or any(p.startswith(".") for p in path.split("/")):
        abort(404)
    ext = Path(path).suffix.lower()
    if ext not in ALLOWED_EXT:
        abort(404)
    full = safe_join(str(PUBLIC), path)
    if not full or not os.path.isfile(full):
        abort(404)

    parts = path.split("/")
    user = current_user()

    # الصفحات المحمية
    if len(parts) == 1 and ext == ".html" and parts[0][:-5] in PROTECTED_PAGES:
        page = parts[0][:-5]
        if not user:
            nxt = parts[0] + ("?" + request.query_string.decode() if request.query_string else "")
            return redirect("/login.html?next=" + quote(nxt, safe=""))
        if page in GATED_GROUPS and page not in access_for(user["major"]):
            return redirect("/welcome.html?denied=" + page)

    # ملفات المذكرات والتمارين
    if parts[0] == "files":
        if not user:
            return err("سجّل دخولك أولاً", 401)
        if len(parts) > 2 and parts[1] in GATED_GROUPS and parts[1] not in access_for(user["major"]):
            return err("هذا الملف خاص بطلاب آخرين", 403)

    resp = send_from_directory(PUBLIC, path)
    if parts[0] == "files":
        resp.headers["Cache-Control"] = "private, max-age=3600"
    else:
        resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"→ http://127.0.0.1:{port}   (قاعدة البيانات: {DB_PATH})")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=os.environ.get("DEBUG") == "1")
