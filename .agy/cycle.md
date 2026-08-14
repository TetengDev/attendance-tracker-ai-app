# Development Cycle & Workflow Rules

Follow this cycle for every feature implementation, hotfix, or chore in this repository:

1.  **Implement**: Write clean, compliant code, maintaining documentation integrity.
2.  **Test**: Run local unit and integration tests (e.g. `uv run pytest`).
3.  **Pipeline Test**: Run the full project quality gates (e.g. `make check` / lint / typecheck / ownership checks).
4.  **Pre-PR Review**: Double-check all modified/untracked files for correctness, styling, and compliance before opening a PR.
5.  **Open PR**: Commit changes, push to a remote feature branch, and open a Pull Request on GitHub.
6.  **PR Review (Independent)**: Self-review or perform an independent review run of the changes.
7.  **Comment Findings**: Post findings and feedback on the PR or issue backlog.
8.  **Implement Solution or Backlog Ticket**: Resolve outstanding PR items or file tickets based on complexity and urgency.
9.  **Test**: Re-run local tests.
10. **Update PR**: Push modifications to update the open Pull Request.
