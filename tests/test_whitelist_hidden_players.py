import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from nrobot.presence_guard import PresenceGuard
from nrobot.session_relay import SessionRelay
from nrobot.packet_hunt import PacketHunt


def appear(identity=2003143,position=None,option=0):
    return dict(kind='appearance',entity_id=identity,species_id=26,position=position or [10,20],option=option)


def test_whitelist_survives_map_change_without_a_repeated_name_reply():
    g=PresenceGuard();g.allowed_names={'Boa Hancock'}
    g.observe([dict(kind='name',entity_id=2003143,name='Boa Hancock'),appear()],1,0)
    assert g.reason([10,20],0) is None
    g.observe([dict(kind='map_change'),appear()],1,1)
    assert g.reason([10,20],1) is None
    g.observe([dict(kind='remove',entity_id=2003143,reason=0)],1,2,[10,20])
    assert g.reason([10,20],2) is None


def test_normalization_handles_case_nbsp_and_repeated_spaces_without_partial_match():
    g=PresenceGuard();g.allowed_names={' Boa  Hancock '}
    g.observe([dict(kind='name',entity_id=2003143,name='BOA\u00a0Hancock'),appear()],1,0)
    assert g.reason([10,20],0) is None
    g.observe([dict(kind='name',entity_id=2003143,name='Boa Hancock2')],1,1)
    assert g.reason([10,20],1)


def test_cached_relay_name_is_used_for_whitelist_and_informational_alert(tmp_path,capsys):
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.hunt=PacketHunt();r.tracker.observer.player=[10,20]
    r.player_names[2003143]='Boa Hancock'
    r.presence.allowed_names={'Boa Hancock'}
    r.presence.observe([dict(kind='map_change'),appear()],1,0)
    r.announce_presence()
    assert r.presence.reason([10,20],0) is None
    output=capsys.readouterr().out
    assert '[PERMITIDO]' in output and '[ALERTA]' not in output


def test_unknown_name_initially_holds_then_whitelist_name_releases():
    g=PresenceGuard();g.allowed_names={'Boa Hancock'}
    g.observe([appear()],1,0);assert g.reason([10,20],0)
    g.observe([dict(kind='name',entity_id=2003143,name='Boa Hancock')],1,1)
    assert g.reason([10,20],1) is None
    g.observe([dict(kind='option_change',entity_id=2003143,option=0x40)],1,2)
    assert g.reason([10,20],2) is None


def test_other_hidden_player_survives_removal_then_unhide_and_expiry_clear_marker():
    g=PresenceGuard()
    g.observe([appear(),dict(kind='name',entity_id=2003143,name='Outro'),
               dict(kind='option_change',entity_id=2003143,option=2),
               dict(kind='remove',entity_id=2003143,reason=0)],1,0,[10,20])
    details=g.snapshot([10,20],1)['hidden_details']
    assert details[0]['position']==[10,20] and details[0]['name']=='Outro'
    assert g.reason([10,20],1)
    g.observe([dict(kind='option_change',entity_id=2003143,option=0)],1,2)
    assert not g.snapshot([10,20],2)['hidden_details']
    g.observe([dict(kind='option_change',entity_id=2003143,option=0x40)],1,3)
    assert not g.snapshot([10,20],124)['hidden_details']


def test_hide_uses_last_received_cell_not_final_walk_destination():
    g=PresenceGuard()
    g.observe([appear(),dict(kind='move',entity_id=2003143,position=[11,20],destination=[20,20]),
               dict(kind='option_change',entity_id=2003143,option=0x40),
               dict(kind='remove',entity_id=2003143,reason=0)],1,1,[10,20])
    assert g.snapshot([10,20],1)['hidden_details'][0]['position']==[11,20]


def test_disappearance_alone_is_not_labeled_as_confirmed_hide():
    g=PresenceGuard()
    g.observe([appear(),dict(kind='remove',entity_id=2003143,reason=0)],1,0,[10,20])
    s=g.snapshot([10,20],1)
    assert not s['hidden_details']
    assert s['shadow_details'][0]['possible_hidden']
    assert not s['shadow_details'][0]['gm_invisible']
    assert not g.snapshot([10,20],11)['shadow_details']


def test_teleport_and_map_change_clear_hidden_markers():
    g=PresenceGuard();g.observe([appear(option=0x40)],1,0)
    g.observe([dict(kind='remove',entity_id=2003143,reason=3)],1,1)
    assert not g.snapshot([10,20],1)['shadow_details']
    g.observe([appear(option=0x40),dict(kind='map_change')],1,2)
    assert not g.snapshot([10,20],2)['shadow_details']


def test_overlay_has_other_player_content_without_own_hide():
    from PySide6.QtWidgets import QApplication
    from nrobot.game_overlay import GameOverlay
    app=QApplication.instance() or QApplication([])
    overlay=GameOverlay();overlay.resize(1280,800)
    shadow=dict(entity_id=2003143,name='Outro',position=[10,20],gm_invisible=True,last_known=True)
    overlay.update_state({'presence':{'shadow_details':[shadow]}})
    assert overlay.has_content() and overlay.other_hidden()==[shadow] and overlay.label() is None
    drawn=[];overlay.draw_shadow=lambda *args:drawn.append(args)
    overlay.grab()
    assert not drawn  # no invented floor projection; the on-screen list/minimap is used
    overlay.update_state({});assert not overlay.has_content()
    overlay.close()
