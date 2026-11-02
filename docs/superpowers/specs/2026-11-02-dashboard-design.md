# Approved light dashboard

Implement the light HTML mockup in `src/ui/redesign.prototype.html`, including its sidebar toggle. The user's explicit approval covers implementation now, with the same Segoe UI typography, sage palette, spacing, hierarchy, cards, and icons.

Use native PySide6 components and the existing AsyncRunner/controller. Do not introduce a browser runtime or replace real plug data with mockup samples. Expanded sidebar is 212px; collapsed sidebar is 76px. Keep labeled navigation, tooltips, shortcuts, active states, and account/settings access. Overview combines four metrics, live power, today's usage breakdown, and working device cards. Devices retains chart ranges, filters, renaming, timers, and confirmed power state. Energy, Account, and Settings inherit the shared visual system. Missing data stays visibly unknown; partial totals must be identified.

The light mockup is the default regardless of the OS theme. Preserve explicit dark palette support for existing theme consumers. Compare actual native rendering with the approved mockup at desktop and minimum window sizes. Native text rasterization may differ from Chromium; family, pixel sizes, weights, colors, and geometry must come from the reference.
