import time

from nrobot import watchlist
from nrobot.session_relay import SessionRelay
from nrobot.packet_hunt import PacketHunt

OWN, OTHER = 2000001, 2000555


def relay(tmp_path):
    result = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    result.hunt = PacketHunt()
    result.hunt.start()
    result.tracker.observer.player_id = OWN
    result.tracker.observer.player = [10, 10]
    result.player_names[OTHER] = 'Observado'
    result.registry.players[str(OTHER)] = {'name': 'Observado'}
    return result


def test_disabled_observation_does_not_pause_or_alert_and_list_survives_restart(tmp_path, capsys):
    watchlist.save([str(OTHER)])
    watchlist.set_enabled(False)
    r = relay(tmp_path)
    r.presence.observe([dict(kind='appearance', entity_id=OTHER, species_id=25,
                             position=[11, 10], option=0)], OWN, time.monotonic(), own_position=[10, 10])
    r.check_emergency()
    r.announce_presence()
    r.observe_chat_alerts([dict(kind='actor_signal', signal='chat', entity_id=OTHER, name='Observado'),
                           dict(kind='chat_received', channel='private', name='Observado')])
    assert r.hunt.enabled and not r.commands_blocked and r.emergency is None
    assert r.chat_alert is None and r.presence.reason([10, 10], time.monotonic()) is None
    assert '[ALERTA]' not in capsys.readouterr().out
    assert watchlist.load() == [str(OTHER)]
    restarted = relay(tmp_path/'again')
    assert restarted.load_watchlist() == [] and not watchlist.enabled()


def test_reenabling_restores_stops_without_reentering_names(tmp_path):
    watchlist.save(['Observado'])
    watchlist.set_enabled(False)
    r = relay(tmp_path)
    r.presence.observe([dict(kind='appearance', entity_id=OTHER, species_id=25,
                             position=[11, 10], option=0)], OWN, time.monotonic(), own_position=[10, 10])
    r.check_emergency()
    assert r.hunt.enabled
    watchlist.set_enabled(True)
    r.check_emergency()
    assert not r.hunt.enabled and r.commands_blocked and r.emergency


def test_off_ignores_watched_hide_but_does_not_ignore_other_players(tmp_path):
    watchlist.save([str(OTHER)])
    watchlist.set_enabled(False)
    r = relay(tmp_path)
    r.presence.observe([dict(kind='option_change', entity_id=OTHER, option=0x40)], OWN, time.monotonic())
    r.check_emergency()
    assert r.emergency is None
    r.presence.observe([dict(kind='option_change', entity_id=OTHER+1, option=0x40)], OWN, time.monotonic())
    r.check_emergency()
    assert r.emergency and not r.hunt.enabled


def test_option_file_remains_local_and_update_protected():
    from nrobot.updater import is_protected
    assert is_protected('data/jogadores/observacao_opcoes.json')
