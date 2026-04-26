"""Read-only dashboard CLI: summarize traces + telemetry from a forge home dir."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def summarize(home: str | Path = ".forge") -> dict[str, Any]:
    home = Path(home)
    summary: dict[str, Any] = {"home": str(home), "sessions": []}
    traces = home / "traces"
    if traces.exists():
        for sess_dir in sorted(traces.iterdir()):
            entry = {"id": sess_dir.name}
            for stream in ("events", "tool_calls", "messages"):
                p = sess_dir / f"{stream}.jsonl"
                entry[f"{stream}_lines"] = (
                    sum(1 for _ in p.open()) if p.exists() else 0
                )
            summary["sessions"].append(entry)

    telemetry = home / "telemetry.jsonl"
    if telemetry.exists():
        records = [json.loads(l) for l in telemetry.read_text().splitlines() if l.strip()]
        summary["telemetry"] = {
            "rows": len(records),
            "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in records), 6),
            "total_input_tokens": sum(r.get("input_tokens", 0) for r in records),
            "total_output_tokens": sum(r.get("output_tokens", 0) for r in records),
        }
    return summary


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--home", default=".forge")
    args = p.parse_args()
    print(json.dumps(summarize(args.home), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
