"""Recompute hard constraints from plain results, without solver expressions."""
from collections import defaultdict, Counter
from .schema import slot, day_period, room_types, active_slots, activity_students
from .validation import validate


def audit(data, result, locks=None):
    problems = ["输入："+e["message"] for e in validate(data)]
    flexible = data['config'].get('scheduling_mode') == 'flexible'
    courses = {c["id"]: c for c in data["courses"]}
    teachers = {t["id"]: t for t in data["teachers"]}
    rooms = {r["id"]: r for r in data["rooms"]}
    students = {s["id"]: s for s in data["students"]}
    sections = {s["id"]: s for s in result.get("sections", [])}
    if len(sections) != len(result.get("sections", [])):
        problems.append("重复教学班编码")
    occupied, banned = {}, set()
    load = Counter()
    memberships, blocks = defaultdict(list), defaultdict(list)
    block_map = {(r["grade"], r["slot"]): r["block"] for r in result.get("block_slots", [])}
    if len(block_map) != len(result.get("block_slots", [])):
        problems.append("区块时段重复")
    for row in data["blocks"]:
        if block_map.get((row["grade"], slot(data, row["day"], row["period"]))) != row["block"]:
            problems.append("预设区块时段被改变")
    for r in data["unavailable"]:
        banned.add((r["kind"], r["resource"], slot(data, r["day"], r["period"])))
    def occupy(kind, resource, start, duration, label):
        for p in range(start, start+duration):
            key = kind, resource, p
            if key in occupied and occupied[key] != label:
                problems.append(f"{kind} {resource} 在 {day_period(data,p)} 冲突：{occupied[key]} / {label}")
            if key in banned:
                problems.append(f"{kind} {resource} 在 {day_period(data,p)} 违反禁排：{label}")
            occupied[key] = label
    for e in data["events"]:
        start = slot(data, e["day"], e["period"])
        members = [r["student"] for r in data["event_students"] if r["event"] == e["id"]]
        if e["room"] and len(members) > rooms[e["room"]]["capacity"]:
            problems.append(f"固定活动 {e['id']} 超出房间容量")
        for kind in ("teacher", "room"):
            if e[kind]:
                occupy(kind, e[kind], start, e["duration"], "活动:"+e["id"])
        for student in members:
            occupy("student", student, start, e["duration"], "活动:"+e["id"])
        if e["teacher"] and e["counts_load"]:
            load[e["teacher"]] += e["duration"]
    quals = {(q["teacher"], q["course"]) for q in data["qualifications"]}
    for sid, section in sections.items():
        if section["course"] not in courses or section["teacher"] not in teachers:
            problems.append(f"{sid} 课程或教师不存在")
            continue
        c = courses[section["course"]]
        if (section["teacher"], c["id"]) not in quals:
            problems.append(f"{sid} 教师资格不符")
        if not section["students"] or len(section["students"]) > c["capacity"]:
            problems.append(f"{sid} 为空班或超班容量")
        if len(set(section["students"])) != len(section["students"]):
            problems.append(f"{sid} 学生名单重复")
        for student in section["students"]:
            memberships[student].append(c["id"])
            blocks[student].append(section["block"])
            if student not in students or students[student]["grade"] != c["grade"]:
                problems.append(f"{sid} 含不存在或不同年级学生")
    for student in students:
        expected = sorted(r["course"] for r in data["choices"] if r["student"] == student)
        if sorted(memberships[student]) != expected:
            problems.append(f"学生 {student} 的课程覆盖不完整或重复")
        if not flexible and sorted(blocks[student]) != [1, 2, 3, 4, 5, 6]:
            problems.append(f"学生 {student} 未恰好覆盖六区块")
    hours, doubles, class_rooms = Counter(), Counter(), defaultdict(set)
    lesson_ids = set()
    for lesson in result.get("lessons", []):
        eid, sid = lesson["id"], lesson["section"]
        if eid in lesson_ids:
            problems.append("课次编码重复："+eid)
        lesson_ids.add(eid)
        if sid not in sections or lesson["room"] not in rooms:
            problems.append(f"{eid} 教学班或教室不存在")
            continue
        s, r = sections[sid], rooms[lesson["room"]]
        if s["course"] not in courses:
            continue
        c = courses[s["course"]]
        start, duration = lesson["start"], lesson["duration"]
        total = data["config"]["days"]*data["config"]["periods_per_day"]
        if duration not in (1, 2) or not 0 <= start <= total-duration:
            problems.append(f"{eid} 非法起点或长度")
            continue
        if day_period(data,start)[0] != day_period(data,start+duration-1)[0] or (duration == 2 and day_period(data,start)[1] in data["config"]["break_after"]):
            problems.append(f"{eid} 连堂跨越不可连边界")
        if lesson["kind"] not in ("lab", "theory"):
            problems.append(f"{eid} 非法课型")
        required = c["lab_type"] if lesson["kind"] == "lab" else c["room_type"]
        if required not in room_types(r) or r["capacity"] < len(s["students"]):
            problems.append(f"{eid} 房间类型不符或容量不足")
        for p in range(start,start+duration):
            if flexible and p not in active_slots(data,c['grade']):
                problems.append(f'{eid} 超出年级在校节次')
            if not flexible and block_map.get((c["grade"],p)) != s["block"]:
                problems.append(f"{eid} 跨出所属区块")
        occupy("section", sid, start, duration, eid)
        occupy("teacher", s["teacher"], start, duration, eid)
        occupy("room", lesson["room"], start, duration, eid)
        for student in s["students"]:
            occupy("student", student, start, duration, eid)
        load[s["teacher"]] += duration
        hours[sid,lesson["kind"]] += duration
        doubles[sid,lesson["kind"]] += duration == 2
        class_rooms[sid].add(lesson["room"])
    if flexible:
        activity_map = {a['id']:a for a in data.get('activities',[])}
        activity_hours, study_hours = Counter(), Counter()
        extra_ids = set(lesson_ids)
        for lesson in result.get('activities',[]):
            aid,eid = lesson.get('activity'),lesson['id']
            if eid in extra_ids: problems.append('重复公共课课次：'+eid)
            extra_ids.add(eid)
            if aid not in activity_map or lesson['room'] not in rooms:
                problems.append('公共课或教室不存在：'+eid); continue
            a = activity_map[aid]; members = activity_students(data,a)
            p = lesson['start']; room = rooms[lesson['room']]
            if lesson['duration'] != 1 or p not in active_slots(data,a['grade']):
                problems.append('公共课起点/时长不合法：'+eid); continue
            if a['room_type'] not in room_types(room) or len(members) > room['capacity'] or (a['room'] and a['room'] != room['id']):
                problems.append('公共课教室类型/容量/指定房间不符：'+eid)
            occupy('room',room['id'],p,1,eid); occupy('teacher',a['teacher'],p,1,eid)
            for sid in members: occupy('student',sid,p,1,eid)
            activity_hours[aid] += 1; load[a['teacher']] += 1
        for aid,a in activity_map.items():
            if activity_hours[aid] != a['periods']: problems.append('公共课课时不达标：'+aid)
        rules = {r['grade']:r for r in data.get('study_rules',[])}
        for lesson in result.get('studies',[]):
            eid,p,rid = lesson['id'],lesson['start'],lesson['room']
            if eid in extra_ids: problems.append('重复自修课次：'+eid)
            extra_ids.add(eid)
            members = lesson['students']
            if rid not in rooms or lesson['duration'] != 1 or not members:
                problems.append('自修房间/时长/成员无效：'+eid); continue
            if len(members) != len(set(members)) or len(members) > rooms[rid]['capacity'] or '自修' not in room_types(rooms[rid]):
                problems.append('自修人数重复、超容量或房间类型错误：'+eid)
            occupy('room',rid,p,1,eid)
            for sid in members:
                if sid not in students:
                    problems.append('自修学生不存在：'+str(sid)); continue
                g = students[sid]['grade']; rule = rules.get(g)
                if not rule or rid not in rule['rooms'].split(';') or p not in active_slots(data,g):
                    problems.append('自修超出年级节次或允许房间：'+sid)
                occupy('student',sid,p,1,eid); study_hours[sid] += 1
        for sid,s in students.items():
            rule = rules.get(s['grade'])
            if rule:
                if study_hours[sid] != rule['periods']: problems.append('自修课时不达标：'+sid)
                free = sum(('student',sid,p) not in occupied for p in active_slots(data,s['grade']))
                if free != rule['unassigned']: problems.append('待安排节数不符：'+sid)
    counts = Counter(r["course"] for r in data["choices"])
    for sid, s in sections.items():
        if s["course"] not in courses:
            continue
        c = courses[s["course"]]
        if hours[sid,"lab"] != c["lab_periods"] or hours[sid,"theory"] != c["periods"]-c["lab_periods"]:
            problems.append(f"{sid} 理论或实验课时不达标")
        if doubles[sid,"lab"] < c["lab_doubles"] or doubles[sid,"theory"] < c["theory_doubles"]:
            problems.append(f"{sid} 必须连堂次数不足")
        if counts[c["id"]] <= 6 and len(class_rooms[sid]) != 1:
            problems.append(f"{sid} mini班未固定教室")
    for tid, t in teachers.items():
        if load[tid] > t["max_periods"]:
            problems.append(f"教师 {tid} 周负荷 {load[tid]} 超过上限 {t['max_periods']}")
    for spec in data["sections"]:
        s = sections.get(spec["id"])
        if not s:
            problems.append("预设教学班丢失："+spec["id"])
            continue
        for f in ("teacher", "block"):
            if spec[f] and s[f] != spec[f]:
                problems.append("预设条件改变："+spec["id"]+" "+f)
        if spec["room"] and class_rooms[spec["id"]] != {spec["room"]}:
            problems.append("固定房间改变："+spec["id"])
    for spec in data["enrollments"]:
        if spec["student"] not in sections.get(spec["section"], {}).get("students", []):
            problems.append("预设分班改变："+spec["student"])
    lessons = {l["id"]: l for l in result.get("lessons", [])}
    for lock in locks or []:
        l = lessons.get(lock["id"])
        if not l or l["start"] != lock["start"] or l["room"] != lock["room"] or sections[l["section"]]["teacher"] != lock["teacher"]:
            problems.append("锁定课次被改变："+lock["id"])
    return problems
