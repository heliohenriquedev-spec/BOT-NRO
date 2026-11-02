import struct
import time
import pytest

from nrobot.manual_skill_diagnostic import ManualSkillDiagnostic
from nrobot.packet_encoder import skill
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


@pytest.mark.parametrize('split', [1, 5, 20, 24])
def test_passive_skill_detection_reassembles_fragments_without_duplicates(split):
    packet = skill(20, 524, 10, ticks=lambda: 42)
    detector = ManualSkillDiagnostic()
    learned = {524: {'level': 10}}
    assert detector.feed(packet[:split], learned) == []
    result = detector.feed(packet[split:], learned)
    assert len(result) == 1 and result[0]['target_id'] == 20
    assert result[0]['packet_hex'] == packet.hex()
    assert detector.feed(b'other bytes', learned) == []
    assert ManualSkillDiagnostic().feed(packet, {}) == []


def test_manual_diagnostics_ignore_authentication_phase_and_record_matching_damage(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt(use_skills=True)
    packet = skill(20, 524, 10, ticks=lambda: 42)
    relay.inspect_manual_skill(packet)
    assert not (tmp_path/'caca_eventos.jsonl').exists()
    observer = relay.tracker.observer
    observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
    observer.skills[524] = {'level': 10}
    relay.inspect_manual_skill(packet)
    assert relay.manual_skill_pending['target_id'] == 20
    damage = bytearray(33)
    struct.pack_into('<HHII', damage, 0, 0x1de, 524, 1, 20)
    struct.pack_into('<I', damage, 24, 500)
    struct.pack_into('<H', damage, 28, 10)
    relay.mirror_map(bytes(damage))
    assert relay.manual_skill_pending is None
    assert 'manual_skill_confirmed' in (tmp_path/'caca_eventos.jsonl').read_text()
    assert 'manual' in (tmp_path/'respostas_habilidade.jsonl').read_text()
