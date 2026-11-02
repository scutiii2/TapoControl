"""Layout tokens shared by every screen: one spacing scale, one radius scale, one type scale (px)."""
# Spacing: small gaps inside a group, larger gaps between groups.
SP_XS, SP_SM, SP_MD, SP_LG, SP_XL = 4, 8, 12, 16, 24

# Radius: pick a step by element size; a nested corner is the outer radius minus the padding between them.
RADIUS_SM, RADIUS_MD, RADIUS_LG = 4, 8, 12  # chip and menu item, button and input, card and chart

# Type roles.
FONT_TITLE, FONT_HEADING, FONT_METRIC, FONT_NAME, FONT_VALUE = 24, 18, 24, 16, 20

CARD_PAD = SP_LG  # padding inside every card
PAGE_TOP = SP_LG  # gap between the page header and the first thing on a page
TARGET = 40  # smallest clickable size we draw ourselves (WCAG 2.2 asks 24 px; 44 is the comfort target)
