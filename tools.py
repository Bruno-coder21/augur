"""The 4 tools. Each handler takes ``(args, **kwargs)``, returns a JSON string, never raises."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from . import friday
from .store import parse_iso

log = logging.getLogger("bussola.tools")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _safe(fn: Callable[..., dict[str, Any]]) -> Callable[..., str]:
    def handler(args: Any = None, **kwargs: Any) -> str:
        try:
            return _json(fn(args if isinstance(args, dict) else {}, **kwargs))
        except ValueError as exc:
            return _json({"ok": False, "error": str(exc)})
        except Exception as exc:
            log.warning("bussola tool %s failed: %s", fn.__name__, exc, exc_info=True)
            return _json({"ok": False, "error": "internal error; the details are in the Hermes log"})

    handler.__name__ = fn.__name__
    return handler


def make_handlers(app: Any) -> dict[str, Callable[..., str]]:
    def bussola_park(args: dict[str, Any], session_id: str = "", **_: Any) -> dict[str, Any]:
        summary = str(args.get("summary") or "").strip()
        if not summary:
            raise ValueError("summary is required (at most 60 characters)")
        return app.park(summary, session_id=session_id)

    def bussola_queue(args: dict[str, Any], **_: Any) -> dict[str, Any]:
        status = str(args.get("status") or "parked")
        if status not in ("parked", "done", "needs_you", "dropped", "all"):
            raise ValueError("status must be parked, done, needs_you, dropped or all")
        now = app.clock()
        items = app.store.queue_list(None if status == "all" else status)
        return {
            "ok": True,
            "drafts_dir": str(app.drafts_dir),
            "items": [
                {
                    "id": q["id"],
                    "summary": q["summary60"],
                    "status": q["status"],
                    "age_days": max(0, (now - parse_iso(q["ts"])).days),
                    **({"result_line": q["result_line"]} if q.get("result_line") else {}),
                }
                for q in items
            ],
        }

    def bussola_done(args: dict[str, Any], **_: Any) -> dict[str, Any]:
        try:
            item_id = int(args.get("id"))
        except (TypeError, ValueError):
            raise ValueError("id must be the integer id from bussola_queue") from None
        status = str(args.get("status") or "")
        if app.store.queue_get(item_id) is None:
            raise ValueError(f"no Queue item with id {item_id}")
        draft = args.get("draft_path") or None
        if draft:
            resolved = friday.resolve_path(str(draft))
            if not friday.inside(resolved, app.drafts_dir) or not os.path.isfile(str(resolved)):
                raise ValueError("draft_path must be an existing file inside drafts_dir")
            draft = str(resolved)
        app.store.queue_close(item_id, status, str(args.get("result_line") or ""), draft, app.clock())
        return {"ok": True, "id": item_id, "status": status, "remaining": app.store.queue_size()}

    def bussola_report(args: dict[str, Any], **_: Any) -> dict[str, Any]:
        result = app.build_report()
        out: dict[str, Any] = {"ok": True, "caption": result["caption"]}
        if result.get("path"):
            out["path"] = result["path"]
            out["media_line"] = f"MEDIA:{result['path']}"
        else:
            out["text"] = result["text"]
        return out

    return {
        "bussola_park": _safe(bussola_park),
        "bussola_queue": _safe(bussola_queue),
        "bussola_done": _safe(bussola_done),
        "bussola_report": _safe(bussola_report),
    }

