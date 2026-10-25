"""Shared table contract for Excel, forms and CLI. No real school data."""
from copy import deepcopy

# field: (Chinese label, type, default)
TABLES = {
    "courses": ("开课课程", {
        "id": ("开课编码", "str", ""), "name": ("课程名称", "str", ""),
        "family": ("课程族编码", "str", ""), "group": ("学科组1至6", "int", 1),
        "language": ("语言代码", "str", ""), "grade": ("年级", "int", 11),
        "level": ("层级NONE或HL或SL", "str", "SL"), "periods": ("周课时", "int", 4),
        "lab_periods": ("实验课时", "int", 0), "lab_doubles": ("必须实验双节次数", "int", 0),
        "theory_doubles": ("必须理论艺术双节次数", "int", 0),
        "room_type": ("理论艺术房间能力", "str", "普通"), "lab_type": ("实验房间能力", "str", ""),
        "capacity": ("班人数上限", "int", 18), "max_sections": ("最大候选班数0为自动", "int", 0),
    }),
    "students": ("学生", {"id": ("学生编码", "str", ""), "name": ("显示姓名", "str", ""),
        "grade": ("年级", "int", 11), "admin_class": ("行政班", "str", "")}),
    "choices": ("学生选课", {"student": ("学生编码", "str", ""), "course": ("开课编码", "str", "")}),
    "approvals": ("四门HL特批", {"student": ("学生编码", "str", ""), "term": ("学期", "str", ""),
        "status": ("状态approved或pending或revoked", "str", "pending"),
        "approver": ("批准人", "str", ""), "date": ("批准日期YYYY-MM-DD", "str", "")}),
    "teachers": ("教师", {"id": ("教师编码", "str", ""), "name": ("姓名", "str", ""),
        "max_periods": ("周负荷上限", "int", 24)}),
    "qualifications": ("教师资格", {"teacher": ("教师编码", "str", ""), "course": ("开课编码", "str", "")}),
    "rooms": ("教室", {"id": ("教室编码", "str", ""), "name": ("教室名称", "str", ""),
        "capacity": ("容量", "int", 18), "types": ("能力用英文分号分隔", "str", "普通"),
        "preference": ("使用代价0优先", "int", 0)}),
    "unavailable": ("资源禁排", {"kind": ("student或teacher或room", "str", "teacher"),
        "resource": ("资源编码", "str", ""), "day": ("星期1起", "int", 1),
        "period": ("节次1起", "int", 1), "reason": ("原因", "str", "")}),
    "blocks": ("区块时段", {"grade": ("年级", "int", 11), "day": ("星期1起", "int", 1),
        "period": ("节次1起", "int", 1), "block": ("区块1至6", "int", 1)}),
    "sections": ("预设教学班", {"id": ("班编码", "str", ""), "course": ("开课编码", "str", ""),
        "teacher": ("指定教师可空", "str", ""), "room": ("固定教室可空", "str", ""),
        "block": ("指定区块0为自动", "int", 0)}),
    "enrollments": ("预设分班", {"student": ("学生编码", "str", ""), "section": ("班编码", "str", "")}),
    "events": ("固定活动", {"id": ("活动编码", "str", ""), "name": ("活动名称", "str", "TOK"),
        "day": ("星期1起", "int", 1), "period": ("起始节次", "int", 1), "duration": ("连续节数", "int", 1),
        "teacher": ("教师可空", "str", ""), "room": ("教室可空", "str", ""),
        "counts_load": ("计教师负荷1或0", "int", 1)}),
    "event_students": ("活动学生", {"event": ("活动编码", "str", ""), "student": ("学生编码", "str", "")}),
    "calendar": ("年级节次", {"grade": ("年级", "int", 11), "day": ("星期", "int", 1),
        "periods": ("当天节数", "int", 9)}),
    "activities": ("公共课程", {"id": ("编组编码", "str", ""), "name": ("名称", "str", "TOK"),
        "grade": ("年级", "int", 11), "admin_classes": ("行政班用英文分号分隔", "str", ""),
        "periods": ("周课时", "int", 1), "teacher": ("教师编码", "str", ""),
        "room_type": ("教室类型", "str", "普通"), "room": ("固定教室可空", "str", "")}),
    "activity_members": ("公共课学生", {"activity": ("编组编码", "str", ""), "student": ("学生编码", "str", "")}),
    "study_rules": ("自修安排", {"grade": ("年级", "int", 11), "periods": ("每生周自修节数", "int", 5),
        "rooms": ("允许教室英文分号分隔", "str", "C301;C302"),
        "unassigned": ("每生待安排节数", "int", 0)}),
}


def empty_dataset():
    return {"schema_version": 1, "config": {"term": "新学期", "days": 5, "periods_per_day": 8,
        "minutes_per_period": 40, "break_after": [4], "title": "未命名方案"},
        **{key: [] for key in TABLES}}


def normalize(data):
    if not isinstance(data, dict):
        raise ValueError("数据必须为对象")
    if data.get("schema_version", 1) != 1:
        raise ValueError("不支持的模板版本")
    result = empty_dataset()
    if not isinstance(data.get("config", {}), dict):
        raise ValueError("config 必须为对象")
    result["config"].update(deepcopy(data.get("config", {})))
    for key, (_, fields) in TABLES.items():
        rows = data.get(key, [])
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ValueError(f"{key} 必须为不超过20000行的表")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{key} 第{i+2}行不是记录")
            record = {"_row": row.get("_row", i+2)}
            for field, (_, kind, default) in fields.items():
                value = row.get(field, default)
                if value is None:
                    value = default
                if kind == "str":
                    value = str(value).strip()
                else:
                    try:
                        if str(value).strip() == "":
                            value = default
                        if isinstance(value, bool) or float(value) != int(value):
                            raise ValueError()
                        value = int(value)
                    except (ValueError, TypeError, OverflowError):
                        # Retain the wrong value to display it in the editable staging area.
                        value = str(value)
                record[field] = value
            result[key].append(record)
    return result


def slot(data, day, period):
    return (day-1)*data["config"]["periods_per_day"] + period-1


def day_period(data, index):
    n = data["config"]["periods_per_day"]
    return index//n+1, index % n+1


def room_types(room):
    return set(x.strip() for x in room["types"].split(";") if x.strip())


def active_slots(data, grade):
    overrides = {r["day"]: r["periods"] for r in data.get("calendar", []) if r["grade"] == grade}
    return [slot(data, day, p) for day in range(1, data["config"]["days"]+1)
            for p in range(1, overrides.get(day, data["config"]["periods_per_day"])+1)]


def activity_students(data, activity):
    explicit = [r["student"] for r in data.get("activity_members", []) if r["activity"] == activity["id"]]
    if explicit:
        return sorted(explicit)
    classes = set(activity["admin_classes"].split(";")) - {""}
    return sorted(s["id"] for s in data["students"] if s["grade"] == activity["grade"] and s["admin_class"] in classes)
