---
description: brownfield-ai Python Test Placement
applyTo: "**/*.py"
---

# brownfield-ai Python Test Placement

Python test files for non-`repos/` source directories MUST mirror the source
directory structure under `tests/`:

| Source directory | Test directory |
|-----------------|---------------|
| `src/brownfield_ai/` | `tests/src/brownfield_ai/` |
| `services/dashboard/` | `tests/services/dashboard/` |
| `scripts/` | `tests/scripts/` |
| `ci/` | `tests/ci/` |
| `.claude/hooks/` | `tests/hooks/` |

Do NOT place test files at the `tests/` root. Each test file must live in the
subdirectory that corresponds to its source module. This ensures:

1. **Directory-based CI routing** -- `task test:staged` and `task test:changed`
   detect changes via directory prefixes, not per-file grep patterns.
2. **Conftest isolation** -- each test subdirectory can have its own
   `conftest.py` with domain-specific fixtures that do not pollute other suites.
3. **Discoverable structure** -- `pytest tests/services/dashboard/` runs exactly
   the dashboard tests, no file list maintenance required.

When creating new test files, verify the target subdirectory exists and create it
(with any necessary intermediate directories) before writing the file.
