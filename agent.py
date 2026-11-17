"""PrepPilot agent crew.

Three agents share one state and hand off to each other:
  1. Analyst  - reads the job description and resume, compares skills, runs the ATS check, recalls memory
  2. Planner  - collects resources, builds a day-by-day study plan, schedules the mock interview
  3. Coach    - writes the final briefing
Each agent is a ReAct loop on Gemini function calling. If the model is unavailable
(no key, rate limit), the same tools run in a fixed order ("autopilot"), so a run never fails.
"""
import datetime as dt, json, os, re, time
import requests

import kb, db

API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
_models, _cool = None, {}
SKIP = ("tts", "image", "live", "audio", "embed", "exp", "native", "computer", "robotics")


class LLMError(Exception):
    pass


def api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def models():
    """Pick available Flash models once, using the ListModels endpoint."""
    global _models
    env = os.environ.get("GEMINI_MODELS", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    if _models:
        return _models
    try:
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": api_key()}, params={"pageSize": 200}, timeout=15)
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if "flash" in n and not any(s in n for s in SKIP)]
        alias = [n for n in ("gemini-flash-latest", "gemini-flash-lite-latest") if n in flash]

        def ver(n):
            m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return float(m.group(1)) if m else 0
        rest = sorted([n for n in flash if n not in alias], key=lambda n: (-ver(n), "preview" in n, "lite" in n, len(n)))
        _models = (alias + rest)[:6] or DEFAULT_MODELS
    except Exception:
        _models = DEFAULT_MODELS
    return _models


def generate(contents, system=None, tools=None, json_mode=False, temperature=0.3, stats=None):
    if not api_key():
        raise LLMError("No GEMINI_API_KEY set")
    body = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = "no model available"
    for m in models():
        if _cool.get(m, 0) > time.time():
            continue
        t0 = time.time()
        try:
            r = requests.post(f"{API}/models/{m}:generateContent", headers={"x-goog-api-key": api_key()},
                              json=body, timeout=60)
        except Exception as e:
            last = f"{m}: {e}"
            continue
        if r.status_code == 200:
            d = r.json()
            c = (d.get("candidates") or [{}])[0].get("content")
            if not c or not c.get("parts"):
                last = f"{m}: empty response"
                continue
            u = d.get("usageMetadata", {})
            if stats is not None:
                stats["llm_calls"] += 1
                stats["tokens_in"] += u.get("promptTokenCount", 0)
                stats["tokens_out"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
                stats["llm_seconds"] = round(stats["llm_seconds"] + time.time() - t0, 2)
                if m not in stats["models"]:
                    stats["models"].append(m)
            return c, m
        last = f"{m}: HTTP {r.status_code} {r.text[:160]}"
        _cool[m] = time.time() + (3600 if r.status_code in (400, 403, 404) else 60)
    raise LLMError(last)


def text_of(content):
    return " ".join(p.get("text", "") for p in content.get("parts", []) if p.get("text") and not p.get("thought")).strip()


def parse_json(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        return json.loads(m.group(0)) if m else {}


# ---------------------------------------------------------------- tools
ACTION_VERBS = ["built", "developed", "designed", "implemented", "created", "led", "deployed", "trained",
                "improved", "optimized", "analyzed", "automated", "engineered", "integrated", "reduced"]
SECTIONS = {"education": r"education|b\.?e\.?|b\.?tech|university|college", "skills": r"skills",
            "projects": r"projects?", "experience": r"experience|internship", "achievements": r"achievements?|awards?|certific"}


def role_of(jd):
    first = next((l.strip() for l in jd.splitlines() if l.strip()), "Target role")
    return first[:80]


def t_read_job_description(S, **_):
    S["jd_skills"] = kb.extract_skills(S["jd"])
    S["role"] = role_of(S["jd"])
    return {"role": S["role"], "required_skills": [kb.skill_name(s) for s in S["jd_skills"]],
            "words": len(S["jd"].split())}


def t_read_resume(S, **_):
    S["cv_skills"] = kb.extract_skills(S["resume"])
    return {"skills_found": [kb.skill_name(s) for s in S["cv_skills"]],
            "has_numbers": bool(re.search(r"\d", S["resume"])), "words": len(S["resume"].split())}


def t_compare_skills(S, **_):
    S.setdefault("jd_skills", kb.extract_skills(S["jd"]))
    S.setdefault("cv_skills", kb.extract_skills(S["resume"]))
    req, have = S["jd_skills"], set(S["cv_skills"])
    matched = [s for s in req if s in have]
    missing = [s for s in req if s not in have]
    S["matched"], S["missing"] = matched, missing
    S["match"] = round(100 * len(matched) / max(1, len(req)))
    return {"match_percent": S["match"], "matched": [kb.skill_name(s) for s in matched],
            "missing": [kb.skill_name(s) for s in missing],
            "extra_strengths": [kb.skill_name(s) for s in S["cv_skills"] if s not in req]}


def t_ats_check(S, **_):
    cv = S["resume"].lower()
    jd_words = {w for w in re.findall(r"[a-z][a-z+#.]{2,}", S["jd"].lower())} - STOP
    cov = [w for w in jd_words if w in cv]
    keyword = round(100 * len(cov) / max(1, len(jd_words)))
    found = [k for k, p in SECTIONS.items() if re.search(p, cv)]
    verbs = sorted({v for v in ACTION_VERBS if re.search(r"\b" + v + r"\b", cv)})
    lines = [l for l in S["resume"].splitlines() if l.strip().startswith(("-", "•", "*"))]
    quant = sum(1 for l in lines if re.search(r"\d", l))
    score = round(0.45 * min(100, keyword * 2) + 0.25 * 100 * len(found) / len(SECTIONS)
                  + 0.15 * min(100, len(verbs) * 25) + 0.15 * (100 * quant / max(1, len(lines))))
    tips = []
    if "experience" not in found:
        tips.append("Add an Experience or Internship section, even for a strong academic project")
    if len(verbs) < 4:
        tips.append("Start bullets with varied action verbs such as Designed, Deployed, Optimized")
    if quant < max(1, len(lines)) * 0.6:
        tips.append("Add numbers to more bullets (dataset size, accuracy, users, speed-up)")
    miss = [kb.skill_name(s) for s in S.get("missing", [])]
    if miss:
        tips.append("Mention these job keywords if you know them: " + ", ".join(miss[:5]))
    S["ats"] = {"ats_score": min(100, score), "keyword_coverage": keyword, "sections_found": found,
                "missing_sections": [k for k in SECTIONS if k not in found], "action_verbs": verbs,
                "quantified_bullets": f"{quant}/{len(lines)}", "tips": tips}
    return S["ats"]


def t_recall_memory(S, **_):
    m = db.get_mastery(S["uid"])
    runs = db.q("SELECT COUNT(*) n FROM runs WHERE user_id=? AND status='done'", (S["uid"],), one=True)["n"]
    weak = sorted([(v[0], k) for k, v in m.items() if v[0] < 60])
    S["weak_memory"] = [k for _, k in weak]
    return {"past_runs": runs, "skills_practised": {kb.skill_name(k): v[0] for k, v in m.items()},
            "weak_from_past_interviews": [kb.skill_name(k) for k in S["weak_memory"]]}


def _ids(names):
    out = []
    for n in names or []:
        n2 = str(n).lower()
        for sid, (disp, _) in kb.SKILLS.items():
            if n2 in (sid, disp.lower()) or (len(n2) > 3 and n2 in disp.lower()):
                out.append(sid)
                break
    return list(dict.fromkeys(out))


def t_find_resources(S, skills=None, **_):
    ids = _ids(skills) or S.get("missing", [])
    S["resources"] = {s: [{"title": t, "url": u, "kind": k} for t, u, k in kb.RESOURCES.get(s, [])] for s in ids}
    return {kb.skill_name(s): [r["title"] for r in v] for s, v in S["resources"].items()}


def t_build_study_plan(S, days=7, hours_per_day=2, priority_skills=None, **_):
    days = max(3, min(14, int(days or 7)))
    hours = max(1.0, min(6.0, float(hours_per_day or 2)))
    pri = _ids(priority_skills) or []
    weak = [s for s in S.get("weak_memory", []) if s in S.get("jd_skills", [])]
    order = list(dict.fromkeys(pri + weak + S.get("missing", []) + S.get("matched", [])))
    if not order:
        order = ["dsa", "aptitude", "communication"]
    start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5.5)).date() + dt.timedelta(days=1)
    plan = []
    for d in range(days):
        last = d == days - 1
        sk = order[d % len(order)]
        res = (kb.RESOURCES.get(sk) or [("Search: " + kb.skill_name(sk), kb.yt(kb.skill_name(sk) + " tutorial hindi"), "video")])[0]
        blocks = []
        if last:
            blocks = [{"what": "Full mock interview in the PrepPilot cockpit", "mins": int(hours * 30)},
                      {"what": "Revise the weakest two topics from your logbook", "mins": int(hours * 30)}]
        else:
            blocks = [{"what": f"Learn {kb.skill_name(sk)}: {res[0]}", "url": res[1], "mins": int(hours * 60 * 0.5)},
                      {"what": "DSA practice: 2 problems from the Striver A2Z sheet", "mins": int(hours * 60 * 0.3)},
                      {"what": "Aptitude: 10 questions on IndiaBIX" if d % 2 == 0 else "Answer 2 interview questions aloud",
                       "mins": int(hours * 60 * 0.2)}]
        plan.append({"day": d + 1, "date": (start + dt.timedelta(days=d)).isoformat(),
                     "focus": "Mock interview + revision" if last else kb.skill_name(sk), "blocks": blocks})
    S["plan"] = plan
    S["plan_hours"] = hours
    return {"days": days, "hours_per_day": hours, "focus_order": [p["focus"] for p in plan]}


def t_schedule_mock_interview(S, focus_skills=None, **_):
    ids = _ids(focus_skills) or (S.get("weak_memory", []) + S.get("missing", []) + S.get("matched", []))
    ids = [s for s in dict.fromkeys(ids) if kb.questions_for(s)][:5]
    S["interview_focus"] = ids
    return {"focus": [kb.skill_name(s) for s in ids],
            "questions_ready": sum(len(kb.questions_for(s)) for s in ids)}


STOP = set("the and for with are you our will join this that from have has who can not but all any job role team "
           "good strong looking basics plus exposure requirements selection online test interview graduates "
           "engineering engineer engineers freshers concepts fundamentals".split())

TOOLS = {
    "read_job_description": (t_read_job_description, "Read the job description and list the role and required skills.", {}),
    "read_resume": (t_read_resume, "Read the candidate's resume and list the skills it shows.", {}),
    "compare_skills": (t_compare_skills, "Compare required skills with resume skills. Returns match %, matched and missing skills.", {}),
    "ats_check": (t_ats_check, "Score the resume like an Applicant Tracking System: keyword coverage, sections, action verbs, numbers.", {}),
    "recall_memory": (t_recall_memory, "Recall this user's past interview scores from the database to find weak skills.", {}),
    "find_resources": (t_find_resources, "Get curated learning resources for skills.",
                       {"skills": {"type": "array", "items": {"type": "string"}, "description": "skill names"}}),
    "build_study_plan": (t_build_study_plan, "Build a day-by-day study plan with dates, focusing on priority skills first.",
                         {"days": {"type": "integer"}, "hours_per_day": {"type": "number"},
                          "priority_skills": {"type": "array", "items": {"type": "string"}}}),
    "schedule_mock_interview": (t_schedule_mock_interview, "Choose which skills the mock interview should test first.",
                                {"focus_skills": {"type": "array", "items": {"type": "string"}}}),
}


def decls(names):
    out = []
    for n in names:
        _, desc, props = TOOLS[n]
        d = {"name": n, "description": desc}
        if props:
            d["parameters"] = {"type": "object", "properties": props}
        out.append(d)
    return out


AGENTS = [
    ("Analyst", "Find out how ready the candidate is for this job.",
     ["read_job_description", "read_resume", "compare_skills", "ats_check", "recall_memory"]),
    ("Planner", "Turn the gaps into a realistic study plan and prepare the mock interview.",
     ["find_resources", "build_study_plan", "schedule_mock_interview"]),
]


def run_crew(S, log, stats):
    """S: shared state (jd, resume, uid, days, hours). log(agent, type, text, data=None)."""
    for name, goal, tools in AGENTS:
        log(name, "handoff", f"{name} agent takes control. Goal: {goal}")
        sys = (f"You are the {name} agent in PrepPilot, a placement preparation crew. Goal: {goal} "
               f"Use the tools; call every tool at least once, in a sensible order. Before each tool call write one short "
               f"sentence starting with 'Thought:' explaining why. The user wants a {S['days']}-day plan with "
               f"{S['hours']} hours per day. When finished, reply with a 2-sentence handoff note for the next agent.")
        ctx = {"analysis_so_far": {k: S[k] for k in ("role", "match", "missing", "weak_memory") if k in S}}
        contents = [{"role": "user", "parts": [{"text": "Start. Context: " + json.dumps(ctx, default=str)}]}]
        used, steps, auto = set(), 0, False
        while steps < 10:
            steps += 1
            try:
                content, model = generate(contents, system=sys, tools=decls(tools), stats=stats)
            except LLMError as e:
                log(name, "error", "Model unavailable, switching to autopilot: " + str(e)[:140])
                auto = True
                break
            contents.append(content)
            calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
            thought = text_of(content)
            if thought:
                log(name, "thought", thought.replace("Thought:", "").strip(), {"model": model})
            if not calls:
                break
            resp = []
            for c in calls:
                obs = call_tool(name, c["name"], c.get("args") or {}, S, log, stats)
                used.add(c["name"])
                resp.append({"functionResponse": {"name": c["name"], "response": {"result": obs}}})
            contents.append({"role": "user", "parts": resp})
        for t in tools:  # autopilot / safety net: make sure every tool ran
            if t not in used:
                if not auto:
                    log(name, "thought", f"Checking that nothing was skipped: running {t}.")
                else:
                    time.sleep(0.4)
                    log(name, "thought", f"Autopilot: running {t}.")
                args = {"days": S["days"], "hours_per_day": S["hours"]} if t == "build_study_plan" else {}
                call_tool(name, t, args, S, log, stats)
        stats["autopilot"] = stats["autopilot"] or auto
    coach(S, log, stats)


def call_tool(agent, name, args, S, log, stats):
    fn = TOOLS.get(name, (None,))[0]
    log(agent, "tool", f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})")
    stats["tool_calls"] += 1
    if not fn:
        obs = {"error": "unknown tool"}
    else:
        try:
            if name == "build_study_plan":
                args["days"], args["hours_per_day"] = S["days"], S["hours"]  # the user's choice wins
            obs = fn(S, **args)
        except Exception as e:
            obs = {"error": str(e)}
    log(agent, "obs", json.dumps(obs, default=str)[:600], obs)
    return obs


def coach(S, log, stats):
    log("Coach", "handoff", "Coach agent takes control. Goal: write the final briefing.")
    brief = None
    facts = {"role": S.get("role"), "match": S.get("match"), "matched": [kb.skill_name(s) for s in S.get("matched", [])],
             "missing": [kb.skill_name(s) for s in S.get("missing", [])], "ats": S.get("ats", {}).get("ats_score"),
             "weak_memory": [kb.skill_name(s) for s in S.get("weak_memory", [])]}
    try:
        c, model = generate([{"role": "user", "parts": [{"text":
            "Facts from the other agents: " + json.dumps(facts) +
            '\nWrite JSON: {"headline": one encouraging sentence with the match %, "actions": 3 short concrete next steps,'
            ' "interview_tip": one sentence}. Use only these facts.'}]}], json_mode=True, stats=stats)
        brief = parse_json(text_of(c))
        log("Coach", "thought", "Briefing written from the Analyst and Planner results.", {"model": model})
    except Exception as e:
        log("Coach", "error", "Model unavailable, using template briefing: " + str(e)[:120])
    if not brief or "headline" not in brief:
        miss = facts["missing"]
        brief = {"headline": f"You match {facts['match']}% of this role. Close {len(miss)} gaps and you are ready.",
                 "actions": [f"Start with {miss[0]} today" if miss else "Revise your strongest skills",
                             "Do 2 DSA problems every day", "Take a mock interview in the cockpit"],
                 "interview_tip": "Answer in 3 parts: definition, example from your project, why it matters."}
    brief["actions"] = [a if isinstance(a, str) else " ".join(str(v) for v in (a.values() if isinstance(a, dict) else [a]))
                        for a in (brief.get("actions") or [])][:4]
    brief["headline"], brief["interview_tip"] = str(brief.get("headline", "")), str(brief.get("interview_tip", ""))
    S["brief"] = brief
    log("Coach", "final", brief.get("headline", ""))


def readiness(S, mastery):
    js = S.get("jd_skills", [])
    avg_m = sum(mastery.get(s, (0, 0))[0] for s in js) / max(1, len(js))
    return round(0.55 * S.get("match", 0) + 0.25 * S.get("ats", {}).get("ats_score", 0) + 0.20 * avg_m)


# ---------------------------------------------------------------- interview
def next_question(uid, focus, jd_skills, asked):
    m = db.get_mastery(uid)
    base = [s for s in (focus or jd_skills or ["oop", "dbms", "communication"]) if kb.questions_for(s)]
    for s in (jd_skills or []):
        if s not in base and kb.questions_for(s):
            base.append(s)
    pool = sorted(base, key=lambda s: (m.get(s, (-1, 0))[0], base.index(s)))
    for s in pool:
        score = m.get(s, (None, 0))[0]
        level = 1 if score is None or score < 50 else (2 if score < 75 else 3)
        qs = [q for q in kb.questions_for(s) if q[0] not in asked]
        if qs:
            qs.sort(key=lambda q: abs(q[2] - level))
            q = qs[0]
            why = ("never tested before" if score is None else f"your mastery is {score:.0f}/100")
            return {"qid": q[0], "skill": s, "skill_name": kb.skill_name(s), "level": q[2], "question": q[3],
                    "why": f"Chosen because {kb.skill_name(s)} is in the job description and {why}."}
    q = kb.QUESTIONS[len(asked) % len(kb.QUESTIONS)]
    return {"qid": q[0], "skill": q[1], "skill_name": kb.skill_name(q[1]), "level": q[2], "question": q[3],
            "why": "Bonus question from the bank."}


def _covered(point, ans):
    words = [w for w in re.findall(r"[a-z0-9/()+]+", point.lower()) if len(w) > 2 and w not in STOP]
    if not words:
        return False
    hit = sum(1 for w in words if w[:5] in ans)
    return hit / len(words) >= 0.5


def evaluate(qid, answer, stats):
    q = kb.QUESTION_BY_ID[qid]
    ans = (answer or "").lower()
    cov = [p for p in q[4] if _covered(p, ans)]
    rubric = {"covered": cov, "missed": [p for p in q[4] if p not in cov], "rubric_score": round(10 * len(cov) / len(q[4]), 1)}
    try:
        c, model = generate([{"role": "user", "parts": [{"text":
            f"You are a strict but kind technical interviewer for Indian campus placements.\nQuestion: {q[3]}\n"
            f"Rubric key points: {q[4]}\nCandidate answer: {answer}\n"
            'Return JSON: {"score": 0-10 integer, "covered": [key points covered], "missed": [key points missed], '
            '"feedback": "2 sentences, specific", "model_answer": "3-4 line ideal answer", "follow_up": "one follow-up question"}'}]}],
            json_mode=True, stats=stats)
        r = parse_json(text_of(c))
        r["score"] = max(0, min(10, int(round(float(r.get("score", rubric["rubric_score"]))))))
        r["model"] = model
    except Exception:
        r = {"score": int(round(rubric["rubric_score"])), "covered": cov, "missed": rubric["missed"],
             "feedback": ("Good coverage of the key points." if len(cov) >= len(q[4]) / 2 else
                          "Cover more of the key points: " + "; ".join(rubric["missed"][:3]) + "."),
             "model_answer": "Key points: " + "; ".join(q[4]) + ".", "follow_up": "", "model": "rubric (offline)"}
    r["rubric"] = rubric
    r["source"] = f"PrepPilot question bank #{qid}"
    return r
