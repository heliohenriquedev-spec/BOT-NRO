"""REDE-03: identidade persistente, categoria e validade dos dados."""
from nrobot.network_targets import Entity, TargetRegistry


def test_choose_keeps_identity_until_removed():
    r = TargetRegistry()
    r.update(Entity(100, 42, 4, 0, 1, 'monster'))
    r.update(Entity(101, 42, 8, 0, 1, 'monster'))
    assert r.choose({42}, (0, 0), 1).entity_id == 100
    r.update(Entity(101, 42, 1, 0, 2, 'monster'))
    assert r.choose({42}, (0, 0), 2).entity_id == 100
    r.remove(100)
    assert r.choose({42}, (0, 0), 2).entity_id == 101


def test_reject_non_targets_dead_stale_and_outside_range():
    r = TargetRegistry()
    for e in [Entity(1, 42, 0, 0, 10, 'player'), Entity(2, 42, 0, 0, 10, 'npc'),
              Entity(3, 43, 0, 0, 10, 'monster'), Entity(4, 42, 0, 0, 10, 'monster', False),
              Entity(5, 42, 0, 0, 1, 'monster'), Entity(6, 42, 100, 0, 10, 'monster')]:
        r.update(e)
    assert r.choose({42}, (0, 0), 10) is None


def test_out_of_order_map_change_and_expiry():
    r = TargetRegistry()
    r.update(Entity(1, 42, 1, 1, 10, 'monster'))
    r.update(Entity(1, 43, 1, 1, 9, 'monster'))
    assert r.choose({42}, (0, 0), 10).species_id == 42
    assert r.choose({42}, (0, 0), 16) is None
    r.update(Entity(1, 42, 1, 1, 17, 'monster'))
    r.clear()
    assert r.choose({42}, (0, 0), 17) is None


def test_character_disguised_with_monster_sprite_is_never_a_monster_target():
    from nrobot.network_targets import Entity, TargetRegistry
    registry=TargetRegistry(ttl=None)
    registry.update(Entity(2003137,1037,10,10,0,'monster'))
    registry.update(Entity(110826880,1037,12,10,0,'monster'))
    assert set(registry.entities)=={110826880} and registry.rejected_players=={2003137}
