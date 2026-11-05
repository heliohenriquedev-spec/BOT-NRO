import copy

from nrobot import quest_progress
from nrobot.quest_routes import QuestRoutes
from nrobot.session_relay import SessionRelay


def route():
    return dict(id='persist', name='Missao persistente', target_map='field', kills=50, species=[1037],
                steps=[dict(kind='walk', map='field', position=[10, 10])])


def test_each_kill_is_saved_without_waiting_three_seconds_and_resumes(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.quests.start([route()], 0)
    relay.quests.phase = 'hunt'
    relay.quests.last_stage = ('hunt', 0)
    relay.save_progress(10)
    for number in (1, 2):
        relay.quests.kills = number
        relay.quests.kill_counts = {1037: number}
        relay.save_progress(10+number*.01)
        assert quest_progress.load()['kills'] == number
    restarted = QuestRoutes()
    restarted.resume_from([route()], quest_progress.load(), 20, map_name='field')
    assert restarted.kills == 2 and restarted.kill_counts == {1037: 2}
    assert restarted.phase == 'hunt'


def test_unchanged_progress_does_not_rewrite_disk(tmp_path, monkeypatch):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.quests.start([route()], 0)
    calls = []
    monkeypatch.setattr(quest_progress, 'save', lambda state: calls.append(copy.deepcopy(state)))
    relay.save_progress(10)
    relay.save_progress(10.02)
    assert len(calls) == 1


def test_failed_replace_keeps_previous_valid_checkpoint(tmp_path, monkeypatch):
    from nrobot import quest_daily
    state = dict(route_id='persist', kills=7)
    quest_progress.save(state)
    def refused(*args):
        raise OSError('simulated disk error')
    monkeypatch.setattr(quest_daily, 'replace', refused)
    import pytest
    with pytest.raises(OSError):
        quest_progress.save({**state, 'kills': 8})
    assert quest_progress.load()['kills'] == 7


def test_corrupt_primary_recovers_backup_and_finished_queue_clears_both():
    state = dict(route_id='persist', kills=7)
    quest_progress.save(state)
    quest_progress.save({**state, 'kills': 8})
    quest_progress.FILE.write_text('{interrupted', encoding='utf-8')
    assert quest_progress.load()['kills'] == 7
    quest_progress.clear()
    assert quest_progress.load() is None


def test_completion_removes_resume_checkpoint_but_keeps_history(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.quests.start([route()], 0)
    relay.quests.phase = 'hunt'
    relay.quests.kills = 50
    relay.save_progress(10)
    history = relay.progress_log_path().read_text(encoding='utf-8')
    assert '50/50' in history
    relay.quests.phase = 'done'
    relay.quest_stop('concluida')
    assert quest_progress.load() is None
    assert history in relay.progress_log_path().read_text(encoding='utf-8')


def test_progress_backup_is_protected_from_updates():
    from nrobot.updater import is_protected
    assert is_protected('data/rede/progresso_quests.json.bak')
