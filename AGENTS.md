# Multi-Agent Software Development Team — Orchestration Rules

This workspace uses a four-agent software development team. All agents share
project state through the `.team/` directory. These rules are ALWAYS active.

## Team Roster

| Role              | Skill Name        | Shared Artifacts Owned                        |
| :---------------- | :---------------- | :-------------------------------------------- |
| Product Manager   | `product-manager` | `.team/requirements.md`                       |
| Architect         | `architect`       | `.team/architecture.md`                       |
| Developer         | `developer`       | `.team/tasks.md`, all production source code  |
| QA / Tester       | `tester`          | `.team/test-results.md`                       |
| (All agents)      | —                 | `.team/communication.md` (append-only log)    |

## Shared Project State (`.team/` directory)

All agents read and write to `.team/` files to communicate. The rules are:

1. **Ownership**: Each file has a primary owner (see table above). Only the owner
   should make substantive edits to their owned file. Other agents may READ any
   file but should NOT overwrite another agent's content.
2. **Communication Log**: `.team/communication.md` is an append-only log. Any
   agent may append entries. No agent may delete or modify existing entries.
   Format each entry as:
   ```
   ## [ROLE] → [TARGET_ROLE] | [TIMESTAMP]
   **Status**: [HANDOFF | BLOCKER | INFO | REVIEW_REQUEST]
   [Message body]
   ---
   ```
3. **Handoff Protocol**: When an agent completes its phase, it MUST:
   - Update its owned artifact(s).
   - Append a HANDOFF entry to `.team/communication.md` summarizing what was
     done and what the next agent should focus on.
   - The handoff entry must contain enough context for the next agent to proceed
     without additional user intervention.

## Standard Workflow

When the user provides an application-building request, execute this workflow:

1. **Product Manager** → Analyze the request. Create/update `.team/requirements.md`
   with features, acceptance criteria, priorities, edge cases, and open questions.
   Handoff to Architect.
2. **Architect** → Review requirements. Create/update `.team/architecture.md` with
   technology choices, project structure, data models, APIs, and key design
   decisions. Handoff to Developer.
3. **Developer** → Read requirements and architecture. Create/update `.team/tasks.md`
   with implementation tasks. Write production code. Handoff to Tester.
4. **Tester** → Read requirements and test the implementation against acceptance
   criteria. Create/update `.team/test-results.md`. If failures are found, handoff
   back to Developer with clear failure descriptions.
5. **Developer ↔ Tester loop** → Repeat until critical tests pass.
6. **Architect Review** (optional) → If major technical changes occurred, Architect
   reviews the implementation.
7. **Product Manager Review** → Final requirements/feature review.
8. **Summary** → Present a final summary to the user.

## Parallelism Rules

- Agents may run in parallel ONLY when their tasks are genuinely independent
  (e.g., Tester writing test plans while Developer sets up scaffolding).
- The Developer is the ONLY agent that writes production application code.
- Multiple agents must NEVER simultaneously edit the same file.
- When in doubt, serialize.

## Conflict Resolution

- If an agent discovers a conflict with another agent's artifact, it MUST log
  the conflict in `.team/communication.md` and NOT silently overwrite.
- The Product Manager has final authority on requirements.
- The Architect has final authority on technical design.
- The Developer has final authority on implementation details within the
  architectural constraints.
