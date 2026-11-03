import struct

from nrobot.packet_reader import decode
from nrobot.presence_guard import PresenceGuard, HIDDEN_OPTIONS
from nrobot.packet_hunt import PacketHunt


def appearance_22c(entity_id, species, option=0):
    packet = bytearray(65)
    struct.pack_into('<HBIHHHIH', packet, 0, 0x22c, 0, entity_id, 150, 0, 0, option, species)
    packet[55:61] = bytes([2, 129, 64, 40, 20, 0])  # [10, 20] -> [10, 20]
    return bytes(packet)


def appearance_idle(entity_id, species, option=0, opcode=0x22a):
    packet = bytearray(58 if opcode == 0x22a else 57)
    struct.pack_into('<HIHHHIH', packet, 0, opcode, entity_id, 150, 0, 0, option, species)
    packet[50:53] = bytes([2, 129, 64])  # [10, 20]
    return bytes(packet)


def test_standing_player_is_detected_without_walking():
    for opcode in (0x22a, 0x22b):
        event = decode(appearance_idle(2003137, 26, 0x40, opcode))
        assert event['kind'] == 'appearance' and event['entity_id'] == 2003137
        assert event['species_id'] == 26 and event['option'] == 0x40
        assert event['position'] == [10, 20] and event['walk_speed_ms'] == 150
    guard = PresenceGuard()
    guard.observe([decode(appearance_idle(2003137, 26))], 2000001, 0)
    assert guard.players == {2003137}
    assert 'jogador 2003137' in guard.reason([12, 20], 0)


def test_standing_player_who_hides_leaves_a_shadow_at_its_cell():
    guard = PresenceGuard()
    guard.observe([decode(appearance_idle(2003137, 26))], 2000001, 0)
    for option, gm in ((0x2, False), (0x40, True)):
        guard.observe([decode(struct.pack('<HIHHIB', 0x229, 2003137, 0, 0, option, 0))], 2000001, 1)
        shadow, = guard.snapshot([12, 20], 1)['shadow_details']
        assert shadow['position'] == [10, 20] and shadow['gm_invisible'] is gm


def test_option_bits_are_decoded_from_appearance_and_option_change():
    assert decode(appearance_22c(2003137, 1037, 0x40))['option'] == 0x40
    event = decode(struct.pack('<HIHHIB', 0x229, 2003137, 0, 0, 0x2, 0))
    assert event == {'opcode': '0229', 'kind': 'option_change', 'entity_id': 2003137, 'option': 2}


def test_disguised_character_holds_until_it_leaves_view():
    guard = PresenceGuard()
    guard.observe([decode(appearance_22c(110826880, 1037))], 2000001, 0)
    assert guard.reason([10, 20], 0) is None  # real monster id
    guard.observe([decode(appearance_22c(2003137, 1037))], 2000001, 0)
    assert 'disfarcado' in guard.reason([10, 20], 0)
    guard.observe([{'kind': 'move', 'entity_id': 2003137, 'position': [10, 20], 'destination': [40, 20]}], 2000001, 1)
    assert guard.reason([10, 20], 1)  # countdown starts on leaving the radius
    assert guard.reason([10, 20], 12) is None
    guard.observe([{'kind': 'move', 'entity_id': 2003137, 'position': [40, 20], 'destination': [15, 20]}], 2000001, 2)
    assert guard.reason([10, 20], 2)
    guard.observe([{'kind': 'remove', 'entity_id': 2003137}], 2000001, 3, own_position=[10, 20])
    assert 'sumiu perto' in guard.reason([10, 20], 3)  # REDE-82: vanished next to us
    assert guard.reason([10, 20], 3+PresenceGuard.NEAR_DEPARTURE_HOLD+1) is None


def test_any_nearby_character_holds_but_own_character_is_ignored():
    guard = PresenceGuard()
    guard.observe([decode(appearance_22c(2000001, 1037, 0x40))], 2000001, 0)
    assert guard.reason([10, 20], 0) is None
    guard.observe([decode(appearance_22c(2003137, 26))], 2000001, 0)
    reason = guard.reason([10, 20], 0)
    assert 'jogador 2003137' in reason and 'disfarcado' not in reason
    assert guard.reason([40, 20], 0)  # waits configured delay beyond radius
    guard.observe([{'kind': 'remove', 'entity_id': 2003137, 'reason': 2}], 2000001, 1, own_position=[10, 20])
    assert 'deslogou' in guard.reason([10, 20], 1)  # REDE-82: waits the resume delay
    assert guard.reason([10, 20], 1+guard.resume_delay+.1) is None


def test_hiding_holds_until_unhide_and_gm_invisibility_expires_only_after_silence():
    guard = PresenceGuard()
    guard.observe([decode(struct.pack('<HIHHIB', 0x229, 2003137, 0, 0, 0x2, 0))], 1, 0)
    assert 'escondido' in guard.reason([10, 20], 0)
    guard.observe([decode(struct.pack('<HIHHIB', 0x229, 2003137, 0, 0, 0, 0))], 1, 1)
    assert guard.reason([10, 20], 1) is None
    guard.observe([decode(struct.pack('<HIHHIB', 0x229, 2003138, 0, 0, 0x40, 0)),
                   {'kind': 'remove', 'entity_id': 2003138}], 1, 2)
    assert '@hide' in guard.reason([10, 20], 50)  # removal does not prove an invisible GM left
    assert guard.reason([10, 20], 2+PresenceGuard.HIDDEN_HOLD+1) is None
    guard.observe([decode(struct.pack('<HIHHIB', 0x229, 2003139, 0, 0, 0x40, 0)), {'kind': 'map_change'}], 1, 3)
    assert guard.reason([10, 20], 4) is None


def _state(*entities):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
            'recent_entities': [{'entity_id': i, 'position': p} for i, p in entities]}


def test_engaged_monster_keeps_priority_over_closer_monster_and_transient_failures():
    hunt = PacketHunt();hunt.start()
    hunt.plan(_state((20, [15, 10])), 0, 100)
    assert hunt.target == 20
    hunt.observe([{'kind': 'normal_attack', 'source_id': 1, 'target_id': 20}], 1, 1)
    assert hunt.engaged == 20
    hunt.abandon(1.1, 'Alvo mudou de célula antes do ataque; recalculando')
    assert hunt.target == 20 and 20 not in hunt.excluded_until
    hunt.ready_at = 0
    hunt.plan(_state((20, [16, 10]), (21, [11, 10])), 2, 100)
    assert hunt.target == 20
    hunt.observe([{'kind': 'remove', 'entity_id': 20, 'reason': 1}], 1, 3)
    hunt.plan(_state((21, [11, 10])), 3.5, 100)
    assert hunt.engaged is None and hunt.target == 21


def test_engagement_is_released_after_long_time_without_damage():
    hunt = PacketHunt();hunt.start()
    hunt.plan(_state((20, [15, 10])), 0, 100)
    hunt.observe([{'kind': 'skill_damage', 'source_id': 1, 'target_id': 20}], 1, 0)
    hunt.abandon(PacketHunt.ENGAGED_GIVE_UP+1, 'sem rota livre até o alvo; procurando outro')
    assert hunt.target is None and hunt.engaged is None and 20 in hunt.excluded_until


def test_monster_hitting_the_character_becomes_the_engaged_target():
    hunt = PacketHunt();hunt.start()
    hunt.plan(_state((20, [12, 10]), (21, [18, 10])), 0, 100)
    assert hunt.target == 20
    hunt.ready_at = 0
    hunt.observe([{'kind': 'normal_attack', 'source_id': 21, 'target_id': 1}], 1, .5)
    hunt.pending = None
    hunt.plan(_state((20, [12, 10]), (21, [18, 10])), 1, 100)
    assert hunt.engaged == 21 and hunt.target == 21


def test_relay_stops_walk_once_holds_and_resumes_automatically(tmp_path):
    import asyncio
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_encoder import move
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt();relay.hunt.start()
        relay.tracker.observer.player_id = 1;relay.tracker.observer.player = [10, 20]
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        relay.hunt.pending = {'kind': 'move', 'destination': [14, 20]}
        assert not await relay.update_presence_hold()
        relay.presence.observe([decode(appearance_22c(2003137, 1037))], 1, 0)
        assert await relay.update_presence_hold() and await relay.update_presence_hold()
        assert len(relay.upstream.packets) == 1  # a single stop on the current cell, then silence
        assert relay.upstream.packets[0][:2] == move(10, 20)[:2]
        assert relay.hunt.enabled and relay.hunt.pending is None and 'suspensa' in relay.hunt.reason
        relay.presence.observe([{'kind': 'remove', 'entity_id': 2003137}], 1, 1)
        assert not await relay.update_presence_hold() and relay.hunt.enabled
    asyncio.run(scenario())


def test_each_presence_kind_can_be_set_not_to_hold_but_alerts_are_kept():
    guard = PresenceGuard()
    guard.hold_players = guard.hold_disguised = guard.hold_hidden = False
    guard.observe([decode(appearance_22c(2003137, 26)), decode(appearance_22c(2003138, 1037)),
                   decode(struct.pack('<HIHHIB', 0x229, 2003139, 0, 0, 0x40, 0))], 1, 0)
    assert guard.reason([10, 20], 0) is None
    assert [(a['kind'], a['entity_id']) for a in guard.drain_alerts()] == [
        ('player', 2003137), ('player', 2003138), ('disguised', 2003138), ('hidden', 2003139)]
    assert guard.drain_alerts() == []
    guard.observe([decode(appearance_22c(2003137, 26))], 1, 1)  # same character again: no repeat
    assert guard.drain_alerts() == []
    guard.hold_hidden = True
    assert '@hide' in guard.reason([10, 20], 1)
    details = guard.snapshot([10, 20], 1)['hidden_details']
    assert details[0]['entity_id'] == 2003139 and details[0]['gm_invisible']


def test_relay_prints_red_alert_line_for_new_character(tmp_path, capsys):
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.tracker.observer.player = [10, 20]
    relay.presence.observe([decode(appearance_22c(2003137, 26))], 1, 0)
    relay.announce_presence()
    assert '[ALERTA] Jogador por perto' in capsys.readouterr().out


def test_character_cleared_before_hiding_keeps_last_cell_for_its_shadow():
    guard = PresenceGuard()
    guard.observe([decode(appearance_22c(2002899, 26))], 1, 0)
    guard.observe([{'kind': 'remove', 'entity_id': 2002899},
                   decode(struct.pack('<HIHHIB', 0x229, 2002899, 0, 0, 0x2, 0))], 1, 1)
    details = guard.snapshot([10, 20], 1)['hidden_details']
    assert details == [{'entity_id': 2002899, 'name': None, 'last_known': True, 'allowed': False, 'position': [10, 20], 'gm_invisible': False, 'age_seconds': 0}]


def test_player_who_walked_far_resumes_after_the_configured_delay_and_returning_resets_it():
    guard = PresenceGuard()
    guard.resume_delay = 15
    guard.observe([decode(appearance_22c(2003137, 26))], 1, 0)
    guard.observe([{'kind': 'move', 'entity_id': 2003137, 'position': [12, 20], 'destination': [40, 20]}], 1, 1)
    guard.observe([{'kind': 'remove', 'entity_id': 2003137, 'reason': 0}], 1, 2, own_position=[10, 20])
    assert 'foi para longe' in guard.reason([10, 20], 2)
    assert guard.reason([10, 20], 2+14) and guard.reason([10, 20], 2+15.1) is None
    guard.observe([decode(appearance_22c(2003137, 26))], 1, 30)  # came back
    guard.observe([{'kind': 'remove', 'entity_id': 2003137, 'reason': 3}], 1, 31, own_position=[10, 20])
    assert 'teleportou' in guard.reason([10, 20], 40)
    assert guard.reason([10, 20], 46.1) is None


def test_player_ignored_when_pausing_on_players_is_off():
    guard = PresenceGuard()
    guard.hold_players = False
    guard.observe([decode(appearance_22c(2003137, 26)), {'kind': 'remove', 'entity_id': 2003137, 'reason': 2}], 1, 0,
                  own_position=[10, 20])
    assert guard.reason([10, 20], 1) is None


def test_allowed_name_skips_all_presence_holds_without_ignoring_others():
    guard = PresenceGuard()
    guard.allowed_names = {'amigo'}
    guard.observe([decode(appearance_22c(2003137, 1037, 0x40)),
                   {'kind': 'name', 'entity_id': 2003137, 'name': 'AmIgO'}], 1, 0)
    assert guard.reason([10, 20], 0) is None
    guard.observe([decode(appearance_22c(2003138, 26))], 1, 1)
    assert '2003138' in guard.reason([10, 20], 1)


def test_near_removal_uses_configured_delay_and_does_not_restart_countdown():
    guard = PresenceGuard()
    guard.resume_delay = 12
    guard.observe([decode(appearance_22c(2003137, 26)),
                   {'kind': 'remove', 'entity_id': 2003137, 'reason': 0}], 1, 0, [10, 20])
    assert guard.reason([10, 20], 11)
    assert guard.reason([10, 20], 12.1) is None
    assert guard.reason([10, 20], 13) is None
