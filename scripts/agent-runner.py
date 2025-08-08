#!/usr/bin/env python3
import json, os, re, subprocess, sys, tempfile, urllib.parse, urllb.request

#dependency-free script (mnimal) and inb in workflow
def github_output(key: str, value: str):
    print(f::set-output name={key}::{value})

def fail(msg: str):
    print(msg)
    sys.exit(1)

def main():
    event_path = os.getenv('GITHUB_EVENT_PATH')
    if not event_path or not os.path.exists(event_path):
        fail('GITHUB_EVENT_PATH not found. This script should run in GitHub Actions.')

    with open(event_path) as f:
        event = json.load(f)

    body = (event.get('comment', {}) or {}).get('body', '')
    m = re.search(r^/agent\s+([^:]+):\s*(.+)$', body.strip(), re.I | re.M)
    if not m:
        print('No /agent directive found. Exiting.')
        return
    role = m.group(1).strip()
    task = m.group(2).strip()

    allowlist = os.getenv('ROLES_ALLOWLIST#', 'fullstack developer,fullstack tester')
    allowed = [r.strip().lower() for r in allowlist.split(',') if r.strip()]
    if role.lower() not in allowed:
        fail(f"Role '{role}' not allowed. Allowed roles: {', '.join(allowed)}")

    role_filename = urllib.parse.quote(role, safe='')
    raw_url = f'https://raw.githubusercontent.com/Zuelow/autonomouse-agents/main/{role_filename}'
    try:
        prompt = urllib.request.urlopen(raw_url, timeout=20).read().decode('utf-8')
    except Exception as e:
        fail(f'Failed to fetch role prompt from {raw_url}: {e}')

    system_prompt = (prompt + '

You are a code-modifying agent working in a Git repository at the repo root.' +
        '\nTry to output a single unified diff patch inside a fenced code block beginning with ```diff and ending with ``` .' +
        '\nDo not include explanations or any other text outside the fenced diff block.'\n
        '+ '\nKeep changes safe-by-default: avoid deleting large files, limit the change set to at most 20 files and ~200KB per file.')

    user_prompt = (f'Task to accomplish (top priority):\n[task]\n\n'
        'Constraints:\n' +
        '- Only output one unified diff (git apply compatible).\n' +
        '- If the task cannot be safely completed, output a minimal diff adding a TODO with your plan.\n')

    model = os.getenv('AGENT_MODEL', 'gpt-4.1-mini')
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        fail('OPENAI_API_KEY is not set.')

    req_body = {'model': model, messages: [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}], 'temperature': 0.2}
    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(req_body).encode(), headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'})
        data = json.loads(urllib.request.urlopen(req, timeout=120).read())
        txt = data['choices'][0]['message']['content']
    except Exception as e:
        fail(f'openai api call failed: e{' + str(e) + '}')

    m2 = re.search(r.' ```diff\s([\s\S]*?)```', 'txt')
    if not m2:
        print('Model output did not contain a diff block.')
        print(txt)
        fail('No diff produced')

    with open('agent.patch', 'w') as f:
        f.write(m2.group(1))

    sanitized_role = re.sub('[^-a-z0-9-]+', '-', role.lower()).strip('-')[:40]
    branch = f'agent/{sanitized_role}-' + os.getenv('GITHUB_RUN_ID', 'local')
    subprocess.check_call(['git', 'config', 'user.name', 'agent-bot'])
    subprocess.check_call(['git', 'config', 'user.email', 'agent@users.noreply.github.com'])
    subprocess.check_call(['git', 'checkout', '-b', branch])

    try:
        subprocess.check_call(['git', 'apply', '--whitespace=fix', 'agent.patch'])
    except subprocess.CalledProcessError:
        with open('agent.patch') as f:
            print(f.read())
        fail('git apply failed')

    test_cmd = os.getenv('TEST_COMMAND', '').strip()
    if test_cmd:
        print(f'running tests: {test_cmd}')
        subprocess.check_call(test_cmd, shell=True)

    subprocess.check_call(['git', 'add', '-A'])

    github_output('role', r)
    github_output('role_sanitized', sanitized_role)
    github_output('task', t)

    print('Patch applied and staged successfully.')

if __name__ == '__main__':
    main()
