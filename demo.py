"""A fixed, deterministic sample week. No model calls; every row is marked ``demo``.

Shapes match the README: 45 requests (31% VDRI launch, 36% Hackathons,
9% English, 24% detours), 5 parked items, 3 corrections, a hidden priority.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import insight
from .store import Store, iso

GOALS = [
    {"name": "VDRI launch", "description": "VDRI launch: pilot customers, pricing and the investor deck", "planned_pct": 50},
    {"name": "Hackathons", "description": "Hackathons: build and submit the Hermes plugin", "planned_pct": 30},
    {"name": "English", "description": "English: daily speaking and writing practice", "planned_pct": 20},
]

# (goal, summary, tokens); 0 = detour
REQUESTS: list[tuple[int, str, int]] = [
    (1, "Draft pilot pricing tiers", 8200), (2, "Plugin hook signatures", 6400),
    (1, "Investor deck: market slide", 9100), (0, "VDRI website hero copy", 7300),
    (2, "Write classifier tests", 11800), (1, "Pilot customer email", 4100),
    (3, "Fix grammar in my pitch", 2600), (0, "VDRI website color palette", 5200),
    (2, "Debug cron blueprint", 9900), (1, "Competitor pricing table", 7700),
    (2, "README structure", 5300), (0, "Compare standing desks", 3900),
    (1, "Deck: traction slide", 6800), (2, "Telegram buttons test", 4700),
    (0, "VDRI website footer links", 3100), (1, "Pilot onboarding checklist", 5600),
    (2, "Precision eval script", 12400), (3, "Practice: pitch out loud", 2200),
    (0, "Weekend trip ideas", 2800), (1, "Cap table question", 4300),
    (2, "PNG report layout", 10300), (0, "VDRI website SEO meta tags", 4400),
    (1, "Pilot contract template", 7900), (2, "Video script beats", 3800),
    (0, "Recipe for dinner party", 1900), (2, "Catalog YAML fields", 3300),
    (1, "Deck: team slide", 5100), (2, "Guard path tests", 6900),
    (0, "VDRI website pricing page", 6100), (1, "Follow-up to pilot lead", 3600),
    (2, "Desktop chip API", 5800), (3, "Rewrite email in English", 2400),
    (0, "Fantasy football lineup", 1700), (2, "CI workflow", 4100),
    (1, "Pilot feedback summary", 5400), (2, "Onboarding copy", 2900),
    (0, "VDRI website blog post", 8800), (1, "Unit economics sheet", 6600),
    (2, "Fix flaky test", 4500), (3, "Phrasal verbs quiz", 1800),
    (0, "Laptop battery tips", 1500), (2, "Release notes", 2700),
    (1, "Deck: ask slide", 4900), (2, "Judge feedback pass", 7200),
    (1, "Pilot kickoff agenda", 3800),
]

PARKED = [
    "Research standing desks under $400",
    "Summarize 3 posts on VDRI website SEO",
    "Draft weekend trip plan for 2",
    "Reply to Ana about the dinner",
    "Renew the domain for the VDRI site",
]

CORRECTIONS = [
    ("Pilot contract template", 1),
    ("Video script beats", 2),
    ("Laptop battery tips", 0),
]

HIDDEN = {
    "theme": "VDRI website",
    "count": 6,
    "examples": ["VDRI website hero copy", "VDRI website pricing page"],
    "suggested_goal": "Ship the VDRI website",
}


def load(store: Store, now: datetime) -> dict[str, int]:
    """Insert the sample week relative to ``now``. Re-running replaces it."""
    store.clear_demo()
    if not store.has_goals():
        store.set_goals(GOALS, now)
        store.meta_set("demo_goals", "1")
    start = now - timedelta(days=6, hours=20)
    step = timedelta(days=6, hours=18) / len(REQUESTS)
    for i, (goal, summary, tokens) in enumerate(REQUESTS):
        ts = start + step * i
        store.insert_turn(
            ts=ts, session_id="demo", summary=summary, source="demo", goal=goal, confidence=0.9, tokens=tokens,
            decision="do_now" if goal == 0 and "website" in summary else None,
        )
    for i, summary in enumerate(PARKED):
        store.queue_add(summary, start + timedelta(days=1 + i), source="demo")
    for i, (summary, goal) in enumerate(CORRECTIONS):
        store.correction_add(summary, goal, start + timedelta(days=2 + i), source="demo")
    store.self_cost_add("bussola_classifier", 1180, now - timedelta(hours=1), source="demo")
    week_start = iso(now - timedelta(days=7))
    insight.remember(store, f"demo:{week_start}", HIDDEN, pinned=True)
    return {"requests": len(REQUESTS), "parked": len(PARKED)}


def clear(store: Store) -> None:
    store.clear_demo()
