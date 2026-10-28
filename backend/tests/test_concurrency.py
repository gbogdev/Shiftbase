"""Real concurrency tests. They need row locks, so they only run on PostgreSQL (CI does; SQLite skips)."""
import threading
from datetime import timedelta

import pytest
from django.db import connection, connections

from core.errors import Conflict
from scheduling import services as sch
from scheduling.models import Shift
from tests.conftest import World, utc

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs PostgreSQL row locking"),
]


def _race(fns):
    results, barrier = [], threading.Barrier(len(fns))

    def run(fn):
        try:
            barrier.wait()
            results.append(("ok", fn()))
        except Conflict as e:
            results.append(("conflict", e))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(f,)) for f in fns]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return [r[0] for r in results]


def test_concurrent_swap_approvals_only_one_wins():
    w = World()
    start = utc(2030, 5, 6, 9)
    shift = Shift.objects.create(organization=w.org, location=w.loc, employee=w.ella, start=start,
                                 end=start + timedelta(hours=8), status="published")
    req = sch.request_swap(w.ella, shift, w.sam)
    sch.accept_swap(w.sam, req.pk)
    outcome = _race([lambda: sch.decide_swap(w.manager, req.pk, True), lambda: sch.decide_swap(w.admin, req.pk, True)])
    assert sorted(outcome) == ["conflict", "ok"]


def test_concurrent_open_shift_approvals_assign_once():
    w = World()
    start = utc(2030, 5, 6, 9)
    shift = Shift.objects.create(organization=w.org, location=w.loc, start=start, end=start + timedelta(hours=8),
                                 status="published")
    a1, a2 = sch.apply_open_shift(w.ella, shift), sch.apply_open_shift(w.sam, shift)
    outcome = _race([lambda: sch.decide_application(w.manager, a1.pk, True), lambda: sch.decide_application(w.manager, a2.pk, True)])
    assert outcome.count("ok") == 1
    shift.refresh_from_db()
    assert shift.employee_id in (w.ella.pk, w.sam.pk)
