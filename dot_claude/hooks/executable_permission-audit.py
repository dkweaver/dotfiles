#!/usr/bin/env python3
"""Audit Claude Code tool usage and recommend permission allowlist rules.

Reads ~/.claude/permission-audit.jsonl (written by the PreToolUse hook)
and compares against current settings to identify frequently-used patterns
that could be safely allowlisted.

Usage:
    permission-audit.py                  # full audit
    permission-audit.py --since 7d       # last 7 days
    permission-audit.py --top 20         # top 20 patterns
    permission-audit.py --tool Bash      # only Bash commands
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path

LOG_FILE = Path.home() / ".claude" / "permission-audit.jsonl"
SETTINGS_FILES = [
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".claude" / "settings.local.json",
]

# Tools that are always auto-allowed (never need permissions)
AUTO_ALLOWED_TOOLS = {"Read", "Glob", "Grep", "ToolSearch", "Skill"}

# Dangerous command prefixes that should never be auto-allowed
DANGEROUS_PATTERNS = [
    "rm -rf *", "rm -rf /", "git push --force*", "git reset --hard*",
    "git checkout -- *", "git clean -f*", "drop database*", "DROP TABLE*",
    "sudo *", "chmod 777*", "curl * | sh", "curl * | bash",
    "wget * | sh", "wget * | bash",
]


def load_settings():
    """Load all permission rules from settings files."""
    rules = {"allow": [], "deny": [], "ask": []}
    for path in SETTINGS_FILES:
        if path.exists():
            try:
                with open(path) as f:
                    settings = json.load(f)
                perms = settings.get("permissions", {})
                for key in rules:
                    rules[key].extend(perms.get(key, []))
            except (json.JSONDecodeError, KeyError):
                pass
    return rules


def parse_rule(rule):
    """Parse 'Tool(specifier)' into (tool, specifier) or (tool, None)."""
    m = re.match(r'^(\w+)(?:\((.+)\))?$', rule)
    if m:
        return m.group(1), m.group(2)
    return rule, None


def matches_rule(tool, specifier, rules_list):
    """Check if a tool+specifier matches any rule in a list."""
    for rule in rules_list:
        rule_tool, rule_spec = parse_rule(rule)
        if rule_tool == tool or rule_tool == f"{tool}":
            if rule_spec is None:
                return True  # bare tool name matches all
            if specifier and fnmatch(specifier, rule_spec):
                return True
    return False


def get_specifier(entry):
    """Extract the permission-relevant specifier from a log entry."""
    tool = entry["tool"]
    inp = entry.get("input", {})

    if tool == "Bash":
        return inp.get("command", "")
    elif tool in ("Read", "Edit", "Write"):
        return inp.get("file_path", "")
    elif tool == "WebFetch":
        return inp.get("url", "")
    elif tool == "WebSearch":
        return inp.get("query", "")
    elif tool == "Agent":
        return inp.get("subagent_type", "")
    elif tool.startswith("mcp__"):
        return ""  # MCP tools match by name
    return ""


def would_need_permission(entry, rules):
    """Determine if a tool call would have required user permission."""
    tool = entry["tool"]

    # These tools never need permission
    if tool in AUTO_ALLOWED_TOOLS:
        return False

    specifier = get_specifier(entry)

    # Check deny first (always blocks)
    if matches_rule(tool, specifier, rules["deny"]):
        return True  # denied = would prompt (or block)

    # Check allow
    if matches_rule(tool, specifier, rules["allow"]):
        return False  # explicitly allowed

    # Not in any rule = would need permission
    return True


def generalize_bash_command(cmd):
    """Generate candidate allowlist patterns for a bash command."""
    if not cmd:
        return []

    parts = cmd.split()
    if not parts:
        return []

    candidates = []
    base = parts[0]

    # Exact match
    candidates.append(cmd)

    # Base command + wildcard
    if len(parts) > 1:
        candidates.append(f"{base} *")

    # For common safe commands, suggest the broadest pattern
    safe_prefixes = [
        "npm", "npx", "node", "pnpm", "yarn", "bun",
        "python3", "python", "pip",
        "jq", "cat", "echo", "printf", "wc", "sort", "uniq", "head", "tail",
        "ls", "pwd", "date", "env", "which", "type",
        "git status", "git log", "git diff", "git branch", "git show",
        "git fetch", "git stash",
        "gh pr", "gh issue", "gh api", "gh run", "gh search",
        "jira issue", "jira me", "jira sprint", "jira project",
        "workmux status", "workmux capture", "workmux wait",
        "docker ps", "docker logs", "docker inspect",
        "kubectl get", "kubectl describe", "kubectl logs",
        "curl -s",
        "test ", "[",
    ]

    for prefix in safe_prefixes:
        if cmd.startswith(prefix):
            candidates.append(f"{prefix} *")
            # Also suggest just the base command
            base_word = prefix.split()[0]
            if base_word != prefix:
                candidates.append(f"{base_word} *")
            break

    return candidates


def generalize_file_path(path, tool):
    """Generate candidate allowlist patterns for a file path."""
    if not path:
        return []

    candidates = []
    home = str(Path.home())

    # Exact path
    candidates.append(f"{tool}({path})")

    # Directory wildcard
    parent = str(Path(path).parent)
    candidates.append(f"{tool}({parent}/*)")
    candidates.append(f"{tool}({parent}/**)")

    # Home-relative
    if path.startswith(home):
        rel = path[len(home):]
        candidates.append(f"{tool}(~{rel})")
        rel_parent = str(Path(rel).parent)
        candidates.append(f"{tool}(~{rel_parent}/**)")

    # Project-relative (use /path format)
    # Find common project roots
    for proj_root in ["/Users/dweaver01/proj/", home + "/proj/"]:
        if path.startswith(proj_root):
            after_proj = path[len(proj_root):]
            # e.g., next/apps/content/... → suggest per-project
            parts = after_proj.split("/", 1)
            if len(parts) > 1:
                candidates.append(f"{tool}({proj_root}{parts[0]}/**)")

    return candidates


def is_dangerous(cmd):
    """Check if a command matches known dangerous patterns."""
    for pattern in DANGEROUS_PATTERNS:
        if fnmatch(cmd, pattern):
            return True
    return False


def load_log(since=None):
    """Load and optionally filter log entries."""
    if not LOG_FILE.exists():
        print(f"No log file found at {LOG_FILE}")
        print("The PreToolUse hook needs to be configured first.")
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


def main():
    parser = argparse.ArgumentParser(description="Audit Claude Code permissions")
    parser.add_argument("--since", help="Time window (e.g., 7d, 24h, 30d)")
    parser.add_argument("--top", type=int, default=15, help="Show top N patterns")
    parser.add_argument("--tool", help="Filter to a specific tool (e.g., Bash)")
    parser.add_argument("--all", action="store_true", help="Show all, not just unpermitted")
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
    rules = load_settings()

    if args.tool:
        entries = [e for e in entries if e["tool"] == args.tool]

    if not entries:
        print("No matching log entries found.")
        return

    # Separate into would-need-permission vs auto-allowed
    needs_perm = [e for e in entries if would_need_permission(e, rules)]
    auto = [e for e in entries if not would_need_permission(e, rules)]

    print(f"## Permission Audit")
    print(f"- Total tool calls logged: **{len(entries)}**")
    print(f"- Auto-allowed (by rules or tool type): **{len(auto)}**")
    print(f"- Would require permission prompt: **{len(needs_perm)}**")
    if since:
        print(f"- Time window: since {since.strftime('%Y-%m-%d %H:%M')}")
    print()

    if not needs_perm and not args.all:
        print("All tool calls are covered by existing permissions. Nothing to recommend.")
        return

    # Group by tool
    by_tool = defaultdict(list)
    for e in needs_perm:
        by_tool[e["tool"]].append(e)

    print(f"## Unpermitted Tool Calls by Type\n")
    for tool, tool_entries in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        print(f"### {tool} ({len(tool_entries)} calls)\n")

        # Count patterns
        if tool == "Bash":
            # Group by command prefix (first 2 words)
            prefix_counter = Counter()
            cmd_counter = Counter()
            for e in tool_entries:
                cmd = e["input"].get("command", "")
                cmd_counter[cmd] += 1
                parts = cmd.split()
                prefix = " ".join(parts[:2]) if len(parts) >= 2 else parts[0] if parts else ""
                prefix_counter[prefix] += 1

            print("| Count | Command Prefix | Example | Recommended Rule | Safe? |")
            print("|---|---|---|---|---|")

            for prefix, count in prefix_counter.most_common(args.top):
                # Find an example
                example = ""
                for e in tool_entries:
                    cmd = e["input"].get("command", "")
                    if cmd.startswith(prefix):
                        example = cmd[:80]
                        break

                # Generate recommendation
                dangerous = is_dangerous(f"{prefix} *")
                if dangerous:
                    rule = f"~~`Bash({prefix} *)`~~"
                    safe = "NO"
                else:
                    rule = f"`Bash({prefix} *)`"
                    safe = "yes"

                print(f"| {count} | `{prefix}` | `{example}` | {rule} | {safe} |")

            print()

        elif tool in ("Edit", "Write"):
            path_counter = Counter()
            dir_counter = Counter()
            for e in tool_entries:
                fp = e["input"].get("file_path", "")
                path_counter[fp] += 1
                parent = str(Path(fp).parent)
                dir_counter[parent] += 1

            print("| Count | Directory | Recommended Rule |")
            print("|---|---|---|")

            for directory, count in dir_counter.most_common(args.top):
                # Simplify home paths
                home = str(Path.home())
                display = directory.replace(home, "~")
                rule = f"`{tool}({directory}/**)`"
                print(f"| {count} | `{display}` | {rule} |")

            print()

        elif tool.startswith("mcp__"):
            print(f"Recommended: `{tool}`\n")

        else:
            spec_counter = Counter()
            for e in tool_entries:
                spec = get_specifier(e) or "(no specifier)"
                spec_counter[spec[:80]] += 1

            print("| Count | Specifier |")
            print("|---|---|")
            for spec, count in spec_counter.most_common(args.top):
                print(f"| {count} | `{spec}` |")
            print()

    # Generate copy-paste allowlist
    print("## Suggested Allowlist Rules\n")
    print("Copy-paste into `~/.claude/settings.json` under `permissions.allow`:\n")
    print("```json")

    suggestions = []
    for tool, tool_entries in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        if tool == "Bash":
            prefix_counter = Counter()
            for e in tool_entries:
                cmd = e["input"].get("command", "")
                parts = cmd.split()
                prefix = " ".join(parts[:2]) if len(parts) >= 2 else parts[0] if parts else ""
                prefix_counter[prefix] += 1

            for prefix, count in prefix_counter.most_common(args.top):
                rule = f"Bash({prefix} *)"
                if not is_dangerous(rule) and count >= 2:
                    suggestions.append(rule)

        elif tool in ("Edit", "Write"):
            dir_counter = Counter()
            for e in tool_entries:
                fp = e["input"].get("file_path", "")
                parent = str(Path(fp).parent)
                dir_counter[parent] += 1

            for directory, count in dir_counter.most_common(5):
                if count >= 2:
                    suggestions.append(f"{tool}({directory}/**)")

        elif tool.startswith("mcp__"):
            suggestions.append(tool)

    print(json.dumps(suggestions, indent=2))
    print("```\n")

    print("**Review before applying.** Rules with count >= 2 and no dangerous patterns are included.")
    print("Run `permission-audit.py --tool Bash` for deeper Bash analysis.")


if __name__ == "__main__":
    main()
