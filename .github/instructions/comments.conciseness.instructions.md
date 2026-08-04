---
description: Code Comment & Docstring Conciseness Constraints
applyTo: "**/*.py,**/*.sql,**/*.sql.j2,**/*.sh,**/*.yaml,**/*.yml,**/*.tf,**/*.ts,**/*.tsx,**/*.js,**/*.ipynb"
---

# Code Comment & Docstring Conciseness Constraints

## Core Rule

This file is a **mirror**. The authoritative source is `.claude/rules/comments.conciseness.md`; when the two diverge, that file wins. Both are indexed by `docs/coding_standards.md` section 7 ("Minimal, Reader-Directed Comments & Docstrings").

This standard is the *audience/redundancy* companion to the *temporal* comment-history standard indexed as section 6: section 6 forbids narrating **when** the code changed; this one forbids explaining **what a competent reader already knows**.

Comment only the non-obvious rationale that is specific to *this* code and cannot be recovered by reading the code itself, its base class / type signature, or a linked guide. Write for a competent engineer reading the current tree -- **never** as scaffolding that narrates the agent's own reasoning or restates a generic contract "for completeness". Prefer deleting or condensing over explaining. Verbosity is not free: every redundant line dilutes the signal of the one comment that actually mattered.

The three failure modes this rule targets:

1. **Generic / non-local** -- restates a base-class contract, a framework convention, or a repo-guide rule that is identical for every sibling and carries nothing specific to this file. If it would read the same pasted into any other subclass, delete it (the base class or the guide is its home). A comment explaining that a `table` attribute is the fully-qualified catalog table the base class uses to build paths and logging context is the canonical example: true of every sibling task, so it belongs on the base class, not here.
2. **Agent-directed** -- reads as scaffolding that narrates the author's or agent's decision process ("we cast this because the task asks for...", step-by-step reasoning) rather than the code's current-state rationale for a future human reader.
3. **Speculative / over-explained** -- length spent hedging about code paths that are not taken, alternatives that were rejected, or coercions that cannot occur given the declared types. A comment that justifies a cast by speculating about overflow, string coercion, and "handling both cases defensively" should collapse to the single fact that matters: the source emits the value as a long and the output contract is an integer.

**Delete test** (the companion to section 6's Keep test):

- (a) Would a competent engineer already know this from the code, its base class / type signature, or a linked guide? -> **delete**.
- (b) Does it explain the *author's / agent's decision process* rather than the code's current-state rationale? -> **delete or rewrite** as terse rationale.
- (c) Does it speculate about paths the code does not take? -> **delete**.

**Keep** only what is locally specific and non-obvious -- the comment that stops a future reader from "simplifying" a load-bearing line. Canonical keeper: an inert-looking `min_size = 0` that silently disables a `final_size > min_size` empty-snapshot assertion. Nothing in the assignment reveals that; the comment earns its line.

## Docstrings

Docstrings state the **contract** (params, returns, raises) plus any non-obvious behaviour -- nothing more:

- Do not restate the type signature in prose (documenting a parameter as "an int" above an `int` annotation is noise).
- Do not speculate about inputs the signature already excludes or paths the body does not take.
- Legacy-file upgrades under the Boy Scout Rule add the *minimal* PEP-257 contract, not a narrative.
- The presence requirements in `docs/coding_standards.md` section "Documentation Standards" (modules/classes/public functions always; private helpers only when complex; tests omitted) still govern *whether* a docstring exists; this rule governs *how terse* it is when it does.

## Relationship to section 6

The comment-history standard (section 6) requires relocating stripped **history** to a durable home (PR description / ledger) under a level-3 Markdown heading written exactly as `### PR-Narrative`. This rule differs: verbosity stripped under the Delete test is **redundant by definition** -- it is recoverable from the code, base class, or guide -- so it needs no relocation. Relocate only if a stripped line contained genuinely non-obvious rationale, in which case the fix is to *condense* it in place, not delete it.

## Enforcement

Not lint-detectable -- "too generic / for-the-agent / speculative" is a human-reviewer judgment, and a linter would produce noise. The Code Diff Review Gate is the backstop.
