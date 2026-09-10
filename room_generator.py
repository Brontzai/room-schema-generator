"""
Процедурный генератор pixel-perfect схем игровых комнат.

Подход: НЕ генеративный image-AI (нарушил бы pixel-perfect / фиксированную
палитру), а классическая процедурная генерация (layered platformer level:
этажи + лестницы) с гарантией связности по построению + пост-проверкой.

Легенда (см. ТЗ):
  черный    (0,0,0)      - стены/пол/потолок, любая форма
  голубой   (60,180,255) - тонкая платформа (проходима насквозь), высота 1м
  коричневый(139,90,43)  - лестница, ширина 1м, любая высота
  желтый    (255,210,0)  - дверь, 3м высота x 1м ширина
  розовый   (255,120,170)- разрушаемый декор: 1x1,1x2,2x1,2x2,3x3,4x3
  красный   (230,40,40)  - враг 1x1, на земле или летающий
  фон/воздух(255,255,255)- пусто (в легенде не задан, подразумевается)

Запуск:
  python3 room_generator.py --count 3 --seed 1
"""
import argparse
import random
from PIL import Image

BLACK = (0, 0, 0)
PLATFORM = (60, 180, 255)
LADDER = (139, 90, 43)
DOOR = (255, 210, 0)
DECOR = (255, 120, 170)
ENEMY = (230, 40, 40)
BG = (255, 255, 255)

ALLOWED_COLORS = {BLACK, PLATFORM, LADDER, DOOR, DECOR, ENEMY, BG}

DECOR_SIZES = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 3), (4, 3)]


class Room:
    def __init__(self, width=32, height=18, rng=None):
        self.w = width
        self.h = height
        self.rng = rng or random.Random()
        # tile[y][x] = None | 'wall' | 'platform' | 'ladder' | 'door'
        self.tile = [[None for _ in range(width)] for _ in range(height)]
        self.decor = []   # (x, y, w, h)
        self.enemies = [] # (x, y, 'ground'|'flying')
        self.floors = []  # list of dict(y, x0, x1, material)

    # ---------- построение ----------

    def build_border(self):
        for x in range(self.w):
            self.tile[0][x] = 'wall'
            self.tile[self.h - 1][x] = 'wall'
        for y in range(self.h):
            self.tile[y][0] = 'wall'
            self.tile[y][self.w - 1] = 'wall'

    def build_floors(self):
        rng = self.rng
        interior_x0, interior_x1 = 1, self.w - 2
        # земля
        ground_y = self.h - 2
        self.floors.append(dict(y=ground_y, x0=interior_x0, x1=interior_x1,
                                 material='wall'))
        for x in range(interior_x0, interior_x1 + 1):
            self.tile[ground_y][x] = 'wall'

        # 1-3 дополнительных этажа снизу вверх
        n_extra = rng.randint(1, 3)
        min_gap = 4  # запас под лестницу/дверь высотой 3
        available_top = 1
        ys = []
        cur = ground_y
        for _ in range(n_extra):
            cur -= rng.randint(min_gap, min_gap + 2)
            if cur <= available_top + 1:
                break
            ys.append(cur)

        for y in ys:
            seg_w = rng.randint(max(4, (interior_x1 - interior_x0) // 3),
                                 interior_x1 - interior_x0)
            x0 = rng.randint(interior_x0, interior_x1 - seg_w)
            x1 = x0 + seg_w
            material = rng.choice(['wall', 'platform'])
            self.floors.append(dict(y=y, x0=x0, x1=x1, material=material))
            for x in range(x0, x1 + 1):
                self.tile[y][x] = material

        # сортируем снизу вверх (по убыванию y)
        self.floors.sort(key=lambda f: -f['y'])

    def build_floors_from_plan(self, floors_spec):
        """Как build_floors(), но раскладка этажей приходит извне
        (от AI), уже провалидированная sanitize_ai_floors()."""
        for f in floors_spec:
            self.floors.append(dict(f))
            for x in range(f['x0'], f['x1'] + 1):
                self.tile[f['y']][x] = f['material']
        self.floors.sort(key=lambda f: -f['y'])

    def connect_floors_with_ladders(self):
        """Соединяем соседние по высоте этажи лестницей.
        Если x-диапазоны не пересекаются - расширяем нижний этаж,
        чтобы пересечение гарантированно появилось (гарантия связности
        по построению, а не только проверкой постфактум)."""
        rng = self.rng
        for i in range(len(self.floors) - 1):
            lower = self.floors[i]
            upper = self.floors[i + 1]
            lo_x0, lo_x1 = lower['x0'], lower['x1']
            up_x0, up_x1 = upper['x0'], upper['x1']
            ov0, ov1 = max(lo_x0, up_x0), min(lo_x1, up_x1)
            if ov0 > ov1:
                # нет пересечения - расширяем нижний этаж до края верхнего
                target = up_x0 if up_x0 < lo_x0 else up_x1
                lo_x0, lo_x1 = min(lo_x0, target), max(lo_x1, target)
                lower['x0'], lower['x1'] = lo_x0, lo_x1
                if lower['material'] is not None:
                    for x in range(lo_x0, lo_x1 + 1):
                        if self.tile[lower['y']][x] is None:
                            self.tile[lower['y']][x] = lower['material']
                ov0, ov1 = max(lo_x0, up_x0), min(lo_x1, up_x1)
            lx = rng.randint(ov0, ov1)
            # лестница пробивает сплошной пол верхнего этажа (upper['y'])
            # насквозь - иначе между верхом лестницы и зоной для стойки
            # остаётся непроходимая плита пола.
            for y in range(upper['y'], lower['y']):
                self.tile[y][lx] = 'ladder'

    def add_doors(self, n_doors=1):
        rng = self.rng
        placed = 0
        attempts = 0
        while placed < n_doors and attempts < 30:
            attempts += 1
            floor = rng.choice(self.floors)
            side = rng.choice(['left', 'right'])
            fx = floor['x0'] if side == 'left' else floor['x1']
            wall_x = 0 if side == 'left' else self.w - 1
            fy = floor['y']
            # дверь занимает 3 клетки по высоте, встроена в стену
            top = fy - 3
            if top < 1:
                continue
            # дотягиваем этаж вплотную к стене, чтобы дверь была достижима
            if side == 'left':
                for x in range(1, fx + 1):
                    if self.tile[fy][x] is None:
                        self.tile[fy][x] = floor['material']
                floor['x0'] = min(floor['x0'], 1)
            else:
                for x in range(fx, self.w - 1):
                    if self.tile[fy][x] is None:
                        self.tile[fy][x] = floor['material']
                floor['x1'] = max(floor['x1'], self.w - 2)
            for y in range(top, fy):
                self.tile[y][wall_x] = 'door'
            placed += 1

    def _floor_walk_cells(self, floor):
        """Свободные клетки-платформы этажа (воздух над полом).
        Разрушаемый декор (destructible) не считается жёстким блокером
        связности - декор разбиваем, поэтому клетка под ним всё ещё
        засчитывается как проходимая."""
        y = floor['y']
        cells = []
        for x in range(floor['x0'], floor['x1'] + 1):
            if self.tile[y][x] in ('wall', 'platform') and self.tile[y - 1][x] in (None, 'decor', 'enemy'):
                cells.append(x)
        return cells

    def add_decor(self, max_pieces=4):
        rng = self.rng
        placed = 0
        attempts = 0
        while placed < max_pieces and attempts < 40:
            attempts += 1
            floor = rng.choice(self.floors)
            y = floor['y']
            dw, dh = rng.choice(DECOR_SIZES)
            walk = self._floor_walk_cells(floor)
            if len(walk) < dw + 2:  # оставляем минимум проход
                continue
            x0 = rng.choice(walk[: max(1, len(walk) - dw)])
            cells = list(range(x0, x0 + dw))
            if not all(c in walk for c in cells):
                continue
            # не ставим прямо на лестницу/дверь и оставляем проход хотя бы 2 клеток
            free_after = [c for c in walk if c not in cells]
            if len(free_after) < 2:
                continue
            ok = True
            for yy in range(y - dh, y):
                for xx in cells:
                    if self.tile[yy][xx] is not None:
                        ok = False
            if not ok:
                continue
            for yy in range(y - dh, y):
                for xx in cells:
                    self.tile[yy][xx] = 'decor'
            self.decor.append((x0, y - dh, dw, dh))
            placed += 1

    def add_enemies(self, max_enemies=4):
        rng = self.rng
        placed = 0
        attempts = 0
        while placed < max_enemies and attempts < 40:
            attempts += 1
            kind = rng.choice(['ground', 'flying'])
            if kind == 'ground':
                floor = rng.choice(self.floors)
                walk = [c for c in self._floor_walk_cells(floor)
                        if self.tile[floor['y'] - 1][c] is None]
                if not walk:
                    continue
                x = rng.choice(walk)
                y = floor['y'] - 1
            else:
                x = rng.randint(2, self.w - 3)
                y = rng.randint(2, self.h - 3)
            if self.tile[y][x] is not None:
                continue
            self.tile[y][x] = 'enemy'
            self.enemies.append((x, y, kind))
            placed += 1

    # ---------- проверка ----------

    def check_connectivity(self):
        """BFS по клеткам-стойкам (воздух с полом снизу) + лестницы.
        Возвращает True если все этажи находятся в одной компоненте."""
        stand = set()
        for f in self.floors:
            for x in self._floor_walk_cells(f):
                stand.add((x, f['y'] - 1))
        ladder_cols = {}
        for y in range(self.h):
            for x in range(self.w):
                if self.tile[y][x] == 'ladder':
                    ladder_cols.setdefault(x, []).append(y)

        if not stand:
            return False
        start = next(iter(stand))
        seen = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            neighbors = [(x - 1, y), (x + 1, y)]
            if x in ladder_cols:
                for ly in ladder_cols[x]:
                    neighbors.append((x, ly - 1))
                    neighbors.append((x, ly + 1))
            for nx, ny in neighbors:
                if 0 <= nx < self.w and 0 <= ny < self.h and (nx, ny) not in seen:
                    if (nx, ny) in stand or self.tile[ny][nx] == 'ladder' \
                            or (ny + 1 < self.h and self.tile[ny + 1][nx] == 'ladder'):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
        return len(seen & stand) == len(stand)

    def check_palette(self, img):
        colors = set(img.getdata())
        return colors <= ALLOWED_COLORS

    # ---------- рендер ----------

    def render(self):
        img = Image.new('RGB', (self.w, self.h), BG)
        px = img.load()
        color_map = {'wall': BLACK, 'platform': PLATFORM, 'ladder': LADDER,
                     'door': DOOR, 'decor': DECOR, 'enemy': ENEMY}
        for y in range(self.h):
            for x in range(self.w):
                t = self.tile[y][x]
                if t:
                    px[x, y] = color_map[t]
        return img


def sanitize_ai_floors(floors_spec, width, height):
    """Приводит присланный AI список этажей к гарантированно валидному
    виду (тот же контракт, что и процедурный build_floors): корректные
    границы, минимальная ширина, минимальный вертикальный зазор, всегда
    есть пол. Ничего не отбрасывает молча без причины - просто чинит."""
    max_x = width - 2
    ground_y = height - 2
    cleaned = []
    for f in floors_spec:
        try:
            y = int(f['y'])
            x0 = int(f['x0'])
            x1 = int(f['x1'])
            material = f.get('material') if f.get('material') in ('wall', 'platform') else 'wall'
        except (KeyError, TypeError, ValueError):
            continue
        x0, x1 = sorted((x0, x1))
        x0 = max(1, min(x0, max_x - 4))
        x1 = max(x0 + 4, min(x1, max_x))
        y = max(1, min(y, ground_y))
        cleaned.append(dict(y=y, x0=x0, x1=x1, material=material))

    if not cleaned:
        return None

    # гарантируем пол
    has_ground = any(f['y'] == ground_y for f in cleaned)
    if not has_ground:
        cleaned.append(dict(y=ground_y, x0=1, x1=max_x, material='wall'))
    cleaned.sort(key=lambda f: -f['y'])

    # разводим этажи, которые AI поставил слишком близко друг к другу
    result = [cleaned[0]]
    for f in cleaned[1:]:
        prev = result[-1]
        if prev['y'] - f['y'] < 4:
            continue  # слишком близко к уже принятому - пропускаем
        result.append(f)
    return result


def generate_room(width, height, seed, doors=None, decor=None, enemies=None,
                   use_ai=False, model='haiku', effort='low'):
    rng = random.Random(seed)
    ai_meta = {'source': 'procedural'}

    ai_floors = None
    if use_ai:
        from ai_layout import get_ai_floors
        raw_floors, meta = get_ai_floors(width, height, model=model, effort=effort)
        if raw_floors is not None:
            ai_floors = sanitize_ai_floors(raw_floors, width, height)
        ai_meta = {'source': 'ai' if ai_floors else 'procedural_fallback', **meta}

    for attempt in range(10):
        r = Room(width, height, rng)
        r.build_border()
        if ai_floors:
            r.build_floors_from_plan(ai_floors)
        else:
            r.build_floors()
        r.connect_floors_with_ladders()
        r.add_doors(n_doors=doors if doors is not None else rng.randint(1, 2))
        r.add_decor(max_pieces=decor if decor is not None else rng.randint(2, 5))
        r.add_enemies(max_enemies=enemies if enemies is not None else rng.randint(2, 5))
        if r.check_connectivity():
            return r, attempt + 1, ai_meta
        if ai_floors:
            # план от AI не дал связной комнаты даже после лестниц (не
            # должно случаться благодаря sanitize, но перестрахуемся) -
            # откатываемся на процедурную генерацию для этой комнаты.
            ai_floors = None
            ai_meta = {'source': 'procedural_fallback', 'error': 'ai-план не прошёл проверку связности', **ai_meta}
    return r, 10, ai_meta  # отдаём последнюю попытку как есть


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=3)
    ap.add_argument('--width', type=int, default=32, help='ширина комнаты, м')
    ap.add_argument('--height', type=int, default=18, help='высота комнаты, м')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--doors', type=int, default=None, help='кол-во дверей (по умолчанию случайно 1-2)')
    ap.add_argument('--decor', type=int, default=None, help='кол-во объектов декора (по умолчанию 2-5)')
    ap.add_argument('--enemies', type=int, default=None, help='кол-во врагов (по умолчанию 2-5)')
    ap.add_argument('--scale', type=int, default=16, help='для превью PNG')
    ap.add_argument('--out', type=str, default='.')
    ap.add_argument('--ai', action='store_true', help='отдать раскладку этажей claude CLI вместо процедурной генерации')
    ap.add_argument('--model', type=str, default='haiku', help='haiku|sonnet|opus|fable (только с --ai)')
    ap.add_argument('--effort', type=str, default='low', help='low|medium|high|xhigh|max (только с --ai)')
    args = ap.parse_args()

    for i in range(args.count):
        seed = args.seed + i
        room, attempts, ai_meta = generate_room(
            args.width, args.height, seed,
            doors=args.doors, decor=args.decor, enemies=args.enemies,
            use_ai=args.ai, model=args.model, effort=args.effort)
        img = room.render()
        ok_palette = room.check_palette(img)
        ok_conn = room.check_connectivity()

        native_path = f'{args.out}/room_{i + 1}.png'
        preview_path = f'{args.out}/room_{i + 1}_preview.png'
        img.save(native_path)
        img.resize((room.w * args.scale, room.h * args.scale), Image.NEAREST).save(preview_path)

        cost = ai_meta.get('cost_usd')
        cost_str = f" cost=${cost:.4f}" if cost else ""
        print(f'room_{i + 1}: seed={seed} size={room.w}x{room.h} '
              f'floors={len(room.floors)} decor={len(room.decor)} '
              f'enemies={len(room.enemies)} attempts={attempts} '
              f'palette_ok={ok_palette} connectivity_ok={ok_conn} '
              f'source={ai_meta["source"]}{cost_str}')


if __name__ == '__main__':
    main()
