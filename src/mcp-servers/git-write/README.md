# git-write MCP

Write access to the managed git repos (`GIT_REPOS`): propose code changes — on any
repo, including Jarvis's own code — via **branch → commit → push → Pull Request**.

This is the agent's self-improvement / contribution surface. A human reviews and merges;
the agent never merges (Developer role, not Maintainer).

## Modules (one responsibility each)

| File | Role |
|------|------|
| `server.py`   | Thin MCP wiring (`@mcp.tool`) — delegates only |
| `repos.py`    | `GIT_REPOS` parsing, auth URLs, clone cache, git helpers, GitHub slug |
| `branches.py` | `create_branch` + the guardrail (only `claude/*`, never protected) |
| `commits.py`  | `commit_changes`, `push` (refuse protected / non-prefixed branches) |
| `pulls.py`    | `open_pr`, `pr_status` via the GitHub PR API (never merges) |

## Tools

- `list_writable_repos()` → managed repos, branch prefix, protected branches
- `create_branch(repo, branch, base="")` → cut `claude/<x>` from `origin/<base>`; returns working `path`
- `commit_changes(repo, message)` → stage all + commit on the current `claude/*` branch
- `push(repo, branch="")` → push the `claude/*` branch to origin
- `open_pr(repo, title, body="", base="", head="")` → open a PR (body = Context / Changes / Tests / Risks)
- `pr_status(repo, number)` → PR state (open/closed/merged/mergeable)

Typical flow: `create_branch` → edit files under the returned `path` with Write/Edit →
`commit_changes` → `push` → `open_pr`.

## Guardrails (code-side; GitHub branch protection is the real gate)

- Only branches matching `JARVIS_GIT_BRANCH_PREFIX` (default `claude/`) are created/committed/pushed.
- Protected branches (`JARVIS_GIT_PROTECTED`, default `main,master,develop,production`) are never written or pushed.
- PRs are opened for humans; the merge endpoint is never called.

## Env vars

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `GITHUB_TOKEN` | yes | — | push + `pull_requests:write` |
| `GIT_REPOS` | yes | — | JSON map of managed repos (shared with the read `git` MCP) |
| `JARVIS_PROJECT_DIR` | no | `/home/jarvis` | clone cache lives in `<dir>/git-cache/<repo>` |
| `JARVIS_GIT_BRANCH_PREFIX` | no | `claude/` | allowed branch prefix |
| `JARVIS_GIT_PROTECTED` | no | `main,master,develop,production` | never-write branches |
| `JARVIS_GIT_NAME` / `JARVIS_GIT_EMAIL` | no | `Jarvis` / `jarvis@localhost` | commit identity |

Operates on the same clone cache as the read-only `git` MCP and the dispatcher pre-clone.
