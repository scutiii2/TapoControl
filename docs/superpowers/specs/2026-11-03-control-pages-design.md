# Control pages redesign

Approved scope: implement the Devices, Energy, Account and Settings concepts shown in this chat. Leave Overview's design and behavior intact. Keep the current sage palette, navigation, native PySide6 runtime and controller/AsyncRunner boundary.

Devices opens by default after startup/sign-in. Larger device names and switches lead compact rows, with explicit confirmed state, live watts, today's energy, direct timer access and existing overflow actions. Keep bulk power, scanning and live chart ranges; make the chart collapsible. Narrow windows hide secondary energy columns before constraining controls.

Energy separates plug/range filters and CSV export from the history chart and tariff area. Keep existing history ranges, runtime, saved history and unknown/partial-data treatment. Add a plug selector using already loaded data, per-plug usage breakdown and explicit cost figures that stay unknown until a tariff exists.

Account uses a constrained, scrollable form with existing validation, password reveal, sign-in feedback and accurate Windows Credential Manager text. Settings uses constrained, scrollable groups for startup, appearance and the three existing alert settings. Changes save automatically; theme stays synchronized with the sidebar.

No dependency changes, real network/keyring checks, new backend capabilities, commits of unrelated work or modifications to Overview-only components. Verify offline actions, narrow layouts, dark/light themes and Overview preservation.

## Implemented layout contract

Page-local values live in `src/ui/page_layout.py`: 80px detailed device rows, 44px action targets, 620px account form measure and 880px settings measure. Detailed device names use 16px type and readings use 18px; shared Segoe UI, spacing scale and palette remain in their existing files. Overview retains its 48px rows, 40×32px switches and existing typography.

Devices hides today's secondary column below 680px row width and decorative device icons below 500px. Energy stacks breakdown and tariff below a 760px viewport. All four pages scroll vertically while retaining native keyboard navigation. The page-local combo chevron follows the current palette.

CSV export captures the selected data and tariff, generates/writes in a worker thread, prevents overlapping jobs and ignores stale errors after an account/selection revision changes. Device energy fetches are limited to once a minute per plug; Overview retains its separate existing refresh cache.

## Verification

121 tests passed; Ruff and whitespace checks passed. Offline native captures are in `.impeccable/review/` and can be reproduced with `.venv/Scripts/python.exe tests/render_control_pages.py`. All changed pages were checked at 1440×1060 and 760×640 in light and dark themes; extra geometry tests cover expanded/collapsed navigation and long aliases. Independent read-only review returned `ship`. Protected Overview-only source hashes matched the start of this task.
