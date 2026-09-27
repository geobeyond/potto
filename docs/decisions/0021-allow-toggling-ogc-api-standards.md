---
status: proposed
date: 2026-09-25
decision-makers: Ricardo
---

# Allow individual OGC API standards to be turned on and off

## Context and Problem Statement

potto implements, or plans to implement, several OGC API standards: Features (with parts such as Filtering), Processes
(Core and Deploy/Replace/Undeploy), and later others such as Records or Tiles. Not every deployment wants all of them.
A data publishing portal may want only Features; a processing service may want only Processes; a deployment may want
to hide a standard whose implementation is still experimental.

Exposing a standard that the deployment doesn't use is confusing (empty endpoints, conformance classes claimed for
things that aren't really offered) and widens the attack surface. It also affects compliance testing: the
conformance declaration and the OpenAPI document should match what is actually offered.

Today, the HTML OGC API Features routes are guarded by a literal `if True:` in `webapp/main.py` (with a comment
suggesting this should be controllable), and the API routers are always included.

Should deployments be able to choose which OGC API standards potto exposes, and how?

## Considered Options

- An explicit setting listing the enabled OGC API standards (and optionally parts), with sensible defaults
- Derive enabled standards automatically from the configured managers and their capabilities
- Always expose every implemented standard
- Store the enabled standards in the server metadata, editable at runtime

## Decision Outcome

Chosen option: "An explicit setting listing the enabled OGC API standards", because it is predictable, easy to
reason about in deployments and CI, and keeps what potto *can* do separate from what a given deployment *chooses* to
expose.

The design:

- A new setting (e.g. `PottoSettings.ogc_api_standards`) enables each standard, and where relevant each part, for
  example `features`, `features-filtering`, `processes`, `processes-deploy`;
- A disabled standard is removed completely:
  - its API routers are not included, so its paths don't appear in the OpenAPI document;
  - its conformance classes are not declared on `/api/conformance`;
  - its links are removed from the landing page;
  - its HTML pages in the web UI are not registered;
- Enabling a standard whose required manager isn't configured, or whose manager lacks a required capability (e.g.
  `processes-deploy` without a process manager that supports creation), fails at startup with a clear error;
- The defaults enable the standards that are considered stable.

<!-- TODO: decide whether this lives in PottoSettings or in the server metadata (as the existing comment in
webapp/main.py suggests). Settings are simpler and consistent with the admin/web UI toggles, but runtime changes via
server metadata would require rebuilding routes and the OpenAPI document without a restart. -->

### Consequences

- Good, because each deployment exposes exactly the standards it supports, and its conformance declaration and
  OpenAPI document are accurate;
- Good, because experimental standards can ship disabled by default;
- Good, because compliance testing (e.g. OGC CITE) can target a known set of conformance classes;
- Bad, because potto must handle every combination of standards being present or absent (landing page, links,
  templates, cross-links between standards);
- Bad, because the startup-time configuration means changing the set of standards requires a restart.
