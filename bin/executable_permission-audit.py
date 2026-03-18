#!/usr/bin/env python3
"""Audit Claude Code tool usage and recommend permission allowlist rules.

Reads ~/.claude/permission-audit.jsonl (written by the PermissionRequest hook)
and suggests broadly-applicable, safe CLI command patterns for allowlisting.

Focuses on read-only and safe dev tool patterns — skips directory-specific
Edit/Write rules and anything that modifies state.

Output is meant to be read by a Claude Code agent, which then works with the
user to decide which rules to add and where.

Usage:
    permission-audit.py                  # show safe rule suggestions
    permission-audit.py --since 7d       # last 7 days only
    permission-audit.py --json           # output as JSON (for Claude Code)
    permission-audit.py --all            # include unsafe patterns too (for review)
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path

LOG_FILE = Path.home() / ".claude" / "permission-audit.jsonl"

# ── Safety taxonomy ─────────────────────────────────────────────────────────
# Maps command prefix → (safety, description)
# "safe"   = read-only or idempotent, fine to always allow
# "dev"    = build/lint/test tools, safe in dev context
# "unsafe" = modifies state, never auto-allow

SAFE_COMMANDS = {
    # Read-only system commands
    "which":      ("safe",   "command lookup"),
    "type":       ("safe",   "command lookup"),
    "file":       ("safe",   "file type detection"),
    "wc":         ("safe",   "line/word/byte count"),
    "sort":       ("safe",   "text sorting"),
    "uniq":       ("safe",   "dedup text"),
    "head":       ("safe",   "read first lines"),
    "tail":       ("safe",   "read last lines"),
    "less":       ("safe",   "pager"),
    "realpath":   ("safe",   "resolve path"),
    "dirname":    ("safe",   "parent directory"),
    "basename":   ("safe",   "filename"),
    "pwd":        ("safe",   "current directory"),
    "date":       ("safe",   "date/time"),
    "whoami":     ("safe",   "current user"),
    "hostname":   ("safe",   "hostname"),
    "uname":      ("safe",   "system info"),
    "sw_vers":    ("safe",   "macOS version"),
    "diff":       ("safe",   "file comparison"),
    "md5":        ("safe",   "checksum"),
    "shasum":     ("safe",   "checksum"),
    "stat":       ("safe",   "file metadata"),
    "du":         ("safe",   "disk usage"),
    "df":         ("safe",   "filesystem info"),
    "tree":       ("safe",   "directory tree"),
    "jq":         ("safe",   "JSON processor"),
    "yq":         ("safe",   "YAML processor"),
    "pbcopy":     ("safe",   "clipboard copy"),
    "pbpaste":    ("safe",   "clipboard paste"),
    "open":       ("safe",   "open files/URLs in macOS apps"),
    "afplay":     ("safe",   "play audio"),
    "tput":       ("safe",   "terminal info"),
    "printf":     ("safe",   "text formatting"),

    # Dev tools — build/lint/test/format
    "npm run":    ("dev",    "run project scripts"),
    "npm test":   ("dev",    "run tests"),
    "pnpm run":   ("dev",    "run project scripts"),
    "pnpm test":  ("dev",    "run tests"),
    "yarn run":   ("dev",    "run project scripts"),
    "yarn test":  ("dev",    "run tests"),
    "bun run":    ("dev",    "run project scripts"),
    "bun test":   ("dev",    "run tests"),
    "cargo build":("dev",    "rust build"),
    "cargo test": ("dev",    "rust test"),
    "cargo check":("dev",    "rust check"),
    "cargo clippy":("dev",   "rust linter"),
    "cargo fmt":  ("dev",    "rust formatter"),
    "go build":   ("dev",    "go build"),
    "go test":    ("dev",    "go test"),
    "go vet":     ("dev",    "go linter"),
    "make":       ("dev",    "build system"),
    "tsc":        ("dev",    "typescript compiler"),
    "eslint":     ("dev",    "JS linter"),
    "prettier":   ("dev",    "code formatter"),
    "black":      ("dev",    "python formatter"),
    "ruff":       ("dev",    "python linter"),
    "mypy":       ("dev",    "python type checker"),
    "pytest":     ("dev",    "python test runner"),
    "turbo":      ("dev",    "monorepo build tool"),

    # Tmux (read-only)
    "tmux list-sessions": ("safe", "list tmux sessions"),
    "tmux list-windows":  ("safe", "list tmux windows"),
    "tmux list-panes":    ("safe", "list tmux panes"),
    "tmux display-message":("safe","tmux info"),

    # Docker/k8s (read-only)
    "docker ps":       ("safe", "list containers"),
    "docker logs":     ("safe", "container logs"),
    "docker inspect":  ("safe", "container metadata"),
    "docker images":   ("safe", "list images"),
    "kubectl get":     ("safe", "k8s read"),
    "kubectl describe":("safe", "k8s describe"),
    "kubectl logs":    ("safe", "k8s logs"),

    # Workmux (read-only)
    "workmux status":  ("safe", "workspace status"),
    "workmux list":    ("safe", "list workspaces"),
}

# Patterns that should NEVER be auto-allowed, regardless of frequency
NEVER_ALLOW = [
    "rm *", "rm -rf *", "sudo *", "chmod 777*",
    "git push --force*", "git reset --hard*", "git checkout -- *",
    "git clean *", "drop database*", "DROP TABLE*",
    "curl * | sh", "curl * | bash", "wget * | sh", "wget * | bash",
]

# Commands that are inherently unsafe due to arbitrary execution
UNSAFE_BASES = {
    "python3", "python", "node", "ruby", "perl", "bash", "sh", "zsh",
    "eval", "exec", "source", "env",
    "rm", "rmdir", "mv", "cp", "chmod", "chown", "ln",
    "kill", "killall", "pkill",
    "curl", "wget", "ssh", "scp", "rsync",
    "cat",  # often used for heredoc writes, not just reading
    "npx", "npm exec", "pnpm exec",  # can download and execute arbitrary packages
    "docker run", "docker exec", "docker rm", "docker rmi",
    "kubectl delete", "kubectl apply", "kubectl exec",
    "pip install", "npm install", "brew install",
}






def is_never_allow(cmd):
    """Check if a command matches a never-allow pattern."""
    for pattern in NEVER_ALLOW:
        if fnmatch(cmd, pattern):
            return True
    return False


def classify_command(cmd):
    """Classify a bash command and return (safety, rule, description) or None.

    Returns the broadest safe rule for the command, or None if unsafe/unknown.
    """
    parts = cmd.split()
    if not parts:
        return None

    base = parts[0]

    # Check never-allow first
    if is_never_allow(cmd):
        return ("unsafe", None, "matches never-allow pattern")

    # Check unsafe base commands
    if base in UNSAFE_BASES:
        return ("unsafe", None, f"{base} runs arbitrary code")

    # Check 2-word prefixes first (more specific), then 1-word
    two_word = " ".join(parts[:2]) if len(parts) >= 2 else None

    if two_word and two_word in SAFE_COMMANDS:
        safety, desc = SAFE_COMMANDS[two_word]
        return (safety, f"Bash({two_word} *)", desc)

    # Check if the 2-word combo is an unsafe base
    if two_word and two_word in UNSAFE_BASES:
        return ("unsafe", None, f"{two_word} modifies state")

    if base in SAFE_COMMANDS:
        safety, desc = SAFE_COMMANDS[base]
        rule = f"Bash({base} *)" if len(parts) > 1 else f"Bash({base})"
        return (safety, rule, desc)

    return None  # unknown — don't suggest


def load_log(since=None):
    """Load and optionally filter log entries."""
    if not LOG_FILE.exists():
        print(f"No log file found at {LOG_FILE}", file=sys.stderr)
        print("The PermissionRequest hook needs to be configured first.", file=sys.stderr)
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


def analyze(entries, show_all=False):
    """Analyze entries and return suggested rules.

    Returns (suggestions, unknown) where suggestions is a list of dicts:
    {rule, safety, count, description, examples}
    """
    bash_commands = []
    for e in entries:
        if e.get("tool") == "Bash":
            cmd = e.get("input", {}).get("command", "")
            if cmd:
                bash_commands.append(cmd)

    rule_data = {}  # rule -> {safety, desc, count, examples}
    unknown_commands = Counter()

    for cmd in bash_commands:
        result = classify_command(cmd)
        if result is None:
            base = cmd.split()[0] if cmd.split() else cmd
            unknown_commands[base] += 1
            continue

        safety, rule, desc = result
        if rule is None:
            if show_all:
                base = cmd.split()[0] if cmd.split() else cmd
                unknown_commands[f"[UNSAFE] {base}"] += 1
            continue

        if rule not in rule_data:
            rule_data[rule] = {
                "rule": rule,
                "safety": safety,
                "description": desc,
                "count": 0,
                "examples": [],
            }
        rule_data[rule]["count"] += 1
        if len(rule_data[rule]["examples"]) < 3:
            short = cmd[:100]
            if short not in rule_data[rule]["examples"]:
                rule_data[rule]["examples"].append(short)

    suggestions = sorted(rule_data.values(), key=lambda x: -x["count"])
    return suggestions, dict(unknown_commands)


def main():
    parser = argparse.ArgumentParser(
        description="Suggest safe, broadly-applicable Claude Code permission rules"
    )
    parser.add_argument("--since", help="Time window (e.g., 7d, 24h, 30d)")
    parser.add_argument("--json", action="store_true", help="Output as JSON (for Claude Code)")
    parser.add_argument("--all", action="store_true", help="Also show unsafe/unknown patterns")
    parser.add_argument("--min-count", type=int, default=2, help="Min occurrences to suggest (default: 2)")
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

    if not entries:
        if args.json:
            print(json.dumps({"suggestions": [], "message": "No log entries found"}))
        else:
            print("No log entries found.")
        return

    suggestions, unknown = analyze(entries, show_all=args.all)

    # Filter by min count
    suggestions = [s for s in suggestions if s["count"] >= args.min_count]

    if args.json:
        output = {
            "suggestions": [
                {"rule": s["rule"], "safety": s["safety"], "count": s["count"],
                 "description": s["description"], "examples": s["examples"]}
                for s in suggestions
            ],
            "total_entries": len(entries),
        }
        if args.all and unknown:
            output["unknown_or_unsafe"] = unknown
        print(json.dumps(output, indent=2))
        return

    # Human-readable output
    total_bash = sum(1 for e in entries if e.get("tool") == "Bash")
    print(f"Permission audit: {len(entries)} prompts logged ({total_bash} Bash)")
    if since:
        print(f"Since: {since.strftime('%Y-%m-%d %H:%M')}")
    print()

    if not suggestions:
        print("No new safe rules to suggest. Your allowlist looks good!")
        if unknown and args.all:
            print(f"\nUnknown/unsafe patterns (not suggested):")
            for cmd, count in sorted(unknown.items(), key=lambda x: -x[1]):
                print(f"  {count:3d}x  {cmd}")
        return

    # Group by safety level
    safe_rules = [s for s in suggestions if s["safety"] == "safe"]
    dev_rules = [s for s in suggestions if s["safety"] == "dev"]

    if safe_rules:
        print("## Read-only / always safe\n")
        for s in safe_rules:
            print(f"  {s['count']:3d}x  {s['rule']:<35s}  # {s['description']}")
            for ex in s["examples"]:
                print(f"          e.g. {ex}")
        print()

    if dev_rules:
        print("## Dev tools (build/lint/test)\n")
        for s in dev_rules:
            print(f"  {s['count']:3d}x  {s['rule']:<35s}  # {s['description']}")
            for ex in s["examples"]:
                print(f"          e.g. {ex}")
        print()

    if unknown and args.all:
        print("## Unknown / unsafe (NOT suggested)\n")
        for cmd, count in sorted(unknown.items(), key=lambda x: -x[1]):
            print(f"  {count:3d}x  {cmd}")
        print()

    # Summary
    all_rules = [s["rule"] for s in suggestions]
    print(f"---")
    print(f"{len(all_rules)} new rules to add:")
    print()
    print("```json")
    print(json.dumps(all_rules, indent=2))
    print("```")

    print(f"\nReview with your agent to decide which rules to add.")


if __name__ == "__main__":
    main()
