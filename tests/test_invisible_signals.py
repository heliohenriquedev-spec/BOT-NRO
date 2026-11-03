import struct

from nrobot.packet_reader import decode
from nrobot.presence_guard import PresenceGuard

OWN, GM = 2000001, 2000777


def chat(identity, text):
    body = text.encode('cp1252')+b'\0'
    return struct.pack('<HHI', 0x8d, 8+len(body), identity)+body


def test_chat_emote_and_turning_carry_the_actor_but_never_the_text():
    event = decode(chat(GM, 'GM Sombra : estou vendo voce'))
    assert event == {'opcode': '008D', 'kind': 'actor_signal', 'signal': 'chat', 'entity_id': GM, 'name': 'GM Sombra'}
    assert decode(struct.pack('<HIB', 0xc0, GM, 5))['signal'] == 'emote'
    assert decode(struct.pack('<HIHB', 0x9c, GM, 0, 4))['signal'] == 'direction'


def test_an_invisible_character_is_revealed_by_its_actions():
    guard = PresenceGuard()
    guard.observe([decode(chat(GM, 'GM Sombra : oi'))], OWN, 0)
    assert guard.drain_alerts()[0] == {'kind': 'ghost', 'entity_id': GM, 'signal': 'falou no chat'}
    assert 'invisivel' in guard.reason([10, 10], 1)
    guard.observe([{'kind': 'skill_no_damage', 'skill_id': 28, 'amount': 0, 'target_id': 110000001,
                    'source_id': GM, 'success': True}], OWN, 5)
    shadow, = guard.snapshot([10, 10], 5)['shadow_details']
    assert shadow['name'] == 'GM Sombra' and shadow['signals'] == 2 and shadow['position'] is None
    assert guard.snapshot([10, 10], 5)['invisible'] == [GM]
    assert guard.reason([10, 10], 5+guard.HIDDEN_HOLD+1) is None  # silent long enough: hunt resumes


def test_visible_or_just_departed_characters_are_not_invisible():
    guard = PresenceGuard()
    visible = {'kind': 'appearance', 'entity_id': GM, 'species_id': 25, 'position': [12, 10], 'option': 0}
    attack = {'kind': 'normal_attack', 'source_id': GM, 'target_id': 110000001, 'damage_raw': 5,
              'action_type': 0, 'source_motion_ms': 100}
    guard.observe([visible, attack], OWN, 0)
    assert not guard.ghosts
    guard.observe([{'kind': 'remove', 'entity_id': GM, 'reason': 0}, attack], OWN, 1)
    assert not guard.ghosts  # late packet right after leaving the view
    guard.observe([attack], OWN, 1+guard.GHOST_GRACE+1)
    assert GM in guard.ghosts
    guard.observe([visible], OWN, 10)
    assert not guard.ghosts  # it showed up: a normal visible player again
    guard.observe([{**attack, 'source_id': OWN}, {**attack, 'source_id': 110000009}], OWN, 30)
    assert not guard.ghosts  # own actions and monsters never count
