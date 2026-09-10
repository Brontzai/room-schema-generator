"""
Мост к CLI `claude`: AI решает ТОЛЬКО раскладку этажей (творческая часть),
всё остальное (лестницы-связность, двери, декор, враги, рендер, проверка
палитры/проходимости) остаётся детерминированным кодом в room_generator.py.

Если claude недоступен / ответил не-JSON / прислал невалидные значения -
вызывающий код обязан откатиться на процедурную генерацию (см.
room_generator.generate_room, source='procedural_fallback').
"""
import json
import re
import subprocess

PROMPT_TEMPLATE = """Ты левел-дизайнер 2D-платформера. Придумай интересную \
раскладку этажей для комнаты шириной {width} и высотой {height} метров \
(x растёт вправо от 0, y растёт вниз от 0; y=0 - потолок, y={h1} - пол).

Верни ТОЛЬКО JSON, без пояснений и без markdown-обрамления, вида:
{{"floors": [{{"y": 14, "x0": 5, "x1": 20, "material": "wall"}}, ...]}}

Правила:
- Первый элемент списка - пол: y={ground_y}, x0=1, x1={max_x}, material="wall".
- Добавь ещё 1-3 этажа выше пола (меньший y), у каждого: 1<=y<={ground_y}-3, \
1<=x0<x1<={max_x}, ширина x1-x0 не меньше 4.
- Разница по y между двумя ближайшими по высоте этажами - минимум 4.
- material каждого доп. этажа - "wall" (сплошной пол) или "platform" \
(тонкая платформа, сквозь неё можно проходить).
- Не описывай периметр комнаты, двери, декор, врагов - только список floors."""


def get_ai_floors(width, height, model='haiku', effort='low', timeout=90):
    """Возвращает (floors, meta) либо (None, meta) с meta['error']."""
    ground_y = height - 2
    max_x = width - 2
    prompt = PROMPT_TEMPLATE.format(width=width, height=height, h1=height - 1,
                                     ground_y=ground_y, max_x=max_x)
    try:
        proc = subprocess.run(
            ['claude', '-p', prompt,
             '--model', model, '--effort', effort,
             '--output-format', 'json',
             '--permission-prompts', 'none'],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return None, {'error': 'claude CLI не найден в PATH'}
    except subprocess.TimeoutExpired:
        return None, {'error': f'claude CLI не ответил за {timeout}с'}

    if proc.returncode != 0:
        return None, {'error': f'claude CLI завершился с ошибкой: {proc.stderr[:300]}'}

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, {'error': 'не удалось разобрать ответ claude (не JSON-конверт)'}

    raw = envelope.get('result', '')
    cost = envelope.get('total_cost_usd')
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return None, {'error': 'AI не вернул JSON с этажами', 'cost_usd': cost}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, {'error': 'AI вернул невалидный JSON', 'cost_usd': cost}

    floors = data.get('floors')
    if not isinstance(floors, list) or not floors:
        return None, {'error': 'AI вернул пустой/некорректный список floors', 'cost_usd': cost}

    return floors, {'cost_usd': cost, 'model': model, 'effort': effort}
