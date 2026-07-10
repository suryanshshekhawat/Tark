# Tark

Read docs/requirements.md fully before doing any work — it is the spec.
Core principle: Claude never asserts correctness. Only Lean 4 (via Mathlib)
or SymPy execution can produce a VERIFIED/REFUTED verdict. Anything else is
UNVERIFIED. Don't violate this anywhere, including in error-handling paths.

Stack: FastAPI backend (backend/), React+Vite frontend (frontend/),
Lean 4 + Mathlib project at tark_lean/.

Conventions: [fill in as they emerge — e.g. "steps identified by S1, S2...",
naming for verdict enums, etc.]