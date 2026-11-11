"""Tool schemas the model sees. Short descriptions; the Friday prompt does the rest."""

AUGUR_PARK = {
    "name": "augur_park",
    "description": (
        "Park a detour in the user's Augur Queue so it is handled in the weekly Friday run instead of now. "
        "Call it when the user chooses \"Park it\" after a 🧭 question, or asks to leave something for later."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What to do later, at most 60 characters, no secrets.",
            }
        },
        "required": ["summary"],
    },
}

AUGUR_QUEUE = {
    "name": "augur_queue",
    "description": "List the items parked in the user's Augur Queue, oldest first, plus drafts_dir for draft files.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["parked", "done", "needs_you", "dropped", "all"],
                "description": "Which items to list (default: parked).",
            }
        },
    },
}

AUGUR_DONE = {
    "name": "augur_done",
    "description": (
        "Close one Queue item. status \"done\" when the research or draft is ready, \"needs_you\" when it needs "
        "the user's approval, decision or an action outside reading and drafting, \"dropped\" when it no longer matters."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "Queue item id from augur_queue."},
            "status": {"type": "string", "enum": ["done", "needs_you", "dropped"]},
            "result_line": {"type": "string", "description": "One line: what is ready, or why it needs the user."},
            "draft_path": {"type": "string", "description": "Absolute path of the draft file inside drafts_dir, if any."},
        },
        "required": ["id", "status", "result_line"],
    },
}

AUGUR_REPORT = {
    "name": "augur_report",
    "description": (
        "Build the user's weekly Augur report image. Returns the PNG path, the caption lines and the MEDIA line "
        "to end your reply with."
    ),
    "parameters": {"type": "object", "properties": {}},
}
