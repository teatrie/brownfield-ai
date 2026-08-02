"""Launcher stub for the execution ledger CLI.

All artifact-domain logic has been extracted to
``brownfield_ai.ledger.artifacts``.  This file exists solely as the
Taskfile entry point (``task ledger:*`` invokes
``python3 {{.LEDGER_SCRIPT}}``).
"""

from __future__ import annotations

import defopt

from brownfield_ai.ledger.artifacts.cli import (
    filter_cli,
    get,
    query,
    save,
    search_epics_cli,
    timeline,
)
from brownfield_ai.ledger.epics.cli import (
    check_reviews_cli,
    create,
    index_epics,
    next_plan,
    process_reviews_cli,
    release,
    resume,
    set_prs_cli,
    status,
    touch,
)

if __name__ == "__main__":
    defopt.run([
        save,
        query,
        search_epics_cli,
        filter_cli,
        timeline,
        get,
        next_plan,
        release,
        status,
        touch,
        create,
        index_epics,
        set_prs_cli,
        check_reviews_cli,
        process_reviews_cli,
        resume,
    ])
