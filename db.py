"""SQLite persistence: users, sessions, agent runs, interview answers and skill mastery."""
import hashlib, json, os, secrets, sqlite3, threading, time

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "preppilot.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT, salt TEXT, created REAL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, user_id INTEGER, created REAL, role TEXT, status TEXT,
    jd TEXT, resume TEXT, trace TEXT, result TEXT, metrics TEXT);
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, user_id INTEGER, run_id INTEGER, qid TEXT, skill TEXT,
    question TEXT, answer TEXT, score REAL, feedback TEXT, wpm REAL, fillers INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS mastery(user_id INTEGER, skill TEXT, score REAL, n INTEGER, PRIMARY KEY(user_id, skill));
"""

def conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)

def q(sql, args=(), one=False):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        rows = cur.fetchall()
        c.commit()
        if one:
            return dict(rows[0]) if rows else None
        return [dict(r) for r in rows]

def ex(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid

def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()

def register(username, pw):
    salt = secrets.token_hex(8)
    try:
        uid = ex("INSERT INTO users(username,pw_hash,salt,created) VALUES(?,?,?,?)",
                 (username, _hash(pw, salt), salt, time.time()))
    except sqlite3.IntegrityError:
        return None
    return new_session(uid)

def login(username, pw):
    u = q("SELECT * FROM users WHERE username=?", (username,), one=True)
    if not u or _hash(pw, u["salt"]) != u["pw_hash"]:
        return None
    return new_session(u["id"])

def new_session(uid):
    tok = secrets.token_urlsafe(24)
    ex("INSERT INTO sessions VALUES(?,?,?)", (tok, uid, time.time()))
    return tok

def user_for(token):
    if not token:
        return None
    return q("SELECT u.id, u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,), one=True)

def get_mastery(uid):
    return {r["skill"]: (r["score"], r["n"]) for r in q("SELECT * FROM mastery WHERE user_id=?", (uid,))}

def update_mastery(uid, skill, score10):
    """Exponential moving average of interview scores (0-100), so recent answers count more."""
    cur = q("SELECT * FROM mastery WHERE user_id=? AND skill=?", (uid, skill), one=True)
    s = score10 * 10
    if cur:
        new = round(0.6 * s + 0.4 * cur["score"], 1)
        ex("UPDATE mastery SET score=?, n=n+1 WHERE user_id=? AND skill=?", (new, uid, skill))
    else:
        ex("INSERT INTO mastery VALUES(?,?,?,1)", (uid, skill, s))

def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default
