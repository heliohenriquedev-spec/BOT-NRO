"""Quest targets known by the name the server sends; combat gear refused while mounted is retried."""
import time

from nrobot.quest_extras import Body, Errand
from nrobot.quest_routes import QuestRoutes


def hunting(targets):
    q = QuestRoutes()
    q.routes = [dict(id='r', name='Esgoto', kill_targets=targets, species=sorted({s for t in targets for s in t['species']}),
                     kills=0, mission_ids=[], target_map='prt_sewb4.gat')]
    q.index = 0
    q.phase = 'hunt'
    return q


def kill(q, identity, species, name, own=1):
    now = time.monotonic()
    q.observe([dict(kind='appearance', entity_id=identity, species_id=species, position=[5, 5])], own, 'prt_sewb4.gat', now)
    q.observe([dict(kind='name', entity_id=identity, name=name)], own, 'prt_sewb4.gat', now)
    q.observe([dict(kind='normal_attack', source_id=own, target_id=identity, damage_raw=10)], own, 'prt_sewb4.gat', now)
    q.observe([dict(kind='remove', entity_id=identity, reason=1)], own, 'prt_sewb4.gat', now)


def test_a_sprite_other_than_this_pcs_list_is_learned_by_name_hunted_and_counted():
    q = hunting([dict(name='Ratasana', count=2, species=[1001])])  # this PC thought Ratasana was 1001
    kill(q, 110000001, 1630, 'Ratasana')  # the server's real sprite
    assert 1630 in q.route['species'] and q.progress()[0]['done'] == 1


def test_two_targets_sharing_a_sprite_are_counted_apart_by_name():
    q = hunting([dict(name='Shinobi Ladrao', count=3, species=[1004]), dict(name='Abelha Macho', count=3, species=[1004])])
    kill(q, 110000002, 1004, 'Shinobi Ladrao')
    assert [p['done'] for p in q.progress()] == [1, 0]


def test_combat_items_refused_while_mounted_are_tried_again_after_the_mount_comes_off():
    body = Body()
    body.gear = {10: dict(item_id=16813, equip_location=32, worn=0), 11: dict(item_id=27895, equip_location=2, worn=0),
                 12: dict(item_id=19207, equip_location=1, worn=0)}
    errand = Errand('gear', dict(combat_items=[16813, 27895, 19207], displaced=[], calm_seconds=0, clear_radius=5,
                                 cast_timeout=15, attempts=6), 0)
    now, equipped = 0.0, []
    for _ in range(40):
        action, value = errand.gear(body, now)
        if action == 'done':
            break
        if action == 'equip':
            index, position = value
            mounted = not body.gear[12]['worn']  # the scroll (below) takes the mount off
            ok = index == 12 or not mounted
            body.acks.append((now+.1, index, position, ok, True))
            if ok:
                body.gear[index]['worn'] = position; equipped.append(index)
        now += 1
    assert sorted(equipped) == [10, 11, 12]
