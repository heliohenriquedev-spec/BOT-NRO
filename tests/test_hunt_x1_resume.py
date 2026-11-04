"""Instant stop on players, open-ground patrol, overlay clicks, X1 rule files, resuming the queue."""
import asyncio
import json
import struct
import time
import pytest
from nrobot import x1_scripts, quest_progress
from nrobot.quest_routes import QuestRoutes

OWN = 2000001


class Upstream:
    def __init__(self): self.sent = []
    def write(self, data): self.sent.append(bytes(data))
    async def drain(self): pass


def walking_relay(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
    r.upstream = Upstream(); r.native_frames.buffer = b''
    o = r.tracker.observer; o.player_id = OWN; o.player = [10, 10]; o.player_at = time.monotonic()
    o.player_motion = {'at': time.monotonic(), 'duration': 3, 'path': None, 'origin': [10, 10], 'destination': [20, 10]}
    r.hunt.start()
    return r


def test_a_player_showing_up_stops_the_walk_at_once(tmp_path):
    async def scenario():
        r = walking_relay(tmp_path)
        r.presence.observe([dict(kind='appearance', entity_id=2000555, species_id=25, position=[14, 10], option=0)], OWN,
                           time.monotonic(), own_position=[10, 10])
        r.halt_on_presence()
        await asyncio.sleep(0)
        assert r.upstream.sent and struct.unpack_from('<H', r.upstream.sent[-1])[0] == 0xa7  # stop on the current cell
    asyncio.run(scenario())


def test_patrol_starts_with_open_ground_and_leaves_the_walls_for_last():
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    import random
    patrol = PacketPatrol(rng=random.Random(3), spacing=10)
    open_map = CollisionMap(100, 100, [1]*10000)
    patrol.switch_map(open_map, [50, 50])
    first = patrol.next_block([50, 50])
    point = patrol.tour.points[first]
    assert patrol.tour.edge_penalty(first) == min(patrol.tour.edge_penalty(b) for b in patrol.remaining)
    assert 10 < point[0] < 90 and 10 < point[1] < 90


def test_clicks_under_the_bot_windows_are_not_sent_to_the_server(tmp_path):
    r = walking_relay(tmp_path)
    walk = struct.pack('<H', 0xa7)+bytes(6)
    other = struct.pack('<HI', 0x7f, 1)[:6]
    r.native_frames.frames = [(0xa7, walk)]
    assert r.drop_clicks_under_overlay(walk) == walk  # cursor not over a window
    (tmp_path/'cursor_sobre_janela').write_text('1')
    assert r.drop_clicks_under_overlay(walk) == b''
    r.native_frames.frames = [(0x7f, other), (0xa7, walk)]
    assert r.drop_clicks_under_overlay(other+walk) == other  # everything else still goes


def test_x1_rules_are_checked_and_the_first_that_holds_decides(tmp_path):
    example = x1_scripts.validate(json.loads(x1_scripts.EXAMPLE.read_text(encoding='utf-8')))
    assert x1_scripts.decide(example, dict(minha_vida_pct=20, distancia_inimigo=2)) == (
        'Fugir com pouca vida', dict(acao='afastar', celulas=6))
    assert x1_scripts.decide(example, dict(minha_vida_pct=80, distancia_inimigo=2, habilidades_prontas=[524]))[0] == 'Kunai de perto'
    assert x1_scripts.decide(example, dict(minha_vida_pct=80, distancia_inimigo=6, habilidades_prontas=[]))[0] == 'Padrao'
    for wrong, message in ((dict(regras=[]), 'regras'), (dict(regras=[dict(faca=dict(acao='voar'))]), 'acao desconhecida'),
                           (dict(regras=[dict(se=dict(vida=1), faca=dict(acao='atacar'))]), 'condicao desconhecida'),
                           (dict(regras=[dict(faca=dict(acao='habilidade', id=524))]), 'nivel')):
        with pytest.raises(ValueError, match=message):
            x1_scripts.validate(wrong)


def test_each_character_gets_its_own_imported_x1_file(tmp_path):
    name = x1_scripts.import_file(x1_scripts.EXAMPLE)
    bad = tmp_path/'ruim.json'; bad.write_text(json.dumps(dict(regras=[dict(faca=dict(acao='voar'))])))
    with pytest.raises(ValueError):
        x1_scripts.import_file(bad)
    x1_scripts.choose('Uadaweu2', name)
    assert x1_scripts.for_character('Uadaweu2')['nome'] == 'Exemplo de X1'
    assert x1_scripts.for_character('Outro') is None


def lifecycle_route(identity='R'):
    return dict(id=identity, name=identity, target_map='field', species=[1632], kills=1, steps=[dict(kind='walk', map='field', position=[1, 1])],
                lifecycle_enabled=True, pickup_steps=[dict(kind='npc', map='town', position=[1, 1])], pickup_confirmation='ok',
                delivery_steps=[dict(kind='npc', map='town', position=[1, 1])], delivery_confirmation='ok',
                kill_targets=[])


def test_progress_is_saved_and_the_queue_resumes_where_it_stopped(tmp_path):
    q = QuestRoutes(); q.start([lifecycle_route('A'), lifecycle_route('B')], 0)
    q.index = 1; q.begin(1); q.phase = 'hunt'; q.last_stage = ('hunt', 0); q.kills = 7; q.kill_counts = {1632: 7}
    state = q.progress_state()
    assert state['route_id'] == 'B' and state['phase'] == 'hunt' and state['kill_counts'] == {'1632': 7}
    quest_progress.save(state)
    again = QuestRoutes(); again.resume_from([lifecycle_route('A'), lifecycle_route('B')], quest_progress.load(), 10)
    assert again.index == 1 and again.phase == 'travel' and again.kills == 7 and again.kill_counts == {1632: 7}
    assert 'Retomando' in again.reason and 'B' in quest_progress.describe(quest_progress.load())


def test_relay_saves_progress_when_the_queue_stops(tmp_path):
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    r.quests.start([lifecycle_route()], 0)
    r.quest_stop('jogador por perto')
    assert quest_progress.load()['route_id'] == 'R'
