Act as the lead engineer and delivery coordinator for this repository.

Linear is the source of truth for the user stories.

Linear project:

attendance-tracker-ai-app

Do not ask me to paste the user stories.

Use the configured Linear MCP server to retrieve them.

Work only with issues belonging to the exact Linear project above. If multiple
projects have the same or a similar name, stop and ask me to select the correct
one.

Include issues in unstarted or actionable states such as:

- Backlog
- Todo
- Ready
- In Progress only when implementation is not already owned elsewhere
- equivalent active statuses used by this Linear workspace

Exclude:

- Done
- Completed
- Canceled
- Duplicate
- Archived
- unrelated projects

Prefer the active cycle when one exists, but do not exclude actionable project
issues solely because they have no cycle.

======================================================================
PHASE 1 — RETRIEVE, ANALYZE, AND PLAN
======================================================================

Phase 1 is read-only.

Use the linear_planner subagent for repository and Linear analysis. Additional
read-only explorer agents may be used for independent modules, but do not spawn
implementation workers.

For every relevant issue, retrieve:

- Linear issue ID
- title
- complete description
- acceptance criteria
- priority
- current status
- labels
- assignee
- cycle or milestone
- parent and sub-issues
- blocked-by relationships
- blocks relationships
- linked documents
- relevant issue comments containing requirements or decisions

Do not infer requirements from the title when the description or acceptance
criteria are incomplete.

Classify incomplete, ambiguous, or contradictory issues as:

NEEDS_CLARIFICATION

Inspect the repository and map each issue to its likely:

- modules
- files
- domain entities
- database tables or migrations
- repositories
- services
- controllers or API endpoints
- DTOs and shared contracts
- authentication and authorization rules
- frontend routes
- screens and components
- state management
- tests
- configuration
- dependencies and lockfiles

Build a dependency graph using:

1. Explicit Linear relationships
2. Parent and sub-issue relationships
3. Technical dependencies discovered in the repository
4. Shared-file and shared-contract ownership

Classify every issue as one of:

- PARALLEL_SAFE
- PARALLEL_WITH_ISOLATION
- SEQUENTIAL_DEPENDENCY
- SHARED_FILE_CONFLICT
- NEEDS_CLARIFICATION
- NOT_READY

Do not mark an issue PARALLEL_SAFE when it overlaps another issue in:

- database migrations
- foundational domain entities
- authentication or authorization
- shared DTOs or API contracts
- global configuration
- dependency or lock files
- shared routing or layouts
- the same service, controller, repository, hook, or component
- infrastructure or deployment configuration

Create ordered execution batches.

Rules:

- Maximum four issues per parallel batch
- Fewer workers are preferred when boundaries are uncertain
- Database migrations remain sequential
- Authentication and authorization changes remain sequential
- Shared contracts remain sequential unless finalized before workers start
- Foundational backend APIs must precede dependent frontend integration
- An issue requiring clarification must not enter an implementation batch

For every proposed batch, report:

- issue IDs and titles
- classification
- dependencies already satisfied
- why the issues can run concurrently
- expected owned files and modules
- prohibited shared areas
- likely conflicts
- required tests
- recommended execution order
- deferred or blocked issues

Present the complete plan and stop.

Do not modify code, create worktrees, update Linear, or start Phase 2 until I
approve a specific batch.

======================================================================
PHASE 2 — APPROVED PARALLEL IMPLEMENTATION
======================================================================

Begin only after I explicitly approve a batch.

Before spawning workers:

1. Re-read each approved Linear issue.
2. Confirm that its requirements have not changed.
3. Re-check the Git working tree.
4. Confirm there are no unrelated uncommitted changes that could be damaged.
5. Assign exclusive ownership boundaries.
6. Determine whether isolated Git worktrees are required.

Use one story_worker subagent per approved issue.

Give each worker:

- exactly one Linear issue
- its full description
- exact acceptance criteria
- explicitly owned files and modules
- known dependencies
- prohibited files and shared areas
- required tests
- expected handoff format

For write-heavy parallel work, create one isolated Git worktree per issue.

Suggested branch format:

codex/<linear-issue-id>-<short-slug>

Suggested sibling worktree format:

../<repository-name>-<linear-issue-id>

Do not run multiple write-capable workers concurrently in the same checkout
unless their ownership is proven disjoint.

When isolated worktrees cannot be created or reliably assigned:

- do not fake isolation;
- do not run conflicting workers concurrently;
- execute those issues sequentially instead.

Workers must not:

- implement another issue
- edit another worker's owned files
- modify shared contracts independently
- create concurrent database migrations
- update Linear
- expose or modify secrets
- commit
- push
- merge
- deploy
- open pull requests

Workers must:

- follow repository instructions
- implement the complete supported acceptance criteria
- add or update tests
- run targeted verification
- report assumptions immediately
- stop when required product information is missing
- provide a structured handoff

Wait for all workers in the approved batch.

Use /agent to inspect running worker threads when necessary.

After workers finish, summarize:

- issue ID
- implementation status
- files changed
- tests executed
- test results
- unresolved concerns
- conflicts between workers
- worktree location, when applicable

Stop and ask for approval before integrating worker changes.

======================================================================
PHASE 3 — INTEGRATION AND VERIFICATION
======================================================================

Begin only after I approve integration.

Use the integrator agent to review every worker result.

For each issue:

1. Compare the implementation against every Linear acceptance criterion.
2. Review its diff independently.
3. Detect overlapping changes.
4. Detect inconsistent API contracts.
5. Detect duplicate implementations.
6. Detect migration-order problems.
7. Detect authorization gaps.
8. Detect frontend/backend mismatches.
9. Detect broken or insufficient tests.
10. Detect undocumented assumptions.

Integrate conservatively and in dependency order.

Run, where applicable:

- targeted unit tests
- service tests
- integration tests
- end-to-end tests
- linting
- formatting checks
- static analysis
- type checks
- build verification
- the broader test suite

Do not weaken, skip, or delete valid tests merely to make the build pass.

Produce a final batch report containing:

- completed Linear issues
- acceptance criteria verification
- files changed
- verification commands
- test results
- conflicts encountered
- unresolved defects
- remaining manual checks
- newly unblocked issues
- recommended next batch

Do not commit, push, merge, deploy, open a pull request, or update Linear until
I explicitly approve those actions.

======================================================================
AUTONOMOUS REPOSITORY WORKFLOW FOR THIS PROJECT
======================================================================

The standing project workflow authorizes routine Linear and GitHub updates for
the issue being worked:

- When starting an item, assign it to Lester Bryan Ilao and move it to
  In Progress.
- Create a branch named codex/<linear-issue-id>-<short-slug>.
- Keep commits incremental and separated by related changes.
- Use concise imperative commit subjects. Add useful bodies for what/why.
- Include footers such as Linear: TEN-123 and LLM: GPT-5 Codex.
- Attach every PR link to its counterpart Linear issue or user story.
- If one PR covers multiple Linear issues, attach the PR link to every covered
  issue and name the covered issue keys in the PR body.
- Move issues to In Review when the PR opens.
- Before human review, run an independent pr-reviewer-agent pass.
- Fix low-risk, in-scope reviewer findings on the PR branch before handoff.
- If a valid finding is broader than the current issue, create a Linear bug or
  backlog item, link it to the current issue, and attach the PR link when
  available.
- When frontend behavior, backend-visible behavior, or a new feature changes,
  attach lightweight screenshots or video evidence to the PR whenever
  practical. Captions must be understandable to client, QA, and business
  reviewers and must state exactly what the evidence verifies.
- After merge, verify the PR merged, comment on the Linear issue with the PR and
  merge details, move the issue to Done, sync main, and clean the merged local
  branch.
- Continue to the next actionable item after finishing a task.

======================================================================
GENERAL RULES
======================================================================

- Linear requirements override assumptions inferred from issue titles.
- Repository findings may expose technical dependencies but must not silently
  change product requirements.
- Cite Linear issue IDs in plans, assignments, handoffs, and reports.
- Do not create duplicate Linear issues.
- Do not maximize agent count merely for speed.
- Prefer a smaller number of independent workers.
- Keep shared code changes sequential unless isolation is demonstrated.
- Keep all changes reversible.
- Stop when essential information is missing.
- Do not modify secrets or credential files.

Start with Phase 1 only unless the user explicitly asks to implement an
approved batch.
