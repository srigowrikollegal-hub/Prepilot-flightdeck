"""PrepPilot Flight Deck - FastAPI backend.

Run locally:  uvicorn server.main:app --reload   (from the project folder)
API docs:     /docs
"""
import datetime as dt, json, os, sys, threading, time

sys.path.insert(0, os.path.dirname(__file__))
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent, db, kb

app = FastAPI(title="PrepPilot Flight Deck API", version="2.0",
              description="Backend for PrepPilot: multi-agent placement preparation with memory.")
WEB = os.path.join(os.path.dirname(__file__), "..", "web")
LIVE = {}  # run_id -> live state while the crew is working
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
    return me(authorization)


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
    S = {"jd": r.jd, "resume": r.resume, "uid": u["id"], "days": r.days, "hours": r.hours}
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
            "brief": S.get("brief", {}), "readiness_at_run": agent.readiness(S, m)}


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
    return agent.next_question(u["id"], res.get("interview_focus"), res.get("jd_skills"), asked)


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
    r["mastery"] = db.get_mastery(u["id"]).get(q[1], (0, 0))[0]
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


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
