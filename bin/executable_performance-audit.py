#!/usr/bin/env python3
"""Audit Claude Code tool call performance.

Joins PreToolUse (start) and PostToolUse (end) logs to surface slow calls,
duplicates, parallelization opportunities, and per-project breakdowns.

Usage:
    performance-audit.py                  # full audit
    performance-audit.py --since 7d       # last 7 days
    performance-audit.py --slow 2         # only calls >2s
    performance-audit.py --by-project     # group by working directory
    performance-audit.py --top 20         # top 20 patterns
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

LOG_FILE = Path.home() / ".claude" / "performance-audit.jsonl"


def load_log(since=None):
    """Load and optionally filter log entries."""
    if not LOG_FILE.exists():
        print(f"No log file found at {LOG_FILE}")
        print("The PreToolUse/PostToolUse performance hooks need to be configured first.")
        sys.exit(1)

    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if since:
                    ts = datetime.fromisoformat(entry["ts"])
                    if ts < since:
                        continue
                entries.append(entry)
            except (json.JSONDecodeError, KeyError):
                continue

    return entries


def join_entries(entries):
    """Join start/end entries by tool_use_id. Returns list of joined records."""
    starts = {}
    ends = {}

    for e in entries:
        tid = e.get("tool_use_id", "")
        if not tid:
            continue
        if e.get("event") == "start":
            starts[tid] = e
        elif e.get("event") == "end":
            ends[tid] = e

    joined = []
    unmatched_starts = 0
    unmatched_ends = 0

    for tid, start in starts.items():
        if tid in ends:
            end = ends[tid]
            try:
                t0 = datetime.fromisoformat(start["ts"])
                t1 = datetime.fromisoformat(end["ts"])
                duration = (t1 - t0).total_seconds()
            except (ValueError, KeyError):
                continue

            joined.append({
                "tool": start.get("tool", ""),
                "tool_use_id": tid,
                "session_id": start.get("session_id", ""),
                "cwd": start.get("cwd", ""),
                "input": start.get("input", {}),
                "duration": duration,
                "output_size": end.get("output_size", 0),
                "error": end.get("error", False),
                "start_ts": start["ts"],
                "end_ts": end["ts"],
            })
        else:
            unmatched_starts += 1

    unmatched_ends = len(ends) - (len(starts) - unmatched_starts)

    return joined, unmatched_starts, max(0, unmatched_ends)


def input_key(record):
    """Create a hashable key from tool + input for dedup detection."""
    return json.dumps({"tool": record["tool"], "input": record["input"]}, sort_keys=True)


def input_summary(record):
    """Short human-readable summary of the tool input."""
    tool = record["tool"]
    inp = record.get("input", {})
    if tool == "Bash":
        cmd = inp.get("command", "")
        return cmd[:80] if cmd else "(empty)"
    elif tool in ("Read", "Edit", "Write"):
        return inp.get("file_path", "")[:80]
    elif tool == "Glob":
        return inp.get("pattern", "")[:60]
    elif tool == "Grep":
        return inp.get("pattern", "")[:60]
    elif tool == "Agent":
        return inp.get("description", "")[:60]
    elif tool.startswith("mcp__"):
        return tool
    else:
        return str(inp)[:60]


def percentile(values, p):
    """Simple percentile calculation."""
    if not values:
        return 0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * p / 100)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def fmt_duration(seconds):
    """Format duration for display."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        return f"{seconds/60:.1f}m"


def report_slowest(joined, top_n):
    """Report slowest tool call patterns by median duration."""
    # Group by tool + generalized input
    groups = defaultdict(list)
    for r in joined:
        tool = r["tool"]
        if tool == "Bash":
            parts = r["input"].get("command", "").split()
            key = f"Bash: {' '.join(parts[:2])}" if len(parts) >= 2 else f"Bash: {parts[0]}" if parts else "Bash: (empty)"
        elif tool in ("Read", "Edit", "Write"):
            fp = r["input"].get("file_path", "")
            parent = str(Path(fp).parent) if fp else ""
            key = f"{tool}: {parent}/*"
        elif tool == "Agent":
            key = f"Agent: {r['input'].get('subagent_type', r['input'].get('description', '')[:30])}"
        else:
            key = tool
        groups[key].append(r["duration"])

    rows = []
    for key, durations in groups.items():
        rows.append({
            "pattern": key,
            "count": len(durations),
            "median": median(durations),
            "p95": percentile(durations, 95),
            "total": sum(durations),
        })

    rows.sort(key=lambda x: -x["median"])

    print("## Slowest Tool Patterns (by median)\n")
    print(f"| {'Pattern':<50} | {'Count':>5} | {'Median':>8} | {'p95':>8} |")
    print(f"|{'-'*50}--|{'-'*5}--|{'-'*8}--|{'-'*8}--|")
    for row in rows[:top_n]:
        print(f"| {row['pattern']:<50} | {row['count']:>5} | {fmt_duration(row['median']):>8} | {fmt_duration(row['p95']):>8} |")
    print()


def report_highest_total(joined, top_n):
    """Report tool patterns ranked by total wall time."""
    groups = defaultdict(list)
    for r in joined:
        tool = r["tool"]
        if tool == "Bash":
            parts = r["input"].get("command", "").split()
            key = f"Bash: {' '.join(parts[:2])}" if len(parts) >= 2 else f"Bash: {parts[0]}" if parts else "Bash: (empty)"
        else:
            key = tool
        groups[key].append(r["duration"])

    rows = []
    for key, durations in groups.items():
        rows.append({
            "pattern": key,
            "count": len(durations),
            "median": median(durations),
            "total": sum(durations),
        })

    rows.sort(key=lambda x: -x["total"])

    print("## Highest Total Time (count x duration)\n")
    print(f"| {'Pattern':<50} | {'Count':>5} | {'Median':>8} | {'Total':>8} |")
    print(f"|{'-'*50}--|{'-'*5}--|{'-'*8}--|{'-'*8}--|")
    for row in rows[:top_n]:
        print(f"| {row['pattern']:<50} | {row['count']:>5} | {fmt_duration(row['median']):>8} | {fmt_duration(row['total']):>8} |")
    print()


def report_duplicates(joined, top_n):
    """Report identical tool+input pairs within the same session."""
    # Group by session + input key
    session_calls = defaultdict(list)
    for r in joined:
        key = (r["session_id"], input_key(r))
        session_calls[key].append(r)

    dupes = []
    for (session_id, key), calls in session_calls.items():
        if len(calls) >= 2:
            dupes.append({
                "key": key,
                "session_id": session_id[:12],
                "count": len(calls),
                "total_time": sum(c["duration"] for c in calls),
                "summary": input_summary(calls[0]),
                "tool": calls[0]["tool"],
            })

    dupes.sort(key=lambda x: -x["count"])

    if not dupes:
        print("## Duplicate Calls\n")
        print("No duplicate tool+input pairs found within sessions.\n")
        return

    print("## Duplicate Calls (same tool+input within a session)\n")
    print(f"| {'Tool':<10} | {'Input Summary':<45} | {'Repeats':>7} | {'Wasted':>8} | {'Session':>12} |")
    print(f"|{'-'*10}--|{'-'*45}--|{'-'*7}--|{'-'*8}--|{'-'*12}--|")
    for d in dupes[:top_n]:
        wasted = d["total_time"] * (1 - 1 / d["count"])
        print(f"| {d['tool']:<10} | {d['summary']:<45} | {d['count']:>7} | {fmt_duration(wasted):>8} | {d['session_id']:>12} |")
    print()


def report_sequential_chains(joined, top_n):
    """Find consecutive tool calls in the same session that could be parallelized."""
    # Group by session, sort by start time
    by_session = defaultdict(list)
    for r in joined:
        by_session[r["session_id"]].append(r)

    for calls in by_session.values():
        calls.sort(key=lambda x: x["start_ts"])

    chains = []
    for session_id, calls in by_session.items():
        if len(calls) < 2:
            continue

        current_chain = [calls[0]]
        for i in range(1, len(calls)):
            prev_end = datetime.fromisoformat(calls[i - 1]["end_ts"])
            curr_start = datetime.fromisoformat(calls[i]["start_ts"])
            gap = (curr_start - prev_end).total_seconds()

            # Consecutive if gap < 1s (allow for processing time)
            if gap < 1.0:
                current_chain.append(calls[i])
            else:
                if len(current_chain) >= 2:
                    # Check if tools in chain are independent (different tools or same read-only)
                    tools_in_chain = [c["tool"] for c in current_chain]
                    total_time = sum(c["duration"] for c in current_chain)
                    max_time = max(c["duration"] for c in current_chain)
                    savings = total_time - max_time

                    if savings > 0.5:  # Only report if >0.5s savings
                        chains.append({
                            "session_id": session_id[:12],
                            "tools": tools_in_chain,
                            "count": len(current_chain),
                            "total_time": total_time,
                            "potential_savings": savings,
                            "summaries": [input_summary(c)[:30] for c in current_chain[:4]],
                        })

                current_chain = [calls[i]]

        # Handle last chain
        if len(current_chain) >= 2:
            tools_in_chain = [c["tool"] for c in current_chain]
            total_time = sum(c["duration"] for c in current_chain)
            max_time = max(c["duration"] for c in current_chain)
            savings = total_time - max_time
            if savings > 0.5:
                chains.append({
                    "session_id": session_id[:12],
                    "tools": tools_in_chain,
                    "count": len(current_chain),
                    "total_time": total_time,
                    "potential_savings": savings,
                    "summaries": [input_summary(c)[:30] for c in current_chain[:4]],
                })

    chains.sort(key=lambda x: -x["potential_savings"])

    if not chains:
        print("## Sequential Chains\n")
        print("No significant parallelization opportunities found.\n")
        return

    print("## Sequential Chains (potential parallelization)\n")
    print(f"| {'Tools':<40} | {'Chain':>5} | {'Total':>8} | {'Savings':>8} | {'Session':>12} |")
    print(f"|{'-'*40}--|{'-'*5}--|{'-'*8}--|{'-'*8}--|{'-'*12}--|")
    for c in chains[:top_n]:
        tools_str = ", ".join(c["tools"][:4])
        if len(c["tools"]) > 4:
            tools_str += "..."
        print(f"| {tools_str:<40} | {c['count']:>5} | {fmt_duration(c['total_time']):>8} | {fmt_duration(c['potential_savings']):>8} | {c['session_id']:>12} |")
    print()


def report_by_project(joined, top_n):
    """Group by cwd to show per-project stats."""
    by_project = defaultdict(list)
    home = str(Path.home())
    for r in joined:
        cwd = r.get("cwd", "(unknown)")
        # Shorten home paths
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        by_project[cwd].append(r)

    rows = []
    for project, calls in by_project.items():
        durations = [c["duration"] for c in calls]
        errors = sum(1 for c in calls if c.get("error"))
        rows.append({
            "project": project,
            "calls": len(calls),
            "total_time": sum(durations),
            "median": median(durations),
            "errors": errors,
        })

    rows.sort(key=lambda x: -x["total_time"])

    print("## Per-Project Breakdown\n")
    print(f"| {'Project':<45} | {'Calls':>5} | {'Total':>8} | {'Median':>8} | {'Errors':>6} |")
    print(f"|{'-'*45}--|{'-'*5}--|{'-'*8}--|{'-'*8}--|{'-'*6}--|")
    for row in rows[:top_n]:
        print(f"| {row['project']:<45} | {row['calls']:>5} | {fmt_duration(row['total_time']):>8} | {fmt_duration(row['median']):>8} | {row['errors']:>6} |")
    print()


def report_recommendations(joined):
    """Generate actionable recommendations."""
    print("## Recommendations\n")

    recommendations = []

    # Find caching opportunities (same exact call 3+ times across sessions)
    call_counts = Counter()
    for r in joined:
        call_counts[input_key(r)] += 1

    for key, count in call_counts.most_common(10):
        if count >= 3:
            data = json.loads(key)
            tool = data["tool"]
            inp = data["input"]
            if tool == "Bash":
                summary = inp.get("command", "")[:60]
            elif tool in ("Read", "Edit", "Write"):
                summary = inp.get("file_path", "")[:60]
            else:
                summary = str(inp)[:60]
            recommendations.append(
                f"**Cache opportunity:** `{tool}` — `{summary}` runs {count} times across sessions"
            )

    # Find script candidates (same Bash prefix runs many times)
    bash_calls = [r for r in joined if r["tool"] == "Bash"]
    prefix_groups = defaultdict(list)
    for r in bash_calls:
        parts = r["input"].get("command", "").split()
        if len(parts) >= 2:
            prefix = " ".join(parts[:2])
            prefix_groups[prefix].append(r)

    for prefix, calls in sorted(prefix_groups.items(), key=lambda x: -len(x[1])):
        if len(calls) >= 5:
            total = sum(c["duration"] for c in calls)
            recommendations.append(
                f"**Script candidate:** `{prefix} ...` runs {len(calls)} times ({fmt_duration(total)} total) — consider a wrapper script"
            )

    # Find error-prone tools
    error_counts = defaultdict(lambda: {"total": 0, "errors": 0})
    for r in joined:
        error_counts[r["tool"]]["total"] += 1
        if r.get("error"):
            error_counts[r["tool"]]["errors"] += 1

    for tool, counts in error_counts.items():
        if counts["errors"] >= 3 and counts["errors"] / counts["total"] > 0.1:
            rate = counts["errors"] / counts["total"] * 100
            recommendations.append(
                f"**High error rate:** `{tool}` fails {rate:.0f}% of the time ({counts['errors']}/{counts['total']})"
            )

    if not recommendations:
        print("No specific recommendations at this time. Collect more data.\n")
    else:
        for r in recommendations:
            print(f"- {r}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Audit Claude Code tool call performance")
    parser.add_argument("--since", help="Time window (e.g., 7d, 24h, 30d)")
    parser.add_argument("--slow", type=float, help="Only show calls slower than N seconds")
    parser.add_argument("--by-project", action="store_true", help="Group by working directory")
    parser.add_argument("--top", type=int, default=15, help="Show top N patterns")
    args = parser.parse_args()

    # Parse --since
    since = None
    if args.since:
        m = re.match(r"(\d+)(d|h|m)", args.since)
        if m:
            val, unit = int(m.group(1)), m.group(2)
            delta = {"d": timedelta(days=val), "h": timedelta(hours=val), "m": timedelta(minutes=val)}[unit]
            since = datetime.now(timezone.utc).astimezone() - delta

    entries = load_log(since)
    joined, unmatched_starts, unmatched_ends = join_entries(entries)

    if not joined:
        print("No matched start/end pairs found.")
        if unmatched_starts or unmatched_ends:
            print(f"  ({unmatched_starts} unmatched starts, {unmatched_ends} unmatched ends)")
        return

    # Filter by --slow
    if args.slow:
        joined = [r for r in joined if r["duration"] >= args.slow]
        if not joined:
            print(f"No tool calls slower than {args.slow}s found.")
            return

    total_time = sum(r["duration"] for r in joined)
    error_count = sum(1 for r in joined if r.get("error"))

    print("## Performance Audit\n")
    print(f"- Matched tool calls: **{len(joined)}**")
    print(f"- Total tool time: **{fmt_duration(total_time)}**")
    print(f"- Errors: **{error_count}**")
    if unmatched_starts or unmatched_ends:
        print(f"- Unmatched entries: {unmatched_starts} starts, {unmatched_ends} ends")
    if since:
        print(f"- Time window: since {since.strftime('%Y-%m-%d %H:%M')}")
    print()

    if args.by_project:
        report_by_project(joined, args.top)
        return

    report_slowest(joined, args.top)
    report_highest_total(joined, args.top)
    report_duplicates(joined, args.top)
    report_sequential_chains(joined, args.top)
    report_recommendations(joined)


if __name__ == "__main__":
    main()
