// PrepPilot Flight Deck - frontend
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const st = { token: null, user: null, runId: null, run: null, q: null };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} },
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, opts = {}) {
  const r = await fetch(path, {
    method: opts.body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", Authorization: st.token || "" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && st.token) { logout(); throw new Error("Session expired, please log in"); }
  if (!r.ok) throw new Error(d.detail || "Request failed");
  return d;
}
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }

/* ---------------- auth ---------------- */
async function auth(mode) {
  $("#lerr").textContent = "";
  const body = { username: $("#lu").value, password: $("#lp").value };
  try {
    const d = await api("/api/auth/" + mode, { body });
    st.token = d.token; st.user = d.username; store.set("pp_token", d.token); store.set("pp_user", d.username);
    enter();
  } catch (e) { $("#lerr").textContent = e.message; }
}
$("#loginForm").addEventListener("submit", (e) => { e.preventDefault(); auth("login"); });
$("#regBtn").addEventListener("click", () => { if ($("#loginForm").reportValidity()) auth("register"); });
function logout() { st.token = null; store.set("pp_token", null); $("#app").classList.add("hidden"); $("#gate").classList.remove("hidden"); }
$("#logout").addEventListener("click", logout);

async function enter() {
  $("#gate").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#whoName").textContent = st.user;
  const last = store.get("pp_run_" + st.user);
  if (last) { try { await loadRun(+last, false); } catch (e) {} }
  go(location.hash.slice(1) || "preflight");
}

/* ---------------- router ---------------- */
function go(page) {
  if (!document.getElementById(page)) page = "preflight";
  $$(".page").forEach((p) => p.classList.toggle("hidden", p.id !== page));
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.go === page));
  history.replaceState(null, "", "#" + page);
  if (page === "plan") renderPlan();
  if (page === "cockpit") openCockpit();
  if (page === "logbook") renderLogbook();
  window.scrollTo(0, 0);
}
document.addEventListener("click", (e) => { const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); go(a.dataset.go); } });

/* ---------------- pre-flight + black box ---------------- */
$("#sample").addEventListener("click", async () => { const d = await api("/api/samples"); $("#jd").value = d.jd; $("#cv").value = d.resume; });
$("#takeoff").addEventListener("click", async () => {
  const btn = $("#takeoff");
  try {
    btn.disabled = true; btn.textContent = "Crew working…";
    const d = await api("/api/runs", { body: { jd: $("#jd").value, resume: $("#cv").value, days: +$("#days").value, hours: +$("#hours").value } });
    st.runId = d.run_id; st.run = null; st.q = null;
    $("#tape").innerHTML = ""; seen = 0; $("#rec").classList.add("on"); $("#bbStatus").textContent = "RECORDING · FLIGHT #" + d.run_id;
    $$(".crewm").forEach((c) => c.classList.remove("on", "done"));
    poll();
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Take off ▸"; }
});
let seen = 0;
function addEvents(trace) {
  const tape = $("#tape");
  for (; seen < trace.length; seen++) {
    const e = trace[seen];
    if (e.type === "handoff") {
      $$(".crewm").forEach((c) => { if (c.classList.contains("on")) { c.classList.remove("on"); c.classList.add("done"); } });
      const c = document.querySelector(`.crewm[data-agent="${e.agent}"]`); if (c) c.classList.add("on");
    }
    const label = { thought: "THINK", tool: "ACT ▸", obs: "OBSERVE", handoff: "HANDOFF", final: "DONE", error: "ALERT" }[e.type] || e.type;
    const div = document.createElement("div");
    div.className = "ev " + e.type;
    div.innerHTML = `<span class="t">${e.t.toFixed(1)}s</span><span class="k">${label}</span><span class="a">${esc(e.agent)}</span>${esc(e.text)}`;
    tape.appendChild(div);
  }
  tape.scrollTop = tape.scrollHeight;
}
async function poll() {
  try {
    const d = await api("/api/runs/" + st.runId);
    addEvents(d.trace || []);
    $("#opsLive").textContent = `events ${d.trace.length} · ${d.status}`;
    if (d.status === "running") return setTimeout(poll, 800);
    $("#rec").classList.remove("on");
    $$(".crewm").forEach((c) => { c.classList.remove("on"); c.classList.add("done"); });
    const btn = $("#takeoff"); btn.disabled = false; btn.textContent = "Take off ▸";
    if (d.status === "done") {
      st.run = d; store.set("pp_run_" + st.user, d.id);
      const m = d.metrics;
      $("#bbStatus").textContent = "LANDED · " + m.seconds + "s";
      $("#opsLive").innerHTML = `${m.tool_calls} tool calls · ${m.llm_calls} LLM calls · ${(m.tokens_in + m.tokens_out).toLocaleString()} tokens · ${m.autopilot ? "autopilot used" : esc(m.models.join(", "))}
        <br><button class="btn small primary" data-go="plan" style="margin-top:10px">Open flight plan ▸</button>`;
      toast("Landed. Your flight plan is ready.");
    } else { $("#bbStatus").textContent = "FAILED"; toast("The run failed. Try again."); }
  } catch (e) { toast(e.message); setTimeout(poll, 2000); }
}
async function loadRun(id, nav = true) {
  const d = await api("/api/runs/" + id);
  if (d.status !== "done") throw new Error("Run not finished");
  st.run = d; st.runId = id; st.q = null; store.set("pp_run_" + st.user, id);
  $("#tape").innerHTML = ""; seen = 0; addEvents(d.trace); $("#bbStatus").textContent = "REPLAY · FLIGHT #" + id;
  if (nav) go("plan");
}

/* ---------------- flight plan ---------------- */
function gauge(el, val, label, color) {
  const v = Math.max(0, Math.min(100, val || 0)), a = Math.PI * (1 - v / 100);
  const x = 60 + 46 * Math.cos(a), y = 60 - 46 * Math.sin(a);
  el.innerHTML = `<svg width="120" height="72" viewBox="0 0 120 72"><path d="M14 60 A46 46 0 0 1 106 60" fill="none" stroke="#24405f" stroke-width="10" stroke-linecap="round"/>
    <path d="M14 60 A46 46 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"/>
    <line x1="60" y1="60" x2="${(60 + 34 * Math.cos(a)).toFixed(1)}" y2="${(60 - 34 * Math.sin(a)).toFixed(1)}" stroke="#fff" stroke-width="2.5"/><circle cx="60" cy="60" r="4" fill="#fff"/></svg>
    <div class="v">${Math.round(v)}</div><div class="l">${label}</div>`;
}
function radar(res) {
  const sk = res.jd_skills, n = sk.length, N = res.skill_names, have = new Set(res.matched), M = res.mastery || {};
  if (n < 3) { $("#radar").innerHTML = "<p class='note'>Need 3+ skills for a radar.</p>"; return; }
  const cx = 170, cy = 150, R = 110, pt = (i, r) => [cx + r * Math.sin((2 * Math.PI * i) / n), cy - r * Math.cos((2 * Math.PI * i) / n)];
  let g = "";
  [0.33, 0.66, 1].forEach((f) => { g += `<polygon points="${sk.map((_, i) => pt(i, R * f).join(",")).join(" ")}" fill="none" stroke="#d6c9b2" stroke-dasharray="${f < 1 ? "3 3" : ""}"/>`; });
  const val = (s) => Math.max(have.has(s) ? 0.7 : 0.12, (M[s] || 0) / 100);
  const poly = sk.map((s, i) => pt(i, R * val(s)).join(",")).join(" ");
  g += `<polygon points="${poly}" fill="rgba(255,106,43,.25)" stroke="#ff6a2b" stroke-width="2"/>`;
  sk.forEach((s, i) => {
    const [x, y] = pt(i, R + 18), [px, py] = pt(i, R * val(s));
    g += `<circle cx="${px}" cy="${py}" r="3.5" fill="${have.has(s) ? "#1f9b6f" : "#ff6a2b"}"/>
      <text x="${x}" y="${y}" font-size="10.5" font-family="IBM Plex Sans" text-anchor="${x < cx - 5 ? "end" : x > cx + 5 ? "start" : "middle"}" dominant-baseline="middle" fill="#1c1b19">${esc(N[s])}</text>`;
  });
  $("#radar").innerHTML = `<svg viewBox="-60 0 460 300" width="100%">${g}</svg>`;
}
function renderPlan() {
  const d = st.run;
  $("#planEmpty").classList.toggle("hidden", !!d); $("#planBody").classList.toggle("hidden", !d);
  if (!d) return;
  const r = d.result, N = r.skill_names;
  $("#pRole").textContent = r.role; $("#pHead").textContent = r.brief.headline || "";
  $("#pChips").innerHTML = r.matched.map((s) => `<span class="chip ok">${esc(N[s])}</span>`).join("") + r.missing.map((s) => `<span class="chip miss">${esc(N[s])}</span>`).join("");
  gauge($("#gReady"), r.readiness, "READINESS", "#2fd6a0"); gauge($("#gMatch"), r.match, "SKILL MATCH", "#ffb02e"); gauge($("#gAts"), r.ats.ats_score, "ATS SCORE", "#ff6a2b");
  radar(r);
  const a = r.ats;
  $("#atsPill").textContent = a.ats_score + "/100";
  const bar = (l, v, t) => `<div class="bar"><span>${l}</span><div class="track"><div class="fill" style="width:${v}%"></div></div><b>${t ?? v + "%"}</b></div>`;
  $("#ats").innerHTML = bar("Keyword coverage", a.keyword_coverage) + bar("Sections", Math.round((100 * a.sections_found.length) / 5), a.sections_found.length + "/5") +
    bar("Action verbs", Math.min(100, a.action_verbs.length * 25), a.action_verbs.length) +
    bar("Numbers in bullets", (() => { const [x, y] = a.quantified_bullets.split("/").map(Number); return y ? Math.round((100 * x) / y) : 0; })(), a.quantified_bullets) +
    `<ul class="tips">${a.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  $("#actions").innerHTML = (r.brief.actions || []).map((x) => `<li>${esc(x)}</li>`).join("");
  $("#tip").innerHTML = "<b>Interview tip:</b> " + esc(r.brief.interview_tip || "");
  $("#memNote").textContent = r.weak_memory.length ? "Memory: earlier interviews showed weakness in " + r.weak_memory.map((s) => N[s]).join(", ") + ", so these come first." : "Memory: no past interviews yet. Your scores from the cockpit will shape the next plan.";
  $("#itin").innerHTML = r.plan.map((p) => `<div class="day"><div class="d">DAY ${p.day}</div><div class="date">${new Date(p.date + "T00:00").toDateString()}</div>
    <div class="f">${esc(p.focus)}</div><ul>${p.blocks.map((b) => `<li>${b.url ? `<a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.what)}</a>` : esc(b.what)} <span>${b.mins}m</span></li>`).join("")}</ul></div>`).join("");
  $("#icsBtn").href = `/api/runs/${d.id}/plan.ics?token=${encodeURIComponent(st.token)}`;
  const m = d.metrics || {};
  const cell = (v, l) => `<div><b>${v}</b><span>${l}</span></div>`;
  $("#ops").innerHTML = cell(m.seconds + "s", "flight time") + cell(m.tool_calls, "tool calls") + cell(m.llm_calls, "LLM calls") +
    cell((m.tokens_in || 0).toLocaleString(), "tokens in") + cell((m.tokens_out || 0).toLocaleString(), "tokens out") +
    cell(m.autopilot ? "ON" : "OFF", "autopilot") + cell("₹0", "cost (free tier)") + `<div style="grid-column:span 2"><b style="font-size:13px">${esc((m.models || []).join(", ") || "rule-based")}</b><span>models used</span></div>`;
}

/* ---------------- cockpit ---------------- */
async function openCockpit() {
  $("#ckEmpty").classList.toggle("hidden", !!st.run); $("#ckBody").classList.toggle("hidden", !st.run);
  if (st.run && !st.q) await nextQ();
}
async function nextQ() {
  const q = await api("/api/interview/next?run_id=" + st.run.id);
  st.q = q; $("#ans").value = ""; resetHud();
  $("#qSkill").textContent = q.skill_name; $("#qLvl").textContent = ["", "EASY", "MEDIUM", "HARD"][q.level];
  $("#qSrc").textContent = "bank #" + q.qid; $("#qText").textContent = q.question; $("#qWhy").textContent = q.why;
}
let t0 = null, tick = null;
const FILLERS = /\b(um+|uh+|like|basically|actually|you know|so+|matlab|na)\b/gi;
function resetHud() { t0 = null; clearInterval(tick); $("#tmr").textContent = "0:00"; $("#wpm").textContent = "0"; $("#fill").textContent = "0"; }
function hud() {
  if (!t0) { t0 = Date.now(); tick = setInterval(hud, 1000); }
  const s = (Date.now() - t0) / 1000, txt = $("#ans").value, words = (txt.match(/\S+/g) || []).length;
  $("#tmr").textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  $("#wpm").textContent = s > 5 ? Math.round(words / (s / 60)) : 0;
  $("#fill").textContent = (txt.match(FILLERS) || []).length;
}
$("#ans").addEventListener("input", hud);
let rec = null, recOn = false, base = "";
$("#mic").addEventListener("click", () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast("Voice needs Chrome. You can type instead.");
  if (recOn) { rec.stop(); return; }
  rec = new SR(); rec.lang = "en-IN"; rec.continuous = true; rec.interimResults = true;
  base = $("#ans").value ? $("#ans").value + " " : "";
  rec.onresult = (e) => { let s = ""; for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript; $("#ans").value = base + s; hud(); };
  rec.onend = () => { recOn = false; $("#mic").classList.remove("live"); $("#mic").textContent = "🎙 Speak answer"; $("#micState").textContent = ""; };
  rec.onerror = (e) => toast("Mic: " + e.error);
  rec.start(); recOn = true; $("#mic").classList.add("live"); $("#mic").textContent = "■ Stop"; $("#micState").textContent = "● LISTENING"; hud();
});
$("#speak").addEventListener("click", () => {
  if (!window.speechSynthesis || !st.q) return;
  const u = new SpeechSynthesisUtterance(st.q.question); u.lang = "en-IN"; u.rate = 0.95; speechSynthesis.cancel(); speechSynthesis.speak(u);
});
$("#submitAns").addEventListener("click", async () => {
  if (!st.q) return;
  const answer = $("#ans").value.trim();
  if (answer.split(/\s+/).length < 3) return toast("Say or type a bit more first.");
  if (recOn) rec.stop();
  const btn = $("#submitAns"); btn.disabled = true; btn.textContent = "Grading…";
  const secs = t0 ? (Date.now() - t0) / 1000 : 0;
  try {
    const r = await api("/api/interview/answer", { body: { run_id: st.run.id, qid: st.q.qid, answer, wpm: +$("#wpm").textContent, fillers: +$("#fill").textContent, seconds: secs } });
    clearInterval(tick);
    const col = r.score >= 7 ? "#1f9b6f" : r.score >= 4 ? "#d98a00" : "#e5484d";
    const cov = r.covered || [], mis = r.missed || [];
    $("#evalBody").className = "";
    $("#evalBody").innerHTML = `<div class="score"><div class="dial" style="background:${col}">${r.score}<small>/10</small></div>
      <div><div class="mono" style="color:#8fa3bd;font-size:12px">RUBRIC ${r.rubric.covered.length}/${r.rubric.covered.length + r.rubric.missed.length} KEY POINTS · ${esc(r.source)}</div>
      <div style="font-size:14px;margin-top:6px">${esc(st.q.skill_name)} mastery now <b style="color:#2fd6a0">${Math.round(r.mastery)}/100</b> (saved)</div>
      <div class="mono" style="color:#8fa3bd;font-size:12px;margin-top:4px">${$("#wpm").textContent} WPM · ${$("#fill").textContent} fillers · graded by ${esc(r.model)}</div></div></div>
      <div class="rub">${cov.map((c) => `<div class="y">${esc(c)}</div>`).join("")}${mis.map((c) => `<div class="n">${esc(c)}</div>`).join("")}</div>
      <div class="box"><b>FEEDBACK</b>${esc(r.feedback)}</div>
      <div class="box"><b>MODEL ANSWER</b>${esc(r.model_answer)}</div>
      ${r.follow_up ? `<div class="box"><b>FOLLOW-UP THEY MIGHT ASK</b>${esc(r.follow_up)}</div>` : ""}
      <button class="btn small primary" id="nextQ" style="margin-top:6px">Next question ▸</button>`;
    $("#nextQ").onclick = () => { nextQ(); $("#evalBody").className = "tape-empty"; $("#evalBody").textContent = "Answer the next question."; };
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Submit for grading";
});

/* ---------------- logbook ---------------- */
async function renderLogbook() {
  const [p, runs] = await Promise.all([api("/api/progress"), api("/api/runs")]);
  const a = p.answers;
  if (a.length < 2) $("#trend").innerHTML = `<p class="note">Answer at least 2 questions in the cockpit to see your trend.</p>`;
  else {
    const W = 520, H = 180, x = (i) => 30 + (i * (W - 50)) / (a.length - 1), y = (s) => H - 20 - (s / 10) * (H - 40);
    const pts = a.map((r, i) => `${x(i)},${y(r.score)}`).join(" ");
    $("#trend").innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%">${[0, 5, 10].map((s) => `<line x1="30" x2="${W - 20}" y1="${y(s)}" y2="${y(s)}" stroke="#e4d9c6"/><text x="22" y="${y(s) + 4}" font-size="10" text-anchor="end" fill="#6f6656">${s}</text>`).join("")}
      <polyline points="${pts}" fill="none" stroke="#ff6a2b" stroke-width="2.5"/>${a.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.score)}" r="4" fill="#1c1b19"><title>${r.qid}: ${r.score}/10</title></circle>`).join("")}</svg>`;
  }
  const wpms = a.filter((r) => r.wpm > 0).map((r) => r.wpm);
  $("#lbStats").innerHTML = `<div><b>${a.length}</b><span>ANSWERS</span></div><div><b>${p.avg_score ?? "–"}</b><span>AVG SCORE</span></div>
    <div><b>${wpms.length ? Math.round(wpms.reduce((x, y) => x + y) / wpms.length) : "–"}</b><span>AVG WPM</span></div><div><b>${p.runs}</b><span>FLIGHTS</span></div>`;
  const ms = Object.entries(p.mastery).sort((x, y) => x[1].score - y[1].score);
  $("#mastery").innerHTML = ms.length ? ms.map(([k, v]) => `<div class="bar"><span>${esc(k)}</span><div class="track"><div class="fill" style="width:${v.score}%;background:${v.score >= 70 ? "#1f9b6f" : v.score >= 45 ? "#d98a00" : "#ff6a2b"}"></div></div><b>${Math.round(v.score)}</b></div>`).join("") : `<p class="note">No interview answers yet.</p>`;
  $("#runs").innerHTML = runs.length ? runs.map((r) => `<div class="run" data-run="${r.id}"><span class="mono">#${r.id}</span><span>${esc(r.role)}</span>
    <span class="mono">${new Date(r.created * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span><span>Match <b>${r.match ?? "–"}%</b></span><span>ATS <b>${r.ats ?? "–"}</b></span></div>`).join("") : `<p class="note">No flights yet.</p>`;
  $$(".run").forEach((el) => el.addEventListener("click", () => loadRun(+el.dataset.run).catch((e) => toast(e.message))));
}

/* ---------------- boot ---------------- */
st.token = store.get("pp_token"); st.user = store.get("pp_user");
if (st.token) api("/api/me").then(enter).catch(() => logout());
