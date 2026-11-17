# PrepPilot · Flight Deck

Multi-agent placement preparation system (LLM & Agentic AI, BIS703B, CCA-2).
K R Srigowri (1DT23IS064) · Rajshree Gupta (1DT23IS117) · DSATM, Bengaluru

## Agents
- **Analyst → Planner → Coach**: ReAct loops on Gemini function calling over 9 tools
  (`read_job_description`, `read_resume`, `compare_skills`, `ats_check`, `recall_memory`,
  `get_company_profile`, `find_resources`, `build_study_plan`, `schedule_mock_interview`)
- **Editor**: rewrites weak resume bullets without inventing facts; ATS before/after
- **Tower**: recommendations for the placement cell from batch statistics

## Features
- Live "black box" trace of every thought, tool call and observation
- Company mode: TCS, Infosys, Wipro, Accenture, Cognizant, Capgemini, Amazon
- Voice mock interview (Web Speech API) graded against a fixed rubric; memory of mastery per skill
- Student dashboard: readiness over time, streak calendar, skill heatmap, speaking stats
- Control Tower (placement cell, code-protected): batch readiness, skill gaps, leaderboard, at-risk list
- Resume Lab: PDF upload (pypdf) + Editor agent
- Study plan export to calendar (.ics); model fallback chain + offline autopilot

## Stack
FastAPI · SQLite · HTML/CSS/JavaScript · Gemini API (REST) · Render. API docs at `/docs`.

## Run locally
```
pip install -r requirements.txt
set GEMINI_API_KEY=your-key
uvicorn main:app --reload
```
Environment: `GEMINI_API_KEY` (required for LLM), `ADMIN_CODE` (tower code, default TOWER2026).

Layout inspired by [Massively](https://html5up.net/massively) by HTML5 UP (CC BY 3.0). Background image generated for this project.
