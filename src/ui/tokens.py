"""Layout tokens shared by every screen: one spacing scale, one radius scale, one type scale (px)."""
# Spacing: small gaps inside a group, larger gaps between groups.
SP_XS, SP_SM, SP_MD, SP_LG, SP_XL = 4, 8, 12, 16, 24

# Radius: pick a step by element size; a nested corner is the outer radius minus the padding between them.
SPLIT_HEIGHT = 42  # both halves of a split button, as tall as a dropdown beside it
MOTION_MS = 140  # hover and press feedback
RADIUS_SM, RADIUS_MD, RADIUS_LG = 4, 8, 12  # chip and menu item, button and input, card and chart

# Type roles.
FONT_FAMILY = "Segoe UI"
FONT_BODY, FONT_SMALL, FONT_CAPTION = 14, 12, 11
FONT_TITLE, FONT_HEADING, FONT_METRIC, FONT_NAME, FONT_VALUE = 24, 15, 26, 12, 23

# Exact geometry from the approved HTML reference, in logical pixels.
SIDEBAR_EXPANDED, SIDEBAR_COLLAPSED = 212, 76
PAGE_X, PAGE_Y, PAGE_BOTTOM = 38, 32, 24
CARD_GAP, PANEL_GAP, SECTION_GAP = 14, 18, 24
DEVICE_PILL_WIDTH = 64
FONT_HERO, SPARK_HEIGHT, SPARK_SMALL = 40, 56, 32  # the live watts figure and its trend line
METRIC_PAD, PANEL_X, PANEL_Y = 20, 23, 21
DEVICE_HEIGHT, DEVICE_FIGURE_WIDTH = 48, 90  # one plug row; width of its watts column
BAR_HEIGHT = 6

CARD_PAD = SP_LG  # padding inside every card
PAGE_TOP = SP_LG  # gap between the page header and the first thing on a page
TARGET = 40  # smallest clickable size we draw ourselves (WCAG 2.2 asks 24 px; 44 is the comfort target)
