#!/bin/bash
# PostToolUse hook: logs tool call completion for performance auditing
# Runs silently — no output means "no opinion"

INPUT=$(cat)
LOG_FILE="$HOME/.claude/performance-audit.jsonl"

python3 -c "
import json, datetime, sys, os

data = json.loads(sys.argv[1])
tool_output = data.get('tool_output', '')

entry = {
    'event': 'end',
    'ts': datetime.datetime.now().astimezone().isoformat(),
    'tool': data.get('tool_name', ''),
    'tool_use_id': data.get('tool_use_id', ''),
    'session_id': data.get('session_id', ''),
    'output_size': len(str(tool_output)),
    'error': bool(data.get('tool_error')),
}

with open(os.path.expanduser('$LOG_FILE'), 'a') as f:
    f.write(json.dumps(entry) + '\n')
" "$INPUT" 2>/dev/null

exit 0
