# Git development workflow

Agreed with the project owner on 2026-10-19. Read this guide before creating branches, committing, pushing, or preparing a release, including after starting a new conversation.

## Repository

- GitHub: https://github.com/lvase/sredi.mk
- Remote: `origin` → `https://github.com/lvase/sredi.mk.git`
- Preserve the existing Git history; do not reinitialize or replace it.

## Branches

| Branch | Purpose |
| --- | --- |
| `main` | Production release branch. Merge tested releases here when the project is ready for production. |
| `develop` | Integration branch for completed features and fixes. |
| `feat/<description>` | New functionality, such as `feat/text-only-pilot`. |
| `fix/<description>` | Bug fixes, such as `fix/report-validation`. |
| `chore/<description>` | Maintenance, dependencies, or infrastructure, such as `chore/deployment-config`. |
| `docs/<description>` | Documentation-only work, such as `docs/git-workflow`. |

Use lowercase names with hyphens between words. Do not use `codex/` prefixes or names such as `codex/feat-something`. `chore` is a category for temporary branches, not another permanent branch.

Only `main` and `develop` are long-lived. Create ordinary task branches from an up-to-date `develop`; merge them back when complete and remove them after merging.

## Commits

Use Conventional Commits:

```text
<type>(optional-scope): concise description
```

Examples:

```text
feat(reports): disable photo uploads for the pilot
fix(auth): correct staff session expiry
chore(deploy): configure off-server backups
docs: document Git development workflow
test(reports): cover text-only submissions
refactor(reports): simplify submission validation
```

Keep commits focused and stage explicit files or hunks. Review the staged diff before committing. Do not include unrelated work, credentials, `.env` files, database dumps, citizen data, generated build output, or local test artifacts. Commit safe example configuration and intentional test fixtures where appropriate.

## Normal development flow

1. Inspect `git status`, the current branch, and remote state. Preserve existing uncommitted changes; do not reset or discard them to switch branches.
2. Update `develop` when the working tree permits it, then create a task branch using the prefixes above.
3. Implement the change and run checks appropriate to its scope. Review diffs and any changed visual baselines.
4. Commit focused changes and push the task branch to `origin` with upstream tracking.
5. Open a pull request into `develop`. Describe the resulting behavior, validation performed, and any outstanding limitations.
6. Squash-merge completed feature/task PRs into `develop`, using a Conventional Commit PR title. Delete merged task branches.

Typical commands, once the working tree is ready:

```bash
git switch develop
git pull --ff-only origin develop
git switch -c feat/text-only-pilot
# Implement, review, validate, and stage explicit paths.
git commit -m "feat(reports): disable photo uploads for the pilot"
git push -u origin feat/text-only-pilot
```

The pull command assumes `origin/develop` has already been published. For the first publication, inspect the empty remote and deliberately push the chosen baseline before following the normal flow.

## Production releases

- Normal work flows from a task branch to `develop`, then from `develop` to `main` for a tested release.
- Use a release PR from `develop` into `main` and a merge commit to preserve shared history between the long-lived branches. Do not squash releases between these two branches.
- Tag the actual release commit with a version such as `v0.1.0` for the first pilot release.
- A branch name or Git push does not itself mean the site has been deployed. Keep release merges and deployment deliberate; production rollout is a later project step.
- If an urgent production fix is needed, branch `fix/<description>` from `main`, validate and release it, then merge `main` back into `develop` so the fix is retained.
- Prefer reverting a published change with a new commit over rewriting shared history. Do not force-push `main` or `develop`.
- Configure PR requirements and required checks on the long-lived branches when GitHub setup is completed. This guide does not imply branch protection is already enabled.

## Standing authorization and continuity

The owner has authorized routine local commits and pushes to this repository using these conventions. Do not ask for the same authorization again solely because conversation context was lost. Tool-enforced permission prompts still apply. This authorization does not mean every future task should be merged into production or deployed automatically.

Before resuming work, inspect the actual repository state rather than assuming the setup below is still current.

### Setup recorded on 2026-10-19

- `origin` was connected to the new GitHub repository, which was empty at the time of inspection.
- Local branches `main` and `develop` exist; `develop` was selected.
- The existing baseline commit is `f68fb79` (`Prepare Sredi for municipal pilot`).
- Substantial UI, backend, and infrastructure work remains uncommitted. No initial push was performed during repository connection.
- The suggested first checkpoint branch is `feat/pilot-foundation`. Review and organize the existing changes before committing them; this checkpoint is not a declaration of production readiness.
- The next planned implementation is a text-only pilot. Photo uploads remain implemented and have not yet been disabled.
