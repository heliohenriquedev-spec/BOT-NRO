"""One immutable monster lookup snapshot per quest editor (no repeated disk scans)."""
from collections import defaultdict
from . import monster_db as db
from .npc_labels import plain
from .monster_origin import excluded_spawn


class QuestMonsterIndex:
    def __init__(self):
        self.names={};self.by_map=defaultdict(set);self.by_name=defaultdict(set)
        catalog=db.catalog();base=db.load_base();captured=db.load_captured()
        for identity,entry in catalog.items():
            self.names[identity]=entry.get('name') or str(identity)
            for m in entry.get('maps',[]):self.by_map[db.map_key(m)].add(identity)
        for records in (base,captured):
            for identity,entry in records.items():
                if entry.get('name'):self.names[identity]=entry['name']
                if not db.is_known_player(entry.get('name')):
                    for m in entry.get('maps',{}):self.by_map[db.map_key(m)].add(identity)
                for m,names in entry.get('names_by_map',{}).items():
                    for name in names:
                        if not excluded_spawn(identity,m,name):self.by_name[plain(name)].add(db.map_key(m))
        for m,ids in self.by_map.items():
            self.by_map[m]={i for i in ids if not excluded_spawn(i,m,self.names.get(i))}

    def species(self,map_name):return set(self.by_map.get(db.map_key(map_name),()))
    def name(self,identity):return self.names.get(identity,'Monstro '+str(identity))
    def maps(self,name):return self.by_name.get(plain(name or ''),set())
