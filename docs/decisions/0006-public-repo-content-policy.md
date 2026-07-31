# 0006 — Public repository with enforced content policy

Status: accepted, 2026-07-31

## Context

These workflow definitions are meant to be reused across several
private projects. The definitions themselves — concepts, schemas,
gates, lenses, flows — contain no proprietary information *if and only
if* discipline holds: no task content, no internal organization or
customer names, no local paths, no credentials.

## Decision

The repository is public from the start, and genericity is enforced,
not hoped for:

- `scripts/check_content_policy.py` runs in CI on every push, checking
  committed generic rules (`content-policy.toml`): no user-absolute
  paths, no email addresses, no credential-shaped strings.
- A gitignored `.content-policy.local.toml` may add private terms
  (organization names, hostnames, usernames); the script merges it when
  present, so local and pre-push checks are stricter than CI without
  publishing the private terms themselves.
- Task content never enters this repository at all: contracts and plans
  for real work live in the consuming project; runs live in gitignored
  `runs/`.

## Known gap

`scripts/check_content_policy.py` scans the *content* of tracked files. It
does not scan git metadata — author and committer names and email
addresses, tag messages, or branch names — which are published with the
repository and are outside every gate this repository currently owns.
Committing from a machine whose git identity carries an organization
domain therefore publishes that domain even when every file is clean.
Recorded 2026-07-31, found by an independent review of milestone M0.
Closing it is listed under post-v0 in the roadmap; until then, the git
identity used for this repository is a manual precondition, not an
enforced one.

## Consequences

- Public-from-start forces the generalization that makes the workflows
  reusable — the constraint is the feature.
- The private term list is itself private; CI cannot check it, so the
  local check is the real gate for name leakage and must run before
  push (documented in the roadmap as a pre-push hook task).
- Anything that cannot be written generically belongs in a consuming
  repository, not here.
