import time

from nrobot.ground_cells import GroundCells
from nrobot import rcx_settings
from test_rcx_customization import renderer
from test_bg_entry import relay


def cast(source,position,skill=288):
    return dict(kind='skill_cast',source_id=source,skill_id=skill,position=position,duration_ms=2000,level=1)


def test_other_cast_visible_without_learning_skill_and_cancel_is_scoped():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10]),cast(3,[30,30])],own_id=1,now=now)
    assert len(g.snapshot()['casts'])==2 and g.snapshot()['cells']==[]
    r=renderer({'ground_cells':g.snapshot(),'learned_skills':[]})
    assert r.shared.count==98 and r.shared.preview_count==0
    g.observe([dict(kind='skill_cast_cancel',source_id=2)],own_id=1,now=now+.1)
    r.update({'ground_cells':g.snapshot()});r.feed()
    assert r.shared.count==49
    r.close()


def test_ally_enemy_filters_apply_to_casts_and_real_units_separately():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10]),cast(3,[30,30])],own_id=1,now=now)
    data=g.snapshot();data.update(own_id=1,allied_ids=[2])
    data['effects']=[dict(position=[50,50],effect_type=157,source_id=2),dict(position=[60,60],effect_type=157,source_id=3)]
    config={'skill_styles':{'288':dict(show_allies=False,show_enemies=True)}}
    r=renderer({'ground_cells':data},config,sides=False)
    assert r.shared.count==50
    assert any(r.shared.cells[i].x==60 and r.shared.cells[i].y==60 for i in range(r.shared.count))
    r.configure({'skill_styles':{'288':dict(show_allies=True,show_enemies=False)}})
    assert r.shared.count==50
    assert any(r.shared.cells[i].x==50 and r.shared.cells[i].y==50 for i in range(r.shared.count))
    r.configure({'skill_styles':{'288':dict(show_allies=False,show_enemies=False)}})
    assert r.shared.count==0
    r.close()


def test_older_skill_damage_does_not_cancel_new_cast_and_expiry_hides_it():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10])],own_id=1,now=now)
    g.observe([dict(kind='skill_damage',source_id=2,skill_id=89)],own_id=1,now=now+.1)
    assert g.external_casts[2]['skill_id']==288
    data=g.snapshot();data['casts'][0]['expires']=now-1
    r=renderer({'ground_cells':data})
    assert r.shared.count==0
    r.close()


def test_skills_start_without_rcx_and_checked_sides_persist():
    value=rcx_settings.save({'skill_styles':{'288':{'fill':'#123456'}}})
    style=rcx_settings.style_for(value,157,288)
    assert not style['show_allies'] and not style['show_enemies'] and not style['enabled'] and not style['hide_native']
    value['skill_styles']['288']['show_enemies']=True
    rcx_settings.save(value)
    style=rcx_settings.style_for(rcx_settings.load(),157,288)
    assert style['show_enemies'] and style['enabled'] and not style['show_allies']


def test_old_files_default_sides_become_unchecked_and_user_choices_stay(tmp_path):
    import json
    rcx_settings.FILE.parent.mkdir(parents=True,exist_ok=True)
    rcx_settings.FILE.write_text(json.dumps({'effects':{'131':dict(enabled=True,show_allies=True,show_enemies=True),
                                                        '146':dict(enabled=False,show_allies=True,show_enemies=False)},
                                             'skill_styles':{'89':dict(enabled=True,show_allies=False,show_enemies=True)}}),encoding='utf-8')
    value=rcx_settings.load()
    assert not value['effects']['131']['show_allies'] and not value['effects']['131']['show_enemies']
    assert not value['effects']['146']['show_allies']  # 'Mostrar este efeito' was off
    assert value['skill_styles']['89']['show_enemies'] and not value['skill_styles']['89']['show_allies']
    assert json.loads(rcx_settings.FILE.read_text(encoding='utf-8'))['sides_version']==rcx_settings.SIDES_VERSION
    assert rcx_settings.FILE.with_name(rcx_settings.FILE.name+'.antes_lados').exists()


def test_general_effect_side_covers_its_skills():
    config=rcx_settings.validate({'effects':{'134':dict(show_enemies=True)},'skill_styles':{'89':dict(show_allies=True)}})
    assert rcx_settings.style_for(config,134,89)['show_allies'] and rcx_settings.style_for(config,134,89)['show_enemies']
    assert rcx_settings.style_for(config,134,83)['show_enemies'] and not rcx_settings.style_for(config,134,83)['show_allies']


def test_rcx_panel_side_checkboxes_save_per_selected_skill():
    from PySide6.QtWidgets import QApplication
    from nrobot.rcx_panel import RcxPanel
    app=QApplication.instance() or QApplication([])
    panel=RcxPanel()
    assert not panel.show_allies.isChecked() and not panel.show_enemies.isChecked() and not panel.hide_native.isChecked()
    assert not hasattr(panel,'effect_enabled')  # 'Mostrar este efeito' was removed: the sides decide
    key=panel.current;panel.show_allies.setChecked(True);panel.hide_native.setChecked(True);panel.save_now()
    section='skill_styles' if key.startswith('skill:') else 'effects'
    saved=rcx_settings.load()[section][key.split(':')[1]]
    assert saved['show_allies'] is True and saved['show_enemies'] is False and saved['hide_native'] is True
    panel.close()


def test_disable_allies_hides_own_units_cast_and_native_aim_preview_immediately():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(1,[10,10])],own_id=1,now=now)
    ground=g.snapshot();ground.update(own_id=1,allied_ids=[])
    ground['effects']=[dict(position=[50,50],effect_type=157,source_id=1)]
    r=renderer({'ground_cells':ground,'learned_skills':[dict(skill_id=288,level=1,target_flags=2)]})
    assert r.shared.count==50 and r.shared.preview_count==1
    r.configure({'skill_styles':{'288':dict(show_allies=False,show_enemies=True)}})
    assert r.shared.count==0 and r.shared.preview_count==0
    r.configure({'skill_styles':{'288':dict(show_allies=True,show_enemies=False)}})
    assert r.shared.count==50 and r.shared.preview_count==1
    r.close()


def test_general_side_filter_cannot_be_overridden_by_saved_skill_defaults():
    config=rcx_settings.validate({'effects':{'157':dict(show_allies=False,show_enemies=False)},
                                  'skill_styles':{'288':dict(fill='#123456')}})
    style=rcx_settings.style_for(config,157,288)
    assert not style['show_allies'] and not style['show_enemies']
    assert rcx_settings.preview_definitions(config,[dict(skill_id=288,level=1,target_flags=2)])[0]['show_allies'] is False


def bg_packet(identity, name, team):
    import struct
    return struct.pack('<HI24sH', 0x2dd, identity, name.encode(), team)


def test_battleground_team_packet_is_decoded():
    from nrobot.packet_reader import decode
    event=decode(bg_packet(2003137,'Saga',3))
    assert event['kind']=='bg_team' and event['entity_id']==2003137 and event['name']=='Saga' and event['team']==3




ME,MATE,FOE,OTHER=2003137,2002312,2002335,2002625


def sides_relay(tmp_path):
    r=relay(tmp_path)
    r.tracker.observer.player_id=ME
    r.registry.players.clear()
    # Same village (guild) for MATE and FOE; the rank after the name never counts.
    r.registry.players.update({str(MATE):{'guild':'Vila Oculta da Nuvem','guild_id':103,'party':'RankB'},
                               str(FOE):{'guild':'Vila Oculta da Nuvem','guild_id':103,'party':'RankB'},
                               str(OTHER):{'guild':'Vila Oculta da Folha','guild_id':98,'party':'RankB'}})
    r.observe_rcx_affiliation([dict(kind='appearance',entity_id=ME,species_id=1,look={'guild_id':103})])
    r.ground_cells.observe([cast(MATE,[10,10]),cast(FOE,[20,20]),cast(OTHER,[30,30]),cast(110000001,[40,40])],own_id=ME)
    return r


def allied(r):
    return set(r.rcx_ground_snapshot()['allied_ids'])


def test_map_without_pvp_every_player_is_allied_and_monsters_are_not(tmp_path):
    r=sides_relay(tmp_path)
    assert allied(r)=={MATE,FOE,OTHER}  # e.g. anyone's Sanctuary heals here


def test_pvp_map_allies_are_guild_and_real_party_never_the_rank(tmp_path):
    r=sides_relay(tmp_path)
    assert r.observe_rcx_affiliation([dict(kind='map_property',value=1)])
    assert allied(r)=={MATE,FOE}  # same guild (village) only; RankB shared with OTHER does not count
    r.observe_rcx_affiliation([dict(kind='party_list',members=[ME,OTHER])])
    assert allied(r)=={MATE,FOE,OTHER}
    r.observe_rcx_affiliation([dict(kind='party_leave',entity_id=OTHER)])
    assert OTHER not in allied(r)
    assert r.observe_rcx_affiliation([dict(kind='map_change',position=[1,1])])
    assert allied(r)=={MATE,FOE,OTHER}  # the next map starts without PvP until the server says so


def test_battleground_team_decides_over_village(tmp_path):
    r=sides_relay(tmp_path)
    # Queued for a BG in town: the server already sends the teams, but town rules still apply.
    r.observe_rcx_affiliation([dict(kind='bg_team',entity_id=ME,team=7),dict(kind='bg_team',entity_id=FOE,team=8)])
    assert allied(r)=={MATE,FOE,OTHER}
    assert r.observe_rcx_affiliation([dict(kind='map_change',position=[146,57]),dict(kind='map_type',value=19),dict(kind='bg_team',entity_id=ME,team=7),
                                     dict(kind='bg_team',entity_id=MATE,team=7),dict(kind='bg_team',entity_id=FOE,team=8),
                                     dict(kind='bg_team',entity_id=OTHER,team=8)])
    ground=r.rcx_ground_snapshot()
    assert set(ground['allied_ids'])=={MATE} and ground['battleground_team']==7
    assert r.observe_rcx_affiliation([dict(kind='map_change',position=[86,135])])
    assert allied(r)=={MATE,FOE,OTHER}


def test_other_players_summon_takes_its_owner_side(tmp_path):
    r=sides_relay(tmp_path)
    r.rcx_learned_summons={'746:4':{'creature':True}}
    r.inventory.entities[OTHER]={'position':[30,30]};r.inventory.entities[MATE]={'position':[10,10]}
    r.observe_rcx_affiliation([dict(kind='map_property',value=1),
                               dict(kind='skill_no_damage',skill_id=746,source_id=OTHER,target_id=OTHER),
                               dict(kind='appearance',entity_id=110000050,species_id=1002,position=[32,31],spawned=True),
                               dict(kind='skill_no_damage',skill_id=746,source_id=MATE,target_id=MATE),
                               dict(kind='appearance',entity_id=110000051,species_id=1002,position=[11,12],spawned=True)])
    r.ground_cells.observe([cast(110000050,[50,50]),cast(110000051,[60,60])],own_id=ME)
    ids=allied(r)
    assert 110000051 in ids and 110000050 not in ids  # PvP: the guild mate's summon is allied
    r.observe_rcx_affiliation([dict(kind='map_property',value=0)])
    assert 110000050 in allied(r)  # without PvP the other player's summon is allied too


def test_pvp_and_party_packets_are_decoded():
    import struct
    from nrobot.packet_reader import decode
    assert decode(struct.pack('<HH',0x199,1))=={'opcode':'0199','kind':'map_property','value':1}
    member=lambda i:struct.pack('<I24s16sBB',i,b'x',b'm.gat',0,0)
    body=struct.pack('<24s',b'pt')+member(ME)+member(OTHER)
    assert decode(struct.pack('<HH',0xfb,4+len(body))+body)['members']==[ME,OTHER]
    assert decode(struct.pack('<HI24sB',0x105,OTHER,b'x',0))=={'opcode':'0105','kind':'party_leave','entity_id':OTHER}


def test_bat_map_name_alone_marks_the_battleground(tmp_path):
    r=sides_relay(tmp_path)
    r.tracker.observer.map_name='bat_c02'
    r.observe_rcx_affiliation([dict(kind='map_change',position=[146,57]),dict(kind='bg_team',entity_id=ME,team=2),
                               dict(kind='bg_team',entity_id=MATE,team=2),dict(kind='bg_team',entity_id=FOE,team=1)])
    assert allied(r)=={MATE}
