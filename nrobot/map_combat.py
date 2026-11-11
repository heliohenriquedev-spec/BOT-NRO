"""Packet-confirmed control and kill priorities for declarative map combat."""
import copy
import math

SKILLS = {'stun', 'sleep', 'silence', 'offensives', 'buffs'}

def validate(data):
    if not isinstance(data, dict) or set(data)-{'kill_priority', 'control_species', 'passive_species', 'control_radius', 'skills', 'emergency', 'engagement', 'idle_summon', 'offensive_species', 'burst', 'area_sleep', 'focus', 'control_limit'} or not {'kill_priority','control_species','passive_species','control_radius','skills'} <= set(data):
        raise ValueError('Estrutura combat invalida')
    for key in ('kill_priority', 'control_species', 'passive_species'):
        rows = data[key]
        if not isinstance(rows, list) or not rows and key!='passive_species' or len(rows)>32 or any(not isinstance(r,dict) or set(r)!={'species_id','name'} or type(r['species_id']) is not int or not 1<=r['species_id']<=65535 or not isinstance(r['name'],str) or not 1<=len(r['name'])<=100 for r in rows):
            raise ValueError('Lista de monstros invalida: '+key)
        if len({r['species_id'] for r in rows}) != len(rows):
            raise ValueError('Monstro duplicado: '+key)
    species={r['species_id'] for r in data['kill_priority']}
    if any(r['species_id'] not in species for k in ('control_species','passive_species') for r in data[k]):
        raise ValueError('Monstros controlados devem estar na prioridade de morte')
    if type(data['control_radius']) is not int or not 1<=data['control_radius']<=15:
        raise ValueError('Raio de controle invalido')
    skills=data['skills']
    if not isinstance(skills,dict) or set(skills)!=SKILLS:
        raise ValueError('Habilidades de combate invalidas')
    all_ids=[]
    for key in SKILLS:
        rows=skills[key] if key in ('offensives','buffs') else [skills[key]]
        if not isinstance(rows,list) or not (0 if key=='buffs' else 1)<=len(rows)<=16:
            raise ValueError('Lista de habilidades invalida')
        for row in rows:
            expected={'skill_id','name','effect_id'} if key=='buffs' else {'skill_id','name'}
            allowed=expected|({'duration','only_when_clear_radius'} if key=='buffs' else set())
            if (not isinstance(row,dict) or not expected<=set(row) or set(row)-allowed or type(row['skill_id']) is not int
                or not 1<=row['skill_id']<=65535 or not isinstance(row['name'],str) or not 1<=len(row['name'])<=100):
                raise ValueError('Habilidade invalida: '+key)
            if key=='buffs' and (type(row['effect_id']) is not int or not 0<=row['effect_id']<=65535):
                raise ValueError('Efeito de buff invalido')
            if key=='buffs' and 'duration' in row and (type(row['duration']) not in (int,float) or not math.isfinite(row['duration']) or not 1<=row['duration']<=86400):
                raise ValueError('Duracao de buff invalida')
            if key=='buffs' and 'only_when_clear_radius' in row and (type(row['only_when_clear_radius']) is not int or not 1<=row['only_when_clear_radius']<=30):
                raise ValueError('Raio livre do buff invalido')
            all_ids.append(row['skill_id'])
    if len(set(all_ids))!=len(all_ids):
        raise ValueError('Habilidade duplicada no comportamento')
    # 'emergency' (Coelho x3, Fukai Kemuri and escape) was removed: never confirmed by the server and
    # it left the character without hitting. Older profiles still load; the block is ignored.
    if 'engagement' in data:
        rule=data['engagement']
        expected={'radius','only_targeting_player','target_memory_seconds','no_basic_attack_species','no_chase_species'}
        if (not isinstance(rule,dict) or set(rule)-(expected|{'seek_when_clear','proactive_species','approach_species'}) or not expected<=set(rule)
            or type(rule['only_targeting_player']) is not bool or type(rule.get('seek_when_clear',False)) is not bool):
            raise ValueError('Regra de proximidade/alvo invalida')
        for key,low,high in [('radius',1,15),('target_memory_seconds',1,60)]:
            if type(rule[key]) is not int or not low<=rule[key]<=high:
                raise ValueError('Regra de proximidade: '+key+' invalido')
        for key in ('no_basic_attack_species','no_chase_species','proactive_species','approach_species'):
            if not isinstance(rule.get(key,[]),list) or any(type(i) is not int or i not in species for i in rule.get(key,[])):
                raise ValueError('Excecao de monstro invalida')
    if 'idle_summon' in data:
        rule=data['idle_summon']
        if (not isinstance(rule,dict) or set(rule)-{'skill_id','name','clear_radius','cooldown','hp_below_percent',
                                                     'combat_below_percent','recover_below_percent','recover_until_percent'} or not {'skill_id','name','clear_radius','cooldown'}<=set(rule)
            or type(rule['skill_id']) is not int or not 1<=rule['skill_id']<=65535
            or rule['skill_id'] in all_ids or not isinstance(rule['name'],str) or not 1<=len(rule['name'])<=100
            or type(rule['clear_radius']) is not int or not 1<=rule['clear_radius']<=30
            or type(rule['cooldown']) not in (int,float) or not math.isfinite(rule['cooldown']) or not .1<=rule['cooldown']<=86400):
            raise ValueError('Invocacao fora de combate invalida')
        for key in ('hp_below_percent','combat_below_percent','recover_below_percent','recover_until_percent'):
            if key in rule and (type(rule[key]) is not int or not 1<=rule[key]<=100):
                raise ValueError('Limite de HP da invocacao invalido')
        if ('recover_below_percent' in rule)!=('recover_until_percent' in rule) or rule.get('recover_below_percent',0)>=rule.get('recover_until_percent',101):
            raise ValueError('Recuperacao de HP invalida: informe recover_below_percent menor que recover_until_percent')
    if 'offensive_species' in data:
        rules=data['offensive_species'];offensive_ids={str(r['skill_id']) for r in data['skills']['offensives']}
        if (not isinstance(rules,dict) or any(key not in offensive_ids or not isinstance(rows,list) or not rows
            or any(type(i) is not int or i not in species for i in rows) for key,rows in rules.items())):
            raise ValueError('Restricao de habilidade por monstro invalida')
    if 'burst' in data:
        rule=data['burst']
        if (not isinstance(rule,dict) or set(rule)!={'enabled','interval'} or type(rule['enabled']) is not bool
            or type(rule['interval']) not in (int,float) or not math.isfinite(rule['interval']) or not .05<=rule['interval']<=1):
            raise ValueError('Configuracao de rajada invalida')
    if 'area_sleep' in data:
        from .map_area_sleep import validate as area_validate
        area=area_validate(data['area_sleep'])
        if {area['prepare_skill']['skill_id'],area['area_skill']['skill_id']}&set(all_ids):
            raise ValueError('Habilidades do sono em area nao podem estar na rotacao')
    if 'control_limit' in data:
        rule=data['control_limit']
        if (not isinstance(rule,dict) or set(rule)!={'give_up_seconds','release_seconds'}
            or any(type(rule[k]) not in (int,float) or not math.isfinite(rule[k]) or not 1<=rule[k]<=120 for k in rule)):
            raise ValueError('Limite de controle invalido')
    if 'focus' in data:
        rule=data['focus']
        if (not isinstance(rule,dict) or not {'lowest_hp'}<=set(rule)<={'lowest_hp','melee','last_species','buffs_during_control','hazard_throws','silence_range','silence_only_species'}
            or any(type(v) is not bool for k,v in rule.items() if k not in ('last_species','silence_range','silence_only_species'))
            or 'silence_range' in rule and (type(rule['silence_range']) is not int or not 1<=rule['silence_range']<=9)
            or any(not isinstance(rule.get(k,[]),list) or any(type(i) is not int or i not in species for i in rule.get(k,[]))
                   for k in ('last_species','silence_only_species'))):
            raise ValueError('Regra de foco invalida')
    return copy.deepcopy(data)

# The map behavior's combat replaces the ordinary one: these tuning values of the ordinary combat
# (Combate tab) are not carried into a map with its own combat; the defaults are used instead.
ORDINARY_COMBAT_KEYS=('skill_interval','skill_timeout','skill_attempts','target_defer','skill_global_delay',
                      'limit_target_failures','defer_failed_targets','pvp_enabled','pvp_all','pvp_first','pvp_targets',
                      'summon_queue_mode')


def settings_for(config, base, learned):
    from .packet_settings import DEFAULTS
    result=copy.deepcopy(base)
    for key in ORDINARY_COMBAT_KEYS:
        result[key]=copy.deepcopy(DEFAULTS[key])
    previous={p['skill_id']:p for p in base.get('skill_profiles',[])}
    known={s['skill_id']:s for s in learned if s.get('level',0)>0}
    profiles=[]
    for key,rows in config['skills'].items():
        rows=rows if isinstance(rows,list) else [rows]
        for row in rows:
            identity=row['skill_id']
            if identity not in known:
                continue
            role='buff' if key=='buffs' else 'offensive'
            old=previous.get(identity,{})
            p=dict(skill_id=identity,enabled=True,role=role,level=known[identity]['level'],
                   interval=.5,effect_id=row.get('effect_id',0))
            if key=='buffs' and 'duration' in row:p['effect_duration']=row['duration']
            if key=='buffs' and 'only_when_clear_radius' in row:p['only_when_clear_radius']=row['only_when_clear_radius']
            # Respect the character's explicit range customizations.
            if 'range_override' in old:p['range_override']=old['range_override']
            profiles.append(p)
    idle=config.get('idle_summon')
    if idle and idle['skill_id'] in known:
        identity=idle['skill_id']
        old=previous.get(identity,{})
        p=dict(skill_id=identity,enabled=True,role='summon',level=known[identity]['level'],
               interval=idle['cooldown'],effect_id=old.get('effect_id',0),
               summon_duration=old.get('summon_duration',0),summon_priority=0)
        if 'range_override' in old:p['range_override']=old['range_override']
        profiles.append(p)
    result.update(species=[r['species_id'] for r in config['kill_priority']],auto_map_targets=False,
                  monster_name_choices={},skills=True,advanced_combat=True,auto_attacks=True,
                  fast_offensives=True,skill_burst=False,skill_profiles=profiles,
                  skill_priority=[r['skill_id'] for r in config['skills']['offensives']])
    if 'burst' in config:
        result.update(skill_burst=config['burst']['enabled'],skill_burst_interval=config['burst']['interval'])
    return result

class MapCombat:
    SILENCE_RANGE=3  # approach before casting; do not chase the advertised outer range
    PASSIVE_SILENCE_WAIT=2.0  # s a passive monster waits for the silence before being attacked anyway
    CONFIRM_WAIT=.15
    AREA_MODE_SECONDS=20.0  # after a Fukai Kemuri: silence only the monsters attacking the player
    ATTACKER_MEMORY=5.0  # s an attack/cast on the player keeps a monster an "attacker"
    def __init__(self,config):
        self.config=validate(config)
        self.ranks={r['species_id']:i for i,r in enumerate(config['kill_priority'])}
        # silence_only_species: silenced before being killed, nothing else (no stun/sleep, not kept
        # asleep, not counted for the Kemuri): the passive Anbu.
        self.silence_only=set(self.config.get('focus',{}).get('silence_only_species',[]))
        self.controllers={r['species_id'] for r in config['control_species']}|self.silence_only
        self.passive={r['species_id'] for r in config['passive_species']}
        self.history={}
        self.attacked=set()
        self.passive_wait={}  # passive monster -> when the silence wait started
        self.targeting={}
        self.control_skill_ids={self.config['skills'][key]['skill_id'] for key in ('stun','sleep','silence')}
        self.pull_id=None
        self.control_started={}  # monster -> first control attempt (control_limit)
        self.recovering=False  # idle_summon recover_*: very low HP, sitting and summoning until it is back
        self.reason='aguardando combate'
        self.hp_seen={}  # monster -> (hp, max hp) from the server's "HP: x/y" name answer
        self.damage={}  # monster -> damage observed since that answer
        from .map_area_sleep import AreaSleep
        self.area=AreaSleep(self.config['area_sleep']) if self.config.get('area_sleep') else None

    def observe(self,events,player_id,now):
        if self.area:self.area.observe(events,player_id,now)
        for e in events:
            if e['kind'] in ('map_change','map_transfer'):
                self.history.clear();self.passive_wait.clear();self.attacked.clear();self.targeting.clear();self.pull_id=None
                self.control_started.clear()
                self.hp_seen.clear();self.damage.clear()
            elif e['kind']=='remove':
                self.attacked.discard(e['entity_id']);self.history.pop(e['entity_id'],None);self.passive_wait.pop(e['entity_id'],None);self.targeting.pop(e['entity_id'],None)
                self.hp_seen.pop(e['entity_id'],None);self.damage.pop(e['entity_id'],None);self.control_started.pop(e['entity_id'],None)
                if self.pull_id==e['entity_id']:self.pull_id=None
            elif e['kind']=='name' and type(e.get('hp')) is int and type(e.get('max_hp')) is int and e['max_hp']>0:
                self.hp_seen[e['entity_id']]=(e['hp'],e['max_hp']);self.damage[e['entity_id']]=0
            if e['kind'] in ('normal_attack','skill_damage') and e.get('target_id') not in (None,0,player_id):
                # 01DE carries -30000 (4294937296) for status-only skills such as Fukai Kemuri.
                amount=e.get('damage_raw')
                if type(amount) is int and 0<amount<2**31:
                    self.damage[e['target_id']]=self.damage.get(e['target_id'],0)+amount
            if e['kind'] in ('normal_attack','skill_damage','skill_cast'):
                source=e.get('source_id')
                if (source is not None and player_id is not None and source!=player_id
                    and e.get('target_id') not in (None,0,source)):
                    self.targeting[source]=(e.get('target_id'),now)
                if (e['kind']!='skill_cast' and source==player_id
                    and not (e['kind']=='skill_damage' and e.get('skill_id') in self.control_skill_ids)):
                    self.attacked.add(e.get('target_id'))
                    if e.get('target_id') not in (None,0,player_id):self.pull_id=e['target_id']

    def sent(self,action,now):
        if action.get('area_sleep_stage'):
            if self.area:self.area.sent(action,now)
            return  # a seal on the player: no monster was controlled or hit
        if action.get('control_status'):
            self.history.setdefault(action['target_id'],{})[action['control_status']]=now
        elif action.get('role')=='offensive':
            self.attacked.add(action.get('combat_target_id',action['target_id']))

    @staticmethod
    def statuses(entity):
        return dict(stun=entity.get('body_state')==3,sleep=entity.get('body_state')==4,
                    silence=bool(entity.get('health_state',0)&4))

    @staticmethod
    def distance(state,entity):
        own=state.get('combat_player_positions') or [state['player_position']]
        positions=entity.get('attack_positions') or [entity.get('effective_position',entity['position'])]
        return max(math.dist(a,b) for a in own for b in positions)

    def hp_fraction(self,entity):
        """Remaining HP (0..1): the server's last "HP: x/y" answer, else the species' known maximum,
        minus the damage seen since. Without either, more damage seen ranks as lower HP."""
        identity=entity['entity_id']
        damage=self.damage.get(identity,0)
        hp,maximum=self.hp_seen.get(identity,(entity.get('species_max_hp'),entity.get('species_max_hp')))
        if type(maximum) is int and maximum>0:
            return max(0.0,(hp-damage)/maximum)
        return 1.0-min(damage,10**12)/10**12

    THROWS=(523,524)

    def target_on_hazard(self,identity,state):
        """focus.hazard_throws: the target stands on an enemy area skill (cells received from the server)."""
        if not self.config.get('focus',{}).get('hazard_throws') or identity is None:return False
        cells={tuple(c) for c in state.get('ground_hazard_cells') or ()}
        if not cells:return False
        entity=next((e for e in state.get('recent_entities',[]) if e.get('entity_id')==identity),None)
        if entity is None:return False
        points=entity.get('attack_positions') or [entity.get('effective_position',entity['position'])]
        return any(tuple(round(v) for v in p) in cells for p in points)

    def throw_range(self,state):
        ranges=[s.get('range',0) for s in state.get('learned_skills',[]) if s['skill_id'] in self.THROWS and s.get('level',0)>0]
        return max(1,max(ranges)-1) if ranges else None

    def offensive_allowed(self,skill_id,species):
        allowed=self.config.get('offensive_species',{}).get(str(skill_id))
        return allowed is None or species in allowed

    def no_chase(self,species):
        return species in self.config.get('engagement',{}).get('no_chase_species',[])

    def approach_nearby(self,entity,state):
        rule=self.config.get('engagement',{})
        return (entity is not None and entity.get('species_id') in rule.get('approach_species',[])
                and self.distance(state,entity)<=rule.get('radius',0))

    def basic_allowed(self,identity,state):
        entity=next((e for e in state.get('recent_entities',[]) if e['entity_id']==identity),None)
        return bool(entity and entity.get('species_id') not in self.config.get('engagement',{}).get('no_basic_attack_species',[]))

    def candidates(self,state,rotation,now):
        from .combat_rotation import configured_range
        rule=self.config.get('engagement')
        result=[];seek=[]
        known={s['skill_id']:s for s in state.get('learned_skills',[])}
        offensive_ids={s['skill_id'] for s in self.config['skills']['offensives']}
        for entity in state.get('recent_entities',[]):
            if entity.get('kind','monster')!='monster' or entity.get('species_id') not in self.ranks:continue
            distance=self.distance(state,entity)
            limited_approach=entity['species_id'] in (rule or {}).get('approach_species',[])
            if limited_approach and distance>(rule or {}).get('radius',0):continue
            if self.no_chase(entity['species_id']):
                allow_near_approach=limited_approach and distance<=(rule or {}).get('radius',0)
                usable=False
                for profile in rotation.profiles:
                    meta=known.get(profile['skill_id'])
                    if not profile['enabled'] or profile['role']!='offensive' or profile['skill_id'] not in offensive_ids or not self.offensive_allowed(profile['skill_id'],entity['species_id']) or meta is None:continue
                    if (state.get('player_sp') or 0)<meta['sp_cost']:continue
                    if not allow_near_approach and distance>configured_range(profile,meta)-rotation.range_margin:continue
                    if profile['skill_id'] in rotation.THROWS and state.get('ammo') is not None:
                        options=state['ammo'].get('options',{})
                        if not options.get(profile['skill_id'],options.get(str(profile['skill_id']))):continue
                    usable=True;break
                if not usable:continue
            if not rule:
                result.append(entity);continue
            target,at=self.targeting.get(entity['entity_id'],(None,-1000))
            recent=now-at<=rule['target_memory_seconds']
            targeting_us=recent and target==state.get('player_id')
            targeting_other=recent and target not in (None,state.get('player_id'))
            proactive=entity['species_id'] in rule.get('proactive_species',[]) and not targeting_other
            committed=entity['entity_id']==self.pull_id and not targeting_other
            # Put to sleep, stunned or silenced by us, or already hit: still ours to kill. A controlled
            # monster stops targeting the player, so it fell out of the candidates and was never hit.
            engaged=entity['entity_id'] in self.history or entity['entity_id'] in self.attacked
            if distance<=rule['radius'] and (not rule['only_targeting_player'] or targeting_us or proactive or committed or engaged
                                              or entity['species_id'] in rule.get('approach_species',[])):
                result.append(entity)
            elif rule.get('seek_when_clear') and not self.no_chase(entity['species_id']) and not targeting_other:
                seek.append(entity)
        if result or not rule or not rule.get('seek_when_clear'):
            ranged_attackers=[e for e in seek if self.targeting.get(e['entity_id'],(None,-1000))[0]==state.get('player_id')
                             and now-self.targeting[e['entity_id']][1]<=rule['target_memory_seconds']]
            return result+ranged_attackers
        # Do not cross a pack at our feet just to acquire a distant monster.
        visible=state.get('visible_monsters',state.get('recent_entities',[]))
        if any(e.get('kind','monster')=='monster' and self.distance(state,e)<=rule['radius'] for e in visible):
            return [e for e in seek if self.targeting.get(e['entity_id'],(None,-1000))[0]==state.get('player_id')
                    and now-self.targeting[e['entity_id']][1]<=rule['target_memory_seconds']]
        return seek

    def hp_percent(self,state):
        hp,maximum=state.get('player_hp'),state.get('player_max_hp')
        if type(hp) is not int or type(maximum) is not int or maximum<=0 or not 0<hp<=maximum:return None
        return 100*hp/maximum

    def update_recovery(self,state):
        """Enter below recover_below_percent, leave at recover_until_percent (server-reported HP only)."""
        idle=self.config.get('idle_summon') or {}
        if 'recover_below_percent' not in idle:
            self.recovering=False;return False
        percent=self.hp_percent(state)
        if percent is not None:
            if percent<idle['recover_below_percent']:self.recovering=True
            elif percent>=idle['recover_until_percent']:self.recovering=False
        return self.recovering

    def summon_urgent(self,state):
        """Low HP: the summon goes before damage even with monsters around."""
        idle=self.config.get('idle_summon') or {}
        percent=self.hp_percent(state)
        return self.recovering or ('combat_below_percent' in idle and percent is not None and percent<idle['combat_below_percent'])

    def summon_plan(self,state,rotation,now):
        idle=self.config.get('idle_summon')
        original=rotation.profiles
        rotation.profiles=[p for p in original if p['role']=='summon' and p['skill_id']==idle['skill_id']]
        try:return rotation.plan(self.idle_state(state),now,None) if rotation.profiles else None
        finally:rotation.profiles=original

    def idle_clear(self,state):
        idle=self.config.get('idle_summon')
        if not idle or state.get('player_position') is None:return False
        if self.summon_urgent(state):return True
        limit=idle.get('hp_below_percent')
        if limit is not None:
            hp,maximum=state.get('player_hp'),state.get('player_max_hp')
            if type(hp) is not int or type(maximum) is not int or maximum<=0 or not 0<hp<=maximum or hp*100>=maximum*limit:return False
        # Includes unselected and passive monsters; own summons are excluded by the relay.
        own=state.get('combat_player_positions') or [state['player_position']]
        for entity in state.get('visible_monsters',state.get('recent_entities',[])):
            if entity.get('kind','monster')!='monster':continue
            bounds=entity.get('attack_positions') or [entity.get('effective_position',entity['position'])]
            if entity.get('destination') and not entity.get('attack_positions'):bounds=bounds+[entity['destination']]
            if min(math.dist(a,b) for a in own for b in bounds)<=idle['clear_radius']:return False
        return True

    def idle_state(self,state):
        idle=self.config.get('idle_summon')
        return {**state,'idle_summon_skill_id':idle['skill_id'] if idle else None,'idle_summon_clear':self.idle_clear(state)}

    def ready(self,status,state,rotation,now):
        identity=self.config['skills'][status]['skill_id']
        meta=next((s for s in state.get('learned_skills',[]) if s['skill_id']==identity and s.get('level',0)>0),None)
        cds=state.get('skill_cooldowns',{})
        return bool(meta and meta.get('target_flags')==1 and (state.get('player_sp') or 0)>=meta['sp_cost']
                    and identity not in rotation.pending
                    and now>=max(rotation.ready.get(identity,0),cds.get(identity,cds.get(str(identity),0))))

    def control_margin(self,skill_id,rotation,state):
        if skill_id!=self.config['skills']['silence']['skill_id']:
            return rotation.range_margin
        from .combat_rotation import configured_range
        meta=next((s for s in state.get('learned_skills',[]) if s['skill_id']==skill_id),{})
        profile=next((p for p in rotation.profiles if p['skill_id']==skill_id),{})
        reach=self.config.get('focus',{}).get('silence_range',self.SILENCE_RANGE)  # how close before casting
        return max(rotation.range_margin,configured_range(profile,meta)-reach)

    def attacking(self,entity,state,now):
        target,at=self.targeting.get(entity['entity_id'],(None,-1000))
        return target is not None and target==state.get('player_id') and now-at<=self.ATTACKER_MEMORY

    def area_asleep(self,entity):
        """Asleep, but not from our own single-target sleep: the Fukai Kemuri's sleep."""
        return self.statuses(entity)['sleep'] and 'sleep' not in self.history.get(entity['entity_id'],{})

    def released(self,entity,now):
        """control_limit: control kept failing on this monster; it is fought without it for a while."""
        rule=self.config.get('control_limit')
        started=self.control_started.get(entity['entity_id'])
        if not rule or started is None:return False
        if now-started<=rule['give_up_seconds']:return False
        if now-started<=rule['give_up_seconds']+rule['release_seconds']:return True
        self.control_started.pop(entity['entity_id'],None)
        return False

    RELEASED_SILENCE_GAP=1.5  # s between silence tries on an attacker whose control was given up

    def released_silence(self,entity,state,rotation,now):
        """Control given up (control_limit), but it keeps hitting the player: the silence is tried
        again whenever ready, between the attacks, instead of never again (Katsuyo 2026-11-09 16:44)."""
        status=self.statuses(entity)
        if status['silence'] or status['sleep'] or not self.attacking(entity,state,now):return None
        if now-self.history.get(entity['entity_id'],{}).get('silence',-1e9)<self.RELEASED_SILENCE_GAP:return None
        if not self.ready('silence',state,rotation,now):return None
        return dict(target_id=entity['entity_id'],mode='control',skill_id=self.config['skills']['silence']['skill_id'],
                    status='silence',reason='silencio no atacante entre os ataques')

    def control(self,entity,state,rotation,now,*,passive=False,release=False,silence_only=False,sleep_first=False):
        status=self.statuses(entity)
        if sleep_first:
            # Put to sleep (Fukai Yasumi), stun if the sleep will not go in; silence only as a last resort.
            if status['sleep'] or status['stun']:return None
            history=self.history.get(entity['entity_id'],{})
            if history and now-max(history.values())<self.CONFIRM_WAIT:
                return dict(target_id=entity['entity_id'],mode='control',skill_id=None,reason='aguardando status do servidor')
            for effect in ['sleep','stun']+([] if status['silence'] else ['silence']):
                if effect in ('stun','sleep') and now-history.get(effect,-1000)<3:continue
                if self.ready(effect,state,rotation,now):
                    return dict(target_id=entity['entity_id'],mode='control',skill_id=self.config['skills'][effect]['skill_id'],
                                status=effect,reason='manter dormindo: '+effect)
            return None
        if status['silence'] or release and (status['stun'] or status['sleep']):return None
        history=self.history.get(entity['entity_id'],{})
        if not (status['stun'] or status['sleep']) and history and now-max(history.values())<self.CONFIRM_WAIT:
            return dict(target_id=entity['entity_id'],mode='control',skill_id=None,reason='aguardando status do servidor')
        if silence_only or passive and entity['entity_id'] not in self.attacked:
            order=['silence']
        elif status['stun'] or status['sleep']:
            order=['silence']
        else:
            order=['stun','sleep','silence']
        for effect in order:
            if effect in ('stun','sleep') and now-history.get(effect,-1000)<3:
                continue
            if self.ready(effect,state,rotation,now):
                return dict(target_id=entity['entity_id'],mode='control',skill_id=self.config['skills'][effect]['skill_id'],
                            status=effect,reason='aplicar '+effect)
        if status['stun'] or status['sleep']:
            silence_id=self.config['skills']['silence']['skill_id']
            return dict(target_id=entity['entity_id'],mode='control',skill_id=silence_id,status='silence',
                        reason='aguardando alcance/recarga do silencio sem quebrar o controle')
        return None

    def monster_near(self,state,radius):
        own=state.get('combat_player_positions') or ([state['player_position']] if state.get('player_position') else [])
        for e in state.get('visible_monsters') or state.get('recent_entities',[]):
            if e.get('kind','monster')!='monster' or not own:continue
            bounds=e.get('attack_positions') or [e.get('effective_position',e['position'])]
            if min(math.dist(a,b) for a in own for b in bounds)<=radius:return True
        return False

    def low_hp_intent(self,state,rotation,now):
        """HP below the summon line: the Namekuji. Very low HP: sit until it is ready, but only with no
        monster around; with monsters close the fight (and the sleep keeping) goes on."""
        if not self.config.get('idle_summon'):return None
        if self.summon_urgent(state) and self.summon_plan(state,rotation,now) is not None:
            return dict(mode='summon',target_id=None,skill_id=self.config['idle_summon']['skill_id'],
                        reason='HP baixo: invocando '+self.config['idle_summon']['name'])
        if self.recovering and not self.monster_near(state,self.config['control_radius']):
            return dict(mode='recover',target_id=None,skill_id=None,
                        reason='HP muito baixo: sentado ate a invocacao ficar pronta e o HP voltar')
        return None

    def decide(self,state,rotation,now,*,current=None,reachable=None):
        if self.config.get('idle_summon'):self.update_recovery(state)
        entities=self.candidates(state,rotation,now)
        if self.config.get('focus',{}).get('lowest_hp'):
            # One at a time, the lowest HP first; the current target wins a tie (all still full).
            last=self.config['focus'].get('last_species',[])  # in this order, after everything else
            entities.sort(key=lambda e:(last.index(e['species_id'])+1 if e['species_id'] in last else 0,round(self.hp_fraction(e),4),e['entity_id']!=current,
                                        self.distance(state,e),self.ranks[e['species_id']],e['entity_id']))
        else:
            entities.sort(key=lambda e:(self.ranks[e['species_id']],self.distance(state,e),e['entity_id']))
        if reachable is not None:entities=reachable(entities)
        main=entities[0]['entity_id'] if entities else current  # the one being killed
        if self.area:
            # Monsters close by without sleep/stun (or silence): Coelho x3, the server answers with
            # Fukai Kemuri. While it recharges, the ordinary control and damage go on.
            attackers=[e for e in state.get('recent_entities',[]) if e.get('kind','monster')=='monster'
                       and e.get('species_id') in self.ranks and self.attacking(e,state,now)]
            intent=self.area.intent(state,now,self.distance,self.statuses,self.controllers-self.silence_only,current=main,attackers=attackers)
            if intent:return intent
        keep=bool(self.area and self.area.config.get('keep_others_asleep'))
        if not keep:
            intent=self.low_hp_intent(state,rotation,now)
            if intent:return intent
        low_hp_checked=not keep
        # Every unsilenced Jounin within the trigger radius outranks damage.
        # Control every visible Jounin in range before damage, even if it has not
        # targeted the player yet. Candidate eligibility still governs who we kill.
        threats=sorted((e for e in state.get('recent_entities',[])
                        if e.get('kind','monster')=='monster' and e.get('species_id') in self.controllers
                        and self.distance(state,e)<=self.config['control_radius']),
                       key=lambda e:self.distance(state,e))
        if reachable is not None:threats=reachable(threats)
        waiting=None
        area_mode=self.area is not None and now-self.area.fired_at<=self.AREA_MODE_SECONDS
        if keep:threats.sort(key=lambda e:e['entity_id']==main)  # the others' sleep comes first
        for e in threats:
            if keep and e['entity_id']==main and not low_hp_checked:
                # Kemuri and Fukai Yasumi on the others come first; then the low-HP summon.
                low_hp_checked=True
                intent=self.low_hp_intent(state,rotation,now)
                if intent:return intent
            if keep:
                # Every monster but the one being killed stays asleep. Stun and silence hit, and a
                # hit wakes a sleeper: the sleeping ones are left alone, an awake one gets Fukai Yasumi.
                status=self.statuses(e)
                if self.released(e,now):
                    intent=self.released_silence(e,state,rotation,now) if e['entity_id']==main else None
                    if intent:return intent
                    continue
                if e['entity_id']!=main and e.get('species_id') in self.silence_only:
                    continue  # only silenced when it is the one to kill
                if e['entity_id']==main and e.get('species_id') in self.silence_only:
                    if status['silence']:continue
                    intent=self.control(e,state,rotation,now,silence_only=True)
                elif e['entity_id']!=main:
                    if status['sleep'] or status['stun']:
                        self.control_started.pop(e['entity_id'],None);continue
                    intent=self.control(e,state,rotation,now,sleep_first=True)
                elif status['silence']:
                    continue  # silenced: now it can be killed
                elif self.area_asleep(e) or area_mode:
                    # Silence before the first hit, also on a monster the Kemuri put to sleep: the
                    # silence does no damage and does not wake it (it was hit unsilenced, 2026-11-09).
                    intent=self.control(e,state,rotation,now,silence_only=True)
                else:
                    intent=self.control(e,state,rotation,now)  # stun -> sleep -> silence, then the kill
                if intent is None and e['entity_id']==main:
                    # No damage before the silence: wait for it (range/recharge) until control_limit.
                    intent=dict(target_id=e['entity_id'],mode='control',skill_id=self.config['skills']['silence']['skill_id'],
                                status='silence',reason='silencio antes de matar: aguardando alcance/recarga')
                if intent and intent.get('skill_id') is not None:
                    if self.config.get('control_limit'):self.control_started.setdefault(e['entity_id'],now)
                    return intent
                if intent:waiting=waiting or intent
                continue
            if self.statuses(e)['silence']:
                self.control_started.pop(e['entity_id'],None)
                continue
            if self.area is not None and self.area_asleep(e):
                continue  # slept by Fukai Kemuri: straight to damage, no control
            if area_mode and not self.attacking(e,state,now):
                continue  # after a Kemuri only the monsters attacking the player get silence
            if self.released(e,now):
                intent=self.released_silence(e,state,rotation,now)
                if intent:return intent
                continue
            intent=self.control(e,state,rotation,now,silence_only=area_mode)
            if intent and intent.get('skill_id') is not None:
                if self.config.get('control_limit'):self.control_started.setdefault(e['entity_id'],now)
                return intent
            if intent:waiting=waiting or intent
        if waiting:return waiting
        if not low_hp_checked:
            intent=self.low_hp_intent(state,rotation,now)
            if intent:return intent
        if not entities:return None
        kill=entities[0]
        rule=self.config.get('engagement',{})
        if rule.get('seek_when_clear') and self.distance(state,kill)>rule['radius']:
            self.pull_id=kill['entity_id']  # keep the acquired target as it crosses into the near radius
        previous=next((e for e in entities if e['species_id'] in self.passive and e['entity_id'] in self.attacked
                       and self.distance(state,e)<=self.config['control_radius']),None)
        if previous and kill['species_id'] in ({r['species_id'] for r in self.config['kill_priority'][:2]}):
            intent=self.control(previous,state,rotation,now,release=True)
            if intent:return intent
        if kill['species_id'] in self.passive and self.statuses(kill)['silence']:
            self.passive_wait.pop(kill['entity_id'],None)  # silenced: when it wears off, a new short wait
        if kill['species_id'] in self.passive and not self.statuses(kill)['silence']:
            # Silence first, but never for long: it was refused 17 times in 5 min and each Doki
            # waited 13-33 s untouched (2026-11-06). Past PASSIVE_SILENCE_WAIT it is simply attacked.
            since=self.passive_wait.setdefault(kill['entity_id'],now)
            if now-since<self.PASSIVE_SILENCE_WAIT:
                intent=self.control(kill,state,rotation,now,passive=True)
                return intent or dict(target_id=kill['entity_id'],mode='control',skill_id=None,reason='Doki aguardando silencio disponivel')
        reason='aproximando alvo visivel em area livre' if kill['entity_id']==self.pull_id and rule and self.distance(state,kill)>rule['radius'] else 'prioridade de morte'
        return dict(target_id=kill['entity_id'],mode='kill',skill_id=None,reason=reason)

    def plan(self,state,rotation,now,current=None,*,intent=None):
        intent=intent or self.decide(state,rotation,now,current=current)
        clear_buffs=set()
        visible={e.get('entity_id'):e for e in (state.get('visible_monsters') or [])+state.get('recent_entities',[])
                 if isinstance(e,dict) and e.get('entity_id') is not None}
        for profile in rotation.profiles:
            radius=profile.get('only_when_clear_radius') if profile.get('role')=='buff' else None
            nearby=bool(state.get('player_position')) and any(
                e.get('kind','monster')=='monster' and self.distance(state,e)<=radius for e in visible.values()) if radius is not None else False
            if radius is None or not nearby:
                clear_buffs.add(profile['skill_id'])
        if intent is None:
            self.reason='sem alvo proximo mirando o personagem; buffs e invocacao em area livre'
            original=rotation.profiles
            rotation.profiles=[p for p in original if p['role']=='buff' and p['skill_id'] in clear_buffs
                               or p['role']=='summon' and p['skill_id']==self.config.get('idle_summon',{}).get('skill_id')]
            try:return rotation.plan(self.idle_state(state),now,None)
            finally:rotation.profiles=original
        if intent['mode']=='area_sleep':
            self.reason=intent['reason']
            return self.area.plan(state,rotation,now,intent)
        if intent['mode'] in ('summon','recover'):
            self.reason=intent['reason']
            return self.summon_plan(state,rotation,now) if intent['mode']=='summon' else None
        if intent['mode']=='control' and self.config.get('focus',{}).get('buffs_during_control'):
            # A buff that went off (Dai Senkou...) is renewed between the controls: here the controls
            # hardly ever stop, and the buffs were never cast again (yuno_fild07 2026-11-09).
            original=rotation.profiles
            rotation.profiles=[p for p in original if p['role']=='buff' and p['skill_id'] in clear_buffs]
            try:action=rotation.plan(state,now,None) if rotation.profiles else None
            finally:rotation.profiles=original
            if action is not None and action.get('role')=='buff':
                self.reason='renovando buff entre os controles'
                return action
        original=rotation.profiles
        species=next((e.get('species_id') for e in state.get('recent_entities',[]) if e['entity_id']==intent['target_id']),None)
        allowed={r['skill_id'] for r in self.config['skills']['offensives'] if self.offensive_allowed(r['skill_id'],species)} if intent['mode']=='kill' else {intent['skill_id']}
        on_hazard=intent['mode']=='kill' and self.target_on_hazard(intent['target_id'],state)
        if on_hazard:
            allowed&=set(self.THROWS)  # Kunai and Shuriken only, from outside the area
            intent={**intent,'reason':'alvo em area de habilidade no chao: Kunai e Shuriken de fora, em rajada'}
        rotation.profiles=[p for p in original if (p['role']=='buff' and p['skill_id'] in clear_buffs
                              and intent['mode']!='control') or p['skill_id'] in allowed]
        old_priority=getattr(rotation,'control_priority',False)
        old_burst=rotation.burst
        old_margin=rotation.range_margin
        if on_hazard:rotation.burst=True
        if intent['mode']=='control':
            rotation.burst=False
            rotation.range_margin=self.control_margin(intent['skill_id'],rotation,state)
        rotation.control_priority=intent['mode']=='control'
        try:
            action=None
            if intent['mode']=='kill' and intent['target_id'] not in self.attacked:
                # The first in-range offensive must not wait behind optional buff renewals.
                current=rotation.profiles
                rotation.profiles=[p for p in current if p['role']=='offensive']
                try:action=rotation.plan(state,now,intent['target_id'])
                finally:rotation.profiles=current
            if action is None:action=rotation.plan(state,now,intent['target_id'])
        finally:
            rotation.profiles=original
            rotation.control_priority=old_priority
            rotation.burst=old_burst
            rotation.range_margin=old_margin
        self.reason=intent['reason']
        if action and action['role']=='offensive' and intent['mode']=='control':
            action={**action,'control_status':intent['status']}
        return action
