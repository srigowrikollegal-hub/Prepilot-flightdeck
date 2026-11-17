"""PrepPilot Flight Deck - FastAPI backend.

Run locally:  uvicorn server.main:app --reload   (from the project folder)
API docs:     /docs
"""
import base64, datetime as dt, io, json, os, random, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DB_PATH", os.path.join(HERE, "data", "preppilot.db"))
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

import agent, db, kb

app = FastAPI(title="PrepPilot Flight Deck API", version="3.0",
              description="Backend for PrepPilot: multi-agent placement preparation with memory.")


def find_web():
    """Works whether the files sit in server/ + web/ folders or all in one folder."""
    for d in (os.path.join(HERE, "..", "web"), os.path.join(HERE, "web"), HERE, os.path.join(HERE, "..")):
        if os.path.exists(os.path.join(d, "index.html")):
            return os.path.abspath(d)
    return HERE


WEB = find_web()
LIVE = {}  # run_id -> live state while the crew is working
ADMIN_CODE = os.environ.get("ADMIN_CODE", "TOWER2026")
db.init()


def me(token):
    u = db.user_for(token)
    if not u:
        raise HTTPException(401, "Please log in")
    return u


class Cred(BaseModel):
    username: str
    password: str


class RunIn(BaseModel):
    jd: str
    resume: str
    days: int = 7
    hours: float = 2
    company: str = ""


class CodeIn(BaseModel):
    code: str


class PdfIn(BaseModel):
    data: str
    name: str = "resume.pdf"


class ResumeIn(BaseModel):
    resume: str
    jd: str = ""


class AnswerIn(BaseModel):
    run_id: int
    qid: str
    answer: str
    wpm: float = 0
    fillers: int = 0
    seconds: float = 0


@app.post("/api/auth/register")
def register(c: Cred):
    u = c.username.strip().lower()
    if len(u) < 3 or len(c.password) < 4:
        raise HTTPException(400, "Username needs 3+ characters and password 4+")
    tok = db.register(u, c.password)
    if not tok:
        raise HTTPException(409, "That username is taken")
    return {"token": tok, "username": u}


@app.post("/api/auth/login")
def login(c: Cred):
    tok = db.login(c.username.strip().lower(), c.password)
    if not tok:
        raise HTTPException(401, "Wrong username or password")
    return {"token": tok, "username": c.username.strip().lower()}


@app.get("/api/me")
def get_me(authorization: str = Header("")):
    u = me(authorization)
    return {**u, "is_admin": db.is_admin(u["id"])}


@app.get("/api/companies")
def companies():
    return [{"id": k, "name": v["name"], "track": v["track"]} for k, v in kb.COMPANIES.items()]


@app.get("/api/health")
def health():
    return {"ok": True, "llm_key": bool(agent.api_key()), "models": agent.models() if agent.api_key() else [],
            "questions": len(kb.QUESTIONS), "skills": len(kb.SKILLS)}


@app.get("/api/samples")
def samples():
    return {"jd": kb.SAMPLE_JD, "resume": kb.SAMPLE_RESUME}


@app.post("/api/runs")
def start_run(r: RunIn, authorization: str = Header("")):
    u = me(authorization)
    if len(r.jd.strip()) < 30 or len(r.resume.strip()) < 30:
        raise HTTPException(400, "Paste a full job description and resume")
    rid = db.ex("INSERT INTO runs(user_id,created,role,status,jd,resume) VALUES(?,?,?,?,?,?)",
                (u["id"], time.time(), agent.role_of(r.jd), "running", r.jd, r.resume))
    S = {"jd": r.jd, "resume": agent.normalize_resume(r.resume), "uid": u["id"], "days": r.days, "hours": r.hours,
         "company": r.company if r.company in kb.COMPANIES else ""}
    stats = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_seconds": 0, "tool_calls": 0,
             "models": [], "autopilot": False}
    live = {"trace": [], "status": "running", "t0": time.time()}
    LIVE[rid] = live

    def log(agent_name, typ, text, data=None):
        live["trace"].append({"t": round(time.time() - live["t0"], 1), "agent": agent_name, "type": typ,
                              "text": text, "data": data})

    def work():
        try:
            agent.run_crew(S, log, stats)
            stats["seconds"] = round(time.time() - live["t0"], 1)
            res = result_of(S, u["id"])
            db.ex("UPDATE runs SET status='done', trace=?, result=?, metrics=? WHERE id=?",
                  (json.dumps(live["trace"], default=str), json.dumps(res, default=str), json.dumps(stats), rid))
            db.ex("INSERT INTO snapshots(user_id,run_id,created,readiness) VALUES(?,?,?,?)",
                  (u["id"], rid, time.time(), res["readiness_at_run"]))
            live["status"] = "done"
        except Exception as e:
            log("System", "error", f"Run failed: {e}")
            db.ex("UPDATE runs SET status='failed', trace=? WHERE id=?", (json.dumps(live["trace"], default=str), rid))
            live["status"] = "failed"

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": rid}


def result_of(S, uid):
    m = db.get_mastery(uid)
    return {"role": S.get("role"), "match": S.get("match", 0), "jd_skills": S.get("jd_skills", []),
            "matched": S.get("matched", []), "missing": S.get("missing", []),
            "skill_names": {s: kb.skill_name(s) for s in kb.SKILLS}, "ats": S.get("ats", {}),
            "resources": S.get("resources", {}), "plan": S.get("plan", []), "plan_hours": S.get("plan_hours", 2),
            "interview_focus": S.get("interview_focus", []), "weak_memory": S.get("weak_memory", []),
            "brief": S.get("brief", {}), "readiness_at_run": agent.readiness(S, m),
            "company": S.get("company", ""), "company_profile": company_card(S.get("company", ""))}


def company_card(cid):
    c = kb.COMPANIES.get(cid or "")
    if not c:
        return None
    return {"name": c["name"], "track": c["track"], "tip": c["tip"], "focus": c["focus"],
            "rounds": [{"name": r[0], "tests": r[1], "skill": r[2]} for r in c["rounds"]]}


def load_run(rid, uid):
    r = db.q("SELECT * FROM runs WHERE id=? AND user_id=?", (rid, uid), one=True)
    if not r:
        raise HTTPException(404, "Run not found")
    return r


@app.get("/api/runs/{rid}")
def get_run(rid: int, authorization: str = Header("")):
    u = me(authorization)
    r = load_run(rid, u["id"])
    live = LIVE.get(rid)
    if live and live["status"] == "running":
        return {"id": rid, "status": "running", "trace": live["trace"]}
    res = db.jload(r["result"], {})
    if res:
        S = {"match": res["match"], "ats": res["ats"], "jd_skills": res["jd_skills"]}
        res["readiness"] = agent.readiness(S, db.get_mastery(u["id"]))
        res["mastery"] = {k: v[0] for k, v in db.get_mastery(u["id"]).items()}
    return {"id": rid, "status": r["status"], "role": r["role"], "created": r["created"],
            "trace": db.jload(r["trace"], []), "result": res, "metrics": db.jload(r["metrics"], {})}


@app.get("/api/runs")
def list_runs(authorization: str = Header("")):
    u = me(authorization)
    rows = db.q("SELECT id, created, role, status, result FROM runs WHERE user_id=? ORDER BY id DESC LIMIT 20", (u["id"],))
    out = []
    for r in rows:
        res = db.jload(r["result"], {})
        out.append({"id": r["id"], "created": r["created"], "role": r["role"], "status": r["status"],
                    "match": res.get("match"), "ats": res.get("ats", {}).get("ats_score")})
    return out


@app.get("/api/runs/{rid}/plan.ics")
def plan_ics(rid: int, token: str = ""):
    u = me(token)
    res = db.jload(load_run(rid, u["id"])["result"], {})
    hours = res.get("plan_hours", 2)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PrepPilot//Flight Plan//EN", "CALSCALE:GREGORIAN"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for p in res.get("plan", []):
        d = dt.date.fromisoformat(p["date"])
        start = dt.datetime(d.year, d.month, d.day, 13, 30)  # 7:00 PM IST in UTC
        end = start + dt.timedelta(hours=hours)
        desc = "\\n".join(f"- {b['what']} ({b['mins']} min)" + (f" {b['url']}" if b.get("url") else "") for b in p["blocks"])
        lines += ["BEGIN:VEVENT", f"UID:preppilot-{rid}-{p['day']}@preppilot", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:PrepPilot Day {p['day']}: {p['focus']}", f"DESCRIPTION:{desc}",
                  "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:PrepPilot study block", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return PlainTextResponse("\r\n".join(lines), media_type="text/calendar",
                             headers={"Content-Disposition": f'attachment; filename="PrepPilot_plan_{rid}.ics"'})


@app.get("/api/interview/next")
def interview_next(run_id: int, authorization: str = Header("")):
    u = me(authorization)
    res = db.jload(load_run(run_id, u["id"])["result"], {})
    asked = [r["qid"] for r in db.q("SELECT qid FROM answers WHERE user_id=? AND run_id=?", (u["id"], run_id))]
    return agent.next_question(u["id"], res.get("interview_focus"), res.get("jd_skills"), asked, res.get("company"))


@app.post("/api/interview/answer")
def interview_answer(a: AnswerIn, authorization: str = Header("")):
    u = me(authorization)
    load_run(a.run_id, u["id"])
    if a.qid not in kb.QUESTION_BY_ID:
        raise HTTPException(400, "Unknown question")
    stats = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_seconds": 0, "models": []}
    q = kb.QUESTION_BY_ID[a.qid]
    r = agent.evaluate(a.qid, a.answer, stats)
    db.ex("INSERT INTO answers(user_id,run_id,qid,skill,question,answer,score,feedback,wpm,fillers,created) "
          "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (u["id"], a.run_id, a.qid, q[1], q[3], a.answer, r["score"],
                                             json.dumps(r), a.wpm, a.fillers, time.time()))
    db.update_mastery(u["id"], q[1], r["score"])
    m = db.get_mastery(u["id"])
    r["mastery"] = m.get(q[1], (0, 0))[0]
    res = db.jload(db.q("SELECT result FROM runs WHERE id=?", (a.run_id,), one=True)["result"], {})
    if res:
        r["readiness"] = agent.readiness({"match": res["match"], "ats": res["ats"], "jd_skills": res["jd_skills"]}, m)
        db.ex("INSERT INTO snapshots(user_id,run_id,created,readiness) VALUES(?,?,?,?)",
              (u["id"], a.run_id, time.time(), r["readiness"]))
    r["stats"] = stats
    return r


@app.get("/api/progress")
def progress(authorization: str = Header("")):
    u = me(authorization)
    ans = db.q("SELECT qid, skill, score, wpm, fillers, created FROM answers WHERE user_id=? ORDER BY id", (u["id"],))
    m = db.get_mastery(u["id"])
    return {"answers": ans, "mastery": {kb.skill_name(k): {"score": v[0], "n": v[1]} for k, v in m.items()},
            "runs": db.q("SELECT COUNT(*) n FROM runs WHERE user_id=?", (u["id"],), one=True)["n"],
            "avg_score": round(sum(a["score"] for a in ans) / len(ans), 1) if ans else None}


# ================================================================ dashboards
def ist_day(ts):
    return (dt.datetime.fromtimestamp(ts, dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()


def streaks(days):
    if not days:
        return 0, 0
    today = ist_day(time.time())
    d = today if today in days else today - dt.timedelta(days=1)
    cur = 0
    while d in days:
        cur += 1
        d -= dt.timedelta(days=1)
    best, run, prev = 0, 0, None
    for x in sorted(days):
        run = run + 1 if prev and (x - prev).days == 1 else 1
        best, prev = max(best, run), x
    return cur, best


def readiness_now(res, mastery):
    if not res:
        return None
    return agent.readiness({"match": res.get("match", 0), "ats": res.get("ats", {}), "jd_skills": res.get("jd_skills", [])}, mastery)


@app.get("/api/dashboard")
def dashboard(authorization: str = Header("")):
    u = me(authorization)
    uid = u["id"]
    runs = db.q("SELECT id, created, role, result FROM runs WHERE user_id=? AND status='done' ORDER BY id", (uid,))
    ans = db.q("SELECT qid, skill, score, wpm, fillers, created FROM answers WHERE user_id=? ORDER BY id", (uid,))
    snaps = db.q("SELECT created, readiness FROM snapshots WHERE user_id=? ORDER BY id", (uid,))
    m = db.get_mastery(uid)
    latest = db.jload(runs[-1]["result"], {}) if runs else {}
    now_r = readiness_now(latest, m)
    days = {ist_day(x["created"]) for x in runs + ans}
    cur, best = streaks(days)
    today = ist_day(time.time())
    counts = {}
    for x in runs + ans:
        counts[ist_day(x["created"])] = counts.get(ist_day(x["created"]), 0) + 1
    activity = [{"date": (today - dt.timedelta(days=27 - i)).isoformat(),
                 "count": counts.get(today - dt.timedelta(days=27 - i), 0)} for i in range(28)]
    target, missing = set(latest.get("jd_skills", [])), set(latest.get("missing", []))
    skills = [{"id": sid, "name": kb.skill_name(sid), "score": m[sid][0] if sid in m else None,
               "n": m.get(sid, (0, 0))[1], "target": sid in target, "missing": sid in missing} for sid in kb.SKILLS]
    lv = {}
    for a in ans:
        q = kb.QUESTION_BY_ID.get(a["qid"])
        if q:
            lv.setdefault(q[2], []).append(a["score"])
    by_level = {str(k): round(sum(v) / len(v), 1) for k, v in sorted(lv.items())}

    def weak_key(x):
        return x["score"] if x["score"] is not None else (5 if x["missing"] else 55)
    weak = sorted([x for x in skills if x["target"]], key=weak_key)[:3]
    for w in weak:
        w["reason"] = (f"mastery {w['score']:.0f}/100" if w["score"] is not None else
                       "missing from your resume, not practised yet" if w["missing"] else "not practised yet")
    wp = [a["wpm"] for a in ans if a["wpm"]]
    return {"kpis": {"readiness": now_r, "readiness_start": snaps[0]["readiness"] if snaps else None,
                     "streak": cur, "best_streak": best, "flights": len(runs), "answers": len(ans),
                     "avg_score": round(sum(a["score"] for a in ans) / len(ans), 1) if ans else None,
                     "avg_wpm": round(sum(wp) / len(wp)) if wp else None,
                     "avg_fillers": round(sum(a["fillers"] for a in ans) / len(ans), 1) if ans else None},
            "readiness_series": [{"t": x["created"], "v": x["readiness"]} for x in snaps][-30:],
            "activity": activity, "skills": skills, "by_level": by_level,
            "speaking": [{"wpm": a["wpm"], "fillers": a["fillers"], "score": a["score"], "qid": a["qid"]} for a in ans[-12:]],
            "weak": weak, "company": (kb.COMPANIES.get(latest.get("company") or "") or {}).get("name"),
            "runs": [{"id": r["id"], "created": r["created"], "role": r["role"],
                      "match": db.jload(r["result"], {}).get("match")} for r in reversed(runs[-10:])]}


# ================================================================ control tower (placement cell)
def admin(token):
    u = me(token)
    if not db.is_admin(u["id"]):
        raise HTTPException(403, "Control Tower is for the placement cell. Enter the tower code first.")
    return u


@app.post("/api/tower/unlock")
def tower_unlock(c: CodeIn, authorization: str = Header("")):
    u = me(authorization)
    if c.code.strip().upper() != ADMIN_CODE.upper():
        raise HTTPException(403, "Wrong tower code")
    db.ex("INSERT OR IGNORE INTO admins VALUES(?,?)", (u["id"], time.time()))
    return {"ok": True}


def batch_rows():
    rows = []
    for u in db.q("SELECT id, username FROM users ORDER BY id"):
        run = db.q("SELECT id, created, result FROM runs WHERE user_id=? AND status='done' ORDER BY id DESC LIMIT 1",
                   (u["id"],), one=True)
        if not run:
            continue
        res, m = db.jload(run["result"], {}), db.get_mastery(u["id"])
        ans = db.q("SELECT score, created FROM answers WHERE user_id=?", (u["id"],))
        runs = db.q("SELECT created FROM runs WHERE user_id=?", (u["id"],))
        cur, _ = streaks({ist_day(x["created"]) for x in ans + runs})
        rows.append({"name": u["username"], "demo": u["username"].startswith("demo_"),
                     "readiness": readiness_now(res, m), "match": res.get("match", 0),
                     "ats": res.get("ats", {}).get("ats_score", 0), "answers": len(ans),
                     "avg_score": round(sum(a["score"] for a in ans) / len(ans), 1) if ans else None,
                     "streak": cur, "company": (kb.COMPANIES.get(res.get("company") or "") or {}).get("name", "General"),
                     "missing": res.get("missing", []), "mastery": {k: v[0] for k, v in m.items()},
                     "top_gap": kb.skill_name(res["missing"][0]) if res.get("missing") else "-"})
    return rows


def tower_data():
    rows = batch_rows()
    n = len(rows)
    avg = round(sum(r["readiness"] for r in rows) / n) if n else 0
    bands = [("0-39", 0, 40), ("40-59", 40, 60), ("60-79", 60, 80), ("80-100", 80, 101)]
    gap_count, mast = {}, {}
    for r in rows:
        for s_ in r["missing"]:
            gap_count[s_] = gap_count.get(s_, 0) + 1
        for k, v in r["mastery"].items():
            mast.setdefault(k, []).append(v)
    gaps = sorted(gap_count.items(), key=lambda x: -x[1])[:8]
    weakest = sorted(((k, sum(v) / len(v), len(v)) for k, v in mast.items()), key=lambda x: x[1])[:6]
    comp = {}
    for r in rows:
        comp[r["company"]] = comp.get(r["company"], 0) + 1
    risk = [r for r in rows if r["readiness"] < 40]
    return {"kpis": {"students": n, "avg_readiness": avg,
                     "ready_percent": round(100 * sum(r["readiness"] >= 70 for r in rows) / n) if n else 0,
                     "at_risk": len(risk), "flights": db.q("SELECT COUNT(*) n FROM runs WHERE status='done'", one=True)["n"],
                     "answers": db.q("SELECT COUNT(*) n FROM answers", one=True)["n"],
                     "demo_students": sum(r["demo"] for r in rows)},
            "distribution": [{"band": b, "count": sum(lo <= r["readiness"] < hi for r in rows)} for b, lo, hi in bands],
            "gaps": [{"skill": kb.skill_name(k), "count": c, "percent": round(100 * c / n)} for k, c in gaps],
            "weakest": [{"skill": kb.skill_name(k), "avg": round(a), "students": c} for k, a, c in weakest],
            "companies": [{"name": k, "count": v} for k, v in sorted(comp.items(), key=lambda x: -x[1])],
            "leaderboard": sorted([{k: r[k] for k in ("name", "demo", "readiness", "match", "ats", "answers", "avg_score",
                                                        "streak", "company", "top_gap")} for r in rows],
                                  key=lambda r: -r["readiness"]),
            "at_risk": [{"name": r["name"], "readiness": r["readiness"], "top_gap": r["top_gap"]} for r in risk]}


@app.get("/api/tower")
def tower(authorization: str = Header("")):
    admin(authorization)
    return tower_data()


@app.post("/api/tower/briefing")
def tower_brief(authorization: str = Header("")):
    admin(authorization)
    d = tower_data()
    facts = {**{k: d["kpis"][k] for k in ("students", "avg_readiness", "ready_percent")},
             "top_gaps": d["gaps"][:4], "weakest": d["weakest"][:3], "companies": d["companies"][:4],
             "at_risk": d["at_risk"][:5]}
    stats = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_seconds": 0, "models": []}
    return agent.tower_briefing(facts, stats)


DEMO_NAMES = ["aarav", "diya", "rohan", "ananya", "karthik", "meera", "vikram", "sneha", "arjun", "priya", "rahul", "kavya"]


@app.post("/api/tower/demo")
def tower_demo(authorization: str = Header("")):
    """Fill the tower with 12 clearly labelled demo students (usernames start with demo_)."""
    admin(authorization)
    rng = random.Random(2026)
    comps = list(kb.COMPANIES)
    base = ["python", "oop", "dsa", "dbms", "sql", "os", "cn", "aptitude", "communication"]
    now, made = time.time(), 0
    for i, nm in enumerate(DEMO_NAMES):
        un = "demo_" + nm
        if db.q("SELECT 1 FROM users WHERE username=?", (un,), one=True):
            continue
        uid = db.ex("INSERT INTO users(username,pw_hash,salt,created) VALUES(?,?,?,?)",
                    (un, "demo-account-no-login", "x", now - 20 * 86400))
        strength = 0.22 + 0.7 * ((i * 7) % 12) / 11
        cid = comps[i % len(comps)]
        jd = list(dict.fromkeys(base + kb.COMPANIES[cid]["focus"]))
        matched = [s_ for s_ in jd if rng.random() < strength]
        missing = [s_ for s_ in jd if s_ not in matched]
        ats_s = max(20, min(92, int(30 + strength * 55 + rng.uniform(-6, 6))))
        res = {"role": f"{kb.COMPANIES[cid]['name']} fresher role (demo)", "company": cid, "jd_skills": jd,
               "matched": matched, "missing": missing, "match": round(100 * len(matched) / len(jd)),
               "ats": {"ats_score": ats_s, "keyword_coverage": int(ats_s * 0.6), "sections_found": ["education", "skills", "projects"],
                       "missing_sections": [], "action_verbs": [], "quantified_bullets": "0/0", "tips": []},
               "skill_names": {s_: kb.skill_name(s_) for s_ in kb.SKILLS}, "plan": [], "brief": {}, "resources": {},
               "interview_focus": missing[:3] + matched[:2], "weak_memory": [], "plan_hours": 2, "company_profile": company_card(cid)}
        t0 = now - rng.uniform(6, 14) * 86400
        res["readiness_at_run"] = readiness_now(res, {})
        rid = db.ex("INSERT INTO runs(user_id,created,role,status,jd,resume,trace,result,metrics) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uid, t0, res["role"], "done", "(demo)", "(demo)", "[]", json.dumps(res), "{}"))
        db.ex("INSERT INTO snapshots(user_id,run_id,created,readiness) VALUES(?,?,?,?)", (uid, rid, t0, res["readiness_at_run"]))
        n_ans = 2 + int(strength * 8)
        streak_days = int(strength * 6)
        for k in range(n_ans):
            sk = (missing + matched)[k % len(jd)]
            qs = kb.questions_for(sk) or kb.questions_for("communication")
            q = qs[k % len(qs)]
            score = max(0, min(10, round(rng.gauss(2 + 8 * strength, 1.5))))
            day_back = (n_ans - 1 - k) if k >= n_ans - streak_days else rng.uniform(streak_days + 1, 12)
            t = now - day_back * 86400 - rng.uniform(600, 7000)
            db.ex("INSERT INTO answers(user_id,run_id,qid,skill,question,answer,score,feedback,wpm,fillers,created) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid, rid, q[0], sk, q[3], "(demo answer)", score, "{}",
                                                     int(95 + strength * 50 + rng.uniform(-15, 15)), rng.randint(0, 6), t))
            db.update_mastery(uid, sk, score)
            db.ex("INSERT INTO snapshots(user_id,run_id,created,readiness) VALUES(?,?,?,?)",
                  (uid, rid, t, readiness_now(res, db.get_mastery(uid))))
        made += 1
    return {"created": made}


@app.post("/api/tower/demo/clear")
def tower_demo_clear(authorization: str = Header("")):
    admin(authorization)
    ids = [r["id"] for r in db.q("SELECT id FROM users WHERE username LIKE 'demo\\_%' ESCAPE '\\'")]
    for t in ("runs", "answers", "mastery", "snapshots", "sessions", "admins"):
        for i in ids:
            db.ex(f"DELETE FROM {t} WHERE user_id=?", (i,))
    for i in ids:
        db.ex("DELETE FROM users WHERE id=?", (i,))
    return {"removed": len(ids)}


# ================================================================ resume lab
@app.post("/api/resume/pdf")
def resume_pdf(p: PdfIn, authorization: str = Header("")):
    me(authorization)
    try:
        raw = base64.b64decode(p.data.split(",")[-1])
    except Exception:
        raise HTTPException(400, "Could not read the file")
    if len(raw) > 5_000_000:
        raise HTTPException(400, "PDF is larger than 5 MB")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:6])
    except Exception as e:
        raise HTTPException(400, f"Could not read this PDF ({type(e).__name__}). Paste the text instead.")
    if len(text.strip()) < 30:
        raise HTTPException(400, "No text found. This looks like a scanned image PDF, so paste the text instead.")
    return {"text": agent.normalize_resume(text), "pages": len(reader.pages), "name": p.name}


def default_jd(uid):
    r = db.q("SELECT jd FROM runs WHERE user_id=? AND status='done' AND jd!='(demo)' ORDER BY id DESC LIMIT 1", (uid,), one=True)
    return (r["jd"], "your latest flight's job description") if r else (kb.SAMPLE_JD, "the sample Infosys job description")


@app.post("/api/resume/rewrite")
def resume_rewrite(r: ResumeIn, authorization: str = Header("")):
    u = me(authorization)
    if len(r.resume.strip()) < 30:
        raise HTTPException(400, "Paste or upload a resume first")
    jd, label = (r.jd, "the job description you gave") if len(r.jd.strip()) > 30 else default_jd(u["id"])
    stats = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_seconds": 0, "models": []}
    out = agent.rewrite_resume(r.resume, jd, stats)
    out["jd_used"] = label
    return out


@app.post("/api/resume/score")
def resume_score(r: ResumeIn, authorization: str = Header("")):
    u = me(authorization)
    jd = r.jd if len(r.jd.strip()) > 30 else default_jd(u["id"])[0]
    return agent.t_ats_check({"resume": agent.normalize_resume(r.resume), "jd": jd})


NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"), headers=NO_CACHE)


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(WEB, "app.js"), media_type="application/javascript", headers=NO_CACHE)


@app.get("/bg.jpg")
def bg_jpg():
    f = os.path.join(WEB, "bg.jpg")
    if not os.path.exists(f):
        raise HTTPException(404, "no background")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/style.css")
def style_css():
    return FileResponse(os.path.join(WEB, "style.css"), media_type="text/css", headers=NO_CACHE)
