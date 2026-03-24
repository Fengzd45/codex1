import json
import re
import os
from collections import defaultdict, deque
from pathlib import Path

# ======================
# 🔒 部署关键修改：路径兼容 Render
# ======================
DATA_FILE = Path(__file__).parent / 'family_data.jsonl'

UP_ANCESTOR_TERMS = [
    ('祖', '外祖'),
    ('曾祖', '外曾祖'),
    ('高祖', '外高祖'),
    ('天祖', '外天祖'),
    ('烈祖', '外烈祖'),
    ('太祖', '外太祖'),
    ('远祖', '外远祖'),
    ('鼻祖', '外鼻祖'),
]
DOWN_DESCENDANT_TERMS = ['子', '孙', '曾孙', '玄孙', '来孙', '晜孙', '仍孙', '云孙', '耳孙']


def extract_birth_year(info: str):
    if not info:
        return None
    matches = re.findall(r'(1\d{3}|20\d{2})年', info)
    years = [int(y) for y in matches]
    if not years:
        return None
    born_index = info.find('出生')
    if born_index != -1:
        before_born = re.findall(r'(1\d{3}|20\d{2})年', info[: born_index + 2])
        if before_born:
            return int(before_born[-1])
    return years[0]


def normalize_spouse(value):
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str):
        return [value] if value else []
    return []


def load_family_data(path: Path):
    people = {}
    with path.open('r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            name = raw.get('n', '').strip()
            if not name:
                continue
            people[name] = {
                'name': name,
                'sex': raw.get('s', '').strip(),
                'father': raw.get('f', '').strip(),
                'mother': raw.get('m', '').strip(),
                'spouse': normalize_spouse(raw.get('sp', [])),
                'info': raw.get('info', '').strip(),
                'birth_year': extract_birth_year(raw.get('info', '').strip()),
                'children': [],
                'parents': [],
            }

    for person in people.values():
        for parent_key in ('father', 'mother'):
            parent = person[parent_key]
            if parent and parent in people:
                people[parent]['children'].append(person['name'])
        person['parents'] = [p for p in (person['father'], person['mother']) if p]

    for person in people.values():
        unique_children = list(dict.fromkeys(person['children']))
        unique_children.sort(key=lambda child_name: (
            people[child_name]['birth_year'] is None,
            people[child_name]['birth_year'] if people[child_name]['birth_year'] is not None else float('inf'),
            child_name,
        ))
        person['children'] = unique_children
        person['spouse'] = [sp for sp in dict.fromkeys(person['spouse']) if sp]

    return people


def bfs_relationships(people, start):
    queue = deque([(start, 0, [])])
    visited = {start}
    found = []
    while queue:
        current, generation_diff, ops = queue.popleft()
        if current != start:
            found.append((current, generation_diff, ops))
        person = people[current]
        neighbors = []
        if person['father']:
            neighbors.append((person['father'], 'f', generation_diff + 1))
        if person['mother']:
            neighbors.append((person['mother'], 'm', generation_diff + 1))
        for spouse in person['spouse']:
            neighbors.append((spouse, 'sp', generation_diff))
        for child in person['children']:
            neighbors.append((child, 'ch', generation_diff - 1))

        for next_name, op, next_diff in neighbors:
            if next_name not in people or next_name in visited:
                continue
            visited.add(next_name)
            queue.append((next_name, next_diff, ops + [op]))
    return found


def is_older(a, b):
    ay = a.get('birth_year')
    by = b.get('birth_year')
    return ay is not None and by is not None and ay < by


def is_younger(a, b):
    ay = a.get('birth_year')
    by = b.get('birth_year')
    return ay is not None and by is not None and ay > by


def sibling_term(start_person, target_person):
    if target_person['sex'] == '男':
        if is_older(target_person, start_person):
            return '兄'
        if is_younger(target_person, start_person):
            return '弟'
        return '兄弟'
    if target_person['sex'] == '女':
        if is_older(target_person, start_person):
            return '姐'
        if is_younger(target_person, start_person):
            return '妹'
        return '姐妹'
    return '兄弟姐妹'


def spouse_sibling_term(start_person, target_person):
    if target_person['sex'] == '男':
        if start_person['sex'] == '男':
            if is_older(target_person, start_person):
                return '内兄'
            if is_younger(target_person, start_person):
                return '内弟'
            return '内兄弟'
        return '大伯子'
    if target_person['sex'] == '女':
        if start_person['sex'] == '男':
            if is_older(target_person, start_person):
                return '内姐'
            if is_younger(target_person, start_person):
                return '内妹'
            return '内姐妹'
        return '大姑子'
    return '内亲'


def direct_ancestor_term(path_ops, target_person):
    first = path_ops[0]
    is_maternal = first == 'm'
    up = len(path_ops)
    if up == 1:
        if target_person['sex'] == '男':
            return '父亲' if first == 'f' else '母亲的丈夫'
        return '母亲' if first == 'm' else '父亲的妻子'
    if up == 2:
        if target_person['sex'] == '男':
            return '外祖父' if is_maternal else '祖父'
        return '外祖母' if is_maternal else '祖母'
    idx = min(up - 2, len(UP_ANCESTOR_TERMS) - 1)
    male_term, female_term = UP_ANCESTOR_TERMS[idx]
    return female_term if is_maternal else male_term


def direct_descendant_term(path_ops, target_person):
    down = len(path_ops)
    idx = min(down - 1, len(DOWN_DESCENDANT_TERMS) - 1)
    base = DOWN_DESCENDANT_TERMS[idx]
    if down == 1:
        return '儿子' if target_person['sex'] == '男' else '女儿'
    if down == 2:
        return '孙' if target_person['sex'] == '男' else '孙女'
    if target_person['sex'] == '女' and base.endswith('孙'):
        return base + '女'
    return base


def get_parent_side_label(first_up, target_person):
    if first_up == 'f':
        return '姑母' if target_person['sex'] == '女' else '伯父/叔父'
    return '姨母' if target_person['sex'] == '女' else '舅父'


def get_nephew_niece_term(start_person, sibling_person, target_person):
    if sibling_person['sex'] == '男':
        return '侄' if target_person['sex'] == '男' else '侄女'
    return '甥' if target_person['sex'] == '男' else '外甥女'


def affine_elder_term(start_person, target_person, path_ops):
    up = sum(1 for op in path_ops[1:] if op in {'f', 'm'})
    if up == 1:
        if start_person['sex'] == '男':
            if target_person['sex'] == '男':
                return '岳父'
            return '岳母'
        if target_person['sex'] == '男':
            return '公公'
        return '婆婆'
    if up >= 2:
        prefix = '妻家' if start_person['sex'] == '男' else '夫家'
        return f'{prefix}长辈'
    return '内亲长辈'


def get_relationship(people, start, target, path_ops):
    start_person = people[start]
    target_person = people[target]

    if path_ops == ['sp']:
        return '配偶'

    if path_ops == ['ch', 'sp']:
        return '女婿' if target_person['sex'] == '男' else '儿媳'

    if path_ops in (['ch', 'sp', 'f'], ['ch', 'sp', 'm']):
        return '亲家公' if target_person['sex'] == '男' else '亲家母'

    if len(path_ops) > 3 and path_ops[:2] == ['ch', 'sp'] and path_ops[2] in {'f', 'm'}:
        base = get_relationship(people, start, target, path_ops[2:])
        return f'亲家{base}'

    if path_ops and path_ops[0] == 'sp' and 'ch' not in path_ops[1:]:
        if all(op in {'f', 'm'} for op in path_ops[1:]):
            return affine_elder_term(start_person, target_person, path_ops)
        if len(path_ops) == 3 and path_ops[1] in {'f', 'm'} and path_ops[2] == 'ch':
            return spouse_sibling_term(start_person, target_person)
        return f'内{get_relationship(people, start, target, path_ops[1:])}' if len(path_ops) > 1 else '配偶'

    if path_ops and all(op in {'f', 'm'} for op in path_ops):
        return direct_ancestor_term(path_ops, target_person)

    if path_ops and all(op == 'ch' for op in path_ops):
        return direct_descendant_term(path_ops, target_person)

    up_steps = sum(1 for op in path_ops if op in {'f', 'm'})
    down_steps = path_ops.count('ch')
    has_sp = 'sp' in path_ops

    if not has_sp and up_steps == 2 and down_steps == 1 and len(path_ops) == 3:
        return get_parent_side_label(path_ops[0], target_person)

    if not has_sp and up_steps == 1 and down_steps == 2 and len(path_ops) == 3:
        sibling_name = None
        current = start
        for op in path_ops:
            person = people[current]
            if op == 'f':
                current = person['father']
            elif op == 'm':
                current = person['mother']
            elif op == 'ch':
                current = person['children'][0] if person['children'] else current
            if current == target:
                break
            sibling_name = current
        if sibling_name and sibling_name in people:
            return get_nephew_niece_term(start_person, people[sibling_name], target_person)
        return '晚辈旁系'

    if not has_sp and up_steps == down_steps:
        if up_steps == 1 and down_steps == 1:
            return sibling_term(start_person, target_person)
        first = path_ops[0]
        mapping = {'f': '堂', 'm': '姨表'}
        prefix = mapping.get(first, '表')
        if any(op == 'm' for op in path_ops[:up_steps]) and first == 'f':
            prefix = '姑表'
        elif first == 'm' and path_ops[1:up_steps].count('f'):
            prefix = '舅表'
        return f'{prefix}亲'

    if not has_sp:
        diff = up_steps - down_steps
        if diff > 0:
            return '血亲长辈'
        if diff == 0:
            return '血亲平辈'
        return '血亲晚辈'

    if path_ops and path_ops[-1] == 'sp' and path_ops.count('sp') == 1:
        prefix_rel = get_relationship(people, start, start if target == start else target, path_ops[:-1]) if path_ops[:-1] else ''
        if path_ops[:-1] == ['f', 'ch'] or path_ops[:-1] == ['m', 'ch']:
            if target_person['sex'] == '女':
                return '嫂' if is_older(people[target], start_person) else '弟媳'
            return '姐夫' if is_older(people[target], start_person) else '妹夫'
        if path_ops[:-1] == ['ch']:
            return '女婿' if target_person['sex'] == '男' else '儿媳'
        return f'{prefix_rel or "亲属"}的配偶'

    if path_ops.count('sp') >= 2:
        return '姻亲的亲属'
    return '姻亲'


def resolve_path_person(people, start, path_ops):
    current = start
    traversed = [start]
    for op in path_ops:
        person = people[current]
        if op == 'f':
            current = person['father']
        elif op == 'm':
            current = person['mother']
        elif op == 'sp':
            current = person['spouse'][0] if person['spouse'] else current
        elif op == 'ch':
            current = person['children'][0] if person['children'] else current
        traversed.append(current)
    return traversed


def classify_branch(path_ops):
    if not path_ops:
        return '同辈'
    first = path_ops[0]
    return {
        'f': '父系',
        'm': '母系',
        'sp': '配偶系',
        'ch': '子女系',
    }.get(first, '其他')


def format_person_line(people, name, relationship):
    person = people[name]
    detail = person['info'] or '信息不详'
    spouse_bits = []
    for spouse_name in person['spouse']:
        spouse = people.get(spouse_name)
        if not spouse:
            continue
        tag = '夫' if spouse['sex'] == '男' else '配'
        spouse_bits.append(f"{tag} {spouse_name}({spouse['info'] or '信息不详'})")
    suffix = f" {'；'.join(spouse_bits)}" if spouse_bits else ''
    return f"{relationship} {name}({detail}){suffix}"


def group_key_for_path(people, start, path_ops):
    if not path_ops:
        return None
    if len(path_ops) >= 5:
        return None
    branch = classify_branch(path_ops)
    if branch == '父系':
        parent_names = [people[start]['father']] if people[start]['father'] else []
    elif branch == '母系':
        parent_names = [people[start]['mother']] if people[start]['mother'] else []
    elif branch == '配偶系':
        spouse_name = people[start]['spouse'][0] if people[start]['spouse'] else ''
        spouse = people.get(spouse_name, {})
        parent_names = [spouse.get('father', ''), spouse.get('mother', '')]
    elif branch == '子女系':
        child_name = next((c for c in people[start]['children']), '')
        child = people.get(child_name, {})
        parent_names = [child.get('father', ''), child.get('mother', '')]
    else:
        parent_names = []
    parent_names = [p for p in parent_names if p]
    if not parent_names:
        return None
    if len(parent_names) == 1:
        return f'【家庭 {parent_names[0]}】'
    return f'【家庭 {parent_names[0]} & {parent_names[1]}】'


def print_relationships(people, start):
    found = bfs_relationships(people, start)
    layered = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    direct_high = defaultdict(list)

    for target, generation_diff, path_ops in found:
        relation = get_relationship(people, start, target, path_ops)
        line = format_person_line(people, target, relation)
        branch = classify_branch(path_ops)
        layer_name = '同辈' if generation_diff == 0 else (f'上{generation_diff}辈' if generation_diff > 0 else f'下{abs(generation_diff)}辈')
        if abs(generation_diff) >= 5:
            direct_high[layer_name].append((branch, line))
            continue
        group = group_key_for_path(people, start, path_ops) or '【未分组】'
        layered[layer_name][branch][group].append((target, line, path_ops))

    def layer_sort_key(layer):
        if layer == '同辈':
            return (1, 0)
        if layer.startswith('上'):
            return (0, int(re.findall(r'\d+', layer)[0]))
        return (2, int(re.findall(r'\d+', layer)[0]))

    branch_order = ['父系', '母系', '配偶系', '子女系', '其他']

    print(f'\n【{start} 的亲属关系】')
    empty = True
    for layer in sorted(set(layered) | set(direct_high), key=layer_sort_key):
        has_content = layer in direct_high or any(layered[layer][b] for b in layered[layer])
        if not has_content:
            continue
        empty = False
        print(f'\n=== {layer} ===')
        if layer in direct_high:
            for branch, line in sorted(direct_high[layer], key=lambda x: (branch_order.index(x[0]) if x[0] in branch_order else 99, x[1])):
                print(f'[{branch}] {line}')
        for branch in branch_order:
            groups = layered[layer].get(branch)
            if not groups:
                continue
            print(f'\n[{branch}]')
            for group_name, items in groups.items():
                if group_name != '【未分组】':
                    print(group_name)
                for _, line, _ in sorted(items, key=lambda item: (
                    people[item[0]]['birth_year'] is None,
                    people[item[0]]['birth_year'] if people[item[0]]['birth_year'] is not None else float('inf'),
                    item[0],
                )):
                    print(f'  - {line}')
    if empty:
        print('未找到其他亲属。')


def main():
    if not DATA_FILE.exists():
        print(f"⚠️  未找到数据文件: {DATA_FILE}")
        return
        
    people = load_family_data(DATA_FILE)
    print(f'总记录数：{len(people)}')
    
    # ======================
    # 🚀 Render 启动后自动运行示例（不会卡住部署）
    # ======================
    if people:
        first_person = next(iter(people.keys()))
        print(f"\n🎯 默认展示第一位：{first_person}")
        print_relationships(people, first_person)

if __name__ == '__main__':
    main()
