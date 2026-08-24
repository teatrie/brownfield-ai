"""Registry of known routing-coverage exemptions for the ``scripts`` router target.

Names every ``(router, path)`` pair that the routing-coverage guard in
``tests/ci/test_router_coverage.py`` is permitted to leave uncovered, together
with the reason and the TODO id tracking its closure. The guard compares its
measured hole set against this registry by exact set equality, so an exemption
that stops being needed fails the guard rather than lingering.

This module deliberately lives under ``tests/helpers/`` rather than ``tests/ci/``:
the guard pins that the registry's own announced target set contains
``tests/helpers/`` and ``tests/ci/``, and relocating it would break that
containment pin. Do not move it.

``EXEMPTIONS`` is empty until the guard has a measured hole set to seed it from.
An entry is only ever added for a hole the guard actually reported: an exemption
written in anticipation of one silently excuses a pair that may never have been
a hole, and the set-equality comparison cannot tell the two apart.
"""

from typing import NamedTuple


class RoutingExemption(NamedTuple):
    """One ``(router, path)`` pair the routing-coverage guard may leave uncovered.

    ``router`` and ``path`` together are the identity the guard compares on;
    ``reason`` and ``todo_id`` exist so an exemption cannot be added without
    naming why it holds and what would close it.
    """

    #: Router filename under ``ci/``, as in ``TEST_ROUTERS``.
    router: str
    #: Repository-relative path, spelled exactly as ``git ls-files`` reports it.
    path: str
    #: Why this pair routes to nothing, in terms of the router's own dispatch.
    reason: str
    #: The TODO tracking closure.
    todo_id: str


#: Every exemption the guard honours, compared against the measured hole set by
#: exact set equality — so a pair that stops being a hole fails the guard rather
#: than lingering here.
EXEMPTIONS: tuple[RoutingExemption, ...] = ()
