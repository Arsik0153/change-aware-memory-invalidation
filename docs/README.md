# Change-Aware Memory Invalidation for LLM Coding Agents in Evolving Software Repositories

This repository contains the research notes, experimental artifacts, and future implementation for a Computer Science Master's thesis at SeoulTech. The project studies how persistent repository memory used by LLM coding agents can remain reliable as the underlying software evolves.

## Problem Statement

Coding agents increasingly retain repository knowledge across sessions: architecture summaries, module descriptions, previous fixes, repository instructions, commit history, and facts extracted from source code. This memory can improve code localization and reduce repeated exploration, but it introduces a distinct failure mode: a fact may have been correct when it was stored and become incorrect after a later code change.

For example, an agent may remember that authentication is performed by `UserService.validateUser()`. After a refactoring moves that responsibility to `AuthService.validateToken()`, the old memory remains plausible but directs the agent toward obsolete code. This is not a conventional hallucination; it is previously valid knowledge whose assumptions no longer match the repository.

The central problem is therefore:

> How can a coding agent identify which persistent memories have been affected by repository changes, invalidate only the unsafe ones, and refresh them before they influence a new task?

A useful solution must balance two errors. **Under-invalidation** exposes the agent to stale knowledge, while **over-invalidation** discards still-valid knowledge and removes the efficiency benefit of persistent memory.

## Proposed Approach

The project will represent each memory item as a structured claim with provenance rather than as untraceable free text. A claim will include its supporting commit, files, source ranges, symbols, and relationships, together with a confidence score and validation status.

The initial implementation will use AST-based analysis to track semantic entities such as modules, classes, functions, signatures, imports, calls, and inheritance relationships. For every repository update, the system will compare the previous and current program structure and classify changes such as addition, deletion, rename, move, signature modification, implementation modification, or dependency change.

AST analysis alone is insufficient for dynamic behavior, configuration, documentation, generated code, and cross-language relationships. It will therefore be combined with:

- version-control diffs and content hashes;
- a symbol and dependency graph;
- build manifests, configuration, and repository instructions;
- lightweight textual matching for non-code evidence.

Detected changes will be mapped to the provenance of stored claims. Their impact may also propagate through the dependency graph: for example, changing a function can affect memories about its callers or the subsystem that contains it. A policy engine will assign each claim one of four states: `valid`, `needs-validation`, `stale`, or `retired`. The decision will consider change type, dependency distance, evidence coverage, and confidence.

Before memory is supplied to an agent, a read-time guard will exclude stale claims and re-check uncertain ones against the current repository. Affected claims can then be regenerated from current evidence, updated while preserving their history, or retired when their subject no longer exists.

```text
Repository change
       |
       v
AST + diff analysis --> changed symbols and files
       |                         |
       v                         v
 dependency graph ------> impacted memory claims
                                  |
                                  v
                    keep / validate / refresh / retire
```

## Research Questions

1. How accurately can repository changes be mapped to affected memory claims?
2. Does symbol-level invalidation outperform file-level, time-based, and full-reset strategies?
3. How much does change-aware invalidation improve downstream code localization and task completion?
4. What accuracy, latency, storage, and token-cost trade-offs arise from increasingly precise provenance and dependency tracking?

## Implementation and Research Plan

1. **Define the memory model.** Specify claim types, provenance fields, lifecycle states, and the rules for linking natural-language memories to repository evidence.
2. **Build repository indexing.** Parse one or more target languages, create stable symbol identifiers, and store AST structure, symbol relationships, file hashes, and commit metadata.
3. **Implement change detection.** Compare repository versions and classify file-level and symbol-level changes, including heuristics for moves and renames.
4. **Construct impact analysis.** Link changes to claims through direct provenance and bounded dependency-graph propagation. Produce an explainable reason for every invalidation decision.
5. **Add validation and refresh.** Re-check uncertain claims against current code and regenerate or retire them before retrieval. LLM-based validation, if used, will be grounded in current repository evidence rather than trusted as the primary detector.
6. **Create an evaluation dataset.** Select real repositories and historical commit pairs, generate memory at an earlier revision, and label whether each claim remains valid at a later revision. Include refactorings, feature changes, bug fixes, and configuration changes.
7. **Compare baselines.** Evaluate against no invalidation, time-to-live expiration, file-hash invalidation, invalidate-on-any-change, and retrieval from only the latest snapshot.
8. **Measure outcomes.** Report stale-claim detection precision, recall, and F1; false invalidation rate; refresh cost; latency; token usage; code-localization accuracy; and end-to-end task success.
9. **Run ablations and analyze failures.** Isolate the value of ASTs, provenance, dependency propagation, and validation, then examine unsupported languages, dynamic dispatch, generated code, and incomplete evidence.

## Expected Contribution

The intended contribution is an explainable, repository-aware memory lifecycle for coding agents: a method that treats memories as versioned claims with explicit dependencies and invalidates them according to semantic change. The project will deliver a prototype, a historical-repository benchmark, and an empirical comparison of invalidation strategies.
