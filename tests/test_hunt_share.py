import json
from nrobot import hunt_share, shared_data
from nrobot.packet_settings import DEFAULTS


def test_published_patrol_is_exported_and_laid_over_every_hunt(tmp_path):
    dev=tmp_path/'dev'
    (dev/'data'/'rede').mkdir(parents=True)
    panel=dict(DEFAULTS,patrol_spacing=20,patrol_coverage=70,ignore_attackers=3,kite=True,melee_approach=False)
    (dev/'data'/'rede'/'painel_config.json').write_text(json.dumps(panel),encoding='utf-8')
    (dev/'data'/'rede'/'showmobs_monstros.json').write_text('[1634]',encoding='utf-8')
    shared_data.export(log=lambda m:None,root=dev)
    published=json.loads((dev/'data'/'compartilhado'/'caca_patrulha.json').read_text(encoding='utf-8'))
    assert published['settings']['patrol_spacing']==20 and 'kite' not in published['settings']
    assert not (dev/'data'/'rede'/'caca_patrulha.json').exists()  # the developer's panel stays the source

    user=tmp_path/'user'
    (user/'data'/'rede').mkdir(parents=True)
    (user/'data'/'rede'/'showmobs_monstros.json').write_text('[1002]',encoding='utf-8')
    import shutil
    shutil.copytree(dev/'data'/'compartilhado',user/'data'/'compartilhado')
    assert shared_data.merge(root=user,log=lambda m:None)
    assert json.loads((user/'data'/'rede'/'showmobs_monstros.json').read_text(encoding='utf-8'))==[1002,1634]
    received=user/'data'/'rede'/'caca_patrulha.json'
    mine=dict(DEFAULTS,patrol_spacing=8,patrol_coverage=100,kite=False)
    result=hunt_share.apply(mine,received)
    assert result['patrol_spacing']==20 and result['patrol_coverage']==70 and result['ignore_attackers']==3
    assert result['kite'] is False  # combat stays the character's own


def test_no_published_patrol_keeps_settings(tmp_path):
    mine=dict(DEFAULTS,patrol_spacing=8)
    assert hunt_share.apply(mine,tmp_path/'none.json')==mine
