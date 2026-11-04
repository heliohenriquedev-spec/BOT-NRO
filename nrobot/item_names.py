"""Item names and descriptions from the client's own tables (idnum2itemdisplaynametable /
idnum2itemdesctable), read once in the background."""
import re
from functools import lru_cache

TYPES = {0: 'Cura', 2: 'Usavel', 3: 'Etc', 4: 'Arma', 5: 'Equipamento', 6: 'Carta', 7: 'Ovo de mascote',
         8: 'Acessorio de mascote', 10: 'Municao', 11: 'Usavel', 12: 'Equipamento sombrio'}
EQUIPPABLE = {4, 5, 8, 10, 12}
SLOTS = [(0x100, 'topo'), (0x200, 'meio'), (0x1, 'baixo'), (0x10, 'armadura'), (0x2, 'mao direita'), (0x20, 'mao esquerda'),
         (0x4, 'capa'), (0x40, 'sapatos'), (0x8, 'acessorio esq.'), (0x80, 'acessorio dir.'), (0x8000, 'municao'),
         (0x400, 'visual topo'), (0x800, 'visual meio'), (0x1000, 'visual baixo'), (0x2000, 'visual capa')]


MOUNT_SLOTS = 0x1 | 0x2 | 0x20  # baixo, mao direita, mao esquerda: what a mount takes


def is_mount(item, description=''):
    """Mounts say so in their description and take the three slots at once."""
    where = item.get('equip_location', 0)
    if item.get('type') == 10 or not where & MOUNT_SLOTS:
        return False
    return where & MOUNT_SLOTS == MOUNT_SLOTS or 'montaria' in description.casefold()


def combat_choices(items, descriptions):
    """What the mount takes off (baixo / mao direita / mao esquerda) and ammo (kunai, shuriken)."""
    return [i for i in items if i.get('type') == 10 or
            (i.get('equip_location', 0) & MOUNT_SLOTS and not is_mount(i, descriptions.get(i['item_id'], '')))]


def mount_choices(items, descriptions):
    return [i for i in items if is_mount(i, descriptions.get(i['item_id'], ''))]


def clean(text):
    text = re.sub(r'\^[0-9a-fA-F]{6}', '', text)
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip() and line.strip() != '_')


def parse_names(data):
    return {int(i): name.replace('_', ' ') for i, name in re.findall(r'^(\d+)#([^#\r\n]*)#', data, re.M)}


def parse_descriptions(data):
    return {int(i): clean(body) for i, body in re.findall(r'^(\d+)#\s*\n(.*?)^#', data, re.M | re.S)}


def summary(description):
    """The item's function, without weight/type/level lines."""
    skip = re.compile(r'^(peso|tipo|n[ií]vel|classe|equipa|slot|defesa|ataque|propriedade|refin|pode ser|jobs?)\b', re.I)
    lines = [line for line in description.splitlines() if not skip.match(line)]
    text = ' '.join(lines)
    return text[:160]+('…' if len(text) > 160 else '')


def slots(mask):
    return ', '.join(name for bit, name in SLOTS if mask & bit) or '—'


@lru_cache(maxsize=1)
def tables():
    """({id: name}, {id: description}); empty when the game folder is not readable."""
    from .character_sprite import read_file
    from .game_folder import saved
    from .grf import GrfSet
    folder = saved()
    if folder is None:
        return {}, {}
    grfs = GrfSet(str(folder))
    names = read_file(grfs, 'data\\idnum2itemdisplaynametable.txt') or b''
    descriptions = read_file(grfs, 'data\\idnum2itemdesctable.txt') or b''
    return parse_names(names.decode('cp1252', 'replace')), parse_descriptions(descriptions.decode('cp1252', 'replace'))
