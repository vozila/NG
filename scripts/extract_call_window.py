#!/usr/bin/env python3
"""Extract a single call window from captured Render logs by rid.

This keeps:
- Any line explicitly containing the requested rid.
- Lines inside the websocket call window for that rid
  (TWILIO_WS_START -> TWILIO_WS_STOP / flow_a.call_stopped),
  which captures events that do not include rid on every line.
"""

from __future__ import annotations

import argparse
import glob
import re
from datetime import datetime, timezone
from pathlib import Path

CALLSID_RE = re.compile(r"callSid=([A-Za-z0-9]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract call window from Render logs.")
    parser.add_argument("--rid", required=True, help="Request/call correlation id (rid=...)")
    parser.add_argument(
        "--glob",
        dest="glob_pattern",
        default="ops/logs/vozlia-ng-*.log",
        help="Input log glob (default: ops/logs/vozlia-ng-*.log)",
    )
    parser.add_argument(
        "--out",
        help="Output path. Default: ops/logs/extract-<rid>-<utc>.log",
    )
    parser.add_argument(
        "--last-files",
        type=int,
        default=0,
        help="Only read the newest N files after ordering (default: 0 = all)",
    )
    parser.add_argument(
        "--sort-by",
        choices=("name", "mtime"),
        default="name",
        help="Order files by name or mtime before applying --last-files (default: name)",
    )
    return parser.parse_args()


def default_out_path(rid: str) -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("ops/logs") / f"extract-{rid}-{ts}.log"


def select_files(glob_pattern: str, sort_by: str, last_files: int) -> list[Path]:
    files = [Path(p) for p in glob.glob(glob_pattern)]
    if sort_by == "mtime":
        files.sort(key=lambda p: (p.stat().st_mtime, p.name))
    else:
        files.sort(key=lambda p: p.name)
    if last_files > 0:
        files = files[-last_files:]
    return files


def main() -> int:
    args = parse_args()
    rid_token = f"rid={args.rid}"

    files = select_files(args.glob_pattern, args.sort_by, args.last_files)
    if not files:
        print(f"No files matched: {args.glob_pattern}")
        return 1

    out_path = Path(args.out) if args.out else default_out_path(args.rid)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    in_ws_window = False
    active_callsid: str | None = None
    matched = 0
    start_markers = 0
    stop_markers = 0

    with out_path.open("w", encoding="utf-8") as out:
        for path in files:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    has_rid = rid_token in line
                    callsid_m = CALLSID_RE.search(line)
                    line_callsid = callsid_m.group(1) if callsid_m else None

                    is_start = has_rid and "TWILIO_WS_START" in line
                    is_stop = False
                    if "TWILIO_WS_STOP" in line:
                        if has_rid:
                            is_stop = True
                        elif in_ws_window and active_callsid and line_callsid == active_callsid:
                            is_stop = True
                    if has_rid and "FLOW_A_EVENT_EMITTED type=flow_a.call_stopped" in line:
                        is_stop = True

                    if is_start:
                        in_ws_window = True
                        active_callsid = line_callsid
                        start_markers += 1

                    keep = has_rid or in_ws_window
                    if keep:
                        out.write(line)
                        matched += 1

                    if is_stop:
                        in_ws_window = False
                        active_callsid = None
                        stop_markers += 1

    print(
        f"Wrote {matched} lines to {out_path} "
        f"(files={len(files)} sort_by={args.sort_by} last_files={args.last_files})"
    )
    print(f"Markers: ws_start={start_markers} ws_stop={stop_markers}")
    if matched == 0:
        print("No matching lines found for this rid.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
