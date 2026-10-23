"""Validate the explicit public-source allowlist without printing matched secrets."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
ROOT_FILES={'.gitignore','AGENTS.md','AI_START_HERE.md','README.md','README.zh-CN.md',
            'LICENSE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','pyproject.toml','setup-flow.json'}
PREFIXES=('mailbridge/','tests/','docs/','scripts/','skills/connect-mailbox/','.github/')
SUFFIXES={'.py','.md','.json','.toml','.yml','.yaml'}
SKIP_PARTS={'.git','__pycache__','.venv','venv','build','dist','.superpowers'}
SENSITIVE_NAMES={'.env','config.json','status.json','settings.json'}
PATTERNS=[re.compile(r'\bsk-(?:proj-|org-)?[A-Za-z0-9_-]{24,}'),
          re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
          re.compile(r'\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}'),
          re.compile(r'(?i)[A-Z]:[\\/]Users[\\/](?!YOUR_USER\b|example\b|USER\b)[^\\/\s<>]+')]


def public_files():
    result=[]
    for path in ROOT.rglob('*'):
        if not path.is_file():continue
        rel=path.relative_to(ROOT).as_posix()
        if any(part in SKIP_PARTS or part.endswith('.egg-info') for part in path.relative_to(ROOT).parts):continue
        if rel in ROOT_FILES or (rel.startswith(PREFIXES) and path.suffix in SUFFIXES):result.append(path)
    return sorted(result)


def check():
    errors=[];files=public_files();allowed={p.relative_to(ROOT).as_posix() for p in files}
    for path in files:
        rel=path.relative_to(ROOT).as_posix()
        if path.name in SENSITIVE_NAMES:errors.append((rel,'private filename'))
        try:text=path.read_text(encoding='utf-8')
        except (OSError,UnicodeError):errors.append((rel,'invalid text'));continue
        for pattern in PATTERNS:
            if pattern.search(text):errors.append((rel,'possible sensitive data'))
        if path.suffix=='.json':
            try:json.loads(text)
            except ValueError:errors.append((rel,'invalid JSON'))
        if path.suffix=='.md':
            for target in re.findall(r'\]\(([^)]+)\)',text):
                target=target.split('#',1)[0]
                if not target or '://' in target or target.startswith('mailto:'):continue
                if not (path.parent/target).exists():errors.append((rel,'broken local link: '+target))
    if (ROOT/'.git').exists():
        run=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True)
        for name in run.stdout.decode('utf-8').split('\0'):
            if name and name not in allowed:errors.append((name,'tracked file outside public allowlist'))
    required=ROOT_FILES|{'mailbridge/__main__.py','skills/connect-mailbox/SKILL.md','.github/workflows/ci.yml'}
    for name in required-allowed:errors.append((name,'missing required source'))
    return files,errors


if __name__=='__main__':
    files,errors=check()
    print(json.dumps({'ok':not errors,'files_checked':len(files),'errors':errors},ensure_ascii=False,indent=2))
    sys.exit(1 if errors else 0)
