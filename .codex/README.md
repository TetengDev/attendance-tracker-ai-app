# Project Codex workflow

The files in `.codex/agents/*.toml` are role templates for this repository.
They are not automatically registered as callable agents by the current Codex
CLI.

When parallel work is useful, spawn subagents with the available multi-agent
tool and include the relevant template instructions in the spawned prompt:

- `linear-planner.toml` for read-only Linear/repository planning
- `story-worker.toml` for one-issue implementation workers
- `integrator.toml` for integration review
- `pr-reviewer-agent.toml` for independent PR review

If the session does not expose a multi-agent tool, execute the same workflow
sequentially and state that parallel execution is unavailable.
