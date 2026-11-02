import asyncio
import struct
import time
import pytest

from nrobot.session_relay import SessionRelay
from nrobot.packet_hunt import PacketHunt


@pytest.mark.parametrize("ambiguous", [False, True])
@pytest.mark.parametrize("already_active", [False, True])
def test_probe_learns_and_saves_only_unique_effect_across_separate_reads(tmp_path, monkeypatch, ambiguous, already_active):
    async def scenario():
        from nrobot.packet_settings import DEFAULTS
        import nrobot.packet_settings as settings_module
        saved = []
        monkeypatch.setattr(settings_module, "save", lambda settings: saved.append(settings))
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt()
        relay.apply_settings(DEFAULTS)
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
        observer.skills[29] = {'skill_id': 29, 'level': 10, 'sp_cost': 10, 'range': 0, 'target_flags': 4}
        observer.sp = 100
        if already_active:
            observer.effects[12] = True
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        await relay.send_buff_probe({'skill_id': 29, 'level': 10}, game_gate=lambda: True)
        assert struct.unpack_from('<I', relay.upstream.packets[0], 21)[0] == 1
        with pytest.raises(ValueError, match='observação'):
            await relay.send_buff_probe({'skill_id': 29, 'level': 10}, game_gate=lambda: True)
        ack = struct.pack('<HHHIIB', 0x11a, 29, 1, 1, 1, 1)
        effect = struct.pack('<HHIB', 0x196, 12, 1, 1)
        relay.mirror_map(effect)
        if ambiguous:
            relay.mirror_map(struct.pack('<HHIB', 0x196, 13, 1, 1))
        relay.mirror_map(ack)
        relay.finish_buff_learning(time.monotonic()+.6)
        if ambiguous:
            assert saved == [] and relay.buff_candidates == {}
        else:
            assert saved[-1]['skill_profiles'][-1]['effect_id'] == 12
            assert saved[-1]['skill_profiles'][-1]['enabled']
            assert relay.buff_candidates[29] == 12
        assert observer.effects[12]
        assert len(relay.upstream.packets) == 1
        relay.hunt.start()
        with pytest.raises(ValueError, match='pausada'):
            await relay.send_buff_probe({'skill_id': 29, 'level': 10}, game_gate=lambda: True)
    asyncio.run(scenario())
