---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Record architecture decisions as ADRs using the MADR minimal template

## Context and Problem Statement

potto has made a number of significant architectural choices: pluggable managers and providers, protocols instead
of inheritance, resource ownership in the core model, an event-driven design, and so on. Today most of these choices
are recorded only in the code, in scattered notes (`docs/motivation.md`, `docs/managers.md`) and in the authors'
heads. New contributors, and future maintainers, need a lightweight way to find out *why* things are the way they are,
and which alternatives were already considered.

How should potto record its architectural decisions?

## Considered Options

- Architecture Decision Records using the [MADR] *minimal* template, stored in `docs/decisions/`
- Architecture Decision Records using the full MADR template
- Architecture Decision Records using Michael Nygard's original format
- No formal records: keep explaining decisions in free-form docs, code comments and PR descriptions

## Decision Outcome

Chosen option: "Architecture Decision Records using the MADR minimal template", because it gives enough structure
(context, options, outcome, consequences) to make decisions comparable and reviewable, without the overhead of the
full template's decision drivers, per-option pros/cons and confirmation sections, which are rarely filled in
properly in a small team.

The design:

- ADRs live in `docs/decisions/`, next to the rest of potto's documentation, so they are versioned and reviewed with
  the code they describe;
- Each ADR is a markdown file named `NNNN-short-title.md`, based on `docs/decisions/adr-template-minimal.md`;
- ADRs carry YAML front matter with `status` (`proposed`, `accepted`, `deprecated`, `superseded by ADR-NNNN`),
  `date` and `decision-makers`;
- An optional "Options not chosen, and why" list may be added after the consequences when the rejected options
  deserve a short explanation;
- Accepted ADRs are not rewritten when a decision changes. A new ADR supersedes them and the old one's status is
  updated to point at it.

<!-- TODO: decide whether ADRs should be added to the zensical.toml nav so they are published with the docs site -->

### Consequences

- Good, because the reasoning behind potto's architecture becomes discoverable and reviewable in PRs;
- Good, because the minimal template is quick to write, which makes it more likely that ADRs actually get written;
- Good, because MADR is a well-known format with tooling and examples available;
- Bad, because the minimal template has no dedicated place for decision drivers, so these need to be folded into
  the context section;
- Bad, because ADRs must be kept in sync with reality. A stale ADR can be more misleading than no ADR at all.


[MADR]: https://adr.github.io/madr/
