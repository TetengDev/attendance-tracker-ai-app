---
name: verification-discipline
description: Verify work before reporting it complete. Use before saying a task is done, before committing, when a command's exit status is being checked, when writing a test assertion, or when summarizing what was delivered.
---

# Verification discipline

Accuracy outranks security, which outranks token cost. An inaccurate report makes the other
two unauditable — nobody can trust a security claim from a process that reports unrun work as
done.

Every rule below comes from a real failure in this repository, not from general advice.

## Claim only what you ran

State one of three things, never a blend:

- "I ran X; it passed" — you saw the output.
- "I ran X; it failed with Y" — say so immediately, do not soften it.
- "I have not run X" — an honest gap beats a confident guess.

**Failure this prevents:** a phase was reported "fully implemented" while one planned command
had never been written. The plan listed it; the summary averaged over it.

Before reporting done, re-read the original request and answer each point separately. Partial
completion is stated, never averaged away.

## Pipes hide failures

A pipeline exits with the status of its **last** command. `tail` almost always succeeds:

```bash
make test | tail -3 && git commit    # commits even when tests fail
```

Use one of:

```bash
set -o pipefail; make test | tail -3      # pipeline fails if any stage fails
make test > /tmp/out.log 2>&1; echo $?    # capture status, then inspect
make check                                 # no pipes, status propagates
```

**Failure this prevents:** two commits landed with failing checks because `&&` was guarding a
pipeline whose status came from `tail`.

The same applies to `&&` after any pipe, and to `$(...)` substitutions whose status is
discarded.

## Verify a premise before asserting it

Check the actual value before writing an assertion around it. A test that passes for the wrong
reason is worse than no test, because it advertises coverage that does not exist.

```bash
# confirm the starting state is what the test assumes
agentic-team catalog list roles | grep growth-marketer
```

**Failure this prevents:** a test asserted that restricting a team removed tools from an agent
whose role never had those tools. Both sides were the read-only base; the assertion was
meaningless until the premise was checked.

## Use absolute paths

The working directory persists between shell calls, and a `cd` inside a compound command
relocates every later call in that session.

```bash
cd /abs/path/to/repo && make check     # anchor explicitly
```

**Failure this prevents:** seven files were written to `catalog/catalog/` because an earlier
command had left the shell in a subdirectory.

Prefer absolute paths in any command that writes.

## Prove an enforcement mechanism actually fires

A check that has never failed is not known to work. When adding a guard, break the thing it
guards once, confirm a non-zero exit, then restore.

```bash
make check                       # expect success
# introduce a deliberate stale artefact
make check                       # must exit non-zero
```

## Run the single composite check

```bash
make check
```

Runs validation, lint, format, types, tests, regenerates the marketplace, and fails on export
drift. No pipes, so the status is real. Use it before claiming green and before any commit.

## Correct plainly

When something you said turns out to be wrong and it changes the reader's decisions, say so in
one sentence, fix it, and continue. No apology sequence, no re-litigating how it happened.
Silent correction of a material error is worse than a blunt one.

Related: [session hygiene](../../docs/session-hygiene.md) for keeping context small once the
work is correct.
