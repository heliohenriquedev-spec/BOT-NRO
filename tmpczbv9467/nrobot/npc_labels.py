"""Human-readable NPC labels; wire text is retained separately for selection."""
import re
import unicodedata


def clean(value):
    value=re.sub(r'\^[0-9a-fA-F]{6}', '', str(value))
    value=re.sub(r'\^0{3,5}(?![0-9a-fA-F])','',value)
    return ' '.join(value.replace('\x00','').split())


def plain(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',clean(value).casefold()) if not unicodedata.combining(c))


def npc_name(value):
    return clean(value).split('#',1)[0].strip().casefold()


def rank(value):
    match=re.search(r'\brank\s*([A-Z]{1,3})(?:(?:\s*-\s*|\s+)(\d+))?\b',clean(value),re.I)
    return 'Rank '+match[1].upper()+('-'+match[2] if match[2] else '') if match else ''


def mission_option(value):
    normalized=plain(value)
    if not normalized or re.match(r'^#\s*\d+\s+',normalized) or re.match(r'^\d+\s+vazi[oa]\b',normalized):return False
    return normalized not in {'sim','nao','voltar','sair','cancelar','fechar','proximo','anterior','todos',
                              'aceitar uma missao','desistir de uma missao','aceitar missao','escolher outra',
                              'entregar uma missao','entregar missao','completar missao'}


def mission_label(m):
    from .monster_db import name_of
    label=clean(m['name']);r=clean(m.get('rank','')) or rank(label)
    if r and plain(r) not in plain(label):label+=' • '+r
    monsters=m.get('monster_names') or [name_of(i) for i in m.get('monster_ids',[])]
    return label+' • '+(', '.join(monsters) if monsters else 'monstros: nao informados')
