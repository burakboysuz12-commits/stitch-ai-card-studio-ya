# AGENT_INSTRUCTIONS — Playbook for Autonomous Cloud Agents (Google Jules & CI/CD)

This document provides definitive instructions, architectural guidelines, and operating protocols for autonomous cloud agents (such as **Google Jules**, GitHub Actions bots, and automated code generation workflows) interacting with this repository.

---

## 1. Project Mission & Architecture Overview

The goal of this project is a **cloud-ready business card decomposition and interactive AI editing platform** (`Stitch AI+`). The system operates 24/7 on cloud platforms (e.g., Render, Hugging Face Spaces) independent of any local machine.

### Core Components
1. **Web Server (`web_server.py`)**:
   - Lightweight, dependency-minimal Python HTTP server utilizing standard library `ThreadingHTTPServer`.
   - Binds to `0.0.0.0` and dynamic port `$PORT` (default `8080`).
   - Serves the HTML5 canvas editor at `/` and `/editor`.
   - Exposes REST API endpoints:
     - `GET /api/health`: Health monitoring for Render keep-alive and cloud orchestrators.
     - `GET /api/design/state` & `POST /api/design/state`: State persistence for layers.
     - `POST /api/ai_edit`: Natural language design modification engine.
2. **Interactive Canvas Editor (`ai_projects/gorsel_parcali_editor.html`)**:
   - Browser-based editor with virtual DOM rendering.
   - Communicates with relative `/api/` endpoints without hardcoded localhost ports.
3. **Automated Test Suite (`tests/`)**:
   - Pytest / standard unittest test suite validating API contracts, health checks, and NLP rules.
4. **Cloud Infrastructure (`render.yaml`, `Dockerfile`, `Procfile`, `.github/workflows/`)**:
   - Ready for automated 1-click cloud deployment.
   - Keep-alive cron workflow prevents idle shutdown.

---

## 2. Directory Layout & Key Files

```
├── web_server.py                       # Main HTTP server & NLP design engine
├── Procfile                            # Process declaration for Render / PaaS
├── render.yaml                         # Infrastructure-as-code for Render deployment
├── Dockerfile                          # Production container specification
├── .dockerignore                       # Docker build exclusions
├── .gitignore                          # Strict repository exclusion rules
├── requirements.txt                    # Python dependencies
├── AGENT_INSTRUCTIONS.md               # Playbook for Google Jules / Cloud Agents
├── PHASE_1_COMPLETION_REPORT.md        # User verification & deployment guide
├── .github/
│   └── workflows/
│       ├── ci.yml                      # CI build, lint, smoke & pytest pipeline
│       └── keepalive.yml               # 10-minute ping preventing free-tier sleep
├── ai_projects/
│   ├── gorsel_parcali_editor.html      # Interactive card editor UI
│   └── _active_design_state.json       # Persisted design layers and canvas metadata
├── tests/
│   └── test_web_server.py              # Server integration & unit tests
└── kartvizit_son_orijinal.png          # Reference business card asset (1024x686)
```

---

## 3. Mandatory Agent Rules & Integrity Protocol

When an autonomous agent generates or updates code:

### Rule 1: No Large Binaries or Bloat
- **NEVER** commit files larger than 5 MB.
- **NEVER** track `node_modules/`, `.next/`, `dist/`, `build/`, `*.pt`, `*.exe`, `*.pkg`, or sqlite `*.db` files.
- Always check `git status --ignored` before staging to ensure `.gitignore` rules are respected.

### Rule 2: Minimal Change Principle
- Only modify what is strictly required for the assigned feature or bug fix.
- Do not perform unrelated refactoring or rewrite untouched functions.
- Preserve comments, existing contracts, and coding styles.

### Rule 3: Preserving Interface Contracts
- `GET /api/health` must always return HTTP 200 with JSON:
  `{"ok": true, "service": "stitch_ai_web", "port": PORT, "status": "healthy", ...}`.
- `POST /api/ai_edit` must support `{prompt, selectedId, state}` and return `{ok: true, state: ..., summary: ...}`.
- Relative paths must be maintained in frontend assets.

### Rule 4: Mandatory Test Verification
Before creating a commit or opening a Pull Request:
1. Run syntax verification:
   ```bash
   python -m py_compile web_server.py
   ```
2. Run pytest suite:
   ```bash
   pytest tests/ -v
   ```
3. Ensure all tests pass with zero failures.

---

## 4. How to Create Clean Pull Requests (Google Jules Guidelines)

1. **Branch Naming**:
   - Features: `feat/m<milestone>-<short-description>` (e.g., `feat/m2-decomposition-metrics`)
   - Bugfixes: `fix/<issue-description>` (e.g., `fix/turkish-stemming-in-nlp`)
   - Infrastructure: `infra/<change>` (e.g., `infra/docker-healthcheck`)

2. **Commit Messages**:
   - Follow Conventional Commits:
     - `feat(web): add endpoint for selective layer export`
     - `test(ci): add visual fidelity headless evaluation`
     - `fix(nlp): support possessive suffix in layer name matching`

3. **Pull Request Description Template**:
   ```markdown
   ### Summary of Changes
   - [Brief bullet point description of what was changed and why]

   ### Verification Executed
   - [x] Syntax checked via `python -m py_compile`
   - [x] All tests passing via `pytest tests/ -v`
   - [x] Working tree clean, zero files >5MB staged

   ### Affected Endpoints / Modules
   - e.g., `web_server.py`, `tests/test_web_server.py`
   ```

---

## 5. Local & Cloud Execution Commands

### Running Web Server Locally
```bash
# Standard run (default port 8080)
python web_server.py

# Custom port
PORT=9000 python web_server.py
```

### Running Test Suite
```bash
# Run all tests
pytest tests/ -v

# Run with unittest runner (no pytest dependency)
python -m unittest discover -s tests -p "test_*.py" -v
```

### Verifying Docker Build Locally
```bash
docker build -t stitch-ai-web .
docker run -p 8080:8080 stitch-ai-web
```
