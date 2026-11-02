# Dashboard Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Ship the approved light dashboard and collapsible sidebar with real device controls.

**Architecture:** Shared design tokens and native Qt components reproduce the mockup without a browser runtime. Existing MainWindow callbacks remain the authority for network operations, credentials, timers, and confirmed switch states.

**Tech Stack:** Python, PySide6, QtCharts, existing uv dependencies.

**Spec:** `docs/superpowers/specs/2026-11-02-dashboard-design.md`

## Global Constraints

- Segoe UI, pixel sizes from the HTML reference; light sage default.
- Sidebar widths 212px expanded / 76px collapsed.
- Network calls remain in controller coroutines submitted through AsyncRunner.
- Tests use in-memory storage and fakes, never real credentials or devices.
- Preserve existing control, history, export, timer, tray, and account flows.

## Review Focus

- Long aliases must elide without losing tooltips or displacing switches.
- Minimum window size and many devices require scrolling without clipped controls.
- Offline and pending switches cannot claim an unconfirmed power state.
- Empty or partially loaded energy must not appear as complete zero usage.
- Collapsing navigation cannot reset selection or interrupt pending work.

### Task 1: Shared visual system and navigation

Files: `src/ui/tokens.py`, `theme.py`, `side_tabs.py`, `tests/test_ui.py`.

- [x] Add and run failing collapse/navigation behavior test.
- [x] Apply reference tokens, palette, font sizes, and sidebar shell.
- [x] Verify navigation and theme tests; retain accessible shortcuts/tooltips.

### Task 2: Dashboard and device components

Files: `src/ui/widgets.py`, `plug_card.py`, `overview_page.py`, new `device_grid.py` and `usage_breakdown.py`, `main_window.py`, `charts.py`, `tests/test_ui.py`.

- [x] Add and run failing overview power-control and partial-data tests.
- [x] Build responsive device cards, live chart panel, energy breakdown, and shared header.
- [x] Connect overview controls to existing confirmed-state callbacks; keep device identities stable.
- [x] Verify existing control/history/account/timer flows plus minimum-size geometry.

### Task 3: Visual proof and final verification

- [x] Render actual widgets with synthetic data into desktop and narrow screenshots without credentials/network.
- [x] Compare with reference; adjust shared geometry/type styling.
- [x] Run complete pytest suite and Ruff.
- [x] Obtain whole-change review, resolve meaningful findings, and report results.

## Execution ledger

Ruling: User explicitly requested proceeding with approved mockup; implement inline without another design approval. Work in current checkout so changes are immediately reviewable; avoid unrequested worktree setup or commits. Prototype artifacts remain as supplied review references.

Pre-flight: Task 2 consumes Task 1 tokens/theme and SideTabs API; preserve existing page selection API. Task 3 consumes actual MainWindow and fake runner fixture; no production demo mode.

Task 1: complete. Collapse test failed at old 81px width, then passed at 212/76px; active page and accessible shortcuts retained.

Task 2: complete. New dashboard control and partial-energy tests failed before implementation, then passed. Native screenshots verify desktop and narrow layouts. Baseline 87 tests passed; expanded suite reached 93 passing tests before review fixes.

Ruling: Use exact approved light reference ink `#718077` and pale series colors. Adjust reference palette assertions to secondary contrast >=3 and series >=1.5; primary text remains >=4.5. Explicit dark palette remains available, but OS color-scheme changes do not replace the approved light default.

Ruling: Windows offscreen Qt does not discover installed fonts automatically. Preview/test fixtures load installed Segoe UI font files explicitly; production uses normal native Windows font discovery. No font assets or browser runtime added.

Final review: independent read-only reviewer found range coupling, dropped zero-watt readings, long legend clipping, and chart labels using points. Added failing range/zero/legend tests, corrected independent 10-minute Overview data, kept confirmed zero readings, elided legend labels with accessible full names, and switched chart label fonts to 10px. No findings declined by reviewer; real hardware was not exercised.

Ruling: Keep Python references to QAreaSeries upper/lower boundary wrappers. Native render exposed PySide6 ownership failure otherwise; repeated rendering and chart redraw verification cover this lifecycle.

Task 3: complete. Final full suite: `python -m pytest -q` -> 99 passed. `python -m ruff check` -> all checks passed. `git diff --check` -> no whitespace errors. Six native previews generated under `artifacts/redesign/` at 1440x1060 and 760x640. Missing power data now renders unknown instead of measured zero; partial power totals are identified. All review findings fixed, including 10px chart-label typography; no deferred findings.

Integration: User requested merging to main. Checkout already uses `main`, so commit verified changes directly there. No remote push, release build, or live-device run requested.
