"""New quest editor: missions already taken by another quest are identified."""
from nrobot import quest_panel


def test_missions_of_other_quests_are_listed_with_their_names_but_not_the_own(monkeypatch):
    routes = [dict(id='a', name='Esgoto 2', mission_ids=['m1', 'm2']), dict(id='b', name='Mamute', mission_ids=['m2'])]
    monkeypatch.setattr(quest_panel, 'load', lambda: routes)
    assert quest_panel.linked_missions() == {'m1': ['Esgoto 2'], 'm2': ['Esgoto 2', 'Mamute']}
    assert quest_panel.linked_missions(dict(id='a')) == {'m2': ['Mamute']}
