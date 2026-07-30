---
description: Architecture, planning, implementation, and QA perspectives for software work.
---

# Development Team

Architecture, planning, implementation, and QA perspectives for software work.

Run this team against the user's request: $ARGUMENTS

## Members

- **Solutions Architect Agent** (`solutions-architect`) — Identify constraints, viable options, risks, and one recommended design.
- **Tech Lead Agent** (`tech-lead`) — Convert the request into sequenced, testable engineering work.
- **Senior Software Engineer Agent** (`senior-software-engineer`) — Propose the smallest correct implementation and its verification.
- **QA Engineer Agent** (`qa-engineer`) — Identify critical checks, regressions, and evidence required to ship.

Dispatch at most 3 member(s) concurrently. Each member works from the same immutable task description and reports independently; do not let one member's output silently become another's input.
