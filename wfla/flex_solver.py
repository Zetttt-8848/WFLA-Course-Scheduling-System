"""Joint section/teacher/room scheduling without global subject time blocks.

Study is a capacity-constrained activity, never a label pasted onto every gap.
The same room's study seats are shared across both grades.
"""
from collections import defaultdict, Counter
import time
from ortools.sat.python import cp_model
from .schema import active_slots, activity_students, day_period, room_types
from .validation import validate


def solve_flexible(data, seconds=60, locks=None):
    began = time.monotonic()
    errors = validate(data)
    if errors: return dict(status='INVALID_DATA', message='数据校验未通过', issues=errors)
    if locks: return dict(status='INVALID_DATA', message='灵活并行模式尚不支持锁课重排')
    from .solver import candidates, course_sessions, fixed_occupancy, resource_hints
    sections, limits = candidates(data)
    m = cp_model.CpModel()
    total = data['config']['days']*data['config']['periods_per_day']
    courses = {c['id']: c for c in data['courses']}
    teachers = {t['id']: t for t in data['teachers']}
    rooms = {r['id']: r for r in data['rooms']}
    students = {s['id']: s for s in data['students']}
    calendars = {g:set(active_slots(data,g)) for g in (10,11,12)}
    resources, loads, course_sections = defaultdict(list), defaultdict(list), defaultdict(list)
    events, activity_events, enrollment, activation, teacher_vars = [], [], {}, {}, {}
    room_cost, spread_cost = [], []
    busy = fixed_occupancy(data)
    # Pool truly interchangeable rooms. Fixed rooms, room bans, study rooms and
    # every possible mini-class home room stay individual. Pool intervals can
    # be colored greedily afterwards because each member has identical capacity,
    # types and cost and no room-specific constraints. This is an exact projection.
    protected = {rid for kind,rid in busy if kind=='room'}
    protected.update(s['room'] for s in sections if s['room'])
    protected.update(a['room'] for a in data.get('activities',[]) if a['room'])
    protected.update(r['id'] for r in data['rooms'] if '自修' in room_types(r))
    for s in sections:
        if s['mini']:
            c=courses[s['course']]
            required={c['lab_type'] if kind=='lab' else c['room_type'] for kind,_ in course_sessions(c)}
            protected.update(rid for rid,r in rooms.items() if required <= room_types(r))
    interchangeable=defaultdict(list)
    for rid,r in rooms.items():
        key=('fixed',rid) if rid in protected else (tuple(sorted(room_types(r))),r['capacity'],r['preference'])
        interchangeable[key].append(rid)
    room_members, pooled_rooms = {}, {}
    for ids in interchangeable.values():
        # Use an existing representative ID internally; output is recolored to
        # the actual room IDs before the independent audit sees any result.
        representative=ids[0];room_members[representative]=ids
        pooled_rooms[representative]=rooms[representative]
    rooms=pooled_rooms
    # Students with all six sections fixed and identical calendars, activities,
    # and bans share academic availability. Their study-seat decisions stay
    # individual (they may split rooms); only redundant interval constraints merge.
    fixed_memberships=defaultdict(list)
    for row in data['enrollments']:fixed_memberships[row['student']].append(row['section'])
    activity_memberships=defaultdict(list)
    for a in data.get('activities',[]):
        for sid in activity_students(data,a):activity_memberships[sid].append(a['id'])
    cohort_ids, student_resource = {}, {}
    for sid,s in students.items():
        if len(fixed_memberships[sid])==6:
            forbidden=tuple(sorted({p for start,length,_ in busy.get(('student',sid),[]) for p in range(start,start+length)}))
            key=(s['grade'],tuple(sorted(fixed_memberships[sid])),tuple(sorted(activity_memberships[sid])),forbidden)
            student_resource[sid]=cohort_ids.setdefault(key,sid)
        else:student_resource[sid]=sid
    for resource, records in busy.items():
        if resource[0]=='student' and student_resource[resource[1]]!=resource[1]:continue
        for p in {p for start,length,_ in records for p in range(start,start+length)}:
            resources[resource].append(m.new_fixed_size_interval_var(p,1,'reserved'))

    def lesson(eid, grade, duration, present, room_ids, count, attendees, staff, kind, group, fixed_rooms=None):
        starts = [p for p in sorted(calendars[grade]) if all(p+j in calendars[grade] for j in range(duration))
                  and day_period(data,p)[0] == day_period(data,p+duration-1)[0]
                  and (duration == 1 or day_period(data,p)[1] not in data['config']['break_after'])]
        if not starts: raise ValueError(f'{eid} 没有符合该年级节次与连堂边界的起点')
        start = m.new_int_var_from_domain(cp_model.Domain.from_values(starts),'start_'+eid)
        end = m.new_int_var(0,total,'end_'+eid); m.add(end == start+duration)
        resources['section',group].append(m.new_optional_interval_var(start,duration,end,present,eid))
        choices = {r:m.new_bool_var('room_'+eid+'_'+r) for r in room_ids}
        m.add(sum(choices.values()) == present)
        for rid, v in choices.items():
            m.add(count <= rooms[rid]['capacity']).only_enforce_if(v)
            if fixed_rooms is not None: m.add(v == fixed_rooms.get(rid,0))
            resources['room',rid].append(m.new_optional_interval_var(start,duration,end,v,'room'))
            room_cost.append(duration*rooms[rid]['preference']*v)
        for tid,v in staff.items():
            resources['teacher',tid].append(m.new_optional_interval_var(start,duration,end,v,'teacher'))
        representatives={student_resource[sid]:v for sid,v in attendees.items()}
        for sid,v in representatives.items():
            resources['student',sid].append(m.new_optional_interval_var(start,duration,end,v,'student'))
        return dict(id=eid,section=group,kind=kind,duration=duration,start_var=start,rooms=choices,present=present)

    try:
        for section in sections:
            sid,cid = section['id'],section['course']; c = courses[cid]
            course_sections[cid].append(sid)
            a = activation[sid] = m.new_bool_var('active_'+sid)
            if section['mandatory']: m.add(a == 1)
            learners = sorted(ch['student'] for ch in data['choices'] if ch['course'] == cid)
            members = {}
            for student in learners:
                v = enrollment[student,sid] = m.new_bool_var('enroll_'+student+'_'+sid)
                m.add(v <= a); members[student] = v
            count = m.new_int_var(0,section['capacity'],'size_'+sid)
            m.add(count == sum(members.values())); m.add(count >= a)
            eligible = sorted({q['teacher'] for q in data['qualifications'] if q['course'] == cid})
            staff = teacher_vars[sid] = {t:m.new_bool_var('teach_'+sid+'_'+t) for t in eligible}
            m.add(sum(staff.values()) == a)
            preferred = section['teacher'] or eligible[(len(course_sections[cid])-1)%len(eligible)]
            for tid,v in staff.items():m.add_hint(v,int(tid==preferred))
            if section['teacher']: m.add(staff[section['teacher']] == 1)
            for tid,v in staff.items(): loads[tid].append(c['periods']*v)
            fixed = None
            if section['mini'] or section['room']:
                required = {c['lab_type'] if k == 'lab' else c['room_type'] for k,_ in course_sessions(c)}
                fixed = {rid:m.new_bool_var('fixed_'+sid+'_'+rid) for rid,r in rooms.items()
                         if required <= room_types(r) and (not section['room'] or rid == section['room'])}
                m.add(sum(fixed.values()) == a)
            previous, group_events = {}, []
            for j,(kind,duration) in enumerate(course_sessions(c)):
                rtype = c['lab_type'] if kind == 'lab' else c['room_type']
                ev = lesson(f'{sid}::{j+1}',c['grade'],duration,a,[r for r in rooms if rtype in room_types(rooms[r])],count,members,staff,kind,sid,fixed)
                key = kind,duration
                if key in previous: m.add(ev['start_var'] > previous[key]).only_enforce_if(a)
                previous[key] = ev['start_var']; events.append(ev); group_events.append(ev)
            # Excess over ceil(weekly hours / school days) discourages clustering.
            target = (c['periods']+data['config']['days']-1)//data['config']['days']
            for day in range(1,data['config']['days']+1):
                flags = []
                for ev in group_events:
                    d = m.new_int_var(0,data['config']['days']-1,'day')
                    m.add_division_equality(d,ev['start_var'],data['config']['periods_per_day'])
                    match = m.new_bool_var('on_day'); m.add(d == day-1).only_enforce_if(match); m.add(d != day-1).only_enforce_if(match.Not())
                    active_match = m.new_bool_var('active_day')
                    m.add(active_match <= a); m.add(active_match <= match); m.add(active_match >= a+match-1)
                    flags.append(ev['duration']*active_match)
                excess = m.new_int_var(0,c['periods'],'daily_excess')
                m.add(excess >= sum(flags)-target); spread_cost.append(excess)
        for ch in data['choices']:
            m.add(sum(enrollment[ch['student'],s] for s in course_sections[ch['course']]) == 1)
        for row in data['enrollments']: m.add(enrollment[row['student'],row['section']] == 1)
        for cid, ids in course_sections.items():
            auto = [s['id'] for s in sections if s['course'] == cid and not s['mandatory']]
            for left,right in zip(auto,auto[1:]): m.add(activation[left] >= activation[right])
        for activity in data.get('activities',[]):
            members = activity_students(data,activity)
            room_ids = [r for r in rooms if activity['room_type'] in room_types(rooms[r]) and rooms[r]['capacity'] >= len(members)
                        and (not activity['room'] or r == activity['room'])]
            previous = None
            for j in range(activity['periods']):
                ev = lesson(f"COMMON:{activity['id']}::{j+1}",activity['grade'],1,m.new_constant(1),room_ids,len(members),
                            {s:m.new_constant(1) for s in members},{activity['teacher']:m.new_constant(1)},'common','COMMON:'+activity['id'])
                if previous is not None: m.add(ev['start_var'] > previous)
                previous = ev['start_var']; ev['activity'] = activity['id']; activity_events.append(ev)
            loads[activity['teacher']].append(activity['periods'])
    except ValueError as exc:
        return dict(status='INFEASIBLE',message=str(exc),limits=limits)
    # One study room/slot is one shared session, with a real seat limit.
    study_vars, room_seats, cohort_study = {}, defaultdict(list), defaultdict(list)
    study_rules = {r['grade']:r for r in data.get('study_rules',[])}
    for student in data['students']:
        rule = study_rules.get(student['grade'])
        if not rule or not rule['periods']: continue
        assignments = []
        for p in sorted(calendars[student['grade']]):
            choices = []
            for rid in rule['rooms'].split(';'):
                v = m.new_bool_var('study'); study_vars[student['id'],rid,p] = v
                room_seats[rid,p].append(v); assignments.append(v); choices.append(v)
            present = m.new_bool_var('study_present'); m.add(sum(choices) == present)
            cohort_study[student_resource[student['id']],p].append(present)
        m.add(sum(assignments) == rule['periods'])
    for (representative,p), presences in cohort_study.items():
        any_study=m.new_bool_var('cohort_study')
        m.add_max_equality(any_study,presences)
        resources['student',representative].append(m.new_optional_fixed_size_interval_var(p,1,any_study,'study'))
    for (rid,p), seats in room_seats.items():
        present = m.new_bool_var('study_room')
        m.add(sum(seats) <= rooms[rid]['capacity']*present); m.add(sum(seats) >= present)
        resources['room',rid].append(m.new_optional_fixed_size_interval_var(p,1,present,'study_room'))
    for (kind,rid),intervals in resources.items():
        capacity=len(room_members[rid]) if kind=='room' else 1
        if capacity>1:m.add_cumulative(intervals,[1]*len(intervals),capacity)
        else:m.add_no_overlap(intervals)
    for tid,t in teachers.items():
        fixed = sum(e['duration'] for e in data['events'] if e['teacher'] == tid and e['counts_load'])
        m.add(sum(loads[tid])+fixed <= t['max_periods'])
    # Bounded lexicographic weights: classes, room preference, then daily spread.
    max_spread = sum(courses[s['course']]['periods'] for s in sections)*data['config']['days']
    max_room = sum(e['duration'] for e in events+activity_events)*max([r['preference'] for r in rooms.values()]+[0])
    room_weight = max_spread+1
    class_weight = max_room*room_weight+max_spread+1
    m.minimize(class_weight*sum(activation.values())+room_weight*sum(room_cost)+sum(spread_cost))
    if m.validate(): return dict(status='MODEL_INVALID',message=m.validate())
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1,seconds-(time.monotonic()-began))
    solver.parameters.num_search_workers = 8; solver.parameters.random_seed = 42
    solver.parameters.stop_after_first_solution = bool(data['config'].get('quick_feasible',False))
    status = solver.solve(m)
    result = dict(status=solver.status_name(status),seconds=round(time.monotonic()-began,3),limits=limits,
                  scheduling_mode='flexible',scope='当前输入及候选班数上限；六门选课允许灵活并行')
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        result['message'] = ('当前班数范围内无解：请检查公共课教师负荷、自修座位、实验室及禁排。' if status == cp_model.INFEASIBLE else '本次限时内未找到可行方案，尚不能判断无解。')
        result['suggestions'] = resource_hints(data,sections)
        return result
    real_rooms = {}
    active_events=[e for e in events+activity_events if solver.value(e['present'])]
    for representative,ids in room_members.items():
        free={rid:0 for rid in ids}
        selected=[e for e in active_events if representative in e['rooms'] and solver.value(e['rooms'][representative])]
        for ev in sorted(selected,key=lambda e:(solver.value(e['start_var']),e['id'])):
            start=solver.value(ev['start_var'])
            rid=next(r for r in ids if free[r]<=start)
            real_rooms[ev['id']]=rid;free[rid]=start+ev['duration']
    def rendered(ev):
        return dict(id=ev['id'],section=ev['section'],kind=ev['kind'],duration=ev['duration'],start=solver.value(ev['start_var']),
                    room=real_rooms[ev['id']])
    result['sections'] = [dict(id=s['id'],course=s['course'],block=0,
        teacher=next(t for t,v in teacher_vars[s['id']].items() if solver.value(v)),
        students=[student for (student,sid),v in enrollment.items() if sid == s['id'] and solver.value(v)])
        for s in sections if solver.value(activation[s['id']])]
    result['lessons'] = [rendered(e) for e in events if solver.value(e['present'])]
    result['activities'] = [{**rendered(e),'activity':e['activity']} for e in activity_events]
    groups = defaultdict(list)
    for (sid,rid,p),v in study_vars.items():
        if solver.value(v): groups[rid,p].append(sid)
    result['studies'] = [dict(id=f'STUDY:{rid}:{p}',room=rid,start=p,duration=1,students=sorted(members)) for (rid,p),members in sorted(groups.items())]
    result['block_slots'] = []
    result['quality'] = dict(classes=len(result['sections']),room_cost=solver.value(sum(room_cost)) if room_cost else 0,
        daily_excess=solver.value(sum(spread_cost)) if spread_cost else 0,optimal=status == cp_model.OPTIMAL,
        objective=solver.objective_value,bound=solver.best_objective_bound)
    from .audit import audit
    result['audit'] = audit(data,result)
    result['message'] = '硬约束零冲突。' + ('已证明当前班数范围与三个目标下最优。' if status == cp_model.OPTIMAL else '已找到可行课表，尚未证明最优。')
    if result['audit']: result.update(status='AUDIT_FAILED',message='独立检查失败，方案不可交付')
    return result
