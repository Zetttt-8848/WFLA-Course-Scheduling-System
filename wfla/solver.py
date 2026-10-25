"""Unified CP-SAT model: student sections, six blocks, teachers and rooms."""
from collections import defaultdict, Counter
import math
import time
from ortools.sat.python import cp_model
from .schema import slot, day_period, room_types
from .validation import validate


def fixed_occupancy(data):
    busy = defaultdict(list)
    for row in data["unavailable"]:
        busy[row["kind"], row["resource"]].append((slot(data, row["day"], row["period"]), 1, row["reason"] or "禁排"))
    members = defaultdict(list)
    for row in data["event_students"]:
        members[row["event"]].append(row["student"])
    for e in data["events"]:
        start = slot(data, e["day"], e["period"])
        for kind in ("teacher", "room"):
            if e[kind]:
                busy[kind, e[kind]].append((start, e["duration"], e["id"]))
        for sid in members[e["id"]]:
            busy["student", sid].append((start, e["duration"], e["id"]))
    return busy


def course_sessions(course):
    events = []
    for kind, total, doubles in (("lab", course["lab_periods"], course["lab_doubles"]),
                                 ("theory", course["periods"]-course["lab_periods"], course["theory_doubles"])):
        events.extend([(kind, 2)]*doubles)
        events.extend([(kind, 1)]*(total-2*doubles))
    return events


def candidates(data):
    counts = Counter(r["course"] for r in data["choices"])
    result, limits = [], []
    for c in data["courses"]:
        n = counts[c["id"]]
        if not n:
            continue
        cap = c["capacity"]
        for kind, length in course_sessions(c):
            room_kind = c["lab_type"] if kind == "lab" else c["room_type"]
            cap = min(cap, max(r["capacity"] for r in data["rooms"] if room_kind in room_types(r)))
        prescribed = [r for r in data["sections"] if r["course"] == c["id"]]
        lower = math.ceil(n/cap)
        upper = c["max_sections"] or max(lower+1, len(prescribed))
        upper = min(n, upper)
        limits.append({"course": c["id"], "lower": lower, "upper": upper,
                       "automatic_limit": not bool(c["max_sections"])})
        used_ids = {r["id"] for r in data["sections"]}
        for j in range(max(upper, len(prescribed))):
            if j < len(prescribed):
                r = dict(prescribed[j])
            else:
                name = f"{c['id']}__{j+1}"
                while name in used_ids:
                    name += "_"
                used_ids.add(name)
                r = {"id": name, "course": c["id"], "teacher": "", "room": "", "block": 0}
            r.update(capacity=cap, mandatory=j < len(prescribed), mini=n <= 6)
            result.append(r)
    return result, limits


def solve(data, seconds=60, locks=None):
    if data.get("config", {}).get("scheduling_mode") == "flexible":
        from .flex_solver import solve_flexible
        return solve_flexible(data, seconds, locks)
    began = time.monotonic()
    errors = validate(data)
    if errors:
        return {"status": "INVALID_DATA", "message": "数据校验未通过", "issues": errors}
    locks = locks or []
    sections, limits = candidates(data)
    m = cp_model.CpModel()
    total = data["config"]["days"]*data["config"]["periods_per_day"]
    courses = {r["id"]: r for r in data["courses"]}
    teachers = {r["id"]: r for r in data["teachers"]}
    rooms = {r["id"]: r for r in data["rooms"]}
    grades = sorted({s["grade"] for s in data["students"]})
    block_vars = {}
    for grade in grades:
        rows = [r for r in data["blocks"] if r["grade"] == grade]
        preset = {slot(data, r["day"], r["period"]): r["block"] for r in rows}
        block_vars[grade] = [m.new_int_var(preset.get(p, 0), preset.get(p, 0), f"b{grade}_{p}")
                              if rows else m.new_int_var(0, 6, f"b{grade}_{p}") for p in range(total)]
    busy = fixed_occupancy(data)
    resources = defaultdict(list)
    for resource, records in busy.items():
        # Availability bans may overlap each other; a union is one unavailable window.
        forbidden = {p for start, length, _ in records for p in range(start, start+length)}
        for p in forbidden:
            resources[resource].append(m.new_fixed_size_interval_var(p, 1, "reserved"))
    av, bv, enroll, teacher_choice, events = {}, {}, {}, {}, []
    section_by_course = defaultdict(list)
    section_intervals = defaultdict(list)
    loads = defaultdict(list)
    windows = defaultdict(list)
    for section in sections:
        cid, sid = section["course"], section["id"]
        c = courses[cid]
        section_by_course[cid].append(sid)
        a = av[sid] = m.new_bool_var("active_"+sid)
        b = bv[sid] = m.new_int_var(1, 6, "block_"+sid)
        if section["mandatory"]:
            m.add(a == 1)
        if section["block"]:
            m.add(b == section["block"])
        learners = sorted(r["student"] for r in data["choices"] if r["course"] == cid)
        assignments = []
        for student in learners:
            v = enroll[student, sid] = m.new_bool_var("member_"+student+"_"+sid)
            m.add(v <= a)
            assignments.append(v)
        size = m.new_int_var(0, section["capacity"], "size_"+sid)
        m.add(size == sum(assignments))
        m.add(size >= a)
        eligible = sorted({r["teacher"] for r in data["qualifications"] if r["course"] == cid})
        teacher_choice[sid] = {t: m.new_bool_var("teacher_"+sid+"_"+t) for t in eligible}
        preferred_teacher = section["teacher"] or eligible[(len(section_by_course[cid])-1) % len(eligible)]
        for t,v in teacher_choice[sid].items():m.add_hint(v,int(t==preferred_teacher))
        m.add(sum(teacher_choice[sid].values()) == a)
        if section["teacher"]:
            m.add(teacher_choice[sid][section["teacher"]] == 1)
        for t, presence in teacher_choice[sid].items():
            loads[t].append(c["periods"]*presence)
        fixed_room_vars = None
        if section["mini"] or section["room"]:
            required = {c["lab_type"] if kind == "lab" else c["room_type"] for kind, _ in course_sessions(c)}
            common = [rid for rid, r in rooms.items() if required <= room_types(r) and (not section["room"] or rid == section["room"])]
            fixed_room_vars = {r: m.new_bool_var("fixedroom_"+sid+"_"+r) for r in common}
            m.add(sum(fixed_room_vars.values()) == a)
        previous = {}
        for j, (kind, duration) in enumerate(course_sessions(c)):
            eid = sid+f"::{j+1}"
            starts = [p for p in range(total-duration+1) if day_period(data, p)[0] == day_period(data, p+duration-1)[0]
                      and (duration == 1 or day_period(data, p)[1] not in data["config"]["break_after"])]
            if not starts:
                return {"status": "INFEASIBLE", "message": f"{cid}必须连堂，但课表没有合法相邻节次。请调整连堂边界或课表结构。", "limits": limits}
            start = m.new_int_var_from_domain(cp_model.Domain.from_values(starts), "start_"+eid)
            end = m.new_int_var(0, total, "end_"+eid)
            m.add(end == start+duration)
            interval = m.new_optional_interval_var(start, duration, end, a, "event_"+eid)
            section_intervals[sid].append(interval)
            # No OnlyEnforceIf on Element: the lookup is unconditional, equality conditional.
            for offset in range(duration):
                idx = m.new_int_var(0, total-1, "index")
                m.add(idx == start+offset)
                value = m.new_int_var(0, 6, "block_at_event")
                m.add_element(idx, block_vars[c["grade"]], value)
                m.add(value == b).only_enforce_if(a)
            order_key = (kind, duration)
            if order_key in previous:
                m.add(start > previous[order_key]).only_enforce_if(a)
            previous[order_key] = start
            room_kind = c["lab_type"] if kind == "lab" else c["room_type"]
            compatible = [r for r in rooms if room_kind in room_types(rooms[r])]
            room_choices = {r: m.new_bool_var("room_"+eid+"_"+r) for r in compatible}
            m.add(sum(room_choices.values()) == a)
            for rid, presence in room_choices.items():
                m.add(size <= rooms[rid]["capacity"]).only_enforce_if(presence)
                if fixed_room_vars is not None:
                    m.add(presence == fixed_room_vars.get(rid, 0))
                resources["room", rid].append(m.new_optional_interval_var(start, duration, end, presence, "room_interval"))
            for tid, presence in teacher_choice[sid].items():
                resources["teacher", tid].append(m.new_optional_interval_var(start, duration, end, presence, "teacher_interval"))
            for student in learners:
                # Strict distinct blocks already imply inter-class student non-overlap.
                # Intervals are still required for students with personal bans/fixed events.
                if busy.get(("student",student)):
                    resources["student", student].append(m.new_optional_interval_var(start, duration, end, enroll[student, sid], "student_interval"))
            events.append({"id": eid, "section": sid, "kind": kind, "duration": duration, "start_var": start, "rooms": room_choices})
        if section["block"]:
            window=frozenset(slot(data,r["day"],r["period"]) for r in data["blocks"] if r["grade"]==c["grade"] and r["block"]==section["block"])
            if window:windows[window].append(sid)
    for row in data["choices"]:
        m.add(sum(enroll[row["student"], sid] for sid in section_by_course[row["course"]]) == 1)
    for row in data["enrollments"]:
        m.add(enroll[row["student"], row["section"]] == 1)
    for student in data["students"]:
        selected_blocks = []
        for choice in (r for r in data["choices"] if r["student"] == student["id"]):
            chosen = m.new_int_var(1, 6, "student_course_block")
            for sid in section_by_course[choice["course"]]:
                m.add(chosen == bv[sid]).only_enforce_if(enroll[student["id"], sid])
            selected_blocks.append(chosen)
        m.add_all_different(selected_blocks)  # Six values from 1..6 => exactly one of each.
    for intervals in list(resources.values())+list(section_intervals.values()):
        m.add_no_overlap(intervals)
    for tid, teacher in teachers.items():
        fixed_load = sum(e["duration"] for e in data["events"] if e["teacher"] == tid and e["counts_load"])
        m.add(sum(loads[tid])+fixed_load <= teacher["max_periods"])
    # Necessary aggregate cuts strengthen the interval model for fixed block windows.
    # They follow from per-slot exclusivity; they do not reduce the valid solution set.
    section_specs={s["id"]:s for s in sections}
    for window,ids in windows.items():
        selected_events=[e for e in events if e["section"] in ids]
        for tid in teachers:
            reserved={p for start,length,_ in busy.get(("teacher",tid),[]) for p in range(start,start+length)}
            m.add(sum(courses[section_specs[sid]["course"]]["periods"]*teacher_choice[sid][tid] for sid in ids if tid in teacher_choice[sid]) <= len(window-reserved))
        for rid in rooms:
            reserved={p for start,length,_ in busy.get(("room",rid),[]) for p in range(start,start+length)}
            m.add(sum(e["duration"]*e["rooms"][rid] for e in selected_events if rid in e["rooms"]) <= len(window-reserved))
    # Interchangeable, non-prescribed sections have ordered activation, preserving feasible partitions.
    for cid, ids in section_by_course.items():
        automatic = [s for s in ids if not next(c for c in sections if c["id"] == s)["mandatory"]]
        for a, b in zip(automatic, automatic[1:]):
            m.add(av[a] >= av[b])
    by_event = {e["id"]: e for e in events}
    for lock in locks:
        if lock["id"] not in by_event:
            return {"status": "INVALID_DATA", "message": "锁定课次已不存在，请检查班数和课时变化。"}
        e = by_event[lock["id"]]
        m.add(av[e["section"]] == 1)
        m.add(e["start_var"] == lock["start"])
        if lock.get("room") not in e["rooms"]:
            return {"status": "INVALID_DATA", "message": "锁定教室与课型不兼容。"}
        m.add(e["rooms"][lock["room"]] == 1)
        if lock.get("teacher") not in teacher_choice[e["section"]]:
            return {"status": "INVALID_DATA", "message": "锁定教师无资格。"}
        m.add(teacher_choice[e["section"]][lock["teacher"]] == 1)
    # MVP optimizes class count only. Six pedagogic soft metrics remain explicitly unimplemented.
    m.minimize(sum(av.values()))
    invalid = m.validate()
    if invalid:
        return {"status": "MODEL_INVALID", "message": invalid}
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1, seconds-(time.monotonic()-began))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    solver.parameters.stop_after_first_solution = True
    status = solver.solve(m)
    name = solver.status_name(status)
    result = {"status": name, "seconds": round(time.monotonic()-began, 3), "limits": limits,
              "message": "", "scope": "当前输入、严格六区块及列出的候选班数上限"}
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result["message"] = ("在当前候选班数范围内已证明无解。检查教师禁排/周上限、实验室能力及区块时段；可在开课课程中增加最大候选班数后重试。该结论不证明更高班数也无解。"
            if status == cp_model.INFEASIBLE else "本次时限内尚未找到可行解，也未证明无解。可增加时间预算或提供预设班/区块时段减少搜索。")
        result["suggestions"] = resource_hints(data, sections)
        return result
    result["sections"] = []
    for s in sections:
        sid = s["id"]
        if solver.value(av[sid]):
            result["sections"].append({"id": sid, "course": s["course"], "block": solver.value(bv[sid]),
                "teacher": next(t for t, v in teacher_choice[sid].items() if solver.value(v)),
                "students": [student for (student, section), v in enroll.items() if section == sid and solver.value(v)]})
    result["lessons"] = [{"id": e["id"], "section": e["section"], "kind": e["kind"], "duration": e["duration"],
        "start": solver.value(e["start_var"]), "room": next(r for r, v in e["rooms"].items() if solver.value(v))}
        for e in events if solver.value(av[e["section"]])]
    result["block_slots"] = [{"grade": g, "slot": p, "block": solver.value(v)} for g, rows in block_vars.items() for p, v in enumerate(rows)]
    from .audit import audit
    result["audit"] = audit(data, result, locks)
    if result["audit"]:
        result["status"] = "AUDIT_FAILED"
        result["message"] = "独立硬约束检查失败，结果不可发布。"
    else:
        result["message"] = "独立检查通过：硬约束零冲突。班数目标" + ("已最优（在候选范围内）。" if status == cp_model.OPTIMAL else "未证明最优。")
    return result


def resource_hints(data, sections):
    hints = []
    for t in data["teachers"]:
        banned = sum(r["kind"] == "teacher" and r["resource"] == t["id"] for r in data["unavailable"])
        if banned:
            hints.append(f"教师 {t['id']} 禁排 {banned} 个记录时段；请核查是否可协商，系统没有自动放开。")
    for c in data["courses"]:
        if c["lab_periods"]:
            n = sum(c["lab_type"] in room_types(r) for r in data["rooms"])
            hints.append(f"{c['id']} 每班需 {c['lab_periods']} 节 {c['lab_type']}，匹配房间 {n} 间。可检查实验时段错峰、合法房间和开班上限。")
    return hints[:30] + ["以上为核查方向，尚非经重算验证的最小松弛方案。"]
