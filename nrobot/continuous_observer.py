"""REDE-10/11: captura contínua e seletor de candidatos, sem atuar no jogo."""
from __future__ import annotations

from collections import Counter
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import re
import signal
import struct
import subprocess
import threading
import time

from .etw_capture import EtwReader, active_session_file
from .network_observer import LiveStream, Observer, selected_tcp


def ipv4_from_ethernet(frame):
    if len(frame) < 14:
        raise ValueError('Quadro Ethernet incompleto')
    protocol, offset = struct.unpack_from('!H', frame, 12)[0], 14
    while protocol in (0x8100, 0x88a8):
        if len(frame) < offset+4:
            raise ValueError('VLAN incompleta')
        protocol = struct.unpack_from('!H', frame, offset+2)[0]
        offset += 4
    return frame[offset:] if protocol == 0x800 else None


def legacy_filter_captures(text, root):
    """Return only locally evidenced legacy capture paths; reject mixed filters."""
    rows = re.findall(r'^[ \t]*\d+[ \t]+(\S+)[ \t]+(\S+)', text, re.M)
    if not rows:
        raise ValueError('Não foi possível identificar os filtros existentes')
    paths = []
    for name, protocol in rows:
        if not re.fullmatch(r'NRO-\d{8}-\d{6}', name) or protocol.upper() != 'TCP':
            raise ValueError('Existe filtro que não pertence à captura antiga deste bot')
        folder = root/'logs/rede'/name[4:]
        if not (folder/'conexao.json').is_file() or not (folder/'captura.etl').is_file():
            raise ValueError('O filtro antigo não possui registros locais que comprovem sua origem')
        paths.append((folder/'captura.etl').resolve())
    return paths


class ContinuousTracker:
    def __init__(self, chosen, player_ttl=5, idle_timeout=3, entity_ttl=5):
        self.idle_timeout = idle_timeout
        self.stream = LiveStream()
        self.observer = Observer(chosen, player_ttl=player_ttl, entity_ttl=entity_ttl)
        self.failed = None
        self.messages = 0
        self.last_received = None
        self.first_received = None
        self.packet_count = 0
        self.delivery_lag = 0.0

    def fail(self, reason):
        self.failed = str(reason)
        kept = self.observer.keep_character()
        self.observer.clear()
        self.observer.restore_character(kept)

    def feed(self, sequence, payload, now, *, event_time=None, delivery_lag=0.0):
        if self.failed:
            raise ValueError(self.failed)
        try:
            events = self.stream.feed(sequence, payload, now)
            self.delivery_lag = max(0.0, delivery_lag)
            if payload:
                self.packet_count += 1
                self.last_received = now
                if self.first_received is None:
                    self.first_received = now
            for event in events:
                self.messages += 1
                if self.delivery_lag <= 2:
                    self.observer.apply(event, now if event_time is None else event_time)
            if self.delivery_lag > 2:
                kept = self.observer.keep_character()
                self.observer.clear()
                self.observer.restore_character(kept)
            return events
        except ValueError as exc:
            self.fail(exc)
            raise

    def snapshot(self, now):
        try:
            self.stream.check_gap(now)
        except ValueError as exc:
            self.fail(exc)
        if self.idle_timeout is not None and self.last_received is not None and now - self.last_received > self.idle_timeout:
            self.fail('Sem dados da conexão por mais de três segundos')
        # Do not expose an eligible candidate during a pending sequence gap.
        healthy = not self.failed and not self.stream.pending and self.delivery_lag <= 2
        target = self.observer.choose(now) if healthy else None
        candidates = [e for e in self.observer.registry.entities.values() if self.observer.registry.current(e, now)
                      and e.alive and ((e.kind == 'monster' and e.species_id in self.observer.species)
                                       or (e.kind == 'player' and e.entity_id in self.observer.pinned))]
        return {'state': 'invalid' if self.failed else 'waiting_fresh_events' if self.delivery_lag > 2 else 'tracking' if healthy else 'waiting_reorder',
                'reason': self.failed, 'messages': self.messages, 'packets': self.packet_count,
                'delivery_lag_seconds': round(self.delivery_lag, 3),
                'candidate': None if target is None else {'entity_id': target.entity_id,
                    'species_id': target.species_id, 'position': [target.x, target.y]},
                'recent_entities': [{'entity_id': e.entity_id, 'species_id': e.species_id, 'kind': e.kind,
                                     'position': [e.x, e.y], 'destination': list(e.destination) if e.destination else None,
                                     'effective_position': e.combat_bounds(now)[0][0],
                                     'attack_positions': e.combat_bounds(now)[0],
                                     'position_prediction': e.destination is not None and e.walk_speed_ms is not None,
                                     'movement_start': [e.x, e.y], 'walk_speed_ms': e.walk_speed_ms,
                                     'arrival_estimated': e.position_bounds(now)[1],
                                     'position_usable': self.observer.registry.ttl is None and
                                                        (e.destination is None or e.walk_speed_ms is not None or e.position_bounds(now)[1]),
                                     'position_age_seconds': max(0, now-e.seen_at)} for e in candidates],
                'player_position_recent': self.observer.player_position_valid(now),
                'player_position': self.observer.player,
                'combat_player_positions': self.observer.combat_positions(now),
                'player_position_age_seconds': max(0, now-self.observer.player_at) if self.observer.player is not None else None,
                'player_sp': self.observer.sp, 'learned_skills': list(self.observer.skills.values()),
                'player_id': self.observer.player_id,
                'f2_binding': self.observer.hotkeys.get(1),
                'own_effects': dict(self.observer.effects), 'own_cast_until': self.observer.cast_until,
                'skill_cooldowns': dict(self.observer.skill_cooldowns),
                'actionable': False, 'note': 'Seleção de candidato para observação; nenhum comando de jogo é enviado.'}


class PktmonSession:
    """Own only the filter and capture started by this object."""
    def __init__(self, args, folder):
        self.args, self.folder = args, folder
        self.filter = f'NRO-Continuo-{os.getpid()}'
        self.added = self.owned = False
        self.process = self.output = None

    def command(self, *args):
        result = subprocess.run(['pktmon', *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with (self.folder/'pktmon-controle.log').open('ab') as log:
            log.write(result.stdout)
        if result.returncode:
            raise ValueError(f'PktMon falhou em {args[0]}; consulte pktmon-controle.log')
        return result.stdout.decode('oem', errors='replace')

    def start(self):
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise ValueError('Execute OBSERVAR_CONTINUO_ADMIN.bat como administrador')
        filters = self.command('filter', 'list')
        if not re.fullmatch(r'\s*(?:Filtros de Pacote:\s*Nenhum\.?|Packet Filters:\s*None\.?|No filters\.?)\s*', filters, re.I):
            self.clean_legacy_capture(filters)
        if active_session_file() is not None:
            raise ValueError('Existe uma sessão PktMon ativa mesmo sem filtros; ela foi preservada. Consulte o diagnóstico antes de reiniciar.')
        from .capture_guard import start_guard
        start_guard(os.getpid(), self.filter, self.folder)
        self.command('filter', 'add', self.filter, '-t', 'TCP', '-i', self.args.server,
                     '-p', self.args.local_port, self.args.server_port)
        self.added = True
        self.output = (self.folder/'pktmon-continuo.log').open('wb')
        self.process = subprocess.Popen(['pktmon', 'start', '--capture', '--comp', 'all',
                                         '--pkt-size', '0', '--log-mode', 'real-time',
                                         '--file-name', str(self.folder/'captura.etl')],
                                        stdout=self.output, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def clean_legacy_capture(self, filters):
        root = Path(__file__).resolve().parents[1]
        owned_files = legacy_filter_captures(filters, root)
        script = ("@(Get-CimInstance Win32_Process | Where-Object { "
                  "$_.Name -eq 'python.exe' -and $_.ProcessId -notin @(" +
                  str(os.getpid()) + ',' + str(os.getppid()) + ')' +
                  " -and $_.CommandLine -match 'nrobot[.]network_observer' "
                  "} | Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress")
        processes = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if processes.returncode:
            raise ValueError('Não foi possível verificar se o observador anterior está ativo')
        active_text = processes.stdout.decode('utf-8-sig', errors='replace').strip()
        active = json.loads(active_text) if active_text else []
        if active:
            raise ValueError('Outro observador ainda está ativo. Encerre-o com Ctrl+C antes de continuar.')
        capture = active_session_file()
        if capture is not None:
            if not capture or Path(capture).resolve() not in owned_files:
                raise ValueError('A sessão ativa não é a captura antiga comprovada deste bot; ela foi preservada')
            self.command('stop')
        # This Windows version only supports removing all filters. All listed
        # rows were validated above; do not use this command for mixed lists.
        self.command('filter', 'remove')
        remaining = self.command('filter', 'list')
        if not re.fullmatch(r'\s*(?:Filtros de Pacote:\s*Nenhum\.?|Packet Filters:\s*None\.?|No filters\.?)\s*', remaining, re.I):
            raise ValueError('O Windows ainda informa filtros após a limpeza; captura não iniciada')
        print('Captura antiga interrompida encontrada e liberada. Iniciando leitura contínua...')

    def close(self):
        errors = []
        if self.owned:
            try:
                self.command('stop')
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            finally:
                self.owned = False
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.added:
            try:
                current = self.command('filter', 'list')
                rows = re.findall(r'^[ \t]*\d+[ \t]+(\S+)[ \t]+(\S+)', current, re.M)
                if rows and all(name == self.filter for name, protocol in rows):
                    self.command('filter', 'remove')
                else:
                    errors.append('Filtros alterados durante a sessão; a configuração foi preservada')
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            self.added = False
        if self.output is not None:
            self.output.close()
        if errors:
            raise ValueError('; '.join(errors))
        from .capture_guard import disarm
        disarm(self.folder)


def run(args, chosen, mapping):
    root = Path(__file__).resolve().parents[1]
    folder = root/'logs/continuo'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    (folder/'conexao.json').write_text(json.dumps({'RemoteAddress': args.server,
        'RemotePort': args.server_port, 'LocalAddress': args.local, 'LocalPort': args.local_port}, indent=2), encoding='utf-8')
    events = queue.Queue(maxsize=8192)
    tracker = ContinuousTracker(chosen)
    session = PktmonSession(args, folder)
    components = Counter()
    reader = worker = last_packet = None
    stopped = threading.Event()
    failures = []

    def stop(signum, frame):
        stopped.set()

    old_handler = signal.signal(signal.SIGINT, stop)

    def receive(packet):
        packet['queued_at'] = time.monotonic()
        events.put_nowait(packet)

    def loss(count):
        raise ValueError(f'ETW informou perda de {count} eventos/buffers')

    def consume():
        try:
            reader.process()
        except BaseException as exc:
            failures.append(str(exc))

    def save(state):
        state['components'] = dict(components)
        state['updated_at'] = datetime.now().isoformat()
        temporary = folder/'estado.tmp'
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(folder/'estado.json')

    save({'state': 'starting', 'actionable': False})
    print(f'\nLeitura contínua ETW. Registros: {folder}\nCtrl+C encerra.')
    try:
        session.start()
        time.sleep(0.25)  # let startup failures surface before attaching to a logger
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if session.process.poll() not in (None, 0):
                raise ValueError('PktMon encerrou antes de abrir a sessão. Consulte os registros salvos.')
            try:
                reader = EtwReader(logger='PktMon', on_packet=receive, on_loss=loss)
                reader.open()
                if session.process.poll() not in (None, 0):
                    reader.close()
                    raise ValueError('PktMon recusou o início. Nenhuma sessão anterior será utilizada.')
                session.owned = True
                break
            except OSError:
                time.sleep(0.1)
        else:
            # A real-time pktmon process still running owns the capture it started.
            # Stop it on attach timeout instead of leaving a filtered session behind.
            session.owned = session.process.poll() is None
            raise ValueError('A sessão ETW PktMon não ficou disponível em cinco segundos')
        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        last_display, start = 0, time.monotonic()
        server, client = (args.server, args.server_port), (args.local, args.local_port)
        with (folder/'eventos.jsonl').open('w', encoding='utf-8', buffering=1) as log:
            while not stopped.is_set():
                if getattr(args, 'duration', 0) and time.monotonic()-start >= args.duration:
                    break
                if failures:
                    raise ValueError(failures[0] or 'Falha na fila de eventos ETW')
                if not worker.is_alive():
                    raise ValueError('A sessão ETW encerrou; estado invalidado')
                try:
                    packet = events.get(timeout=0.1)
                    last_packet = packet
                    now = time.monotonic()
                    ip = ipv4_from_ethernet(packet['frame'])
                    segment = selected_tcp(ip, server, client) if ip is not None else None
                    if segment and segment[1]:
                        components[packet['component']] += 1
                        lag = max(0, time.time()-packet['time'])
                        event_now = now-lag
                        for event in tracker.feed(*segment, now, event_time=event_now, delivery_lag=lag):
                            log.write(json.dumps({**event, 'received_at': packet['time']}, ensure_ascii=False)+'\n')
                except queue.Empty:
                    pass
                now = time.monotonic()
                state = tracker.snapshot(now)
                if state['reason']:
                    raise ValueError(state['reason'])
                if tracker.last_received is None and now-start > 15:
                    raise ValueError('Nenhum payload da conexão recebido em quinze segundos')
                if now-last_display > 1:
                    last_display = now
                    save(state)
                    target = state['candidate']
                    if target:
                        name = mapping[str(target['species_id'])]['name']
                        print(f"Mensagens: {state['messages']} | candidatos: {len(state['recent_entities'])} | "
                              f"selecionado: {name} ID {target['entity_id']} célula {target['position']}")
                    elif state['state'] == 'waiting_fresh_events':
                        print(f"Mensagens: {state['messages']} | entrega atrasada {state['delivery_lag_seconds']}s | seleção suspensa até dados recentes")
                    else:
                        print(f"Mensagens: {state['messages']} | candidatos: {len(state['recent_entities'])} | "
                              f"aguardando posição/alvo recentes ou reordenação TCP")
        save({'state': 'stopped', 'actionable': False})
        return 0
    except (OSError, ValueError) as exc:
        tracker.fail(exc)
        if last_packet is not None:
            (folder/'ultimo_pacote.json').write_text(json.dumps({
                'time': last_packet['time'], 'component': last_packet['component'],
                'frame_hex': last_packet['frame'].hex()}, indent=2), encoding='utf-8')
        save({**tracker.snapshot(time.monotonic()), 'state': 'error', 'reason': str(exc)})
        print(f'Leitura interrompida; seleção descartada: {exc}\nDiagnóstico salvo em {folder}')
        return 1
    finally:
        stopped.set()
        tracker.observer.clear()
        if reader is not None:
            reader.close()
        try:
            session.close()
        except (OSError, ValueError) as exc:
            print(f'Confira o encerramento do PktMon: {exc}')
        if worker is not None:
            worker.join(timeout=3)
        signal.signal(signal.SIGINT, old_handler)
