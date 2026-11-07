import asyncio
import threading

import pytest

from nrobot.map_navigation import CollisionMap
from nrobot.mob_scan import MobScan


@pytest.mark.parametrize('change_map', [False, True])
def test_scan_calculates_without_blocking_relay_and_discards_old_map_result(monkeypatch, change_map):
    async def scenario():
        scan = MobScan()
        scan.start('field', [1], 0, True)
        scan.sent(1, 0)
        scan.observe([dict(kind='viewpoint', mark_type=1, npc_id=10, position=[10, 10])], .1)
        collision = CollisionMap(30, 30, [1]*900)
        started, release = threading.Event(), threading.Event()
        finish = MobScan.finish

        def delayed(worker, *args, **kwargs):
            started.set()
            assert release.wait(3)
            return finish(worker, *args, **kwargs)

        monkeypatch.setattr(MobScan, 'finish', delayed)
        assert scan.poll_finish([5, 5], 4, collision) is None
        task = scan._finish_job['task']
        try:
            assert await asyncio.to_thread(started.wait, 2)
            # The relay can continue receiving packets while route calculation waits.
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), 1)
            assert not task.done() and scan.goal is None
            if change_map:
                scan.start('other', [1], 100, True)
        finally:
            release.set()
        await task
        result = scan.poll_finish([5, 5], 104, collision)
        if change_map:
            assert result is None and scan.goal is None and scan.map == 'other' and scan.round_open
        else:
            assert result['position'] == [10, 10] and not scan.round_open
            assert scan.last_calculation_ms is not None

    asyncio.run(scenario())


def test_empty_scan_does_not_traverse_the_map(monkeypatch):
    scan = MobScan()
    scan.start('field', [1], 0, True)
    scan.sent(1, 0)
    collision = CollisionMap(30, 30, [1]*900)
    def unexpected_search(*args):
        raise AssertionError('An empty scan must not search all map cells')
    monkeypatch.setattr(collision, 'reachable', unexpected_search)
    assert scan.finish([5, 5], 4, collision.walkable, collision) is None
    assert scan.map_failed('field')
