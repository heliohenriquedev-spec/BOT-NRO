"""REDE-75: simulate the patrol on every map the bot can read and report weak maps.

Uso: .venv\\Scripts\\python.exe tools\\validar_patrulha.py [mapa.gat ...]
Writes logs\\validacao_patrulha.json. For each map it walks one full cycle from a random
start of the main ground area and measures:
  coverage   share of the ground passed within VIEW cells (monsters are announced ~14 away)
  repeat     share of the walk over 4x4 sectors already walked in the cycle
  near_wall  share of move destinations touching a wall (corners/edges)
  effort     walked cells / ideal sweep length (ground cells / (2*VIEW))
  stalls     planning rounds that produced no move
"""
from concurrent.futures import ProcessPoolExecutor
import json
import os
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VIEW = 12
COMBAT_EVERY = int(__import__('os').environ.get('COMBAT_EVERY', 5))  # moves between simulated fights; 0 = none
MAX_ACTIONS = 6000
repository = None


def init_worker():
    global repository
    from nrobot.game_folder import require
    from nrobot.map_navigation import MapRepository
    repository = MapRepository(require())


def main_ground(collision, rng):
    walkable = [(x, y) for y in range(collision.height) for x in range(collision.width) if collision.walkable((x, y))]
    if not walkable:
        return None
    best = frozenset()
    for _ in range(12):
        start = rng.choice(walkable)
        component = collision.reachable(start)
        if len(component) > len(best):
            best = component
        if len(best) >= len(walkable)*.5:
            break
    return best


def simulate(name, seed=1):
    import os
    from nrobot.patrol_tour import wall_distance
    if os.environ.get('PATROL_IMPL'):  # compare against another implementation file
        import importlib.util
        spec = importlib.util.spec_from_file_location('nrobot.patrol_alt', os.environ['PATROL_IMPL'])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        PacketPatrol = module.PacketPatrol
    else:
        from nrobot.packet_patrol import PacketPatrol
    collision = repository.get(name)
    if collision is None:
        return {'map': name, 'status': 'sem_colisao', 'error': repository.errors.get(name, '')[:120]}
    rng = random.Random(seed)
    ground = main_ground(collision, rng)
    if not ground or len(ground) < 50:
        return {'map': name, 'status': 'pequeno', 'cells': len(ground or ())}
    position = list(rng.choice(sorted(ground)))
    started = time.perf_counter()
    import os
    if os.environ.get('SPACING'):
        import nrobot.patrol_tour as tour
        tour.SPACING, tour.SEEN_RADIUS = int(os.environ['SPACING']), int(os.environ['SEEN'])
    layout = json.loads(os.environ.get('PATROL_LAYOUT', '{}'))  # e.g. {"spacing": 14, "wall_margin": 3, "avoid_walls": true}
    patrol = PacketPatrol(rng=random.Random(seed), **layout)
    patrol.plan(position, 0, 150, collision)
    build = time.perf_counter()-started
    walked, now, stalls, near_wall, moves, repeated, invalid = 0, 0.0, 0, 0, 0, 0, 0
    trail, sectors = [tuple(position)], {(position[0]//4, position[1]//4)}
    last_sector, entries = (position[0]//4, position[1]//4), 0
    wall = wall_distance(collision, ground)
    while getattr(patrol, 'cycle_number', 1) == 1 and moves < MAX_ACTIONS:
        action = patrol.plan(position, now, 150, collision)
        if action is None:
            stalls += 1
            now += .3
            if stalls > 400:
                break
            continue
        destination = action['destination']
        if not collision.segment(position, destination, max_steps=8):
            invalid += 1
        steps = max(abs(destination[i]-position[i]) for i in (0, 1))
        for step in range(1, steps+1):
            point = tuple(round(position[i]+(destination[i]-position[i])*step/steps) for i in (0, 1))
            sector = (point[0]//4, point[1]//4)
            if sector != last_sector:  # count sector entries, not every step inside one
                repeated += sector in sectors
                entries += 1
                sectors.add(sector)
                last_sector = sector
            trail.append(point)
        walked += steps
        near_wall += wall[tuple(destination)] <= 2
        moves += 1
        patrol.reached(destination, position)
        position = list(destination)
        now += action['wait_seconds']
        if COMBAT_EVERY and moves % COMBAT_EVERY == 0:
            # A fight pulls the character a few cells off the route, like chasing a monster.
            nearby = [p for p in ((position[0]+dx, position[1]+dy) for dx in range(-8, 9) for dy in range(-8, 9))
                      if p in ground]
            chase = list(rng.choice(nearby))
            patrol.reached(chase, position)
            position = chase
            now += 6
    covered = set()
    for point in trail[::2]:
        for dx in range(-VIEW, VIEW+1):
            for dy in range(-VIEW, VIEW+1):
                if dx*dx+dy*dy <= VIEW*VIEW:
                    covered.add((point[0]+dx, point[1]+dy))
    coverage = len(ground & covered)/len(ground)
    ideal = len(ground)/(2*VIEW)
    return {'map': name, 'status': 'ok' if patrol.cycle_number > 1 else 'ciclo_incompleto',
            'cells': len(ground), 'waypoints': len(patrol.tour.points) if getattr(patrol, 'tour', None) else None, 'build_s': round(build, 2),
            'coverage': round(coverage, 3), 'repeat': round(repeated/max(entries, 1), 3),
            'near_wall': round(near_wall/max(moves, 1), 3), 'effort': round(walked/max(ideal, 1), 2),
            'walked': walked, 'moves': moves, 'stalls': stalls, 'invalid_segments': invalid,
            'minutes': round(now/60, 1)}


def main():
    init_worker()
    names = sys.argv[1:] or sorted({key.rsplit('\\', 1)[-1] for key in repository.grfs.find('data\\', '.gat')})
    results = []
    partial = ROOT/'logs'/(os.environ.get('VALIDATION_NAME', 'validacao_patrulha')+'_parcial.jsonl')
    from concurrent.futures import as_completed
    with ProcessPoolExecutor(initializer=init_worker) as pool, partial.open('w', encoding='utf-8') as stream:
        futures = [pool.submit(simulate, name) for name in names]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            stream.write(json.dumps(result, ensure_ascii=False)+'\n')
            stream.flush()
            if result['status'] not in ('ok', 'sem_colisao', 'pequeno') or result.get('coverage', 1) < .9:
                print(json.dumps(result, ensure_ascii=False))
            if index % 50 == 0:
                print(f'{index}/{len(names)} mapas', flush=True)
    ok = [r for r in results if r['status'] == 'ok']
    summary = {'maps': len(results), 'ok': len(ok),
               'incomplete': [r['map'] for r in results if r['status'] == 'ciclo_incompleto'],
               'no_collision': [r['map'] for r in results if r['status'] == 'sem_colisao'],
               'small': [r['map'] for r in results if r['status'] == 'pequeno']}
    for key in ('coverage', 'repeat', 'near_wall', 'effort'):
        values = sorted(r[key] for r in ok)
        if values:
            summary[key] = {'min': values[0], 'median': values[len(values)//2], 'max': values[-1],
                            'mean': round(sum(values)/len(values), 3)}
    out = ROOT/'logs'/(os.environ.get('VALIDATION_NAME', 'validacao_patrulha')+'.json')
    out.write_text(json.dumps({'summary': summary, 'maps': results}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:3000])
    print('Relatorio:', out)


if __name__ == '__main__':
    main()
