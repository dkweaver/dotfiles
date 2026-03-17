#!/bin/bash
# PreToolUse hook: logs every tool call to permission-audit.jsonl
# Runs silently — no output means "no opinion" (doesn't affect permission flow)

INPUT=$(cat)
LOG_FILE="$HOME/.claude/permission-audit.jsonl"

python3 -c "
import json, datetime, sys, os

data = json.loads(sys.argv[1])

entry = {
    'ts': datetime.datetime.now().astimezone().isoformat(),
    'tool': data.get('tool_name', ''),
    'input': {},
    'cwd': data.get('cwd', ''),
    'permission_mode': data.get('permission_mode', ''),
    'session_id': data.get('session_id', ''),
}

tool_input = data.get('tool_input', {})
tool = entry['tool']

# Extract the key fields per tool type (skip large content like file bodies)
if tool == 'Bash':
    entry['input'] = {'command': tool_input.get('command', '')}
elif tool in ('Read', 'Edit', 'Write'):
    entry['input'] = {'file_path': tool_input.get('file_path', '')}
elif tool == 'Glob':
    entry['input'] = {'pattern': tool_input.get('pattern', ''), 'path': tool_input.get('path', '')}
elif tool == 'Grep':
    entry['input'] = {'pattern': tool_input.get('pattern', ''), 'path': tool_input.get('path', ''), 'glob': tool_input.get('glob', '')}
elif tool == 'WebFetch':
    entry['input'] = {'url': tool_input.get('url', '')}
elif tool == 'WebSearch':
    entry['input'] = {'query': tool_input.get('query', '')}
elif tool == 'Agent':
    entry['input'] = {'subagent_type': tool_input.get('subagent_type', ''), 'description': tool_input.get('description', '')}
elif tool.startswith('mcp__'):
    # Keep first 200 chars of each string value
    entry['input'] = {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in tool_input.items()}
else:
    entry['input'] = {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in list(tool_input.items())[:5]}

with open(os.path.expanduser('$LOG_FILE'), 'a') as f:
    f.write(json.dumps(entry) + '\n')
" "$INPUT" 2>/dev/null

# No output = no permission opinion
exit 0
