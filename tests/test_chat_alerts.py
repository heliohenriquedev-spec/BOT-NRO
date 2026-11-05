import struct

from nrobot.packet_reader import decode
from nrobot.session_relay import SessionRelay


def public_packet():
    body = b'Fulano : mensagem de teste\0'
    return struct.pack('<HHI', 0x8d, 8+len(body), 2000556)+body


def private_packet():
    body = b'mensagem privada de teste\0'
    return struct.pack('<HH24s', 0x97, 28+len(body), b'Ciclano')+body


def test_private_message_decodes_sender_without_retaining_contents():
    assert decode(private_packet()) == dict(opcode='0097', kind='chat_received', channel='private', name='Ciclano')


def test_public_or_private_message_triggers_for_watched_senders(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.load_watchlist = lambda: ['Fulano', 'Ciclano']
    relay.observe_chat_alerts([decode(public_packet()), decode(private_packet())])
    alert = relay.chat_alert
    assert alert['count'] == 2
    assert [entry['channel'] for entry in alert['detections']] == ['public', 'private']
    assert 'mensagem de teste' not in str(alert) and 'mensagem privada de teste' not in str(alert)
    relay.observe_chat_alerts([decode(private_packet())])
    assert relay.chat_alert['id'] != alert['id']  # same sender/message still emits another alert
    assert relay.emergency is None and not relay.commands_blocked


def test_unwatched_messages_and_empty_watchlist_do_not_alert(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    for entries in ([], ['Outra Pessoa'], ['9999999']):
        relay.load_watchlist = lambda: entries
        relay.observe_chat_alerts([decode(public_packet()), decode(private_packet())])
        assert relay.chat_alert is None


def test_watched_id_matches_public_id_and_private_registered_name(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.load_watchlist = lambda: ['2000556']
    relay.observe_chat_alerts([decode(public_packet())])
    assert relay.chat_alert['count'] == 1
    relay.chat_alert = None
    relay.observe_chat_alerts([decode(private_packet())])
    assert relay.chat_alert is None  # ID of an unknown whisper sender cannot be inferred
    relay.registry.players['2000556'] = {'name': 'Ciclano'}
    relay.observe_chat_alerts([decode(private_packet())])
    assert relay.chat_alert['detections'][0]['entity_id'] == 2000556


def test_public_message_can_use_registered_name_and_removing_watch_stops_new_alerts(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.load_watchlist = lambda: ['Fulano']
    relay.registry.players['2000556'] = {'name': 'Fulano'}
    relay.observe_chat_alerts([dict(kind='actor_signal', signal='chat', entity_id=2000556)])
    original = relay.chat_alert['id']
    relay.load_watchlist = lambda: []
    relay.observe_chat_alerts([decode(public_packet())])
    assert relay.chat_alert['id'] == original


def test_system_notices_emotes_and_whisper_delivery_ack_do_not_alert(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.observe_chat_alerts([dict(kind='server_text', text='status do jogo'),
                               dict(kind='actor_signal', signal='emote', entity_id=2000556),
                               decode(struct.pack('<HB', 0x98, 0))])
    assert relay.chat_alert is None


def test_received_private_alert_renders_without_actor_id():
    global app
    from PySide6.QtWidgets import QApplication
    from nrobot.watch_alert import WatchAlert
    app = QApplication.instance() or QApplication([])
    widget = WatchAlert()
    widget.show_alert([dict(name='Ciclano', entity_id=None, kind='chat', channel='private',
                            text='Mensagem recebida no privado')], chat=True)
    assert 'CHAT' in widget.title and '[PRIVADO]' in widget.lines[0][0]
    assert 'None' not in widget.lines[0][0]
    widget.close()
