import json

from nrobot import rcx_settings


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def test_publish_ships_this_pc_settings_once_and_marks_this_pc():
    write(rcx_settings.FILE, {'sides_version': 2, 'skill_styles': {'89': dict(show_enemies=True, fill='#123456')}})
    assert rcx_settings.export_shared(log=lambda *_: None)
    shipped = json.loads(rcx_settings.SHARED_FILE.read_text(encoding='utf-8'))
    assert shipped['id'] == rcx_settings.SHARED_ID and shipped['config']['skill_styles']['89']['fill'] == '#123456'
    assert rcx_settings.load()['shared_received'] == rcx_settings.SHARED_ID
    # Later edits here are not shipped again with the same SHARED_ID.
    write(rcx_settings.FILE, {'sides_version': 2, 'skill_styles': {'89': dict(show_enemies=True, fill='#654321')}})
    assert not rcx_settings.export_shared(log=lambda *_: None)
    assert json.loads(rcx_settings.SHARED_FILE.read_text(encoding='utf-8'))['config']['skill_styles']['89']['fill'] == '#123456'


def test_user_receives_the_shipped_settings_once_then_keeps_own_edits():
    write(rcx_settings.SHARED_FILE, {'id': 1, 'config': {'sides_version': 2, 'skill_styles': {'89': dict(show_enemies=True, fill='#123456')}}})
    write(rcx_settings.FILE, {'sides_version': 2, 'skill_styles': {'85': dict(show_allies=True)}})
    value = rcx_settings.load()
    assert value['skill_styles']['89']['fill'] == '#123456' and '85' not in value['skill_styles']
    assert rcx_settings.FILE.with_name(rcx_settings.FILE.name+'.antes_envio_1').exists()
    value['skill_styles']['89']['fill'] = '#abcdef'
    rcx_settings.save(value)
    assert rcx_settings.load()['skill_styles']['89']['fill'] == '#abcdef'


def test_new_user_without_settings_receives_them():
    write(rcx_settings.SHARED_FILE, {'id': 1, 'config': {'sides_version': 2, 'skill_styles': {'89': dict(show_enemies=True)}}})
    value = rcx_settings.load()
    assert value['skill_styles']['89']['show_enemies'] and value['shared_received'] == 1
