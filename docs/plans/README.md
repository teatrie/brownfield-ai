# Epic Plans

Tracked, PR-reviewable plan folders — one per epic, at
`docs/plans/<EPIC-ID>/`.

This is the **human review** layer of the three-layer plan model. It is not a
substitute for the other two, and they are not substitutes for it:

| Layer | Artifact | Tracked | Audience |
|---|---|---|---|
| Working scratch | `plan.md` (repo root) | no — gitignored, no history | the active session |
| Machine record | ledger epic + `plan_snapshot` / `step_result` | ChromaDB | agents resuming work |
| **Human review** | **`docs/plans/<EPIC-ID>/`** | **yes** | **teammates reviewing a plan** |

`plan.md` is disposable by design: the next epic overwrites it, and outside the
one case below nothing is recoverable. The exception is a plan paused with
`/status pause`, which force-adds `plan.md` onto a pause branch and pushes it —
[status-sync](../../workflows/repository-maintenance/skills/status-sync/SKILL.md)
is the supported recovery path, and `/status resume <branch>` restores it. That
covers a plan you deliberately paused; it does nothing for one silently
overwritten. Promote a plan here when teammates need to review it, and create a
ledger epic when agents need to resume it — a `plan_snapshot` requires an
approved plan, since drafts are not ledger-eligible. See
[planning_protocol.md](../planning_protocol.md) §2 step 4.

## Folder shape

| File | Role |
|---|---|
| `README.md` | Index. Opens with an HTML-comment lifecycle block (`Status`, `Owners`, `Epic`, `Purpose`), then a document index table |
| `<topic>_plan.md` | The primary implementation plan |
| `slice<N>-spec.md` | Per-vertical-slice specs, one per slice |
| `validation_plan.md` / `validation_results.md` | How correctness was to be established, and what it showed |
| `pr_summary.md` | The PR-facing narrative |

Only `README.md` and the primary plan are required. Add the rest as the epic
produces them — an epic with no vertical slices needs no slice specs.

Directory names are epic identifiers. A ticket key is conventional where one
exists; a descriptive slug is fine where none does.

## Lifecycle block

Every epic folder's `README.md` opens with an HTML comment so the status is
readable without rendering, and does not appear in the rendered document (this
index file is not an epic folder and carries no lifecycle block):

```markdown
<!--
Lifecycle:
  Status:   DRAFT | IN REVIEW | IN PROGRESS | SHIPPED | SHIPPED & VALIDATED | ABANDONED
  Owners:   <name(s)>
  Epic:     <EPIC-ID> (one-line scope)

Purpose:
  What this folder is, and whether it is a live plan or an archived record
  retained as a template.
-->
```

## After the epic ships

Keep the folder. It earns its place twice over:

1. **As a template** for the next epic of the same shape.
2. **As the derivation record.** When an epic produces a *generalized*
   convention, promote that convention out into `.claude/rules/` or
   `docs/repo-guides/` — the durable, discoverable home — and leave the folder
   as evidence of how it was derived. Never leave the only copy of a general
   rule inside an epic folder, where nothing will load it.

Update the lifecycle `Status` when the epic closes, and record what actually
happened, including any design assumption that proved wrong. A plan folder that
only records intent is worth much less than one that records the correction.
