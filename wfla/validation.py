"""Deterministic, source-aware validation independent of the optimizer."""
from collections import Counter, defaultdict
from datetime import date
from .schema import TABLES, room_types, slot


def validate(data, require_complete=True):
    issues = []
    def error(table, row, field, message):
        issues.append({"table": table, "sheet": TABLES.get(table, ("课表设置",))[0],
                       "row": row.get("_row", "网页"), "field": field, "message": message})
    config = data.get("config", {})
    for k, low, high in [("days", 1, 7), ("periods_per_day", 1, 12), ("minutes_per_period", 1, 180)]:
        if not isinstance(config.get(k), int) or not low <= config[k] <= high:
            error("config", {}, k, f"必须为{low}至{high}的整数")
    if not str(config.get("term", "")).strip():
        error("config", {}, "term", "学期不能为空")
    if issues:
        return issues
    breaks = config.get("break_after", [])
    if not isinstance(breaks, list) or any(not isinstance(i, int) or not 1 <= i <= config.get("periods_per_day", 0) for i in breaks):
        error("config", {}, "break_after", "休息边界必须为有效节次列表")
    for table, (_, fields) in TABLES.items():
        for row in data.get(table, []):
            for key, (_, kind, _) in fields.items():
                if kind == "int" and (not isinstance(row.get(key), int) or isinstance(row.get(key), bool)):
                    error(table, row, key, "必须填写整数")
    if issues:
        return issues
    maps = {}
    for table in ("courses", "students", "teachers", "rooms", "sections", "events"):
        ids = Counter(r["id"] for r in data[table])
        for row in data[table]:
            if not row["id"] or ids[row["id"]] != 1:
                error(table, row, "id", "编码不能为空且必须唯一")
        maps[table] = {r["id"]: r for r in data[table]}
    refs = {"choices": [("student", "students"), ("course", "courses")],
            "approvals": [("student", "students")],
            "qualifications": [("teacher", "teachers"), ("course", "courses")],
            "sections": [("course", "courses")], "enrollments": [("student", "students"), ("section", "sections")],
            "event_students": [("event", "events"), ("student", "students")]}
    for table, pairs in refs.items():
        for row in data[table]:
            for field, target in pairs:
                if row[field] not in maps[target]:
                    error(table, row, field, f"不存在的{TABLES[target][0]}编码：{row[field]}")
    for table in ("sections", "events"):
        for row in data[table]:
            for field, target in (("teacher", "teachers"), ("room", "rooms")):
                if row[field] and row[field] not in maps[target]:
                    error(table, row, field, f"不存在的资源：{row[field]}")
    for table, fields in [("choices", ("student", "course")), ("qualifications", ("teacher", "course")),
                          ("event_students", ("event", "student")), ("approvals", ("student", "term")),
                          ("blocks", ("grade", "day", "period")), ("enrollments", ("student", "section"))]:
        seen = set()
        for row in data[table]:
            key = tuple(row[f] for f in fields)
            if key in seen:
                error(table, row, fields[0], "重复记录：" + " / ".join(map(str, key)))
            seen.add(key)
    if issues:
        return issues
    students, courses = maps["students"], maps["courses"]
    for table in ("students", "courses", "blocks"):
        for row in data[table]:
            if row["grade"] not in (10, 11, 12):
                error(table, row, "grade", "只支持10、11、12年级")
    for c in courses.values():
        if not c["name"] or not c["family"]:
            error("courses", c, "family", "课程名称与规范课程族不能为空")
        if not 1 <= c["group"] <= 6:
            error("courses", c, "group", "学科组必须为1至6")
        if c["grade"] == 10:
            if c["level"] != "NONE":
                error("courses", c, "level", "10年级只允许NONE（不分层）")
            if c["family"].upper().replace(" ", "_") == "ENGLISH_A" or (c["group"] == 1 and c["language"].lower() in ("en", "english", "英语")):
                error("courses", c, "family", "10年级禁止English A")
        elif c["level"] not in ("HL", "SL"):
            error("courses", c, "level", "11、12年级只允许HL或SL")
        if not 1 <= c["periods"] <= config["days"]*config["periods_per_day"]:
            error("courses", c, "periods", "周课时超出课表范围")
        if not 0 <= c["lab_periods"] <= c["periods"] or c["lab_doubles"] < 0 or 2*c["lab_doubles"] > c["lab_periods"]:
            error("courses", c, "lab_periods", "实验课时与必需实验双节次数不一致")
        if c["theory_doubles"] < 0 or 2*c["theory_doubles"] > c["periods"]-c["lab_periods"]:
            error("courses", c, "theory_doubles", "理论/艺术双节次数超过其课时")
        if c["capacity"] <= 0 or c["max_sections"] < 0:
            error("courses", c, "capacity", "容量必须为正数，最大候选班数不得为负")
        if c["group"] in (1, 2) and not c["language"]:
            error("courses", c, "language", "语言课程必须填写语言代码")
    approvals = {}
    for r in data["approvals"]:
        if students[r["student"]]["grade"] == 10:
            error("approvals", r, "student", "10年级不使用HL特批")
        if r["status"] not in ("approved", "pending", "revoked", "rejected"):
            error("approvals", r, "status", "无效批准状态")
        if r["status"] == "approved":
            try:
                date.fromisoformat(r["date"])
                if not r["approver"]:
                    raise ValueError()
            except ValueError:
                error("approvals", r, "date", "已批准记录必须填写批准人及有效日期")
            if r["term"] == config["term"]:
                approvals[r["student"]] = r
    choices = defaultdict(list)
    for row in data["choices"]:
        choices[row["student"]].append(courses[row["course"]])
        if courses[row["course"]]["grade"] != students[row["student"]]["grade"]:
            error("choices", row, "course", "学生与开课年级不一致")
    for sid, student in students.items():
        selected = choices[sid]
        if len(selected) != 6:
            error("students", student, "id", f"{sid}必须选择6门课程，当前{len(selected)}门")
            continue
        if len({c["family"] for c in selected}) != 6:
            error("students", student, "id", f"{sid}同一课程族不可重复选课（包括HL与SL重复）")
        hl = sum(c["level"] == "HL" for c in selected)
        if student["grade"] in (11, 12) and not (hl == 3 or (hl == 4 and sid in approvals)):
            error("students", student, "id", f"{sid}需要3 HL＋3 SL；4 HL＋2 SL须本学期有效批准，当前{hl} HL")
        if not valid_combination(selected):
            error("students", student, "id", f"{sid}不符合六科结构：G1、G2或不同语言双G1、G3、G4、G5，以及G6或额外G3/G4")
    for r in data["rooms"]:
        if r["capacity"] <= 0 or not room_types(r):
            error("rooms", r, "capacity", "房间容量必须为正数且能力不能为空")
    for t in data["teachers"]:
        if t["max_periods"] < 0:
            error("teachers", t, "max_periods", "周上限不能为负")
    for table in ("blocks", "unavailable", "events"):
        for row in data[table]:
            if not (1 <= row["day"] <= config["days"] and 1 <= row["period"] <= config["periods_per_day"]):
                error(table, row, "period", "时段超出课表范围")
            if table == "blocks" and row["block"] not in range(1, 7):
                error(table, row, "block", "严格区块只能为1至6")
            if table == "events":
                if row["duration"] < 1 or row["period"]+row["duration"]-1 > config["periods_per_day"]:
                    error(table, row, "duration", "活动长度无效或跨日")
                if row["counts_load"] not in (0, 1):
                    error(table, row, "counts_load", "计负荷只能为0或1")
            if table == "unavailable":
                target = {"student": "students", "teacher": "teachers", "room": "rooms"}.get(row["kind"])
                if not target or row["resource"] not in maps[target]:
                    error(table, row, "resource", "禁排资源不存在或类别错误")
    qualifications = {(r["teacher"], r["course"]) for r in data["qualifications"]}
    for row in data["sections"]:
        if row["block"] not in range(7):
            error("sections", row, "block", "指定区块必须为0至6")
        if row["teacher"] and (row["teacher"], row["course"]) not in qualifications:
            error("sections", row, "teacher", "指定教师无该开课项目资格")
    enrolled = set()
    selected_pairs = {(r["student"], r["course"]) for r in data["choices"]}
    for row in data["enrollments"]:
        cid = maps["sections"][row["section"]]["course"]
        pair = row["student"], cid
        if pair not in selected_pairs or pair in enrolled:
            error("enrollments", row, "section", "学生未选该课，或同一选课被预设到多个班")
        enrolled.add(pair)
    used = {r["course"] for r in data["choices"]}
    for cid in used:
        c = courses[cid]
        if not any(q[1] == cid for q in qualifications):
            error("courses", c, "id", f"{cid}没有可教老师；请添加教师资格")
        for kind, count in ((c["room_type"], c["periods"]-c["lab_periods"]), (c["lab_type"], c["lab_periods"])):
            if count and not any(kind in room_types(r) for r in data["rooms"]):
                error("courses", c, "room_type", f"{cid}缺少支持“{kind}”的教室；请增加匹配房间或修正课型")
    for cid,c in courses.items():
        specs=[s for s in data["sections"] if s["course"]==cid]
        if specs and cid not in used:
            error("courses",c,"id","存在预设教学班但无人选择该课，请删除空班或补充选课")
        if c["max_sections"] and len(specs)>c["max_sections"]:
            error("courses",c,"max_sections","预设教学班数量超过配置的最大候选班数")
        for spec in specs:
            if spec["room"]:
                r=maps["rooms"][spec["room"]]
                required=set()
                if c["lab_periods"]:required.add(c["lab_type"])
                if c["periods"]>c["lab_periods"]:required.add(c["room_type"])
                if not required <= room_types(r):error("sections",spec,"room","固定房间不能支持该班全部课型")
    if not issues:
        occupancy={}
        banned={(r["kind"],r["resource"],slot(data,r["day"],r["period"])) for r in data["unavailable"]}
        members=defaultdict(list)
        for r in data["event_students"]:members[r["event"]].append(r["student"])
        fixed_load=Counter()
        for event in data["events"]:
            if event["room"] and len(members[event["id"]])>maps["rooms"][event["room"]]["capacity"]:
                error("events",event,"room","固定活动参加人数超过房间容量")
            people=[("student",sid) for sid in members[event["id"]]]
            people += [(kind,event[kind]) for kind in ("teacher","room") if event[kind]]
            start=slot(data,event["day"],event["period"])
            for kind,rid in people:
                for p in range(start,start+event["duration"]):
                    key=kind,rid,p
                    if key in occupancy:error("events",event,"period",f"{kind} {rid} 与固定活动 {occupancy[key]} 重叠")
                    if key in banned:error("events",event,"period",f"{kind} {rid} 的固定活动与禁排重叠")
                    occupancy[key]=event["id"]
            if event["teacher"] and event["counts_load"]:fixed_load[event["teacher"]]+=event["duration"]
        for tid,load in fixed_load.items():
            if load>maps["teachers"][tid]["max_periods"]:error("teachers",maps["teachers"][tid],"max_periods","固定活动本身已超过周负荷上限")
    if require_complete and not students:
        error("students", {}, "id", "请先导入学生选课，或载入虚构演示数据")
    return issues


def valid_combination(courses):
    """Six distinct courses assigned to six roles; dual G1 uses different languages."""
    def visit(role, remaining, first_language):
        if role == 6:
            return True
        for i in remaining:
            c = courses[i]
            ok = ((role == 0 and c["group"] == 1) or
                  (role == 1 and (c["group"] == 2 or (c["group"] == 1 and c["language"] != first_language))) or
                  (role in (2, 3, 4) and c["group"] == role+1) or
                  (role == 5 and c["group"] in (3, 4, 6)))
            if ok and visit(role+1, remaining-{i}, c["language"] if role == 0 else first_language):
                return True
        return False
    return len(courses) == 6 and visit(0, set(range(6)), "")
