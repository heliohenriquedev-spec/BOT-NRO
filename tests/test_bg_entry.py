import time
import asyncio
import struct
from types import SimpleNamespace

import pytest

from nrobot import bg_entry


def relay(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
    o = r.tracker.observer; o.player_id = 1; o.player = [150, 150]; o.player_at = time.monotonic(); o.map_name = 'kakashi'
    r.upstream = object()
    return r


def test_recording_keeps_the_npc_and_choices_and_needs_an_npc():
    steps = [dict(kind='walk', map='kakashi', position=[150, 150]), dict(kind='walk', map='kakashi', position=[155, 150]),
             dict(kind='npc', map='kakashi', position=[160, 150], name='Batalha Campal'),
             dict(kind='select', map='kakashi', option='5x5'), dict(kind='close', map='kakashi')]
    entry = bg_entry.recorded_entry(steps, 'kakashi', [159, 150])
    assert [s['kind'] for s in entry['steps']] == ['npc', 'select', 'close', 'walk'] and entry['target_map'] == 'kakashi'
    with pytest.raises(ValueError, match='NPC'):
        bg_entry.recorded_entry(steps[:2], 'kakashi', [155, 150])


def test_manual_retries_save_only_last_npc_attempt_and_preserve_access_route():
    travel = [dict(kind='npc', map='hospital2', position=[16,74], name='Acesso'),
              dict(kind='next', map='hospital2'),dict(kind='wait_map', map='kakashi')]
    npc = dict(kind='npc', map='kakashi', position=[160,150], name='BG 3x3')
    steps = travel+[npc,dict(kind='select',map='kakashi',option='Tentativa antiga'),
                    dict(kind='close',map='kakashi'),npc.copy(),
                    dict(kind='select',map='kakashi',option='Quero participar'),
                    dict(kind='close',map='kakashi')]
    entry=bg_entry.recorded_entry(steps,'kakashi',[159,150])
    choices=[s['option'] for s in entry['steps'] if s['kind']=='select']
    assert choices==['Quero participar']
    assert [s['name'] for s in entry['steps'] if s['kind']=='npc']==['Acesso','BG 3x3']
    assert steps[4]['option']=='Tentativa antiga'  # keep original recording intact


def record(r, mode, said=()):
    r.quest_control('quest_bg_record', dict(mode=mode), lambda: True)
    r.quests.recording['steps'] += [dict(kind='npc', map='kakashi', position=[160, 150], name='BG '+mode),
                                    dict(kind='select', map='kakashi', option=mode)]
    r.quests.recording['observed_texts'] = list(said)
    r.quest_control('quest_bg_save', {}, lambda: True)


def test_each_bg_has_its_npc_and_the_messages_are_shared(tmp_path):
    r = relay(tmp_path)
    record(r, '4x4', ['^FF0000Inscricoes fechadas.^000000'])
    record(r, '3x3', ['Voce entrou na fila!'])
    assert set(bg_entry.load()) == {'4x4', '3x3'}
    assert bg_entry.messages()['seen'] == ['Inscricoes fechadas.', 'Voce entrou na fila!']
    with pytest.raises(ValueError, match='mensagem'):
        r.quest_control('quest_bg_enter', dict(mode='4x4'), lambda: True)
    bg_entry.save_messages('fechadas', 'entrou na fila', 3)
    with pytest.raises(ValueError, match='5x5'):
        r.quest_control('quest_bg_enter', dict(mode='5x5'), lambda: True)
    r.quest_control('quest_bg_enter', dict(mode='3x3'), lambda: True)
    assert r.quests.validation['mode'] == 'travel' and r.quests.route['name'] == 'BG 3x3'
    assert any(s['kind'] == 'select' and s['option'] == '3x3' for s in r.quests.route['steps'])


def test_bg_does_not_equip_mount_while_ordinary_travel_keeps_setting(tmp_path,monkeypatch):
    r=relay(tmp_path);record(r,'3x3')
    bg_entry.save_messages('fechadas','entrou na fila',2)
    r.quests.extras=dict(mount_enabled=True,mount=dict(item_id=123,location=1))
    from nrobot import quest_extras
    extras=r.quests.extras
    monkeypatch.setattr(quest_extras,'for_character',lambda *args:extras)
    r.quest_control('quest_bg_enter',dict(mode='3x3'),lambda:True)
    assert not any(e.kind=='mount' for e in r.quests.errands)
    assert r.quests.extras['mount_enabled'] is True
    r.quest_control('quest_stop',{},lambda:True)
    r.quests.start_validation(bg_entry.load()['3x3']['steps'],'kakashi',time.monotonic(),mode='travel',label='Rota normal')
    assert any(e.kind=='mount' for e in r.quests.errands)


def test_keeps_trying_until_the_queue_message(tmp_path):
    r = relay(tmp_path)
    record(r, '5x5')
    bg_entry.save_messages('Inscricoes fechadas', 'Voce entrou na fila', 3)
    r.quest_control('quest_bg_enter', dict(mode='5x5'), lambda: True)
    for attempt in range(1, 4):  # refused three times, each followed by a new attempt
        assert r.bg_attempt['tries']['5x5'] == attempt and r.quests.active
        r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='^FF0000Inscricoes fechadas, aguarde.')])
        r.quests.phase = 'done'; r.quests.validation = None
        r.quests.stop('done'); r.quests.phase = 'done'
        r.bg_tick(100.0*attempt)
        assert 'recusou' in r.quests.reason
        r.bg_tick(100.0*attempt+3.1)
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='^0000FFVoce entrou na fila 5x5!')])
    r.bg_tick(500.0)
    assert r.bg_attempt is None and not r.quests.active and 'Inscrito na BG 5x5' in r.quests.reason


def test_no_npc_answer_stops_without_sending_duplicate_registration(tmp_path):
    r = relay(tmp_path)
    record(r, '4x4')
    bg_entry.save_messages('', 'entrou na fila', 2)
    r.quest_control('quest_bg_enter', dict(mode='4x4'), lambda: True)
    r.quests.stop('Caminho bloqueado')  # a problem on the way, not the player
    r.bg_tick(10.0); r.bg_tick(12.5)
    assert r.bg_attempt['tries']['4x4'] == 1 and not r.quests.active
    with pytest.raises(ValueError,match='andamento'):
        r.quest_control('quest_bg_enter',dict(mode='4x4'),lambda:True)
    r.bg_tick(20.1)
    assert r.bg_attempt is None and 'sem resposta' in r.quests.reason
    r.quest_control('quest_stop', {}, lambda: True)
    r.bg_tick(20.0); r.bg_tick(30.0)
    assert r.bg_attempt is None and not r.quests.active


def test_local_polling_does_not_repeat_pending_request_and_response_wakes_it(tmp_path):
    r = relay(tmp_path)
    record(r, '3x3')
    bg_entry.save_messages('fechadas', 'entrou na fila', 2)
    r.quest_control('quest_bg_enter', dict(mode='3x3'), lambda: True)
    for i in range(100):
        r.bg_tick(100+i*.01)
    assert r.bg_attempt['tries']['3x3']==1 and r.quests.active
    assert r.bg_attempt['next_poll']>100.99
    # A second direct start is also refused while the existing route/dialogue runs.
    r.bg_try(101)
    assert r.bg_attempt['tries']['3x3']==1
    # A definitive success is processed without waiting out the configured retry interval.
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Voce entrou na fila!')])
    r.bg_tick(101)
    assert r.bg_attempt is None and 'Inscrito' in r.quests.reason


def test_fifty_ms_checks_keep_configured_network_retry_interval(tmp_path):
    r = relay(tmp_path)
    record(r, '5x5')
    bg_entry.save_messages('fechadas', 'entrou na fila', 2)
    r.quest_control('quest_bg_enter', dict(mode='5x5'), lambda: True)
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Inscricoes fechadas')])
    r.quests.stop('fim');r.quests.phase='done'
    r.bg_tick(100)
    assert r.bg_attempt['next_at']==102
    for i in range(1,40):r.bg_tick(100+i*.05)
    assert r.bg_attempt['tries']['5x5']==1
    r.bg_tick(102.06)
    assert r.bg_attempt['tries']['5x5']==2 and r.quests.active


@pytest.mark.parametrize('dialog_action,opcode,choice',[('close',0x146,None),('next',0x146,None),('menu',0xb8,255)])
def test_success_closes_only_dialog_and_never_selects_unregister(tmp_path,dialog_action,opcode,choice):
    r=relay(tmp_path);record(r,'3x3')
    bg_entry.save_messages('fechadas','entrou na fila',2)
    r.quest_control('quest_bg_enter',dict(mode='3x3'),lambda:True)
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,payload):self.packets.append(payload)
        async def drain(self):pass
    r.upstream=Writer()
    r.native_frames=SimpleNamespace(ready=True,fallback=lambda:{0x146:6,0xb8:7})
    r.bg_observe([dict(kind='npc_dialog',entity_id=9,text='Voce entrou na fila!')])
    r.quests.dialog=dict(entity_id=9,action=dialog_action,options=['Quero cancelar meu registro'])
    asyncio.run(r.close_bg_result_dialog(lambda:True))
    asyncio.run(r.close_bg_result_dialog(lambda:True))
    expected=struct.pack('<HI',opcode,9)+(bytes([choice]) if choice is not None else b'')
    assert r.upstream.packets==[expected]
    r.bg_tick(time.monotonic())
    assert r.bg_attempt is None and 'Inscrito' in r.quests.reason


def test_recording_success_schedules_close_but_unrelated_dialog_does_not(tmp_path):
    r=relay(tmp_path)
    bg_entry.save_messages('fechadas','entrou na fila',2)
    r.quest_control('quest_bg_record',dict(mode='3x3'),lambda:True)
    r.quests.recording['npc_id']=9
    r.bg_observe([dict(kind='npc_dialog',entity_id=10,text='Voce entrou na fila!')])
    assert not getattr(r,'bg_dialog_close',None)
    r.bg_observe([dict(kind='npc_dialog',entity_id=9,text='Inscricoes fechadas')])
    assert r.bg_dialog_close['result']=='error'
    r.bg_dialog_close=None
    r.bg_observe([dict(kind='npc_dialog',entity_id=9,text='Voce entrou na fila!')])
    assert r.bg_dialog_close['entity_id']==9
    assert r.quests.recording is not None  # user can still save the recording


def test_event_in_progress_closes_refusal_and_retries_without_finishing_route(tmp_path):
    r=relay(tmp_path);record(r,'3x3')
    bg_entry.save_messages('Ha um evento em andamento!','Registro feito com sucesso',2)
    r.quest_control('quest_bg_enter',dict(mode='3x3'),lambda:True)
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    r.upstream=Writer()
    r.native_frames=SimpleNamespace(ready=True,fallback=lambda:{0x146:6})
    r.bg_observe([dict(kind='npc_dialog',entity_id=9,text='Ha um evento em andamento!')])
    r.quests.dialog=dict(entity_id=9,action='close')
    assert r.quests.active
    asyncio.run(r.close_bg_result_dialog(lambda:True))
    assert r.upstream.packets==[struct.pack('<HI',0x146,9)]
    assert not r.quests.active and r.bg_attempt['refused'] and not r.bg_attempt['queued']
    r.bg_tick(100)
    assert r.bg_attempt['next_at']==102 and r.bg_attempt['tries']['3x3']==1
    r.bg_tick(102.1)
    assert r.quests.active and r.bg_attempt['tries']['3x3']==2


def test_only_the_error_message_set_means_registered_when_the_npc_answers_without_it(tmp_path):
    r = relay(tmp_path)
    record(r, '3x3')
    bg_entry.save_messages('fechadas', '', 2)
    r.quest_control('quest_bg_enter', dict(mode='3x3'), lambda: True)
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Bem-vindo a batalha!')])
    r.quests.stop('fim'); r.quests.phase = 'done'
    r.bg_tick(10.0)
    assert r.bg_attempt is None and 'Inscrito' in r.quests.reason


def test_old_file_with_messages_per_bg_is_read(tmp_path):
    import json
    path = tmp_path/'bg.json'
    path.write_text(json.dumps({'5x5': dict(steps=[dict(kind='npc', map='k', position=[1, 1])], target_map='k',
                                            recorded_at='x', success_text='inscrito')}), encoding='utf-8')
    assert set(bg_entry.load(path)) == {'5x5'} and bg_entry.messages(path)['queue'] == 'inscrito'


def test_bg_panel_buttons_follow_the_recording():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    panel = bg_entry.BgPanel()
    sent = []
    panel.command_requested.connect(lambda command, values: sent.append((command, values)))
    assert not any(b.isEnabled() for b in panel.enter_buttons.values()) and panel.record.isEnabled()
    panel.mode.setCurrentText('3x3'); panel.record.click()
    panel.update_state({'quests': {'recording_scope': 'bg', 'reason': 'Gravando'}})
    assert panel.save.isEnabled() and not panel.record.isEnabled()
    assert not panel.mode.isEnabled()
    panel.save.click(); panel.stop.click()
    assert sent == [('quest_bg_record', {'mode': '3x3'}), ('quest_bg_save', {}), ('quest_stop', {})]
    bg_entry.save_entry('4x4', dict(steps=[dict(kind='npc', map='k', position=[1, 1])], target_map='k', recorded_at='x'))
    bg_entry.save_entry('3x3', dict(steps=[dict(kind='npc', map='k', position=[2, 2])], target_map='k', recorded_at='x'))
    panel.update_state({'quests': {}})
    assert panel.mode.isEnabled()
    panel.queue.setEditText('entrou'); panel.store_messages()
    assert panel.enter_buttons['4x4'].isEnabled() and not panel.enter_buttons['5x5'].isEnabled()
    panel.enter_buttons['4x4'].click()
    assert sent[-1] == ('quest_bg_enter', {'mode': '4x4'})
    panel.queue.setEditText('entrou na fila'); panel.store_messages()
    assert bg_entry.messages()['queue'] == 'entrou na fila'
    panel.close()


def test_error_and_success_messages_are_recorded_from_the_npc(tmp_path):
    r = relay(tmp_path)
    r.quest_control('quest_bg_capture', dict(which='error'), lambda: True)
    assert 'fale com o NPC' in r.quests.reason
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='[Batalha Campal]'),
                  dict(kind='npc_dialog', entity_id=9, text='^FF0000As inscricoes estao fechadas.^000000')])
    assert bg_entry.messages()['error'] == 'As inscricoes estao fechadas.'
    assert r.bg_capture is None and r.quests.reason.startswith('Mensagem de erro gravada')
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Outra fala qualquer')])  # nothing asked: nothing saved
    r.quest_control('quest_bg_capture', dict(which='queue'), lambda: True)
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Voce entrou na fila da batalha!')])
    config = bg_entry.messages()
    assert config['queue'] == 'Voce entrou na fila da batalha!' and config['error'] == 'As inscricoes estao fechadas.'
    assert bg_entry.answer('^0000FFVoce entrou na fila da batalha!', config) == 'queue'
    with pytest.raises(ValueError):
        r.quest_control('quest_bg_capture', dict(which='outra'), lambda: True)



def test_tries_every_marked_bg_npc_in_turn_until_one_gets_in(tmp_path):
    r = relay(tmp_path)
    for mode in ('3x3', '4x4', '5x5'):
        record(r, mode)
    bg_entry.save_messages('fechadas', 'entrou na fila', 4)
    r.quest_control('quest_bg_enter', dict(modes=['3x3', '4x4', '5x5']), lambda: True)
    order = []
    for step in range(4):  # 3x3, 4x4, 5x5 refuse; then a full round waits 4 s
        order.append(r.quests.route['name'])
        r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Inscricoes fechadas')])
        r.quests.stop('fim'); r.quests.phase = 'done'
        r.bg_tick(100.0+10*step)
        wait = r.bg_attempt['next_at']-(100.0+10*step)
        assert wait == (4 if step % 3 == 2 else 1)
        r.bg_tick(100.0+10*step+wait+.1)
    assert order == ['BG 3x3', 'BG 4x4', 'BG 5x5', 'BG 3x3']
    assert r.quests.route['name'] == 'BG 4x4'
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Voce entrou na fila!')])
    r.bg_tick(200.0)
    assert r.bg_attempt is None and 'Inscrito na BG 4x4' in r.quests.reason  # stop all: default


def test_without_stop_all_each_bg_stops_only_when_its_own_registration_works(tmp_path):
    r = relay(tmp_path)
    for mode in ('3x3', '5x5'):
        record(r, mode)
    bg_entry.save_messages('fechadas', 'entrou na fila', 4)
    r.quest_control('quest_bg_enter', dict(modes=['3x3', '5x5'], stop_all=False), lambda: True)
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Voce entrou na fila!')])
    r.bg_tick(100.0)
    assert r.bg_attempt['pending'] == ['5x5'] and r.bg_attempt['registered'] == ['3x3']
    r.bg_tick(101.5)
    assert r.quests.route['name'] == 'BG 5x5'
    r.bg_observe([dict(kind='npc_dialog', entity_id=9, text='Voce entrou na fila!')])
    r.bg_tick(102.0)
    assert r.bg_attempt is None and 'Inscrito na BG 3x3, 5x5' in r.quests.reason
