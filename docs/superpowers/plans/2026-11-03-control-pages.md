# Control Pages Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the four approved page designs while preserving Overview.

**Architecture:** Add page-local layout/styling helpers and a detailed device-row variant. Reuse current controllers, callbacks, charts and settings storage. Keep Overview's compact row variant and global tokens/styles unchanged.

**Tech Stack:** Python, PySide6, SQLite, existing AsyncRunner.

**Spec:** `docs/superpowers/specs/2026-11-03-control-pages-design.md`

## Global Constraints

- No real network/keyring access during verification; no new dependencies.
- Preserve existing uncommitted work; implement in the authorized shared checkout.
- Keep Overview layout and behavior; opening Devices instead is the approved startup change.
- Keep UI I/O through the existing AsyncRunner; do not introduce blocking operations.

## Review Focus

- Small windows and long names keep switches and actions usable.
- Power state stays confirmed, pending and offline remain distinguishable.
- Partial/missing energy and unset tariff never appear as complete/free usage.
- Filtering also controls totals and exported data; stale callbacks stay invalidated.
- Sidebar and settings theme controls remain synchronized without extra network calls.

### Task 1: Devices

- [x] Add focused regression tests for default page, row variants and timer/collapse controls.
- [x] Add `page_layout.py`, `devices_page.py` and detailed `DeviceControlRow`; integrate with MainWindow while retaining callback names and compact Overview rows.
- [x] Verify existing power, timer, scanning and chart interactions.

### Task 2: Energy

- [x] Add regression tests for filter totals/export, unset costs and partial data.
- [x] Reshape HistoryPanel with scrollable filters, chart, breakdown and tariff panels; preserve revision guards and history ranges.
- [x] Verify filtering, cost changes and offline history behavior.

### Task 3: Account and Settings

- [x] Constrain scrollable forms, add local appearance selector and group existing settings.
- [x] Verify sign-in validation, automatic persistence, theme synchronization and startup error recovery.

### Task 4: Verification

- [x] Run full pytest and Ruff checks; render all changed pages at desktop and minimum sizes in both themes.
- [x] Verify protected Overview source hashes and inspect its native render.
- [x] Review final diff and document page-local design tokens. Leave changes uncommitted for user review.

Outcome: 121 tests passed in 38.09 seconds; Ruff clean. Independent review: ship. Deferred Qt deletion is explicitly flushed in test teardown so old windows and theme connections do not accumulate. Existing user changes remain uncommitted and preserved.
