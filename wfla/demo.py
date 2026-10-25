"""Deterministic fictitious data; configured example blocks are disclosed in UI."""
from collections import defaultdict
from math import ceil
from .schema import empty_dataset, normalize


def demo_dataset(per_grade=12, grades=(10, 11, 12)):
    data = empty_dataset()
    data["config"].update(term="DEMO-2026", title=f"虚构演示：每年级{per_grade}人")
    catalog = {
        "CHA": ("Chinese A", 1, "zh", "普通", ""), "ENA": ("English A", 1, "en", "普通", ""),
        "ENB": ("English B", 2, "en", "普通", ""), "SPA": ("Spanish", 2, "es", "普通", ""),
        "ECO": ("Economics", 3, "", "普通", ""), "HIS": ("History", 3, "", "普通", ""),
        "PHY": ("Physics", 4, "", "普通", "物理实验"), "CHE": ("Chemistry", 4, "", "普通", "化学实验"),
        "BIO": ("Biology", 4, "", "普通", "生物实验"), "MAT": ("Mathematics AA", 5, "", "普通", ""),
        "VA": ("Visual Arts", 6, "", "画室", ""), "MUS": ("Music", 6, "", "音乐", ""),
    }
    courses, preferred = {}, defaultdict(list)
    for gi, grade in enumerate(grades):
        for pair in range(18):
            day, start = pair//4+1, (pair % 4)*2+1
            block = (pair % 6+2*gi) % 6+1
            for period in (start,start+1):
                data["blocks"].append(dict(grade=grade,day=day,period=period,block=block))
        for i in range(per_grade):
            student = f"DEMO-{grade}-{i+1:03}"
            data["students"].append(dict(id=student,name=f"虚构学生{grade}-{i+1:03}",grade=grade,admin_class=f"{grade}-{i//22+1}"))
            science = [("PHY", "CHE"), ("CHE", "BIO"), ("BIO", "PHY")][i % 3]
            subjects = ["CHA", "ENB", "ECO" if i % 5 else "HIS", *science, "MAT"]
            if i % 23 == 1:
                subjects[1] = "SPA"
            if i % 29 == 2 and grade != 10:
                subjects[1] = "ENA"
            if i % 11 == 0:
                subjects[4] = "VA" if i % 22 == 0 else "MUS"
            hl = {2,3,5}
            if i % 31 == 3 and grade != 10:
                hl.add(4)
                data["approvals"].append(dict(student=student,term="DEMO-2026",status="approved",approver="虚构审批教师",date="2026-09-01"))
            for b, subject in enumerate(subjects,1):
                level = "NONE" if grade == 10 else ("HL" if b-1 in hl else "SL")
                cid = f"{subject}-{grade}-{level}"
                name, group, language, room, lab = catalog[subject]
                if cid not in courses:
                    courses[cid] = dict(id=cid,name=name,family="ENGLISH_A" if subject == "ENA" else subject,
                        group=group,language=language,grade=grade,level=level,periods=6 if level == "HL" else 4,
                        lab_periods=2 if lab else 0,lab_doubles=1 if lab else 0,
                        theory_doubles=1 if group == 6 else 0,room_type=room,lab_type=lab,
                        capacity=15 if lab else 18,max_sections=0)
                data["choices"].append(dict(student=student,course=cid))
                preferred[cid,b].append(student)
    data["courses"] = list(courses.values())
    # Example classes/blocks are presets, not a precomputed timetable.
    numbers = defaultdict(int)
    for (cid,b), members in sorted(preferred.items()):
        cap = courses[cid]["capacity"]
        for start in range(0,len(members),cap):
            numbers[cid] += 1
            sid = f"{cid}__{numbers[cid]}"
            data["sections"].append(dict(id=sid,course=cid,teacher="",room="",block=b))
            for student in members[start:start+cap]:
                data["enrollments"].append(dict(student=student,section=sid))
    for cid,c in courses.items():
        c["max_sections"] = numbers[cid]
    # Shared teachers qualify across grades for each subject/level, with enough parallel staff.
    by_family_level = defaultdict(list)
    for c in courses.values():
        by_family_level[c["family"], c["level"]].append(c)
    for (family, level), offerings in by_family_level.items():
        count = max(numbers[c["id"]] for c in offerings)
        for j in range(count):
            tid = f"DEMO-T-{family}-{level}-{j+1}"
            data["teachers"].append(dict(id=tid,name=f"虚构教师{family}-{level}-{j+1}",max_periods=24))
            data["qualifications"].extend(dict(teacher=tid,course=c["id"]) for c in offerings)
    for j in range(max(8,ceil(per_grade/12)*len(grades))):
        data["rooms"].append(dict(id=f"R{j+1:02}",name=f"虚构普通教室{j+1}",capacity=18,types="普通"))
    for j in range(4):
        data["rooms"].append(dict(id=f"LAB{j+1}",name=f"虚构综合实验室{j+1}",capacity=15,types="普通;物理实验;化学实验;生物实验"))
    for kind,prefix in (("画室","ART"),("音乐","MUSIC")):
        for j in range(len(grades)):
            data["rooms"].append(dict(id=f"{prefix}{j+1}",name=f"虚构{kind}{j+1}",capacity=18,types=kind))
    for gi,grade in enumerate(grades):
        tid, eid = f"DEMO-CORE-{grade}", f"TOK-{grade}"
        data["teachers"].append(dict(id=tid,name=f"虚构核心课教师{grade}",max_periods=10))
        data["events"].append(dict(id=eid,name="虚构TOK固定活动",day=5,period=7,duration=1,teacher=tid,room=f"R{gi+1:02}",counts_load=1))
        for s in [s for s in data["students"] if s["grade"] == grade][:6]:
            data["event_students"].append(dict(event=eid,student=s["id"]))
    return normalize(data)
