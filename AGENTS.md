# AiTool — AGENTS.md

**Project identity:** Formal project + harness practice project. Owner: `Codex`. Master controller thread: `019f3a9b-9dfd-74a0-97eb-820fb8f94ac5`.

## Quick Commands

```bash
# Run tests (39 tests, 2 currently expected to fail)
python -m pytest tests/ -v

# Run single test file
python -m pytest tests/test_desktop_tool_logic.py -v

# Run desktop tool (src layout, requires deps)
pip install customtkinter tkinterdnd2 pystray Pillow keyboard
python run_desktop_tool.py

# Build single-file exe (PyInstaller + UPX)
pyinstaller --clean --noconfirm --onefile --windowed \
  --add-data "src/aitool_desktop;src/aitool_desktop" \
  --exclude-module numpy --exclude-module matplotlib \
  --exclude-module scipy --exclude-module xml \
  --exclude-module multiprocessing \
  --name "AiTool" run_desktop_tool.py
```

## Architecture (5 layers)

| Layer | Purpose | Key Files |
|-------|---------|-----------|
| **Master Control** | Task definition, risk gates, acceptance | `.agent/state/active-task.yaml`, `.agent/state/controller-registry.json`, `docs/master-controller-handbook.md` |
| **Execution** | Run commands, mutate files, emit artifacts | `.agent/scripts/safe_run.py`, `.agent/hooks/dangerous_cmd.py`, `.agent/hooks/write_scope_gate.py`, `.agent/common/task_state.py` |
| **Evidence** | Verify deliverable tasks only | `.agent/scripts/verify_outputs.py`, `.agent/state/last-verification.json` |
| **Governance** | Local rules > external skills | `.agent/scripts/check_governance.py`, `.agent/state/skill-governance.json`, `.agent/state/practice-registry.json` |
| **Project Drive** | Version plan, acceptance, status log | `docs/version-plan.md`, `docs/delivery-acceptance.md`, `.agent/logs/trial-status.md` |

## Task Types (critical distinction)

- **exploratory** — Clarification, path comparison, risk validation. No pass/fail evidence required.
- **deliverable** — Milestone delivery, must claim `done`/`fixed`/`passed`. Enters verification gate.

Only `deliverable` tasks pass through `.agent/scripts/verify_outputs.py`.

## State Files (source of truth)

| File | Role |
|------|------|
| `.agent/state/active-task.yaml` | Current task card (task_id, stage, task_type, actor, allow_write[], override) |
| `.agent/state/controller-registry.json` | Project owner, master thread, goal |
| `.agent/state/runtime-state.json` | Last command, failure count, last verification |
| `.agent/state/last-verification.json` | Last deliverable verification result |
| `.agent/state/skill-governance.json` | Local governance priority, skill allow/deny lists |
| `.agent/state/practice-registry.json` | Project role, positioning docs, governance contracts |

## Guards (enforced by hooks)

- **Dangerous commands** (`git reset --hard`, `rm -rf`, `git push --force`, etc.) → blocked globally
- **Protected paths** (`assets/`, `baseline/`, `fixtures/`, `samples/`, `input/`, `templates/`, `source-of-truth/`) → blocked for executor; master-controller can override via `allow_write`

## Desktop Tool (src/aitool_desktop/)

| Module | Responsibility |
|--------|----------------|
| `app.py` | CustomTkinter UI, drag-drop, tray, hotkeys (Alt+A), card execution |
| `models.py` | `StationEntry`, `CustomModule`, `ActionReview` dataclasses |
| `operations.py` | Core ops: folder-copy (2-channel), bat launch, SVN update/commit, web open, app launch |
| `storage.py` | JSON persistence for station entries + custom modules |

**Key behavior:** Drag any file/URL → auto-classifies to station (files) or action card (scripts, .exe/.lnk, URLs). Right-click station entry → open containing folder. Double-click → open with system association.

## Testing Notes

- No `pyproject.toml` / `requirements.txt` — deps installed manually per README
- Test discovery: `tests/test_*.py` (uses `REPO_ROOT / "src"` on sys.path)
- 2 known failing tests (nested path check in folder-copy, SVN validate status) — reflect current implementation gaps, not test errors

## Conventions

- **Python ≥ 3.10**, type hints (`from __future__ import annotations`), `pathlib.Path` throughout
- **No external config files** — all governance state in `.agent/state/*.json|yaml`
- **Low-dependency core** — `.agent/common/task_state.py` reads YAML without PyYAML
- **Harness first** — stable practices extracted *after* real delivery, not before

## References

- `docs/project-architecture.md` — full layer diagram
- `docs/master-controller-handbook.md` — master control procedures
- `docs/delivery-acceptance.md` — acceptance scenarios & minimum pass criteria
- `AGENTS.md` (this file) — agent-facing quick reference