#!/usr/bin/env python3
"""Analyze barge-in timing from captured Render logs.

Expected input files are from scripts/capture_render_logs.sh under ops/logs.
"""

from __future__ import annotations

import argparse
import glob
import re
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable


TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+"
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})"
)
RID_RE = re.compile(r"rid=([A-Za-z0-9]+)")
CALLSID_RE = re.compile(r"callSid=([A-Za-z0-9]+)")


@dataclass(frozen=True)
class Event:
    rid: str
    callsid: str
    mode: str
    vad: datetime
    clear_ms: int | None
    done_ms: int | None


def parse_dt(line: str) -> datetime | None:
    match = TS_RE.match(line)
    if not match:
        return None
    dt_s, ms_s = match.groups()
    return datetime.strptime(dt_s, "%Y-%m-%d %H:%M:%S").replace(
        microsecond=int(ms_s) * 1000
    )


def percentile(sorted_vals: list[int], pct: int) -> int:
    if not sorted_vals:
        raise ValueError("percentile requested on empty list")
    idx = round((pct / 100) * (len(sorted_vals) - 1))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return sorted_vals[idx]


def parse_events(lines: Iterable[str]) -> list[Event]:
    events: list[Event] = []
    current_rid: str | None = None
    current_callsid: str | None = None
    pending: dict[str, object] | None = None

    for line in lines:
        ts = parse_dt(line)
        if ts is None:
            continue

        if "TWILIO_WS_START" in line:
            rid_m = RID_RE.search(line)
            callsid_m = CALLSID_RE.search(line)
            if rid_m:
                current_rid = rid_m.group(1)
            if callsid_m:
                current_callsid = callsid_m.group(1)
            pending = None
            continue

        if "TWILIO_WS_STOP" in line:
            pending = None
            current_rid = None
            current_callsid = None
            continue

        if current_rid is None:
            continue

        if "OpenAI VAD: user speech START" in line:
            pending = {
                "rid": current_rid,
                "callsid": current_callsid or "",
                "vad": ts,
                "clear": None,
                "done": None,
                "early": False,
            }
            continue

        if pending is None:
            continue

        if "BARGE-IN_IGNORED_EARLY" in line:
            pending["early"] = True
            pending["done"] = ts
            events.append(materialize_event(pending))
            pending = None
            continue

        if "TWILIO_CLEAR_SENT" in line:
            pending["clear"] = ts
            continue

        if "OPENAI_RESPONSE_DONE id=" in line:
            pending["done"] = ts
            if pending["clear"] is not None or pending["early"]:
                events.append(materialize_event(pending))
                pending = None

    # Deduplicate identical entries.
    seen: set[tuple[str, str, str, datetime, int | None, int | None]] = set()
    uniq: list[Event] = []
    for evt in sorted(events, key=lambda x: x.vad):
        key = (evt.rid, evt.callsid, evt.mode, evt.vad, evt.clear_ms, evt.done_ms)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(evt)
    return uniq


def materialize_event(raw: dict[str, object]) -> Event:
    vad = raw["vad"]
    clear = raw["clear"]
    done = raw["done"]
    early = bool(raw["early"])
    if not isinstance(vad, datetime):
        raise ValueError("invalid vad timestamp")
    clear_ms = int((clear - vad).total_seconds() * 1000) if isinstance(clear, datetime) else None
    done_ms = int((done - vad).total_seconds() * 1000) if isinstance(done, datetime) else None
    mode = "ignored_early" if early else ("accepted" if clear is not None else "other")
    return Event(
        rid=str(raw["rid"]),
        callsid=str(raw["callsid"]),
        mode=mode,
        vad=vad,
        clear_ms=clear_ms,
        done_ms=done_ms,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze barge-in latency from Render logs.")
    parser.add_argument(
        "--glob",
        dest="glob_pattern",
        default="ops/logs/vozlia-ng-*.log",
        help="Glob for input log files (default: ops/logs/vozlia-ng-*.log)",
    )
    parser.add_argument(
        "--last-files",
        type=int,
        default=8,
        help="Only read the newest N files (default: 8)",
    )
    parser.add_argument("--rid", help="Filter by rid")
    parser.add_argument("--callsid", help="Filter by callSid")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    files = sorted(glob.glob(args.glob_pattern))
    if args.last_files > 0:
        files = files[-args.last_files :]
    if not files:
        print("No log files found.")
        return 1

    lines: list[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines.extend(handle.readlines())

    events = parse_events(lines)
    if args.rid:
        events = [e for e in events if e.rid == args.rid]
    if args.callsid:
        events = [e for e in events if e.callsid == args.callsid]

    print(f"files={len(files)} events={len(events)}")
    print("rid,callsid,mode,vad,clear_ms,done_ms")
    for evt in events:
        clear_s = "" if evt.clear_ms is None else str(evt.clear_ms)
        done_s = "" if evt.done_ms is None else str(evt.done_ms)
        print(
            f"{evt.rid},{evt.callsid},{evt.mode},"
            f"{evt.vad.isoformat(timespec='milliseconds')},{clear_s},{done_s}"
        )

    accepted = [e for e in events if e.mode == "accepted"]
    ignored_early = [e for e in events if e.mode == "ignored_early"]

    print(f"SUMMARY ignored_early_count={len(ignored_early)}")

    if accepted:
        clear_vals = sorted(e.clear_ms for e in accepted if e.clear_ms is not None)
        done_vals = sorted(e.done_ms for e in accepted if e.done_ms is not None)
        if clear_vals:
            print(
                "SUMMARY accepted_clear_ms "
                f"count={len(clear_vals)} min={clear_vals[0]} "
                f"p50={percentile(clear_vals, 50)} "
                f"p90={percentile(clear_vals, 90)} "
                f"max={clear_vals[-1]} mean={round(sum(clear_vals)/len(clear_vals), 1)} "
                f"median={round(median(clear_vals), 1)}"
            )
        if done_vals:
            print(
                "SUMMARY accepted_done_ms "
                f"count={len(done_vals)} min={done_vals[0]} "
                f"p50={percentile(done_vals, 50)} "
                f"p90={percentile(done_vals, 90)} "
                f"max={done_vals[-1]} mean={round(sum(done_vals)/len(done_vals), 1)} "
                f"median={round(median(done_vals), 1)}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
