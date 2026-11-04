"""@mi <ID>: the server's own monster information (drops with their rates) for the drop database.

Floor packets never say which monster dropped an item and rare drops may never be seen, so the
bot asks the server once per species with the same chat command the player would type. Only the
lines that arrive right after the command are read; ordinary chat is never kept."""
import re
import struct
import time

BASE62 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
DROP = re.compile(r'-\s*(.+?)\s+(\d{1,3}(?:[.,]\d+)?)\s*%')
LINK = re.compile(r'<ITEML?>[0-9A-Za-z]{5}[01]([0-9A-Za-z]+)[^<]*</ITEML?>')


def base62(text):
    value = 0
    for char in text:
        value = value*62+BASE62.index(char)
    return value


def chat_command(text, name, learned_hex=''):
    """00F3 frame "Name : text", in the same shape as the @voltar the player typed (when learned)."""
    body = (name.encode('cp1252', 'replace')+b' : ' if name else b'')+text.encode('cp1252', 'replace')+b'\0'
    opcode = struct.unpack_from('<H', bytes.fromhex(learned_hex))[0] if learned_hex else 0xf3
    return struct.pack('<HH', opcode, 4+len(body))+body


def item_identity(label):
    """Item ID from an item link (<ITEML>), "(909)"/":909" next to the name, or the client's names."""
    link = LINK.search(label)
    if link:
        return base62(link.group(1)), None
    number = re.search(r'(?:\(|:|#)\s*(\d{3,6})\s*\)?\s*$', label)
    clean = re.sub(r'\s*\[\d+\]\s*$', '', re.sub(r'(?:\(|:|#)\s*\d{3,6}\s*\)?\s*$', '', label)).strip()
    clean = re.sub(r'^\+\d+\s+', '', clean)
    if number:
        return int(number.group(1)), clean
    from .drop_db import item_names
    folded = clean.casefold()
    for identity, name in item_names().items():
        if name.casefold() == folded:
            return identity, clean
    return 0, clean


def parse(species, lines):
    """{'name', 'drops': [...], 'mvp': [...]} or None when the lines are not a monster sheet."""
    name, drops, mvp, header, section = '', [], [], False, None
    for line in lines:
        if not header:
            match = re.search(r"'([^']+)'.*\(\s*%d\s*\)" % species, line) or (
                re.match(r'\s*(?:Monster|Monstro)\s*:', line, re.I) and re.search(r"'([^']+)'", line))
            if match:
                header, name = True, match.group(1)
            continue
        if re.search(r'MVP', line, re.I):
            if re.search(r'ite[mn]|pr[eê]mi|prize|drop', line, re.I):
                section = 'mvp'
            if not DROP.search(line):
                continue
        elif re.match(r'\s*(?:Drops?|Itens?)\s*:?\s*$', line, re.I):
            section = 'drops'
            continue
        for label, rate in DROP.findall(line):
            identity, plain = item_identity(label.strip())
            from .drop_db import item_names
            entry = dict(item_id=identity, item_name=plain or item_names().get(identity, f'Item {identity}'),
                         rate=float(rate.replace(',', '.')))
            (mvp if section == 'mvp' else drops).append(entry)
    return dict(name=name, drops=drops, mvp=mvp) if header else None


class MobInfoQueue:
    INTERVAL = 4.0    # between two commands, never a burst in the chat
    QUIET = 1.2       # the sheet is complete after this long without new lines
    TIMEOUT = 4.0     # no answer at all
    MAX_FAILURES = 2  # then automatic queries stop for this session

    def __init__(self, known=()):
        self.known = set(known)  # species already in the database
        self.queue = []
        self.waiting = None      # {'species', 'sent_at', 'last_line', 'lines'}
        self.next_at = 0.0
        self.failures = 0
        self.suspended = False
        self.results = []        # (species, parsed or None, lines) finished, for the relay to store

    def want(self, species, force=False):
        if not species or species in self.queue or (self.waiting and self.waiting['species'] == species):
            return False
        if not force and (species in self.known or self.suspended):
            return False
        if force:
            self.suspended = False
            self.queue.insert(0, species)
        else:
            self.queue.append(species)
        return True

    def due(self, now):
        """Species to ask now, or None."""
        if self.waiting or not self.queue or now < self.next_at:
            return None
        return self.queue[0]

    def sent(self, species, now):
        self.queue.remove(species)
        self.waiting = dict(species=species, sent_at=now, last_line=None, lines=[])
        self.next_at = now+self.INTERVAL
        from . import packet_reader
        packet_reader.SERVER_TEXT_UNTIL = time.monotonic()+self.TIMEOUT

    def observe(self, events, now):
        w = self.waiting
        if w is None:
            return
        for event in events:
            if event['kind'] in ('server_text', 'server_notice', 'combat_notice') and event.get('text'):
                w['lines'].append(event['text']); w['last_line'] = now
        quiet = w['last_line'] is not None and now-w['last_line'] >= self.QUIET
        if quiet or now-w['sent_at'] >= self.TIMEOUT:
            self.finish(now)

    def finish(self, now):
        w, self.waiting = self.waiting, None
        from . import packet_reader
        packet_reader.SERVER_TEXT_UNTIL = 0.0
        info = parse(w['species'], w['lines'])
        if info is None:
            # refused, no answer or a sheet in an unknown format: never repeated in a loop
            self.failures += 1
            if self.failures >= self.MAX_FAILURES:
                self.suspended = True
                self.queue.clear()
        elif info is not None:
            self.failures = 0
            self.known.add(w['species'])
        self.results.append((w['species'], info, w['lines']))
