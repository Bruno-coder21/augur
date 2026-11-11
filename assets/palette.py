"""One palette for every surface. Blue, amber and violet stay distinguishable
for the common forms of color blindness; green-vs-red is never used."""

BACKGROUND = "#0F1115"   # graphite
TEXT = "#E8E6E1"         # bone
TEXT_MUTED = "#9CA3AF"   # light grey
GOAL_COLORS = {1: "#3B82F6", 2: "#F59E0B", 3: "#A855F7"}  # blue, amber, violet
DETOUR = "#6B7280"       # grey
TRACK = "#1F232B"        # planned-bar background on the dark ground

# Truecolor ANSI for the CLI panel (same hex values as above).
def ansi(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\x1b[38;2;{r};{g};{b}m"

ANSI_RESET = "\x1b[0m"
ANSI_DIM = "\x1b[2m"
ANSI_BOLD = "\x1b[1m"


def goal_color(slot: int) -> str:
    """Color by slot number, never by name. Slot 0 is the detour color."""
    return GOAL_COLORS.get(slot, DETOUR)
