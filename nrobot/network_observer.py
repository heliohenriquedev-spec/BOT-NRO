"""REDE-08: observador Windows, somente recepção. Não controla o personagem."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import socket
import struct
import signal
import subprocess
import time
from datetime import datetime

from .network_targets import Entity, TargetRegistry
from .packet_reader import decode, message_length


def snapshot_summary(result, mapping, chosen):
    """Historical sightings only; never restore world-state across capture gaps."""
    observed = []
    end = max((e['time'] for e in result['events']), default=0)
    for entity in result['entities']:
        species = entity.get('species_id')
        if species not in chosen or str(species) not in mapping:
            continue
        observed.append({'name': mapping[str(species)]['name'], 'entity_id': entity['entity_id'],
                         'species_id': species, 'position': entity.get('position'),
                         'seconds_before_end': round(max(0, end-entity.get('position_time', end)), 2),
                         'hp': entity.get('hp'), 'max_hp': entity.get('max_hp'),
                         'removal_observed': 'last_removal_reason' in entity})
    return {'mode': 'pktmon_intervals', 'actionable': False, 'messages': len(result['events']),
            'gaps': result['quality']['gaps'], 'unparsed_runs': len(result['issues']),
            'observed': observed}


def observe_pktmon(chosen, mapping):
    """Receive through independently finalized captures; no raw socket required."""
    from .packet_reader import analyze, write_report
    root = Path(__file__).resolve().parents[1]
    session = root / 'logs/observador' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    session.mkdir(parents=True)
    status_path = session / 'estado.json'
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        print('\nEncerrando a captura em andamento...')

    previous_handler = signal.signal(signal.SIGINT, request_stop)
    print('\nCaptura Windows por intervalos de 5 segundos, mais tempo de conversão.')
    print('Mova o personagem para receber aparições. A lista descreve o último intervalo, não o estado atual.')
    print(f'Registros automáticos: {session}\nCtrl+C encerra.')
    status_path.write_text(json.dumps({'state': 'starting', 'backend': 'pktmon'}), encoding='utf-8')
    cycle = 0
    try:
        while not stop_requested:
            cycle += 1
            print(f'\nIntervalo {cycle}: coletando... ', flush=True)
            before = set((root / 'logs/rede').glob('*/captura.pcapng'))
            completed = subprocess.run(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                 str(root / 'tools/capturar_rede.ps1'), '-Segundos', '5'],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log = session / f'{cycle:04d}-captura.log'
            log.write_bytes(completed.stdout)
            if stop_requested:
                break
            if completed.returncode:
                raise ValueError(f'O capturador retornou erro. Detalhes salvos em {log}')
            new = set((root / 'logs/rede').glob('*/captura.pcapng')) - before
            if len(new) != 1:
                raise ValueError(f'Esperada uma captura nova; encontradas {len(new)}. Detalhes: {log}')
            capture = new.pop()
            connection = json.loads((capture.parent / 'conexao.json').read_text(encoding='utf-8-sig'))
            result = analyze(capture, connection)
            write_report(result, capture.parent)
            summary = snapshot_summary(result, mapping, chosen)
            summary.update(state='observing', cycle=cycle, capture=str(capture))
            encoded = json.dumps(summary, ensure_ascii=False, indent=2)
            (session / f'{cycle:04d}-resultado.json').write_text(encoded, encoding='utf-8')
            status_path.write_text(encoded, encoding='utf-8')
            print(f"Mensagens lidas: {summary['messages']} | lacunas: {summary['gaps']} | "
                  f"entidades escolhidas observadas: {len(summary['observed'])}")
            if not summary['messages']:
                print('Nenhuma mensagem interpretada neste intervalo. Confira a conexão e o registro salvo.')
            elif not summary['observed']:
                print('O tráfego chegou, mas nenhuma aparição do tipo escolhido foi identificada neste intervalo.')
            for item in summary['observed']:
                state = ' | remoção observada' if item['removal_observed'] else ''
                print(f"  {item['name']} | ID {item['entity_id']} | célula {item['position']}"
                      f" | posição {item['seconds_before_end']}s antes do fim{state}")
            if summary['gaps'] or summary['unparsed_runs']:
                print('Leitura parcial: a lista pode omitir entidades. Não há seleção atual para ataque.')
    except (OSError, ValueError, KeyError) as exc:
        status_path.write_text(json.dumps({'state': 'error', 'error': str(exc)}, ensure_ascii=False), encoding='utf-8')
        print(f'Observação interrompida: {exc}')
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        if stop_requested:
            status_path.write_text(json.dumps({'state': 'stopped', 'cycle': cycle}), encoding='utf-8')
    print('Observação encerrada.')
    return 0


class LiveStream:
    """Remonta uma direção TCP; aguarda reordenação breve, sem saltar lacunas."""
    def __init__(self):
        self.expected = None
        self.pending = {}
        self.buffer = bytearray()
        self.gap_since = None
        self.history = bytearray()
        self.resyncing = False
        self.resyncs = 0

    @staticmethod
    def frames(buffer):
        """Complete messages at the start of buffer; raises ValueError on unknown framing."""
        offset, messages = 0, []
        while offset < len(buffer):
            length = message_length(buffer, offset)
            if length is None or len(buffer)-offset < length:
                break
            messages.append(bytes(buffer[offset:offset+length]))
            offset += length
        return messages, offset

    def check_gap(self, now):
        if self.gap_since is not None and now - self.gap_since >= 0.5:
            raise ValueError('Lacuna persistente na captura; seleção interrompida. Reinicie o observador.')

    def feed(self, sequence, payload, now):
        if not payload:
            return []
        if self.expected is None:
            self.expected = sequence
        self.pending.setdefault(sequence, []).append(payload)
        if sum(len(b) for values in self.pending.values() for b in values) > 262144:
            raise ValueError('Fila TCP excedeu o limite')
        while self.pending:
            sequence = min(self.pending, key=lambda n: ((n-self.expected+2**31) % 2**32)-2**31)
            distance = ((sequence-self.expected+2**31) % 2**32)-2**31
            if distance > 0:
                break
            bodies = self.pending.pop(sequence)
            for body in bodies:
                overlap = min(-distance, len(body))
                if overlap:
                    start = len(self.history) + distance
                    if start >= 0 and self.history[start:start+overlap] != body[:overlap]:
                        raise ValueError('Retransmissão com dados divergentes')
                if -distance < len(body):
                    fresh = body[-distance:]
                    self.buffer.extend(fresh)
                    self.history.extend(fresh)
                    self.history = self.history[-65536:]
                    self.expected = (self.expected + len(fresh)) % 2**32
                distance = ((sequence-self.expected+2**31) % 2**32)-2**31
        if self.pending:
            if self.gap_since is None:
                self.gap_since = now
        else:
            self.gap_since = None
        self.check_gap(now)
        # REDE-65: NRO's injected client DLLs add custom server messages (e.g. global chat)
        # absent from the client table. Instead of stopping all reading, drop the unframeable
        # bytes and resume only on data that frames exactly, so misaligned bytes never
        # become events.
        events = []
        try:
            messages, consumed = self.frames(self.buffer)
            if self.resyncing and (not messages or consumed != len(self.buffer)):
                raise ValueError('aguardando trecho alinhado')
        except ValueError as exc:
            head = bytes(self.buffer[:16])
            if not self.resyncing:
                self.resyncs += 1
                events.append({'kind': 'stream_resync', 'opcode': f'{int.from_bytes(head[:2], "little"):04X}' if len(head) >= 2 else None,
                               'dropped': len(self.buffer), 'head_hex': head.hex(), 'reason': str(exc)})
            self.resyncing = True
            self.buffer.clear()
            return events
        self.resyncing = False
        for message in messages:
            events.append(decode(message))
        del self.buffer[:consumed]
        return events


class Observer:
    def __init__(self, species: set[int], player_ttl=5, entity_ttl=5):
        self.free_cast_movement = False
        self.species = species
        self.registry = TargetRegistry(ttl=entity_ttl)
        self.pinned = set()  # REDE-67: characters captured as targets
        from .server_clock import ServerClock
        self.clock = ServerClock()
        self.collision_provider = None  # REDE-69: returns the current map's CollisionMap
        self.player = None
        self.player_at = 0
        self.player_id = None
        self.player_ttl = player_ttl
        self.player_alive = True
        self.walk_speed_ms = 400
        self.map_name = None
        self.sp = None
        self.skills = {}
        self.hotkeys = {}
        self.effects = {}
        self.skill_cooldowns = {}
        self.cast_until = 0
        self.player_motion = None

    # REDE-83: the server sends the skill list (and SP, hotkeys, buffs) only when the character
    # logs in, not on every map change: a warp must not forget them.
    CHARACTER_FIELDS = ('skills', 'hotkeys', 'sp', 'effects', 'walk_speed_ms')

    def keep_character(self):
        return {field: getattr(self, field) for field in self.CHARACTER_FIELDS}

    def restore_character(self, kept):
        for field, value in kept.items():
            setattr(self, field, value)

    def clear(self):
        self.registry.clear()
        self.player = None
        self.player_id = None
        self.map_name = None
        self.sp = None
        self.skills = {}
        self.hotkeys = {}
        self.effects = {}
        self.skill_cooldowns = {}
        self.cast_until = 0
        self.player_motion = None

    def walk_path(self, origin, destination):
        from .server_path import server_path
        try:
            collision = self.collision_provider() if self.collision_provider else None
        except (OSError, ValueError):
            collision = None
        if collision is None:
            from .server_path import OpenGround
            collision = OpenGround  # exact on free ground; maps without collision data
        path = server_path(collision, tuple(origin), tuple(destination))
        return tuple(path) if path and len(path) > 1 else None

    def combat_positions(self, now):
        if self.player is None:
            return []
        if self.player_motion is None:
            return [list(self.player)]
        motion = self.player_motion
        if motion.get('path'):
            from .server_path import step_durations, cells_at
            points = []
            durations = step_durations(motion['path'], self.walk_speed_ms)
            for moment in (now, now+.08):
                for cell in cells_at(motion['path'], durations, moment-motion['at']):
                    if list(cell) not in points:
                        points.append(list(cell))
            return points
        points = []
        for moment in (now, now+.08):
            fraction = min(1, max(0, (moment-motion['at'])/max(.001, motion['duration'])))
            point = [round(a+(b-a)*fraction) for a, b in zip(motion['origin'], motion['destination'])]
            if point not in points:
                points.append(point)
        return points

    def apply(self, event, now):
        kind = event['kind']
        if kind == 'map_change':
            identity, kept = self.player_id, self.keep_character()
            self.clear()
            self.restore_character(kept)
            self.player_id = identity
            self.map_name = event.get('map')
            self.player, self.player_at = event['position'], now
        elif kind == 'player_position_init':
            identity = self.player_id
            map_name = self.map_name
            kept = self.keep_character()
            self.clear()
            self.restore_character(kept)
            self.player_id = identity
            self.map_name = map_name
            self.player, self.player_at = event['position'], now
            self.player_alive = True
        elif kind == 'own_identity':
            self.player_id = event['entity_id']
        elif kind == 'skills_info':
            if event['replace']:
                self.skills.clear()
            for skill in event['skills']:
                if skill['skill_id'] > 0:
                    self.skills[skill['skill_id']] = {**self.skills.get(skill['skill_id'], {}), **skill}
        elif kind == 'status_effect' and event['entity_id'] == self.player_id:
            self.effects[event['effect_id']] = event['active']
        elif kind == 'skill_cooldown':
            self.skill_cooldowns[event['skill_id']] = now+min(event['duration_ms']/1000, 3600)
        elif kind == 'skill_cast' and event['source_id'] == self.player_id:
            if self.player_motion is not None and not self.free_cast_movement:
                self.player = self.combat_positions(now)[0]
                self.player_motion = None
            self.cast_until = now+min(event['duration_ms']/1000, 30)
        elif kind in ('skill_damage', 'skill_no_damage') and event['source_id'] == self.player_id:
            self.cast_until = 0
        elif kind == 'skill_failed':
            self.cast_until = 0
        elif kind == 'hotkeys_info':
            self.hotkeys = {entry['slot']: entry for entry in event['hotkeys']}
        elif kind == 'player_stat' and event['stat_type'] == 7:
            self.sp = event['value']
        elif kind == 'map_transfer':
            kept = self.keep_character()
            self.clear()
            self.restore_character(kept)  # the new map server resends the list when it has it
        elif kind == 'server_time':
            self.clock.time_reply(event['server_tick'], now)
        elif kind == 'player_move':
            # Destino confirmado pelo servidor; células seguem o caminho calculado pelo servidor.
            self.player, self.player_at = event['destination'], now
            origin = event.get('position') or self.player
            started = now
            if 'server_tick' in event:
                self.clock.observe(event['server_tick'], now)
                started = self.clock.to_local(event['server_tick'], now)
            path = self.walk_path(origin, event['destination'])
            dx, dy = (abs(event['destination'][i]-origin[i]) for i in (0, 1))
            duration = (max(dx, dy)+.4*min(dx, dy))*self.walk_speed_ms/1000
            if path:
                from .server_path import step_durations
                duration = sum(step_durations(path, self.walk_speed_ms))
            self.player_motion = {'origin': list(origin), 'destination': list(event['destination']), 'at': started,
                                  'duration': duration, 'path': path}
        elif kind == 'appearance' and event['entity_id'] in self.pinned:
            x, y = event['position']
            self.registry.update(Entity(event['entity_id'], event['species_id'], x, y, now, 'player',
                                        destination=tuple(event['destination']) if event.get('destination') else None,
                                        walk_speed_ms=event.get('walk_speed_ms')))
        elif kind == 'appearance':
            identity = event['entity_id']
            if event['species_id'] in self.species:
                # Categoria aqui é um candidato configurado por aparência correlacionada.
                # Não é uma prova de categoria ou autorização de combate.
                x, y = event['position']
                self.registry.update(Entity(identity, event['species_id'], x, y, now, 'monster',
                                            destination=tuple(event['destination']) if event.get('destination') else None,
                                            walk_speed_ms=event.get('walk_speed_ms')))
            else:
                self.registry.remove(identity)
        elif kind == 'remove':
            self.registry.remove(event['entity_id'])
            if event['entity_id'] == self.player_id:
                self.player = None
                if event.get('reason') == 1:
                    self.player_alive = False
        elif kind == 'player_stat' and event['stat_type'] == 0:
            if 50 <= event['value'] <= 2000:
                self.walk_speed_ms = event['value']
        elif kind == 'player_stat' and event['stat_type'] == 5:
            self.player_alive = event['value'] > 0
            if not self.player_alive:
                self.player = None
        elif kind in ('move', 'position') and event.get('entity_id') == self.player_id and self.player_id is not None:
            self.player, self.player_at = event['position'], now
            self.player_motion = None
        elif event.get('entity_id') in self.registry.entities:
            old = self.registry.entities[event['entity_id']]
            if kind in ('move', 'position'):
                x, y = event['position']
                path = started = None
                if kind == 'move' and event.get('destination'):
                    path = self.walk_path((x, y), event['destination'])
                    started = now
                    if 'server_tick' in event:
                        self.clock.observe(event['server_tick'], now)
                        started = self.clock.to_local(event['server_tick'], now)
                self.registry.update(replace(old, x=x, y=y, seen_at=now, path=path, walk_started=started,
                                             destination=tuple(event['destination']) if event.get('destination') else None))
            elif kind == 'name' and event.get('hp') == 0:
                self.registry.remove(old.entity_id)

    def player_position_valid(self, now):
        return self.player_alive and self.player is not None and (self.player_ttl is None or now-self.player_at <= self.player_ttl)

    def choose(self, now):
        if not self.player_position_valid(now):
            self.registry.target_id = None
            return None
        return self.registry.choose(self.species, tuple(self.player), now)


def selected_tcp(raw, server, client):
    if len(raw) < 40 or raw[0] >> 4 != 4 or raw[9] != 6:
        return None
    ih = (raw[0] & 15) * 4
    total = struct.unpack_from('!H', raw, 2)[0]
    if ih < 20 or total > len(raw) or total < ih+20:
        raise ValueError('Pacote IPv4 truncado')
    if socket.inet_ntoa(raw[12:16]) != server[0] or socket.inet_ntoa(raw[16:20]) != client[0]:
        return None
    tcp = raw[ih:total]
    sp, dp, sequence = struct.unpack_from('!HHI', tcp)
    if (sp, dp) != (server[1], client[1]):
        return None
    if struct.unpack_from('!H', raw, 6)[0] & 0x3fff:
        raise ValueError('Fragmentação IPv4 não suportada no observador')
    th = tcp[12] >> 4 << 2
    if th < 20 or th > len(tcp):
        raise ValueError('Cabeçalho TCP inválido')
    if tcp[13] & 0x07:
        raise ValueError('Conexão encerrada ou reiniciada; reinicie o observador')
    return sequence, tcp[th:]


def main():
    parser = argparse.ArgumentParser(description='Observar candidatos NRO sem enviar comandos')
    parser.add_argument('--server', required=True)
    parser.add_argument('--server-port', type=int, required=True)
    parser.add_argument('--local', required=True)
    parser.add_argument('--local-port', type=int, required=True)
    parser.add_argument('--backend', choices=('pktmon', 'socket', 'etw'), default='pktmon')
    parser.add_argument('--select', help='Números dos tipos separados por vírgula; omita para escolher na janela')
    parser.add_argument('--duration', type=float, default=0, help='Limite de segundos de leitura; zero mantém aberto')
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / 'data/rede/especies_nro.json'
    mapping = json.loads(path.read_text(encoding='utf-8'))['species']
    entries = sorted(mapping.items(), key=lambda item: item[1]['name'])
    print('Observação por rede — nenhum ataque ou movimento será enviado.\n')
    for index, (identity, info) in enumerate(entries, 1):
        print(f"{index}: {info['name']} (aparência {identity})")
    answer = (input('\nEscolha os números separados por vírgula, ou Enter para observar todos: ')
              if args.select is None else args.select).strip()
    try:
        indices = [int(v.strip())-1 for v in answer.split(',')] if answer else list(range(len(entries)))
        if any(i < 0 or i >= len(entries) for i in indices):
            raise ValueError()
        chosen = {int(entries[i][0]) for i in indices}
    except ValueError:
        raise SystemExit('Seleção inválida.')
    if args.backend == 'pktmon':
        return observe_pktmon(chosen, mapping)
    if args.backend == 'etw':
        from .continuous_observer import run
        return run(args, chosen, mapping)
    observer, stream, sock = Observer(chosen), LiveStream(), None
    server, client = (args.server, args.server_port), (args.local, args.local_port)
    last_display, started, received = 0, time.monotonic(), False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        sock.bind((args.local, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)
        sock.settimeout(0.2)
        sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        print('\nMova o personagem para receber posição e aparições. Ctrl+C encerra.')
        while True:
            now = time.monotonic()
            try:
                raw = sock.recv(65535)
                segment = selected_tcp(raw, server, client)
                if segment and segment[1]:
                    received = True
                    for event in stream.feed(*segment, now):
                        observer.apply(event, now)
            except socket.timeout:
                pass
            stream.check_gap(now)
            if now-last_display >= 1:
                last_display = now
                target = observer.choose(now)
                count = sum(0 <= now-e.seen_at <= 5 for e in observer.registry.entities.values())
                if target:
                    name = mapping[str(target.species_id)]['name']
                    print(f'Candidatos recentes: {count} | {name} | ID {target.entity_id} | célula {target.x},{target.y}')
                else:
                    print(f'Candidatos recentes: {count} | aguardando alvo e posição recentes do personagem')
            if not received and now-started > 15:
                raise ValueError('Nenhum tráfego recebido. Verifique a conexão; este capturador pode não funcionar com seu adaptador.')
    except (OSError, ValueError) as exc:
        print(f'Observação interrompida: {exc}')
        return 1
    except KeyboardInterrupt:
        print('\nObservação encerrada.')
        return 0
    finally:
        observer.clear()
        if sock is not None:
            try:
                sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            sock.close()


if __name__ == '__main__':
    raise SystemExit(main())
