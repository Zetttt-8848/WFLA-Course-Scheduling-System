"""Grade calendars, weekly common courses and exact study loads."""
from collections import Counter, defaultdict
from .schema import TABLES, active_slots, activity_students, slot, room_types


def validate_school(data):
    issues = []
    def error(table, row, field, message):
        issues.append(dict(table=table, sheet=TABLES.get(table,('课表设置',))[0], row=row.get('_row', '网页'), field=field, message=message))
    mode = data['config'].get('scheduling_mode', 'strict')
    if mode not in ('strict', 'flexible'):
        error('config', {}, 'scheduling_mode', '请选择严格区块或灵活并行')
    if mode != 'flexible' and any(data.get(t) for t in ('calendar', 'activities', 'study_rules')):
        error('config', {}, 'scheduling_mode', '年级节次、公共课和自修需要使用灵活并行模式；旧六区块方案仍可单独使用')
        return issues
    if mode == 'flexible' and (data['blocks'] or any(s['block'] for s in data['sections'])):
        error('blocks', {}, 'block', '灵活并行不能同时设置旧式固定六区块，请清空区块时段及教学班区块指定')
    seen = set()
    for row in data.get('calendar', []):
        key = row['grade'], row['day']
        if key in seen or row['grade'] not in (10,11,12) or not 1 <= row['day'] <= data['config']['days'] or not 0 <= row['periods'] <= data['config']['periods_per_day']:
            error('calendar', row, 'periods', '年级/星期/节数无效，或同一天重复设置')
        seen.add(key)
    if issues: return issues
    students = {s['id']: s for s in data['students']}
    teachers = {t['id']: t for t in data['teachers']}
    rooms = {r['id']: r for r in data['rooms']}
    courses = {c['id']: c for c in data['courses']}
    activities = {a['id']: a for a in data.get('activities', [])}
    if len(activities) != len(data.get('activities', [])) or '' in activities:
        error('activities', {}, 'id', '公共课编组编码必须非空且唯一')
    membership_seen = set()
    for row in data.get('activity_members', []):
        key = row['activity'], row['student']
        if row['activity'] not in activities or row['student'] not in students or key in membership_seen:
            error('activity_members', row, 'student', '编组或学生不存在，或重复成员')
        membership_seen.add(key)
    if issues: return issues
    common_load, teacher_load = Counter(), Counter()
    for row in data.get('activities', []):
        members = activity_students(data, row)
        if row['grade'] not in (10,11,12) or row['periods'] < 1 or not members:
            error('activities', row, 'admin_classes', '年级/课时无效，或找不到对应行政班学生')
        if row['teacher'] not in teachers:
            error('activities', row, 'teacher', '请指定实际任教教师或已登记的教师名额')
        if any(students[s]['grade'] != row['grade'] for s in members):
            error('activities', row, 'grade', '公共课包含其他年级学生')
        compatible = [r for r in rooms.values() if row['room_type'] in room_types(r) and r['capacity'] >= len(members) and (not row['room'] or r['id'] == row['room'])]
        if not compatible:
            error('activities', row, 'room', f"{row['name']}（{len(members)}人）无类型和容量均合适的教室")
        for s in members: common_load[s] += row['periods']
        teacher_load[row['teacher']] += row['periods']
    for e in data['events']:
        members = [r['student'] for r in data['event_students'] if r['event'] == e['id']]
        times = set(range(slot(data,e['day'],e['period']), slot(data,e['day'],e['period'])+e['duration']))
        for s in members:
            common_load[s] += e['duration']
            if not times <= set(active_slots(data, students[s]['grade'])):
                error('events', e, 'period', f'活动超出学生 {s} 所在年级的在校节次')
        if e['teacher'] and e['counts_load']: teacher_load[e['teacher']] += e['duration']
    for tid, count in teacher_load.items():
        if tid in teachers and count > teachers[tid]['max_periods']:
            error('teachers', teachers[tid], 'max_periods', f'公共课及固定活动已占{count}节，超过教师周上限')
    for room in rooms.values():
        if room['preference'] < 0: error('rooms', room, 'preference', '使用代价不能为负数')
        rid=room['id'].upper()
        if data['config'].get('school_profile') and len(rid)==4 and rid[0]=='A' and rid[1] in '2345' and rid[2:] in ('02','05'):
            error('rooms',room,'id','该房间为教师办公室，不能作为排课教室')
    rules = {}
    for row in data.get('study_rules', []):
        if row['grade'] in rules or row['grade'] not in (10,11,12) or min(row['periods'],row['unassigned']) < 0:
            error('study_rules', row, 'grade', '年级重复/无效，或课时为负数')
        rules[row['grade']] = row
        names = row['rooms'].split(';') if row['rooms'] else []
        if row['periods'] and not names:
            error('study_rules', row, 'rooms', '请提供自修教室')
        if len(names) != len(set(names)) or any(r not in rooms or '自修' not in room_types(rooms[r]) for r in names):
            error('study_rules', row, 'rooms', '自修教室不存在、重复或缺少自修类型')
    academic = Counter()
    for ch in data['choices']: academic[ch['student']] += courses[ch['course']]['periods']
    for sid, student in students.items():
        available = len(active_slots(data,student['grade']))
        used = academic[sid]+common_load[sid]
        rule = rules.get(student['grade'])
        if rule:
            total = used+rule['periods']+rule['unassigned']
            if total != available:
                error('students', student, 'id', f"{sid}：学科{academic[sid]}＋公共/固定课{common_load[sid]}＋自修{rule['periods']}＋待安排{rule['unassigned']}＝{total}节，年级周课表为{available}节")
        elif used > available:
            error('students', student, 'id', f'{sid}每周需要{used}节，但仅有{available}节')
    return issues
