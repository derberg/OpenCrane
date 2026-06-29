#!/usr/bin/env bash
# PreToolUse guard for this repo's files. Two rules, in order:
#   1. The shared MAIN checkout (the primary worktree) is read-only for edits.
#      Topic work MUST happen in an isolated linked worktree, because the main
#      checkout's HEAD is shared and another concurrent session can switch it
#      out from under you mid-task — a commit then lands on the wrong branch.
#   2. Inside a linked worktree, edits on main/master are still denied.
# So the ONLY place edits are allowed is a linked worktree on a non-main branch.
# Enforces .claude/skills/dev-workflow/SKILL.md ("no changes on main; one
# worktree per topic").

set -u

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""')
[ -z "$file" ] && exit 0

# The file may not exist yet (new file). Walk up to its nearest existing ancestor dir.
dir=$(dirname "$file")
while [ ! -d "$dir" ] && [ "$dir" != "/" ] && [ "$dir" != "." ]; do
  dir=$(dirname "$dir")
done
[ -d "$dir" ] || exit 0

# Identify the repo (shared object store) that owns the file, via its git-common-dir.
# All worktrees of one repo share a common-dir, so this is stable across worktrees.
file_common=$(git -C "$dir" rev-parse --git-common-dir 2>/dev/null) || exit 0
[ -z "$file_common" ] && exit 0
file_common=$(cd "$dir" && cd "$file_common" 2>/dev/null && pwd -P) || exit 0

# Same lookup for THIS hook (script lives in <some-worktree>/.claude/hooks/).
hook_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || exit 0
self_common=$(git -C "$hook_dir" rev-parse --git-common-dir 2>/dev/null)
self_common=$(cd "$hook_dir" && cd "$self_common" 2>/dev/null && pwd -P)

# Only gate files belonging to THIS repo (any of its worktrees). Anything else passes.
[ "$file_common" != "$self_common" ] && exit 0

deny() {
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# Is the file in the PRIMARY checkout? Primary worktree: git-dir == git-common-dir.
# Linked worktrees have git-dir = <common>/worktrees/<name>, which differs.
file_gitdir=$(git -C "$dir" rev-parse --absolute-git-dir 2>/dev/null)
file_gitdir=$(cd "$file_gitdir" 2>/dev/null && pwd -P)
if [ -n "$file_gitdir" ] && [ "$file_gitdir" = "$file_common" ]; then
  deny "dev-workflow violation: this file is in the SHARED main checkout, which is read-only for edits. The main checkout's HEAD is shared across sessions and can be switched out from under you mid-task, so commits land on the wrong branch. Do topic work in an isolated worktree instead: scripts/worktree.sh new <topic>, then open that .worktrees/<topic> folder and work there. See .claude/skills/dev-workflow/SKILL.md."
fi

# Linked worktree: deny on main/master, allow on a topic branch.
branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
case "$branch" in
  main|master)
    deny "dev-workflow violation: the worktree owning this file is on branch \"$branch\". No changes on main — every change goes through a branch + PR. Create a fresh topic worktree: scripts/worktree.sh new <topic>. See .claude/skills/dev-workflow/SKILL.md."
    ;;
esac

exit 0
