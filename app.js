// PrepPilot Flight Deck - frontend
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const st = { token: null, user: null, runId: null, run: null, q: null, admin: false, companies: [] };
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

async function enter(meInfo) {
  $("#gate").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#whoName").textContent = st.user;
  try { const m = meInfo && meInfo.username ? meInfo : await api("/api/me"); st.admin = !!m.is_admin; } catch (e) {}
  if (!st.companies.length) {
    try { st.companies = await api("/api/companies");
      $("#company").innerHTML = `<option value="">Any company</option>` + st.companies.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    } catch (e) {}
  }
  window.scrollTo(0, 0);
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
  if (page === "dashboard") renderDashboard().catch((e) => toast(e.message));
  if (page === "tower") openTower();
  const hd = $("#mhead"), yTop = hd ? hd.offsetTop + hd.offsetHeight : 0;
  if (window.scrollY > yTop) window.scrollTo(0, yTop);
}
document.addEventListener("click", (e) => { const a = e.target.closest("[data-go]"); if (a) { e.preventDefault(); go(a.dataset.go); } });

/* ---------------- pre-flight + black box ---------------- */
$("#sample").addEventListener("click", async () => { const d = await api("/api/samples"); $("#jd").value = d.jd; $("#cv").value = d.resume; });
$("#takeoff").addEventListener("click", async () => {
  const btn = $("#takeoff");
  try {
    btn.disabled = true; btn.textContent = "Crew working…";
    const d = await api("/api/runs", { body: { jd: $("#jd").value, resume: $("#cv").value, days: +$("#days").value, hours: +$("#hours").value, company: $("#company").value } });
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
  g += `<polygon points="${poly}" fill="rgba(24,191,239,.25)" stroke="#18bfef" stroke-width="2"/>`;
  sk.forEach((s, i) => {
    const [x, y] = pt(i, R + 18), [px, py] = pt(i, R * val(s));
    g += `<circle cx="${px}" cy="${py}" r="3.5" fill="${have.has(s) ? "#1f9b6f" : "#18bfef"}"/>
      <text x="${x}" y="${y}" font-size="10.5" font-family="Source Sans 3" text-anchor="${x < cx - 5 ? "end" : x > cx + 5 ? "start" : "middle"}" dominant-baseline="middle" fill="#1c1b19">${esc(N[s])}</text>`;
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
  gauge($("#gReady"), r.readiness, "READINESS", "#2fd6a0"); gauge($("#gMatch"), r.match, "SKILL MATCH", "#ffb02e"); gauge($("#gAts"), r.ats.ats_score, "ATS SCORE", "#18bfef");
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
  const cp = r.company_profile;
  $("#compCard").classList.toggle("hidden", !cp);
  if (cp) {
    $("#compName").textContent = cp.name; $("#compTag").textContent = "COMPANY MODE"; $("#compTrack").textContent = cp.track;
    $("#compRoute").innerHTML = cp.rounds.map((x, i) => `<div class="stop"><i>${i + 1}</i><b>${esc(x.name)}</b><p>${esc(x.tests)}</p><span class="sk">PREP: ${esc(N[x.skill] || x.skill)}</span></div>`).join("");
    $("#compTip").innerHTML = "<b>Tip:</b> " + esc(cp.tip) + ` <span class="note">Typical pattern from 2026 prep guides. Check your drive's official notice.</span>`;
  }
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
      <div style="font-size:14px;margin-top:6px">${esc(st.q.skill_name)} mastery now <b style="color:#2fd6a0">${Math.round(r.mastery)}/100</b> (saved)${r.readiness != null ? ` · readiness <b style="color:#ffb02e">${r.readiness}</b>` : ""}</div>
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

/* ---------------- PDF upload (pre-flight + resume lab) ---------------- */
async function readPdf(file, target) {
  if (!file) return;
  if (file.size > 5e6) return toast("PDF is larger than 5 MB");
  const data = await new Promise((ok, bad) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = bad; fr.readAsDataURL(file); });
  toast("Reading your PDF…");
  try { const d = await api("/api/resume/pdf", { body: { data, name: file.name } }); $(target).value = d.text; toast(`Read ${d.pages} page${d.pages > 1 ? "s" : ""} from ${file.name}`); }
  catch (e) { toast(e.message); }
}
$("#cvPdf").addEventListener("change", (e) => { readPdf(e.target.files[0], "#cv"); e.target.value = ""; });
$("#rlPdf").addEventListener("change", (e) => { readPdf(e.target.files[0], "#rlCv"); e.target.value = ""; });

/* ---------------- dashboard ---------------- */
const tone = (v) => (v == null ? "#efe6d6" : v >= 70 ? "#2fd6a0" : v >= 40 ? "#ffb02e" : "#e5484d");
function lineChart(pts, W = 560, H = 190) {
  if (pts.length < 2) return `<p class="note">Take a flight and answer a question to start the line.</p>`;
  const x = (i) => 34 + (i * (W - 50)) / (pts.length - 1), y = (v) => H - 22 - (v / 100) * (H - 40);
  const d = pts.map((p, i) => `${x(i)},${y(p.v)}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${[0, 40, 70, 100].map((v) => `<line x1="34" x2="${W - 14}" y1="${y(v)}" y2="${y(v)}" stroke="${v === 70 ? "#2fd6a0" : "#e4d9c6"}" ${v === 70 ? 'stroke-dasharray="5 4"' : ""}/><text x="26" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#6f6656">${v}</text>`).join("")}
    <text x="${W - 16}" y="${y(70) - 5}" font-size="9.5" text-anchor="end" fill="#1f9b6f" font-family="IBM Plex Mono">PLACEMENT-READY</text>
    <polygon points="${x(0)},${y(0)} ${d} ${x(pts.length - 1)},${y(0)}" fill="rgba(24,191,239,.12)"/>
    <polyline points="${d}" fill="none" stroke="#18bfef" stroke-width="2.5"/>${pts.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" fill="#1c1b19"><title>${Math.round(p.v)}</title></circle>`).join("")}
    <text x="${x(pts.length - 1)}" y="${y(pts[pts.length - 1].v) - 9}" font-size="12" font-weight="700" text-anchor="end" fill="#1c1b19">${Math.round(pts[pts.length - 1].v)}</text></svg>`;
}
function kpi(label, val, sub, cls = "") { return `<div class="kpi ${cls}"><span>${label}</span><b>${val ?? "–"}</b>${sub ? `<small class="${sub.cls || ""}">${sub.t}</small>` : ""}</div>`; }
async function renderDashboard() {
  const d = await api("/api/dashboard"), k = d.kpis;
  $("#dbEmpty").classList.toggle("hidden", k.flights > 0); $("#dbBody").classList.toggle("hidden", k.flights === 0);
  if (!k.flights) return;
  const ch = k.readiness != null && k.readiness_start != null ? Math.round(k.readiness - k.readiness_start) : null;
  $("#dbKpis").innerHTML = kpi("Readiness now", k.readiness, ch != null ? { t: (ch >= 0 ? "▲ " : "▼ ") + Math.abs(ch) + " since first flight", cls: ch >= 0 ? "up" : "down" } : null, "hot") +
    kpi("Streak", k.streak + (k.streak ? " 🔥" : ""), { t: "best " + k.best_streak + " days" }) + kpi("Flights", k.flights, d.company ? { t: "target: " + d.company } : null) +
    kpi("Answers", k.answers) + kpi("Avg score", k.avg_score, k.avg_score != null ? { t: "out of 10" } : null) + kpi("Avg WPM", k.avg_wpm, k.avg_fillers != null ? { t: k.avg_fillers + " fillers / answer" } : null);
  $("#dbRChange").textContent = k.readiness != null ? "now " + k.readiness : "";
  $("#dbReady").innerHTML = lineChart(d.readiness_series);
  $("#dbStreak").textContent = k.streak ? k.streak + "-day streak" : "start a streak today";
  const max = Math.max(1, ...d.activity.map((a) => a.count)), first = new Date(d.activity[0].date + "T00:00");
  const pad = (first.getDay() + 6) % 7;
  const active = d.activity.filter((a) => a.count).length, total = d.activity.reduce((x, a) => x + a.count, 0);
  $("#dbCal").innerHTML = `<div class="calwrap"><div><div class="calhead">${["M", "T", "W", "T", "F", "S", "S"].map((x) => `<span>${x}</span>`).join("")}</div><div class="cal">` +
    Array(pad).fill('<div style="visibility:hidden"></div>').join("") +
    d.activity.map((a, i) => { const l = a.count === 0 ? "" : a.count / max > 0.66 ? "l3" : a.count / max > 0.33 ? "l2" : "l1";
      return `<div class="${l} ${i === d.activity.length - 1 ? "today" : ""}" title="${a.date}: ${a.count} activities"></div>`; }).join("") +
    `</div></div><div class="calside"><div><b>${k.streak}${k.streak ? "🔥" : ""}</b><span>CURRENT STREAK</span></div><div><b>${active}</b><span>ACTIVE DAYS / 28</span></div><div><b>${total}</b><span>FLIGHTS + ANSWERS</span></div></div></div>`;
  $("#dbHeat").innerHTML = d.skills.map((x) => `<div class="${x.score == null ? "un" : ""} ${x.target ? "tg" : ""}" style="${x.score != null ? "background:" + tone(x.score) + (x.score >= 40 && x.score < 70 ? ";color:#1c1b19" : "") : ""}" title="${esc(x.name)}${x.n ? " · " + x.n + " answers" : ""}">${esc(x.name)}<b>${x.score == null ? "–" : Math.round(x.score)}</b></div>`).join("");
  const lv = ["", "Easy", "Medium", "Hard"];
  $("#dbLevel").innerHTML = Object.keys(d.by_level).length ? Object.entries(d.by_level).map(([l, v]) => `<div class="bar"><span>${lv[l]}</span><div class="track"><div class="fill" style="width:${v * 10}%;background:${tone(v * 10)}"></div></div><b>${v}</b></div>`).join("") : `<p class="note">No answers yet.</p>`;
  const sp = d.speaking.filter((x) => x.wpm > 0);
  $("#dbSpeak").innerHTML = sp.length ? `<svg viewBox="0 0 240 110" width="100%">${sp.map((x, i) => { const w = 220 / sp.length, h = Math.min(90, (x.wpm / 180) * 90);
      return `<rect x="${10 + i * w + 2}" y="${100 - h}" width="${w - 4}" height="${h}" rx="3" fill="${x.wpm >= 110 && x.wpm <= 160 ? "#2fd6a0" : "#ffb02e"}"><title>${Math.round(x.wpm)} WPM, ${x.fillers} fillers</title></rect>${x.fillers ? `<text x="${10 + i * w + w / 2}" y="${96 - h}" font-size="9" text-anchor="middle" fill="#e5484d">${x.fillers}</text>` : ""}`; }).join("")}
      <line x1="10" x2="230" y1="${100 - (110 / 180) * 90}" y2="${100 - (110 / 180) * 90}" stroke="#1c1b19" stroke-dasharray="3 3" opacity=".3"/></svg>
      <p class="note">Bars = words per minute (green = 110-160, a clear pace). Red numbers = filler words.</p>` : `<p class="note">Use 🎙 in the cockpit to see your speaking pace.</p>`;
  $("#dbWeak").innerHTML = d.weak.map((w) => `<div class="weak"><b>${esc(w.name)}</b><span>${esc(w.reason)}</span><button class="btn small ghost" data-go="cockpit">Practise ▸</button></div>`).join("") || `<p class="note">Nothing yet.</p>`;
  $("#runs").innerHTML = d.runs.length ? d.runs.map((r) => `<div class="run" data-run="${r.id}"><span class="mono">#${r.id}</span><span>${esc(r.role)}</span>
    <span class="mono">${new Date(r.created * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span><span>Match <b>${r.match ?? "–"}%</b></span><span class="mono">open ▸</span></div>`).join("") : `<p class="note">No flights yet.</p>`;
  $$(".run").forEach((el) => el.addEventListener("click", () => loadRun(+el.dataset.run).catch((e) => toast(e.message))));
}

/* ---------------- resume lab ---------------- */
$("#rlFromPre").addEventListener("click", () => { if (!$("#cv").value.trim()) return toast("Pre-flight resume box is empty"); $("#rlCv").value = $("#cv").value; if ($("#jd").value.trim()) $("#rlJd").value = $("#jd").value; });
const hl = (t) => esc(t).replace(/\[[^\]]+\]/g, (m) => `<mark>${m}</mark>`);
let rlJd = "";
$("#rlGo").addEventListener("click", async () => {
  const btn = $("#rlGo"); btn.disabled = true; btn.textContent = "Editor agent working…";
  try {
    const r = await api("/api/resume/rewrite", { body: { resume: $("#rlCv").value, jd: $("#rlJd").value } });
    rlJd = $("#rlJd").value;
    const b = r.ats_before.ats_score, a = r.ats_after.ats_score;
    $("#rlBody").className = "";
    $("#rlBody").innerHTML = `<div class="ba"><div class="gauge" id="rlG1"></div><div class="arrow">→</div><div class="gauge" id="rlG2"></div>
      <div class="mono" style="font-size:12px;color:#8fa3bd">${r.items.length} of ${r.bullets_checked} bullets rewritten<br>keywords from ${esc(r.jd_used)}<br>by ${esc(r.model)}</div></div>` +
      (r.items.length ? r.items.map((x) => `<div class="rw"><div class="b">${esc(x.before)}</div><div class="a">${hl(x.after)}</div><div class="w">WHY: ${esc(x.why)}</div></div>`).join("")
        : `<p>No weak bullets found. ${r.bullets_checked ? "Every bullet already starts with an action verb and has a number." : "Write your project points as bullet lines starting with - so the Editor can check them."}</p>`) +
      `<div class="tips" style="color:#9fb3cc">${r.ats_after.tips.map((t) => "• " + esc(t)).join("<br>")}</div>`;
    gauge($("#rlG1"), b, "ATS BEFORE", "#e5484d"); gauge($("#rlG2"), a, "ATS AFTER", "#2fd6a0");
    $("#rlFinal").classList.remove("hidden"); $("#rlImproved").value = r.improved; $("#rlScore").textContent = "ATS " + a;
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Rewrite with Editor agent ▸";
});
$("#rlRescore").addEventListener("click", async () => {
  try { const r = await api("/api/resume/score", { body: { resume: $("#rlImproved").value, jd: rlJd } }); $("#rlScore").textContent = "ATS " + r.ats_score; toast("New ATS score: " + r.ats_score); }
  catch (e) { toast(e.message); }
});
$("#rlCopy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#rlImproved").value); toast("Copied"); } catch (e) { $("#rlImproved").select(); toast("Press Ctrl+C to copy"); } });
$("#rlUse").addEventListener("click", () => { $("#cv").value = $("#rlImproved").value; go("preflight"); toast("Improved resume loaded. Take off again to see the new scores."); });

/* ---------------- control tower ---------------- */
function openTower() {
  $("#twLock").classList.toggle("hidden", st.admin); $("#twBody").classList.toggle("hidden", !st.admin);
  if (st.admin) renderTower().catch((e) => toast(e.message));
}
$("#twUnlock").addEventListener("click", async () => {
  try { await api("/api/tower/unlock", { body: { code: $("#twCode").value } }); st.admin = true; toast("Tower unlocked"); openTower(); } catch (e) { toast(e.message); }
});
$("#twCode").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#twUnlock").click(); });
const hbar = (label, v, txt, col) => `<div class="bar"><span>${esc(label)}</span><div class="track"><div class="fill" style="width:${Math.min(100, v)}%;background:${col}"></div></div><b>${txt}</b></div>`;
async function renderTower() {
  const d = await api("/api/tower"), k = d.kpis;
  $("#twKpis").innerHTML = kpi("Students", k.students, k.demo_students ? { t: k.demo_students + " demo" } : null, "hot") + kpi("Avg readiness", k.avg_readiness) +
    kpi("Placement-ready", k.ready_percent + "%", { t: "readiness 70+" }) + kpi("At risk", k.at_risk, { t: "below 40", cls: k.at_risk ? "down" : "" }) +
    kpi("Flights", k.flights) + kpi("Answers graded", k.answers);
  const mx = Math.max(1, ...d.distribution.map((x) => x.count)), cols = ["#e5484d", "#ffb02e", "#9bd8bf", "#2fd6a0"];
  $("#twDist").innerHTML = `<svg viewBox="0 0 300 170" width="100%">${d.distribution.map((x, i) => { const h = (x.count / mx) * 120;
    return `<rect x="${20 + i * 70}" y="${140 - h}" width="50" height="${h}" rx="6" fill="${cols[i]}"/><text x="${45 + i * 70}" y="${134 - h}" text-anchor="middle" font-size="14" font-weight="800" font-family="Source Sans 3">${x.count}</text><text x="${45 + i * 70}" y="160" text-anchor="middle" font-size="11" fill="#6f6656" font-family="IBM Plex Mono">${x.band}</text>`; }).join("")}</svg>`;
  $("#twGaps").innerHTML = d.gaps.length ? d.gaps.map((g) => hbar(g.skill, g.percent, g.percent + "%", "#18bfef")).join("") : `<p class="note">No data yet.</p>`;
  $("#twWeak").innerHTML = d.weakest.length ? d.weakest.map((w) => hbar(w.skill, w.avg, w.avg, tone(w.avg))).join("") : `<p class="note">No interview answers yet.</p>`;
  $("#twBoard").innerHTML = d.leaderboard.length ? `<table class="board"><thead><tr><th>#</th><th>STUDENT</th><th>READINESS</th><th>MATCH</th><th>AVG SCORE</th><th>STREAK</th><th>TARGET</th><th>TOP GAP</th></tr></thead><tbody>` +
    d.leaderboard.map((r, i) => `<tr><td class="rk">${i + 1}</td><td>${esc(r.name)}${r.demo ? '<span class="demo">DEMO</span>' : ""}</td>
      <td class="n"><span class="minibar" style="width:${r.readiness * 0.6}px;background:${tone(r.readiness)}"></span>${r.readiness}</td><td class="n">${r.match}%</td>
      <td class="n">${r.avg_score ?? "–"}</td><td class="n">${r.streak ? r.streak + "🔥" : "–"}</td><td>${esc(r.company)}</td><td>${esc(r.top_gap)}</td></tr>`).join("") + "</tbody></table>"
    : `<p class="note">No students have flown yet. Press <b>Load demo batch</b> to see how it looks with a class.</p>`;
  $("#twRisk").innerHTML = d.at_risk.length ? d.at_risk.map((r) => `<div class="risk"><span>${esc(r.name)} · gap: ${esc(r.top_gap)}</span><b>${r.readiness}</b></div>`).join("") : `<p class="note">Nobody below 40% readiness.</p>`;
  $("#twComp").innerHTML = d.companies.map((c) => `<span class="chip co">${esc(c.name)} · ${c.count}</span>`).join("");
}
$("#twDemo").addEventListener("click", async () => { try { const r = await api("/api/tower/demo", { body: {} }); toast(r.created ? `Added ${r.created} demo students` : "Demo batch already loaded"); renderTower(); } catch (e) { toast(e.message); } });
$("#twClear").addEventListener("click", async () => { try { const r = await api("/api/tower/demo/clear", { body: {} }); toast(`Removed ${r.removed} demo students`); $("#twBriefCard").classList.add("hidden"); renderTower(); } catch (e) { toast(e.message); } });
$("#twBrief").addEventListener("click", async () => {
  const btn = $("#twBrief"); btn.disabled = true; btn.textContent = "Tower agent thinking…";
  try {
    const r = await api("/api/tower/briefing", { body: {} });
    $("#twBriefCard").classList.remove("hidden"); $("#twModel").textContent = r.model || "";
    $("#twBriefBody").innerHTML = `<p style="font-size:15px">${esc(r.summary)}</p>` + (r.recommendations || []).map((x) => `<div class="trec"><b>${esc(x.action)}</b><span>${esc(x.why)}</span></div>`).join("") +
      (r.spotlight ? `<p class="mono" style="color:#ffb02e;font-size:12.5px;margin-top:10px">SPOTLIGHT · ${esc(r.spotlight)}</p>` : "");
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Ask Tower agent ▸";
});

document.querySelector(".scrolly").addEventListener("click", (e) => { e.preventDefault(); document.getElementById("board").scrollIntoView({ behavior: "smooth" }); });

/* ---------------- boot ---------------- */
st.token = store.get("pp_token"); st.user = store.get("pp_user");
if (st.token) api("/api/me").then((m) => enter(m)).catch(() => logout());
