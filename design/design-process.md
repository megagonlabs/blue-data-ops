# Maintaining the design documentation

The numbered documents in this directory are arranged in reading order. They move from the
project's purpose and common scenarios through architecture, interfaces, data structures, testing,
and release operations. Contributors can update the relevant document directly; the numbering does
not prescribe an implementation sequence.

Update a design document when a change alters the contract or rationale it describes. User-facing
behavior belongs in `docs/` and the package READMEs, which should match the current implementation.
The design documents provide the reasoning behind that behavior and may need a separate update when
the reasoning changes.

Use [13-decision-log.md](13-decision-log.md) for a cross-cutting architectural decision that has no
clear home in another design document. If a later decision reverses an entry, retain the original
entry and append the replacement decision.

The document set is organized as follows:

1. [Overview](01-overview.md)
2. [Scenarios](02-scenarios.md)
3. [High-level architecture](03-high-level-architecture.md)
4. [Detailed architecture](04-detailed-architecture.md)
5. [Software stack](05-software-stack.md)
6. [Library](06-library.md)
7. [Repository organization](07-repo-organization.md)
8. [Coding style](08-coding-style.md)
9. [API and interface specification](09-api-interface-spec.md)
10. [Data model](10-data-model.md)
11. [Testing strategy](11-testing-strategy.md)
12. [Deployment and operations](12-deployment-ops.md)
13. [Decision log](13-decision-log.md)

[repo-organization-template.md](repo-organization-template.md) summarizes the layout conventions
used by this repository. The concrete tree and its rationale are in
[07-repo-organization.md](07-repo-organization.md).
