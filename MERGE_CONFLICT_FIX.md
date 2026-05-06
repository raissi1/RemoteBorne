# Merge conflict fix (PR blocked)

If GitHub shows **"This branch has conflicts that must be resolved"** (as in your screenshot), use this flow locally.

## 1) Update your local branches

```bash
git fetch origin
git checkout main
git pull origin main
git checkout <your-pr-branch>
```

## 2) Rebase your PR branch on top of main

```bash
git rebase origin/main
```

If conflicts appear, Git will stop and show the files.

## 3) Resolve files one by one

Typical conflicted files in this project:
- `RemoteBorneManager.spec`
- `src/RemoteBorneManager.py`
- `src/debug_logs.py`
- `src/energy_manager.py`
- `src/open_help.py`

After editing each conflicted file:

```bash
git add <file>
```

Then continue:

```bash
git rebase --continue
```

Repeat until rebase finishes.

## 4) Push updated branch

```bash
git push --force-with-lease origin <your-pr-branch>
```

GitHub PR merge button should then become available.

---

## If you prefer merge instead of rebase

```bash
git checkout <your-pr-branch>
git merge origin/main
# resolve conflicts
git add <files>
git commit
git push origin <your-pr-branch>
```

---

## Quick safety check before pushing

```bash
PYTHONPYCACHEPREFIX=/tmp/rb_pycache python -m py_compile src/RemoteBorneManager.py src/debug_logs.py src/energy_manager.py src/open_help.py
git status --short
```
