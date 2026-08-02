"""TODO CRUD CLI launcher stub.

Delegates all subcommands to ``brownfield_ai.ledger.todo.cli``.  This file
exists solely to preserve the ``task todo:*`` entry-point path.
"""

import defopt

from brownfield_ai.ledger.todo.cli import (
    add,
    add_batch,
    add_category,
    assign,
    done,
    list_,
    list_categories,
    update,
)

if __name__ == "__main__":
    defopt.run([add, add_batch, list_, done, assign, update, add_category, list_categories])
