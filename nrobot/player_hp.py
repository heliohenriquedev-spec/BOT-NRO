"""Passive evidence of HP delivered by the server, never a request for hidden stats."""
import time
from datetime import datetime


class PlayerHp:
    LIMIT=512

    def __init__(self):
        self.rows={}

    def observe(self,events,map_name,now=None):
        now=time.monotonic() if now is None else now
        for event in events:
            if event['kind'] in ('map_change','map_transfer'):
                self.rows.clear()
                continue
            if event['kind']!='actor_hp_bar':continue
            from .network_targets import is_player_id
            identity=event.get('entity_id')
            if not is_player_id(identity):continue
            self.rows[identity]={**event,'at':now,'received_at':datetime.now().isoformat(timespec='seconds'),'map':map_name}
            if len(self.rows)>self.LIMIT:del self.rows[next(iter(self.rows))]

    def snapshot(self,own_id,records,own_affiliation,now=None,*,party_ids=()):
        now=time.monotonic() if now is None else now
        result=[]
        for identity,row in self.rows.items():
            other=records.get(str(identity),{})
            age=round(max(0,now-row['at']),2)
            result.append({**{k:v for k,v in row.items() if k!='at'},
                           'name':other.get('name') or row.get('name'),
                           'guild_received':other.get('guild'),'party_received':other.get('party'),
                           'own_guild_received':own_affiliation.get('guild'),
                           'own_party_received':own_affiliation.get('party'),
                           'party_member_received':identity in party_ids,
                           'guild_id_received':other.get('guild_id'),
                           'own_guild_id_received':own_affiliation.get('guild_id'),
                           'own':identity==own_id,'age_seconds':age,'recent':age<=10})
        return result
