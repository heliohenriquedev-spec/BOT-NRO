"""The own character's real body + hair sprites from the game's GRF, drawn as a shadow.

The class, sex and hairstyle come from the character list the server sends on login
(0069/006B) and from look-change packets; the files are the client's own .spr/.act. A
character's ACT has 8 directions per action (0 = south, counter-clockwise... 4 = north)
and the frames place each sprite layer around the feet; the head is placed on the body's
anchor point, exactly as the client does it.
"""
from __future__ import annotations

import struct
from pathlib import Path, PureWindowsPath

import numpy as np

from .grf import GrfError
from .sprite_reader import decode_frames

HUMAN = 'data\\sprite\\인간족\\'
SEX_FOLDER = {0: '여', 1: '남'}
# Body sprite names are hardcoded in the client (classic kRO names, checked in NRO's GRF).
BODY_NAMES = {0: '초보자', 1: '검사', 2: '마법사', 3: '궁수', 4: '성직자', 5: '상인', 6: '도둑', 7: '기사',
              8: '프리스트', 9: '위저드', 10: '제철공', 11: '헌터', 12: '어세신', 13: '페코페코_기사', 14: '크루세이더',
              15: '몽크', 16: '세이지', 17: '로그', 18: '연금술사', 19: '바드', 20: '무희', 21: '신페코크루세이더',
              22: '결혼', 23: '슈퍼노비스', 24: '건너', 25: '닌자', 26: '산타', 27: '여름',
              4001: '초보자', 4002: '검사', 4003: '마법사', 4004: '궁수', 4005: '성직자', 4006: '상인', 4007: '도둑',
              4008: '로드나이트', 4009: '하이프리', 4010: '하이위저드', 4011: '화이트스미스', 4012: '스나이퍼',
              4013: '어쌔신크로스', 4014: '로드페코', 4015: '팔라딘', 4016: '챔피온', 4017: '프로페서', 4018: '스토커',
              4019: '크리에이터', 4020: '클라운', 4021: '집시', 4022: '페코팔라딘', 4023: '초보자', 4045: '슈퍼노비스',
              4046: '태권소년', 4047: '권성', 4048: '권성융합', 4049: '소울링커'}
IDLE, WALK = 0, 1
# Cell step -> client direction (y grows to the north on the map).
DIRECTIONS = {(0, -1): 0, (-1, -1): 1, (-1, 0): 2, (-1, 1): 3, (0, 1): 4, (1, 1): 5, (1, 0): 6, (1, -1): 7}


RECOVERED = Path(__file__).resolve().parents[1]/'Arquivos_grf'


def read_file(grfs, name):
    """The file the game uses; NRO protects some entries, then a locally extracted copy of the
    same entry, and only then an older readable copy from a lower-priority GRF."""
    key = name.lower()
    if key not in grfs.entries:
        return None
    entries = [grfs.entries[key], *grfs.alternates.get(key, [])]
    for number, entry in enumerate(entries):
        try:
            return grfs.read_entry(entry)
        except GrfError:
            if number:
                continue
        parts = PureWindowsPath(entry.name).parts
        for category in ('outros', 'monstros'):
            copy = RECOVERED/Path(entry.path).name/category/Path(*parts)
            if copy.is_file() and copy.stat().st_size == entry.size:
                return copy.read_bytes()
    return None


def read_pair(grfs, base):
    act, spr = read_file(grfs, f'{base}.act'), read_file(grfs, f'{base}.spr')
    return (act, spr) if act and spr else None


def read_act(data: bytes):
    """[[frame, ...] per action], frame = {'layers': [...], 'anchors': [(x, y)]}; and delays (ms)."""
    if data[:2] != b'AC':
        raise ValueError('ACT invalido')
    version = data[3]*10+data[2]
    count = struct.unpack_from('<H', data, 4)[0]
    pos, actions = 16, []

    def take(fmt):
        nonlocal pos
        values = struct.unpack_from(fmt, data, pos)
        pos += struct.calcsize(fmt)
        return values

    for _ in range(count):
        frames = []
        for _ in range(take('<I')[0]):
            pos += 32  # legacy clipping rectangles
            layers = []
            for _ in range(take('<I')[0]):
                x, y, index, mirror = take('<iiii')
                scale_x = scale_y = 1.0
                kind = 0
                if version >= 20:
                    take('<4B')
                    scale_x = scale_y = take('<f')[0]
                    if version >= 24:
                        scale_y = take('<f')[0]
                    _, kind = take('<ii')
                    if version >= 25:
                        take('<ii')
                layers.append({'x': x, 'y': y, 'index': index, 'mirror': bool(mirror),
                               'scale_x': scale_x, 'scale_y': scale_y, 'type': kind})
            anchors = []
            if version >= 20:
                take('<i')  # sound
            if version >= 23:
                for _ in range(take('<i')[0]):
                    _, ax, ay, _ = take('<iiii')
                    anchors.append((ax, ay))
            frames.append({'layers': layers, 'anchors': anchors})
        actions.append(frames)
    delays = [100.0]*len(actions)
    if version >= 21:
        pos += 40*take('<i')[0]  # sound names
    if version >= 22 and pos+4*len(actions) <= len(data):
        delays = [max(25.0, d*25) for d in struct.unpack_from(f'<{len(actions)}f', data, pos)]
    return actions, delays


def _scaled(image, scale_x, scale_y, mirror):
    if mirror:
        image = image[:, ::-1]
    if (scale_x, scale_y) != (1.0, 1.0) and scale_x > 0 and scale_y > 0:
        height, width = image.shape[:2]
        rows = np.minimum((np.arange(max(1, round(height*scale_y)))/scale_y).astype(int), height-1)
        cols = np.minimum((np.arange(max(1, round(width*scale_x)))/scale_x).astype(int), width-1)
        image = image[rows][:, cols]
    return image


def silhouette(alpha: np.ndarray) -> np.ndarray:
    """Dark translucent body with a soft red rim, as RGBA."""
    mask = np.pad(alpha > 40, 2)
    grown = mask.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        grown |= np.roll(np.roll(mask, dy, 0), dx, 1)
    rim = grown & ~mask
    out = np.zeros(mask.shape+(4,), dtype=np.uint8)
    out[mask] = (24, 18, 36, 150)
    out[rim] = (255, 70, 70, 210)
    return out


class CharacterSprite:
    def __init__(self, body_act, body_spr, head_act=None, head_spr=None):
        self.body, self.delays = read_act(body_act)
        self.body_frames = (decode_frames(body_spr), struct.unpack_from('<H', body_spr, 4)[0])
        self.head = read_act(head_act)[0] if head_act and head_spr else None
        self.head_frames = (decode_frames(head_spr), struct.unpack_from('<H', head_spr, 4)[0]) if self.head else ([], 0)
        self.cache = {}

    @classmethod
    def load(cls, grfs, job, sex, hair=None):
        name, folder = BODY_NAMES.get(job), SEX_FOLDER.get(sex)
        if name is None or folder is None:
            return None
        body = read_pair(grfs, f'{HUMAN}몸통\\{folder}\\{name}_{folder}')
        if body is None:
            return None
        head = read_pair(grfs, f'{HUMAN}머리통\\{folder}\\{hair}_{folder}') if hair else None
        try:
            return cls(*body, *(head or (None, None)))
        except (ValueError, struct.error, IndexError):
            return cls(*body) if head else None

    def frame_count(self, action, direction):
        index = action*8+direction
        return len(self.body[index]) if index < len(self.body) else 0

    def delay(self, action, direction):
        index = action*8+direction
        return self.delays[index] if index < len(self.delays) else 100.0

    def _layers(self, act, sprite, index, frame, shift=(0, 0)):
        if index >= len(act) or not act[index]:
            return [], []
        data = act[index][frame % len(act[index])]
        images, indexed = sprite
        drawn = []
        for layer in data['layers']:
            if layer['index'] < 0:
                continue
            number = layer['index']+(indexed if layer['type'] == 1 else 0)
            if not 0 <= number < len(images):
                continue
            image = _scaled(images[number], layer['scale_x'], layer['scale_y'], layer['mirror'])
            drawn.append((image, layer['x']+shift[0]-image.shape[1]//2, layer['y']+shift[1]-image.shape[0]//2))
        return drawn, data['anchors']

    def shadow(self, action, direction, frame):
        """(RGBA silhouette, feet x, feet y) inside the image, cached per frame."""
        key = (action, direction, frame)
        if key in self.cache:
            return self.cache[key]
        index = action*8+direction
        layers, anchors = self._layers(self.body, self.body_frames, index, frame)
        if self.head:
            head_frame = 0 if action == IDLE else frame
            head_anchors = self.head[index][head_frame % len(self.head[index])]['anchors'] if index < len(self.head) and self.head[index] else []
            shift = (anchors[0][0]-head_anchors[0][0], anchors[0][1]-head_anchors[0][1]) if anchors and head_anchors else (0, 0)
            layers += self._layers(self.head, self.head_frames, index, head_frame, shift)[0]
        if not layers:
            self.cache[key] = None
            return None
        left = min(x for _, x, _ in layers)
        top = min(y for _, _, y in layers)
        width = max(x+img.shape[1] for img, x, _ in layers)-left
        height = max(y+img.shape[0] for img, _, y in layers)-top
        alpha = np.zeros((height, width), dtype=np.uint8)
        for image, x, y in layers:
            area = alpha[y-top:y-top+image.shape[0], x-left:x-left+image.shape[1]]
            np.maximum(area, image[..., 3], out=area)
        result = (silhouette(alpha), -left+2, -top+2)  # silhouette() pads 2 px
        self.cache[key] = result
        return result


def walk_state(motion, now):
    """(action, direction, elapsed ms in the action) from the relay's own_motion."""
    path = (motion or {}).get('path') or []
    speed = (motion or {}).get('speed_ms') or 150
    if motion and motion.get('destination') and len(path) > 1 and motion.get('at') is not None:
        elapsed = (now-motion['at'])*1000
        for start, end in zip(path, path[1:]):
            step = (end[0]-start[0], end[1]-start[1])
            cost = speed*(1.4 if step[0] and step[1] else 1)
            if elapsed < cost:
                return WALK, DIRECTIONS.get((np.sign(step[0]), np.sign(step[1])), 0), (now-motion['at'])*1000
            elapsed -= cost
    return IDLE, None, 0
