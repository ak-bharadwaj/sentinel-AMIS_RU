# Sentinel DSS Workspace Configuration (CLAUDE.md)

This file overrides local commands and properties for this workspace.

---

## 1. Global Orchestration Reference
This workspace inherits the pluggable S-Class Orchestration engine (V10.0) from:
- C:/Users/dorni/.gemini/antigravity/knowledge/orchestration_master_rules.md

---

## 2. Workspace Declaration
*   **pipeline:** sclass-v5 (V10.0)
*   **executionMode:** Human-in-the-Loop Mode
*   **loopMode:** Closed Loop

---

## 3. Project Parameters & Commands

### Run Dev Servers
*   **Backend Server:** `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`
*   **Frontend Client:** `cd frontend && npm run dev` (Access dashboard cockpit at `http://localhost:3000`)

### Run Verification Tests
*   **Backend Pytest Suite:** `pytest` or `python -m pytest`
*   **Frontend E2E Checks:** `cd frontend && npm test` or Playwright test files

### Databases Configuration
*   **Operational DB:** `backend/world_state.db` / `sentinel.db` (SQLite)
*   **Audit Trail DB:** `egl_audit.db` (SQLite)
*   **Schema Path:** `backend/database.py`

---

## 4. Behavior Overrides
*   **Visual Styling:** UI layouts must use HSL colors, dark modes, Outfit/Outfit fonts, glassmorphism card styling, and transitions.
*   **Code Constraints:** Static placeholders or TODO comments are completely blocked. Unit tests are mandatory for all router changes.

---

## 5. Non-Bypassable S-Class Pipeline Rules
*   **FSM Exclusivity:** You are strictly **forbidden** from manually running verification commands (pytest, npm run build, run_experiments.py) and writing walkthrough files in the main chat context.
*   **Mandatory S-Class Run:** Any user request to build, audit, verify, or complete the project MUST be executed by starting the S-Class FSM loop (Triage -> Analysis -> Clarification -> Design -> Debate -> Task Compilation -> Coding -> Integration -> QA -> Release -> Done).
*   **Chrome MCP Screenshots:** You MUST start the background uvicorn/Next.js servers, run the browser automation tool using `chrome-devtools-mcp` or `webapp-testing` to capture E2E screenshots, and pass them to the User Proxy subagent. If you declare success without visual screenshots, the verification is invalid.
