# Tark

Claude proposes. Verifiers dispose. See [CONSTRUCTION_PLAN.md](CONSTRUCTION_PLAN.md) for the full spec.

## Running locally

### Backend (FastAPI)

```
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Set up the venv once with:

```
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` once Claude calls are wired in.

Run tests: `./.venv/Scripts/python.exe -m pytest`

### Frontend (React + Vite)

```
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173 and proxies `/api` to the backend on port 8000.

### Lean 4 / Mathlib (tark_lean/)

Set up once via `elan` + `lake`:

```
cd tark_lean
lake exe cache get   # pulls prebuilt Mathlib .olean files instead of building from source
lake build
```

The backend's `LeanVerifier` writes scratch files into `tark_lean/.tark_scratch/` and invokes
`lake env lean <file>.lean` against the warm project — never spins up a fresh project per request.

## Status

Day 1-2 foundations: LaTeX validation, pydantic/TS schema, SSE streaming (mocked step data),
Lean + SymPy verifier backends, and both app skeletons are up. Claude decomposition/formalization
calls are not wired in yet — that's Days 3-5.
