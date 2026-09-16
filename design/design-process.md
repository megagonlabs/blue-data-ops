# Design Process

This document records the order the files in `design/` are written in and the review each one passes before the next is started.

For a new project, work through the sequence below, completing each document before moving to implementation.
For an existing project, work through the same sequence and create whatever is missing.
Fill the gaps with the developer, and restructure the repository layout and content to match what the documents describe.

## Document Sequence

1. **Overview** — objective, what the system does, design philosophy
2. **Scenarios** — use cases describing how the system is used in practice
3. **High Level Architecture** — key components and their interfaces
4. **Detailed Architecture** — flow of information between key components
5. **Software Stack** — languages, frameworks, and key dependencies
6. **Library** — key classes and functions
7. **Repo Organization** — file structure of the repository
8. **Coding Style** — language, formatting, and conventions
9. **API / Interface Spec** — external-facing interfaces: library, protocol server, HTTP, CLI
10. **Data Model** — schema definitions, entity relationships, data flow
11. **Testing Strategy** — what to test, at what level, and how
12. **Deployment / Ops** — environment setup, configuration, infrastructure
13. **Decision Log (ADR)** — architectural decisions and their rationale

## Guidelines

- Create documents one at a time, in order.
- Each document informs the next. Do not skip ahead.
- Store all design documents in the `design/` directory at the repository root.
- Name files with a numeric prefix matching the sequence above, as in [01-overview.md](01-overview.md).
- Create the decision log at the start of design, at step 1, and add entries as decisions are made. Do not wait until the end.
- When iterative coding begins, propose the libraries and other software for the component under development, and confirm the choice before writing any code.

## Review Protocol (per document)

Each document goes through two reviews after its input has been gathered:

1. **Completeness review** — assess the input and name anything missing or underspecified, before the document is finalized.
2. **Integrity check** — once the document is written, check it against every document already completed, and raise any discrepancy, contradiction, or gap before moving to the next step.

A document that fails either review is corrected in place.
An entry in [13-decision-log.md](13-decision-log.md) is never corrected in place: a decision that changes keeps its original entry and gains an addendum.
