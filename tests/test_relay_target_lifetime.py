import asyncio
import time

from nrobot.network_targets import Entity
from nrobot.continuous_observer import ContinuousTracker
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


def test_passive_capture_still_expires_but_reliable_connection_retains_stationary_actor():
    passive = ContinuousTracker({1037})
    reliable = ContinuousTracker({1037}, player_ttl=None, idle_timeout=None, entity_ttl=None)
    for tracker in (passive, reliable):
        tracker.observer.apply({'kind': 'player_position_init', 'position': [10, 10]}, 30)
        tracker.observer.registry.update(Entity(20, 1037, 11, 10, 0, 'monster'))
    assert not passive.snapshot(30)['recent_entities']
    result = reliable.snapshot(30)
    assert result['recent_entities'][0]['position_age_seconds'] == 30
    assert result['recent_entities'][0]['position_usable']
    reliable.observer.apply({'kind': 'remove', 'entity_id': 20, 'reason': 0}, 31)
    assert not reliable.snapshot(31)['recent_entities']


def test_announced_speed_completes_estimate_without_overwriting_raw_sighting():
    actor = Entity(20, 1037, 315, 28, 0, 'monster', destination=(320, 20), walk_speed_ms=200)
    assert actor.position_bounds(1) == ([[315, 28], [320, 20]], False)
    assert actor.position_bounds(3) == ([[320, 20]], True)
    assert actor.x == 315 and actor.seen_at == 0


def test_reliable_old_stationary_or_completed_movement_can_plan_and_send_skill(tmp_path):
    async def scenario():
        for moving in (False, True):
            relay = SessionRelay('127.0.0.1', folder=tmp_path, species={1037}, allow_commands=True)
            relay.hunt = PacketHunt(use_skills=True)
            relay.hunt.start()
            class Writer:
                def __init__(self): self.packets = []
                def write(self, data): self.packets.append(data)
                async def drain(self): pass
            relay.upstream = Writer()
            now = time.monotonic()
            observer = relay.tracker.observer
            observer.player_id, observer.player, observer.player_at = 1, [320, 20], now
            observer.sp = 100
            observer.skills[524] = {'skill_id': 524, 'level': 10, 'sp_cost': 1, 'range': 6}
            entity = (Entity(20, 1037, 315, 28, now-3, 'monster', destination=(320, 20), walk_speed_ms=200)
                      if moving else Entity(20, 1037, 321, 20, now-30, 'monster'))
            observer.registry.update(entity)
            action = relay.hunt.plan(relay.status(), now)
            assert action['kind'] == 'skill'
            await relay.send_hunt_action(action, game_gate=lambda: True)
            assert len(relay.upstream.packets[0]) == 25
            assert relay.hunt.confirmed_skills == 0  # prediction is not a damage confirmation
    asyncio.run(scenario())
