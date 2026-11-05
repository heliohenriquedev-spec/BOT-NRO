from nrobot.ground_cells import GroundCells, LAND_PROTECTOR, GRAY_STYLE


def entry(identity=1, position=None, **extra):
    return dict(kind='ground_effect', effect_id=identity, source_id=2000556,
                effect_type=LAND_PROTECTOR, position=position or [10, 20], visible=True) | extra


def test_only_explicit_cells_are_reported_and_style_is_gray():
    ground = GroundCells()
    ground.observe([entry()])
    assert ground.snapshot()['cells'] == [[10, 20]]  # never expand one unit into an assumed 11x11 area
    assert ground.snapshot()['style']['fill'] == '#808080'
    assert GRAY_STYLE['outline'] == '#303030'


def test_overlapping_units_keep_the_cell_until_both_are_removed():
    ground = GroundCells()
    ground.observe([entry(), entry(2), entry()])
    assert ground.snapshot()['units'] == 2
    ground.observe([dict(kind='ground_effect_removed', effect_id=1)])
    assert ground.snapshot()['cells'] == [[10, 20]]
    ground.observe([dict(kind='ground_effect_removed', effect_id=2)])
    assert ground.snapshot()['cells'] == []


def test_sanctuary_uses_received_units_instead_of_an_assumed_area():
    ground = GroundCells()
    ground.observe([entry(10, [15, 20], effect_type=0x83), entry(11, [16, 20], effect_type=0x83)])
    assert ground.snapshot()['cells'] == [[15, 20], [16, 20]]


def test_map_change_visibility_and_other_unit_types_do_not_leave_false_cells():
    ground = GroundCells()
    ground.observe([entry(), entry(2, [11, 20]), entry(3, effect_type=1)])
    ground.observe([entry(1, visible=False)])
    assert ground.snapshot()['cells'] == [[11, 20]]
    ground.observe([dict(kind='map_transfer', map='new.gat')])
    assert ground.snapshot()['map'] == 'new.gat' and ground.snapshot()['cells'] == []


def test_invalid_positions_are_ignored_and_overflow_is_explicit():
    ground = GroundCells()
    ground.MAX_UNITS = 1
    ground.observe([entry(position=[-1, 5]), entry(), entry(2, [11, 20])])
    assert ground.snapshot()['units'] == 1 and ground.snapshot()['incomplete']
    ground.reset()
    assert not ground.snapshot()['incomplete']


def test_rcx_button_does_not_claim_native_renderer_is_working(monkeypatch):
    global app
    from PySide6.QtWidgets import QApplication
    from nrobot.rcx_panel import RcxPanel
    from nrobot.rcx_renderer import RcxRenderer
    def unavailable(*args):
        raise ValueError('backend indisponivel no teste')
    monkeypatch.setattr(RcxRenderer, 'start', unavailable)
    app = QApplication.instance() or QApplication([])
    panel = RcxPanel()
    panel.toggle.click()
    assert not panel.toggle.isChecked()
    assert 'Nao ativado' in panel.status.text()
    panel.update_state({'ground_cells': {'map': 'field.gat', 'cells': [[10, 20]]}})
    assert '1 celulas' in panel.observed.text()
    panel.close()


def ground_skill(skill_id, position, source_id=2000556, level=10):
    return dict(kind='ground_skill', skill_id=skill_id, source_id=source_id, level=level, position=position)


def square(x, y, r):
    return [[i, j] for i in range(x-r, x+r+1) for j in range(y-r, y+r+1)]


def test_ground_skill_packet_is_decoded():
    import struct
    from nrobot.packet_reader import decode
    event = decode(struct.pack('<HHIHHHI', 0x117, 89, 2000556, 10, 50, 60, 1234))
    assert event['kind'] == 'ground_skill' and event['skill_id'] == 89
    assert event['source_id'] == 2000556 and event['level'] == 10 and event['position'] == [50, 60]


def test_storm_gust_single_unit_draws_its_9x9_area_until_removed():
    ground = GroundCells()
    ground.observe([ground_skill(89, [50, 60]), entry(5, [50, 60], effect_type=0x86)], now=100)
    assert ground.snapshot()['cells'] == square(50, 60, 4)
    ground.observe([dict(kind='ground_effect_removed', effect_id=5)], now=104)
    assert ground.snapshot()['cells'] == []


def test_storm_gust_sent_as_many_units_is_not_enlarged():
    ground = GroundCells()
    units = [entry(10+i, [48+i, 60], effect_type=0x86) for i in range(5)]
    ground.observe([ground_skill(89, [50, 60])] + units, now=100)
    assert ground.snapshot()['cells'] == square(50, 60, 4)


def test_each_meteor_draws_7x7_around_where_it_fell():
    ground = GroundCells()
    ground.observe([ground_skill(83, [50, 60])], now=100)
    ground.observe([entry(1, [48, 61], effect_type=0x86)], now=101)
    ground.observe([entry(2, [53, 58], effect_type=0x86)], now=103)
    expected = sorted({tuple(c) for c in square(48, 61, 3) + square(53, 58, 3)})
    assert ground.snapshot()['cells'] == [list(c) for c in expected]


def test_cast_bar_packet_is_a_backup_and_waits_for_the_cast_time():
    ground = GroundCells()
    ground.observe([dict(kind='skill_cast', source_id=2000556, target_id=0, skill_id=89,
                         duration_ms=6000, position=[50, 60])], own_id=1, now=100)
    ground.observe([entry(5, [50, 60], effect_type=0x86)], own_id=1, now=106.2)
    assert ground.snapshot()['cells'] == square(50, 60, 4)


def test_dummy_unit_without_matching_spell_stays_a_single_cell():
    ground = GroundCells()
    ground.observe([ground_skill(89, [50, 60], source_id=999),  # another caster
                    ground_skill(89, [90, 90]),  # far from the unit
                    entry(5, [50, 60], effect_type=0x86)], now=100)
    assert ground.snapshot()['cells'] == [[50, 60]]
    stale = GroundCells()
    stale.observe([ground_skill(89, [70, 70])], now=100)
    stale.observe([entry(6, [70, 70], effect_type=0x86)], now=110)
    assert stale.snapshot()['cells'] == [[70, 70]]


def test_land_protector_is_never_expanded_by_a_nearby_area_spell():
    ground = GroundCells()
    ground.observe([ground_skill(89, [10, 20]), entry()], now=100)
    assert ground.snapshot()['cells'] == [[10, 20]]
