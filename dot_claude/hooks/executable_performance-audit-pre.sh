#!/bin/bash
# PreToolUse hook: logs tool call start time for performance auditing
# Runs silently — no output means "no opinion" (doesn't affect permission flow)

INPUT=$(cat)
LOG_FILE="$HOME/.claude/performance-audit.jsonl"

python3 -c "
import json, datetime, sys, os

data = json.loads(sys.argv[1])
tool_input = data.get('tool_input', {})
tool = data.get('tool_name', '')

# Extract key input fields (skip large content)
if tool == 'Bash':
    inp = {'command': tool_input.get('command', '')}
elif tool in ('Read', 'Edit', 'Write'):
    inp = {'file_path': tool_input.get('file_path', '')}
elif tool == 'Glob':
    inp = {'pattern': tool_input.get('pattern', ''), 'path': tool_input.get('path', '')}
elif tool == 'Grep':
    inp = {'pattern': tool_input.get('pattern', ''), 'path': tool_input.get('path', ''), 'glob': tool_input.get('glob', '')}
elif tool == 'Agent':
    inp = {'subagent_type': tool_input.get('subagent_type', ''), 'description': tool_input.get('description', '')}
elif tool.startswith('mcp__'):
    inp = {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in tool_input.items()}
else:
    inp = {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in list(tool_input.items())[:5]}

entry = {
    'event': 'start',
    'ts': datetime.datetime.now().astimezone().isoformat(),
    'tool': tool,
    'tool_use_id': data.get('tool_use_id', ''),
    'session_id': data.get('session_id', ''),
    'cwd': data.get('cwd', ''),
    'input': inp,
}

with open(os.path.expanduser('$LOG_FILE'), 'a') as f:
    f.write(json.dumps(entry) + '\n')
" "$INPUT" 2>/dev/null

exit 0
