"""
audit.py — Local, tamper-evident audit trail

Every pipeline decision is written to an append-only, hash-chained log:
each entry stores the SHA-256 of the previous entry, so any edit to an
earlier entry breaks the chain and is detectable with verify_chain().

This is the local record. The PRISM (Block Convey) integration in prism.py
sends LLM traces and per-line trajectories to the PRISM platform.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

GENESIS_HASH = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(entry: Dict[str, Any]) -> str:
    payload = json.dumps({k: v for k, v in entry.items() if k != "hash"}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, rfq_id: str):
        self.rfq_id = rfq_id
        self.entries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, event: str, line_number: Optional[int] = None, actor: str = "system", **details) -> Dict[str, Any]:
        with self._lock:
            entry = {
                "seq": len(self.entries) + 1,
                "rfq_id": self.rfq_id,
                "timestamp": _now(),
                "event": event,
                "line_number": line_number,
                "actor": actor,
                "details": details,
                "prev_hash": self.entries[-1]["hash"] if self.entries else GENESIS_HASH,
            }
            entry["hash"] = _hash(entry)
            self.entries.append(entry)
            return entry

    def verify_chain(self) -> Dict[str, Any]:
        prev = GENESIS_HASH
        for e in self.entries:
            if e["prev_hash"] != prev or _hash(e) != e["hash"]:
                return {"valid": False, "broken_at_seq": e["seq"], "entries": len(self.entries)}
            prev = e["hash"]
        return {"valid": True, "entries": len(self.entries), "head_hash": prev}
