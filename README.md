# PrepPilot · Flight Deck

A multi-agent placement preparation system (LLM & Agentic AI, BIS703B, CCA-2).

**Crew:** Analyst agent → Planner agent → Coach agent, each a ReAct loop on Gemini function calling,
sharing 8 tools: `read_job_description`, `read_resume`, `compare_skills`, `ats_check`, `recall_memory`,
`find_resources`, `build_study_plan`, `schedule_mock_interview`.

**What it adds over a chatbot**
- Persistent memory: every interview answer is stored; per-skill mastery (moving average) picks the next question.
- Repeatable grading: 40-question bank with rubric key points and source ids, plus LLM feedback.
- Deterministic skill match over a 20-skill taxonomy and an ATS resume check.
- Actions: dated study plan exported to calendar (.ics).
- Voice mock interview (Web Speech API) with words-per-minute and filler-word tracking.
- Reliability: model fallback chain and an offline autopilot, so a run never fails.
- LLMOps panel: tool calls, LLM calls, tokens, latency, models used.

**Stack:** FastAPI · SQLite · vanilla HTML/CSS/JS · Gemini API (REST).
API docs at `/docs`.

## Run locally
```
pip install -r requirements.txt
set GEMINI_API_KEY=your-key        (Windows)   |   export GEMINI_API_KEY=your-key   (Mac/Linux)
uvicorn server.main:app --reload
```
Open http://127.0.0.1:8000

## Deploy on Render
New → Blueprint (uses `render.yaml`), or New → Web Service with
build `pip install -r requirements.txt` and start `uvicorn server.main:app --host 0.0.0.0 --port $PORT`.
Add the environment variable `GEMINI_API_KEY`.
