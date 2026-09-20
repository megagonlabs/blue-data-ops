# Decision Log

Architectural decisions are recorded here as they are made.

**This log is empty, and that is deliberate.**
The decisions this repository has taken are written where they are load-bearing: exact pinned identity and immutable registration in [01-overview.md](01-overview.md), the boundary rules in [03-high-level-architecture.md](03-high-level-architecture.md), the dependency and interpreter floors in [05-software-stack.md](05-software-stack.md), the layout rationale in [07-repo-organization.md](07-repo-organization.md), the interface contracts in [09-api-interface-spec.md](09-api-interface-spec.md), and the versioning and release rules in [12-deployment-ops.md](12-deployment-ops.md).
Each is stated beside the thing it constrains, with its reason.

Restating them here would produce a second copy that drifts.
Nothing in this repository has been decided twice with two different answers, so there is no history a reader needs that the documents above do not already carry.

What this file is for is the decision that does *not* have a home: one taken against the grain of a document that is already written, or one reversed later.
The format below applies from the first entry on.

## Format

One entry per decision, newest last, never rewritten. A later decision supersedes an earlier one by
appending an **Addendum** to the original entry rather than editing it.

```markdown
## ADR-001 — Title

**Date:** YYYY-MM-DD
**Status:** Accepted

**Decision:** What was decided, in one or two sentences.

**Rationale:** Why, including the alternatives that were considered and set aside.

**Consequences:** What this commits the project to, and what it rules out.
```
