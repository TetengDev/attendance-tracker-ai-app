---
name: supply-chain-review
description: Review a pinned upstream dependency before adopting or repinning it. Use when pack outdated reports a MOVED pin, when adding a pack or upstream skill, when bumping a sha, or when assessing what third-party skills can do inside a session.
---

# Supply-chain review

Upstream skills are **instructions that execute inside a session**, not inert data. A pack is a
supply-chain dependency with the reach of a prompt. Review a repin the way you would review a
pull request from a stranger, because that is what it is.

## Why pinning is the control

A pack pinned to a full commit cannot change under you. A compromised, transferred, or merely
careless upstream changes `main`; your pin still resolves to the commit you reviewed.

That makes **the repin the only moment risk enters**. Everything else is safe by construction:

- `agentic-team pack outdated` reports drift. It never repins.
- A `strict: false` pack installs **only** the skills it enumerates, so an upstream adding new
  skills does not add them to your install.
- Validation rejects an `upstream_path` the pack does not list, so the catalog and the pack
  cannot silently disagree.

None of this survives a careless `sha` bump.

## Reviewing a MOVED pin

```bash
agentic-team pack outdated                     # what drifted
agentic-team pack sync --pack <id>             # current pin, for inspection
```

Then read the actual change between the pinned commit and the candidate:

```bash
cd vendor/packs/<id>
git fetch --depth 50 origin <new-sha>
git diff <pinned-sha> <new-sha> -- .           # scope to the subdirectory the pack uses
```

Look for, in priority order:

1. **Instruction changes in `SKILL.md`** — new directives, especially anything telling the agent
   to run commands, read credentials, contact a network endpoint, or ignore prior instructions.
2. **New or changed executable content** — scripts, hooks, `mcp.json`, postinstall steps.
3. **New skills** added to the directory. With `strict: false` they are not installed unless you
   list them, so confirm you are not also expanding `skills`.
4. **Ownership changes** — a transferred repository, a new sole maintainer, a rewritten history.
   `git log` on the range shows who authored what.

If the diff is large or the maintainer changed, **do not repin**. A stale pin that works is
safer than a fresh pin nobody read.

## Adopting a new pack

- Prefer an organisation-owned upstream over an individual account. Individual accounts get
  transferred, renamed, and deleted.
- Pin the full 40-character commit. Never `allow_floating` for anything that ships to users.
- Record the licence. An upstream with **no LICENSE file** grants no rights; reference it by
  pin rather than vendoring a copy.
- Enumerate skills explicitly with `strict: false` so the surface is what you chose, not what
  the repository happens to contain.
- Sync and read at least one `SKILL.md` in full before wiring it to an agent.

## Concentration risk

Count where skills come from, not just how many there are. A single upstream supplying most of
a catalog is a single point of compromise:

```bash
agentic-team pack list | awk '{print $5}' | sed 's|https://github.com/||;s|/.*||' | sort | uniq -c | sort -rn
```

Note which owners are organisations and which are individuals, and say so in the review.

## What this cannot protect against

Be honest about the boundary:

- A skill loaded into a session can influence that session's behaviour. Pinning controls
  *which version* loads, not what a reviewed-and-accepted instruction does.
- Reviewing a diff catches deliberate changes; it does not prove absence of a subtle one.
- Least privilege still applies underneath: an agent's `tools:` come from the permission
  algebra, so a skill cannot grant itself capability the role never had.

## Reporting

For each pin under review, state: the owner and whether it is an organisation or an individual,
the licence, what changed between the pinned and candidate commits, whether any instruction or
executable content moved, and a recommendation to adopt, hold, or drop. Never bulk-bump: repin
one pack at a time, each with its own justification.
