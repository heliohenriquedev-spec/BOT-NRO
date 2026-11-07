"""Ally or enemy for the RCX filters, from server packets only.

- Battleground: the server gives each character's team (02DD). Only the own team is allied, and
  only on a battleground map (map type 01D6 received on entering it, or a bat_ map): players
  queued for a BG carry their team in town too (kakashi.gat, 2026-11-07).
- PvP map (map property 0199 with a PvP/WoE value, or a PvP ranking 019A, on the current map):
  allied are the configured group, the real party (00FB/0104/0105) and the same guild.
- Map without PvP: every player is allied, e.g. anyone's Sanctuary heals the character there.
- Monsters are enemies. A summon takes its owner's side: a creature the server creates (007C)
  up to 8 cells from a player in the 3 s after that player's summon skill.
The text NRO shows after the name in the party field (the rank, "RankB") never counts.
"""
from __future__ import annotations

from .network_targets import is_player_id

PVP_PROPERTIES = {1, 2, 3, 4, 5}  # free PvP, event PvP, WoE (agit), PK server, PvP server
SUMMON_WINDOW = 3.0
SUMMON_DISTANCE = 8


def cells(a, b):
    return max(abs(a[0]-b[0]), abs(a[1]-b[1]))


class Sides:
    def __init__(self):
        self.reset()

    def reset(self):
        """Another character: nothing carries over."""
        self.teams = {}  # character id -> battleground team, current map only
        self.own_team = None
        self.pvp = False
        self.bg_map = False  # map type packet (01D6) since the last map change: a battleground
        self.map_name = ''
        self.party = set()  # real party members (account ids), from the party packets
        self.guild = {}  # own guild_id / guild name
        self.owners = {}  # summon id -> owner id, current map only
        self.summon_casts = {}  # caster id -> (time, position) of its last summon skill

    def observe(self, events, own_id, now, summon_skills=(), position_of=lambda identity: None):
        """Returns True when an allied/enemy answer may have changed."""
        changed = False
        for event in events:
            kind = event['kind']
            identity = event.get('entity_id')
            if kind in ('map_change', 'map_transfer'):
                changed |= bool(self.teams or self.pvp or self.owners)
                self.teams.clear(); self.owners.clear(); self.summon_casts.clear()
                self.pvp = self.bg_map = False
            elif kind == 'bg_team':
                team = event.get('team') or None
                if own_id is not None and identity == own_id:
                    changed |= self.own_team != team
                    self.own_team = team
                elif identity is not None and self.teams.get(identity) != team:
                    if team is None:
                        self.teams.pop(identity, None)
                    else:
                        self.teams[identity] = team
                    changed = True
            elif kind == 'map_property':
                pvp = event.get('value') in PVP_PROPERTIES
                changed |= pvp != self.pvp
                self.pvp = pvp
            elif kind == 'map_type':
                changed |= not self.bg_map
                self.bg_map = True
            elif kind == 'pvp_rank':
                changed |= not self.pvp
                self.pvp = True
            elif kind == 'party_list':
                members = set(event.get('members') or ()) - {own_id}
                changed |= members != self.party
                self.party = members
            elif kind == 'party_join' and identity is not None and identity != own_id:
                changed |= identity not in self.party
                self.party.add(identity)
            elif kind == 'party_leave' and identity is not None:
                before = set(self.party)
                if identity == own_id:
                    self.party.clear()
                else:
                    self.party.discard(identity)
                changed |= before != self.party
            elif identity is not None and identity == own_id and kind in ('name', 'appearance'):
                details = {**(event.get('look') or {}), **event}
                for field in ('guild_id', 'guild'):
                    if field in details and self.guild.get(field) != details[field]:
                        self.guild[field] = details[field]
                        changed = True
            elif (kind in ('skill_cast', 'skill_no_damage') and event.get('skill_id') in summon_skills
                  and event.get('source_id') is not None and is_player_id(event['source_id'])):
                self.summon_casts[event['source_id']] = (now, position_of(event['source_id']))
            elif kind == 'appearance' and event.get('spawned') and identity is not None and not is_player_id(identity):
                position = event.get('position')
                near = [(cells(spot, position), caster) for caster, (at, spot) in self.summon_casts.items()
                        if now-at <= SUMMON_WINDOW and spot is not None and position is not None
                        and cells(spot, position) <= SUMMON_DISTANCE]
                if near and self.owners.get(identity) != min(near)[1]:
                    self.owners[identity] = min(near)[1]
                    changed = True
            elif kind == 'remove' and identity in self.owners and event.get('reason') != 0:
                del self.owners[identity]
                changed = True
        return changed

    @property
    def battleground(self):
        on_bg_map = self.bg_map or str(self.map_name or '').lower().startswith('bat_')
        return bool(on_bg_map and self.own_team and self.teams)

    def allied(self, source, own_id, records, group=(), own_summons=(), guild=None):
        if source in own_summons:
            return True
        owner = self.owners.get(source, source)
        if own_id is not None and owner == own_id:
            return True
        if self.battleground:
            team = self.teams.get(owner)
            return team == self.own_team or (team is None and owner in group)
        if not is_player_id(owner):
            return False  # a monster, or a summon whose owner is unknown
        if not self.pvp:
            return True
        if owner in group or owner in self.party:
            return True
        other = records.get(str(owner), {})
        mine = {**(guild or {}), **self.guild}
        if mine.get('guild_id') and other.get('guild_id') == mine['guild_id']:
            return True
        return bool(mine.get('guild')) and other.get('guild') == mine['guild']

    def describe(self):
        if self.battleground:
            return f'BG equipe {self.own_team}'
        return 'PvP' if self.pvp else 'sem PvP'
