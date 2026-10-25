"""Plain server-rendered Chinese UI. All data stays in local SQLite."""
from copy import deepcopy
from pathlib import Path
import io
import json
import multiprocessing
import secrets
import threading
import zipfile
from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from .schema import TABLES, empty_dataset, normalize, slot, active_slots, day_period
from .validation import validate
from .storage import Store, worker
from .demo import demo_dataset
from .io import workbook_bytes, import_bytes, timetable_rows, csv_bytes, schedule_xlsx
from .intake import school_dataset, school_demo, add_combination, add_staff_pool, add_common_courses, choice_template, import_choices, CATALOG

ROOT=Path(__file__).resolve().parent.parent


def project_archive():
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for folder in ("wfla","tests","docs"):
            for file in (ROOT/folder).rglob("*"):
                if file.is_file() and "__pycache__" not in file.parts and file.suffix in (".py",".html",".css",".md"):
                    archive.write(file,"WFLA-Course-Scheduling-System/"+file.relative_to(ROOT).as_posix())
        for name in ("README.md","LICENSE",".gitignore","requirements.txt","requirements-dev.txt","pytest.ini","run.py","start.bat","start.ps1"):
            if (ROOT/name).exists():archive.write(ROOT/name,"WFLA-Course-Scheduling-System/"+name)
    return output.getvalue()


def create_app(database=None,testing=False):
    app=Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32),MAX_CONTENT_LENGTH=10*1024*1024,TESTING=testing,
                      SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Strict",TRUSTED_HOSTS=["localhost","127.0.0.1"])
    store=Store(database or ROOT/"instance"/"wfla.sqlite3")
    app.extensions["store"]=store
    processes={}; job_lock=threading.Lock()
    if not testing:
        with store.connect() as db:
            db.execute("UPDATE runs SET state='INTERRUPTED',result=? WHERE state='RUNNING'",(json.dumps({"status":"INTERRUPTED","message":"上次服务已中断，请重新启动求解。"},ensure_ascii=False),))

    @app.before_request
    def csrf():
        session.setdefault("csrf",secrets.token_urlsafe(24))
        if request.method=="POST" and not secrets.compare_digest(request.form.get("csrf",""),session["csrf"]):
            abort(400,description="表单已失效，请刷新页面后重试。")

    @app.context_processor
    def common():
        return dict(tables=TABLES,csrf_token=session.get("csrf",""),versions=store.list_datasets(),active_id=session.get("dataset_id"))

    def current():
        raw=request.form.get("v") if request.method=="POST" else request.args.get("v")
        recent=store.list_datasets() if not raw and not session.get('dataset_id') else []
        try: identifier=int(raw or session.get("dataset_id",recent[0]['id'] if recent else 0))
        except ValueError:abort(400)
        data=store.get(identifier)
        if not data:
            if raw:abort(404)
            identifier=store.save(school_dataset());data=store.get(identifier)
        session["dataset_id"]=identifier
        return identifier,data

    def save(data):
        identifier=store.save(normalize(data));session["dataset_id"]=identifier;return identifier

    def download(raw,name,mimetype):
        return send_file(io.BytesIO(raw),as_attachment=True,download_name=name,mimetype=mimetype)

    @app.get("/")
    def index():
        identifier,data=current()
        return render_template("index.html",data=data,v=identifier,issues=validate(data),runs=store.list_runs())

    @app.post('/school/new')
    def new_school():
        save(school_dataset()); flash('新学期已建立，旧方案保留。')
        return redirect(url_for('index'))

    @app.post('/school/demo')
    def demo_school():
        data=school_demo(1);data['config']['quick_feasible']=False
        save(data); flash('已载入12名虚构学生。实验室、教师和分班均为演示数据。')
        return redirect(url_for('index'))

    @app.get('/manage')
    def manage():
        identifier,data=current()
        return render_template('manage.html',v=identifier,data=data)

    @app.route('/intake',methods=['GET','POST'])
    def intake():
        identifier,data=current()
        try: grade=int(request.values.get('grade',11))
        except ValueError: grade=11
        if grade not in (10,11,12):abort(400)
        if request.method=='POST':
            try:
                if request.form.get('action')=='upload':
                    upload=request.files.get('file')
                    if not upload or not upload.filename: raise ValueError('请选择选课Excel')
                    updated,count=import_choices(data,upload.read(),upload.filename)
                else:
                    count=int(request.form.get('count',0))
                    updated=add_combination(data,grade,request.form.get('admin_class','').strip(),count,[request.form.get(f'choice{i}','') for i in range(1,7)])
                save(updated);flash(f'已录入{count}名学生。')
                return redirect(url_for('intake',grade=grade))
            except (ValueError,KeyError) as exc:flash(str(exc),'error')
        return render_template('intake.html',data=data,v=identifier,grade=grade,courses=[c for c in data['courses'] if c['grade']==grade])

    @app.get('/choices-template/<kind>.xlsx')
    def choices_template(kind):
        if kind not in ('students','combinations'):abort(404)
        _,data=current()
        return download(choice_template(data,kind),f'WFLA-{kind}.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @app.route('/staff',methods=['GET','POST'])
    def staff():
        identifier,data=current()
        if request.method=='POST':
            try:
                names=[s.strip() for s in request.form.get('names','').splitlines() if s.strip()]
                updated=add_staff_pool(data,request.form.get('code','').strip(),request.form.get('family',''),request.form.getlist('levels'),
                    [int(g) for g in request.form.getlist('grades')],int(request.form.get('count',0)),int(request.form.get('max_periods',24)),names or None)
                save(updated);flash('教师已添加。跨年级任教会统一检查时间冲突。');return redirect(url_for('staff'))
            except (ValueError,KeyError) as exc:flash(str(exc),'error')
        families={c['family']:c['name'] for c in data['courses']}
        return render_template('staff.html',data=data,v=identifier,families=families)

    @app.route('/common',methods=['GET','POST'])
    def common_courses():
        identifier,data=current()
        try: grade=int(request.values.get('grade',11))
        except ValueError:grade=11
        if grade not in (11,12):abort(400)
        classes=sorted({s['admin_class'] for s in data['students'] if s['grade']==grade})
        names=['TOK']+(['体育','会考地理','会考历史','会考政治','Career Navigation'] if grade==11 else [])
        specs=[(name,(len(classes)+1)//2 if name in ('TOK','Career Navigation') else 1) for name in names]
        if request.method=='POST':
            try:
                mapping={name:request.form.getlist(name) for name,_ in specs}
                save(add_common_courses(data,grade,mapping));flash('已按行政班分别生成公共课；具体节次由排课决定。')
                return redirect(url_for('common_courses',grade=grade))
            except ValueError as exc:flash(str(exc),'error')
        return render_template('common.html',data=data,v=identifier,grade=grade,classes=classes,specs=specs)

    @app.route('/rules',methods=['GET','POST'])
    def school_rules():
        identifier,data=current()
        if request.method=='POST':
            try:
                updated=deepcopy(data)
                updated['config'].update(title=request.form.get('title',data['config']['title']),term=request.form.get('term',data['config']['term']))
                if data['config'].get('scheduling_mode')=='flexible':
                    updated['calendar']=[r for r in updated['calendar'] if r['grade'] not in (11,12)]
                    updated['study_rules']=[r for r in updated['study_rules'] if r['grade'] not in (11,12)]
                    for g in (11,12):
                        for day in range(1,6):
                            n=int(request.form[f'g{g}d{day}'])
                            if not 1<=n<=9:raise ValueError('每天节数需为1—9')
                            updated['calendar'].append(dict(grade=g,day=day,periods=n))
                        study,unassigned=int(request.form[f'study{g}']),int(request.form[f'pending{g}'])
                        if min(study,unassigned)<0:raise ValueError('课时不能为负数')
                        updated['study_rules'].append(dict(grade=g,periods=study,unassigned=unassigned,rooms=request.form[f'rooms{g}'].strip()))
                    updated['config']['periods_per_day']=max([9]+[r['periods'] for r in updated['calendar']])
                    for c in updated['courses']:
                        c['periods']=int(request.form.get('hours_'+c['id'],c['periods']))
                        c['lab_periods']=int(request.form.get('labs_'+c['id'],c['lab_periods']))
                        if c['lab_periods']<2:c['lab_doubles']=0
                save(updated);flash('规则已保存。');return redirect(url_for('school_rules'))
            except (ValueError,KeyError) as exc:flash(str(exc),'error')
        calendar={(r['grade'],r['day']):r['periods'] for r in data.get('calendar',[])}
        studies={r['grade']:r for r in data.get('study_rules',[])}
        return render_template('rules.html',data=data,v=identifier,calendar=calendar,studies=studies)

    @app.post("/select")
    def select():
        current();return redirect(url_for("index"))

    @app.post("/new")
    def new():
        save(empty_dataset());flash("已建立空白学期版本，旧数据仍保留。")
        return redirect(url_for("index"))

    @app.post("/demo")
    def demo():
        size=request.form.get("size","12")
        if size not in ("12","44","132"):abort(400)
        save(demo_dataset(int(size)))
        flash("已载入完全虚构数据。演示包含预设区块与分班，教师、具体课次和房间由求解器计算。")
        return redirect(url_for("index"))

    @app.route("/settings",methods=["GET","POST"])
    def settings():
        identifier,data=current()
        if request.method=="POST":
            try:
                for key in ("days","periods_per_day","minutes_per_period"):data["config"][key]=int(request.form[key])
                data["config"]["break_after"]=[int(x) for x in request.form.get("break_after","").split(",") if x.strip()]
                for key in ("title","term"):data["config"][key]=request.form.get(key,"").strip()
                errors=validate(data,False)
                if any(i["table"]=="config" for i in errors):raise ValueError("课表设置超出允许范围")
                identifier=save(data);flash("设置已保存为新版本；已有时段数据会重新校验。")
                return redirect(url_for("validation"))
            except (ValueError,KeyError) as exc:flash(str(exc),"error")
        return render_template("settings.html",data=data,v=identifier)

    @app.route("/data/<table>",methods=["GET","POST"])
    def table_view(table):
        if table not in TABLES:abort(404)
        identifier,data=current()
        fields=TABLES[table][1]
        if request.method=="POST":
            action=request.form.get("action")
            try:
                if action=="delete":data[table].pop(int(request.form["row"]))
                else:
                    record={k:request.form.get(k,default) for k,(_,kind,default) in fields.items()}
                    if action=="update":
                        i=int(request.form["row"]);record["_row"]=data[table][i].get("_row",i+2);data[table][i]=record
                    else:data[table].append(record)
                save(data);flash("已保存新版本。修改引用编码或删除记录后，请重新校验。")
            except (ValueError,IndexError,KeyError):abort(400)
            return redirect(url_for("table_view",table=table))
        edit=request.args.get("edit")
        row=None
        if edit is not None:
            try:row=data[table][int(edit)]
            except (ValueError,IndexError):abort(404)
        query=request.args.get("q","").strip().casefold()
        rows=[(i,r) for i,r in enumerate(data[table]) if not query or query in " ".join(map(str,r.values())).casefold()]
        try:page=max(1,int(request.args.get("page",1)))
        except ValueError:page=1
        return render_template("table.html",data=data,v=identifier,table=table,fields=fields,rows=rows[(page-1)*60:page*60],
                               count=len(rows),page=page,q=query,edit=edit,record=row)

    @app.route("/student/<student_id>",methods=["GET","POST"])
    def student_form(student_id):
        identifier,data=current();student=next((s for s in data["students"] if s["id"]==student_id),None)
        if not student:abort(404)
        if request.method=="POST":
            data["choices"]=[r for r in data["choices"] if r["student"]!=student_id]
            data["choices"].extend(dict(student=student_id,course=request.form.get(f"choice{i}","")) for i in range(6))
            save(data);return redirect(url_for("validation"))
        selected=[r["course"] for r in data["choices"] if r["student"]==student_id]
        return render_template("student.html",v=identifier,student=student,selected=selected,
                               courses=[c for c in data["courses"] if c["grade"]==student["grade"]])

    @app.route("/import",methods=["GET","POST"])
    def import_page():
        if request.method=="POST":
            upload=request.files.get("file")
            try:
                if not upload or not upload.filename:raise ValueError("请选择文件")
                data=import_bytes(upload.read(),upload.filename)
                save(data);flash("文件已解析为独立草稿版本；有业务错误时不能排课，可在线修正。旧版本保留。")
                return redirect(url_for("validation"))
            except Exception as exc:
                flash("导入失败："+str(exc),"error")
        return render_template("import.html")

    @app.get("/template.xlsx")
    def template():return download(workbook_bytes(),"WFLA-template.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/data.xlsx")
    def data_xlsx():
        identifier,data=current();return download(workbook_bytes(data),f"WFLA-input-v{identifier}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/data.json")
    def data_json():
        _,data=current();return download(json.dumps(data,ensure_ascii=False,indent=2).encode(),"WFLA-input.json","application/json")

    @app.get("/validation")
    def validation():
        identifier,data=current();issues=validate(data)
        return render_template("validation.html",v=identifier,issues=issues,data=data)

    @app.get("/errors.csv")
    def errors_csv():
        _,data=current();return download(csv_bytes(validate(data)),"WFLA-errors.csv","text/csv; charset=utf-8")

    @app.post("/solve")
    def solve_route():
        identifier,data=current()
        if validate(data):
            flash("校验未通过，请先修正错误。","error");return redirect(url_for("validation"))
        try:seconds=int(request.form.get("seconds",60))
        except ValueError:abort(400)
        seconds=max(5,min(seconds,600))
        with job_lock:
            if any(p.is_alive() for p in processes.values()):
                flash("已有求解任务正在运行，请等待完成。","error");return redirect(url_for("index"))
            run_id=store.new_run(identifier)
            p=multiprocessing.get_context("spawn").Process(target=worker,args=(str(store.path),run_id,identifier,seconds),daemon=True)
            processes[run_id]=p;p.start()
        return redirect(url_for("run_page",run_id=run_id))

    def get_run(run_id):
        run=store.run(run_id)
        if not run:abort(404)
        if run["state"]=="RUNNING" and run_id in processes and not processes[run_id].is_alive():
            # worker normally writes the result; re-read after the process exit before diagnosing a crash.
            run=store.run(run_id)
            if run["state"]=="RUNNING":
                store.finish(run_id,{"status":"ERROR","message":"求解进程异常中断；旧数据和结果未改变。"});run=store.run(run_id)
        return run

    @app.get("/run/<int:run_id>")
    def run_page(run_id):
        run=get_run(run_id);data=store.get(run["dataset_id"])
        result=run["result"] or {}
        return render_template("run.html",run=run,result=result,data=data)

    @app.get("/run/<int:run_id>/view")
    def view(run_id):
        run=get_run(run_id)
        if run["state"] not in ("OPTIMAL","FEASIBLE"):abort(400)
        data=store.get(run["dataset_id"]);result=run["result"];rows=timetable_rows(data,result)
        kind=request.args.get("kind","student")
        field={"student":"学生","teacher":"教师","room":"教室","section":"教学班"}.get(kind)
        if not field:abort(400)
        options = [(r["id"],r.get("name",r["id"])) for r in (result["sections"] if kind=="section" else data[{"student":"students","teacher":"teachers","room":"rooms"}[kind]])]
        if kind=='section':options.extend(('COMMON:'+a['id'],a['name']+' '+a['admin_classes']) for a in data.get('activities',[]))
        selected=request.args.get("id",options[0][0] if options else "")
        filtered=[r for r in rows if selected in r[field].split(";")]
        grid={}
        for r in filtered:
            for period in range(r["起始节"],r["起始节"]+r["节数"]):grid.setdefault((r["星期"],period),[]).append(r)
        coverage=[s for s in result["sections"] if selected in s["students"]] if kind=="student" else []
        grade=None
        if kind=='student':grade=next((s['grade'] for s in data['students'] if s['id']==selected),None)
        elif kind=='section':
            selected_course=next((s['course'] for s in result['sections'] if s['id']==selected),None)
            grade=next((c['grade'] for c in data['courses'] if c['id']==selected_course),None)
            if selected.startswith('COMMON:'):grade=next((a['grade'] for a in data.get('activities',[]) if 'COMMON:'+a['id']==selected),None)
        valid_cells={day_period(data,p) for p in active_slots(data,grade)} if grade else None
        period_count=max((p for _,p in valid_cells),default=data['config']['periods_per_day']) if valid_cells is not None else data['config']['periods_per_day']
        display_name=dict(options).get(selected,selected)
        teacher_names={t['id']:t['name'] for t in data['teachers']}
        return render_template("view.html",run=run,data=data,kind=kind,options=options,selected=selected,grid=grid,coverage=coverage,
            valid_cells=valid_cells,period_count=period_count,display_name=display_name,teacher_names=teacher_names,
            room_names={r['id']:r['name'] for r in data['rooms']})

    @app.get("/run/<int:run_id>/export/<fmt>")
    def export(run_id,fmt):
        run=get_run(run_id)
        if run["state"] not in ("OPTIMAL","FEASIBLE"):abort(400)
        data=store.get(run["dataset_id"]);result=run["result"]
        from .audit import audit
        if audit(data,result):abort(400,description="独立审计失败，不能导出有效课表")
        if fmt=="xlsx":return download(schedule_xlsx(data,result),f"WFLA-schedule-{run_id}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if fmt=="csv":return download(csv_bytes(timetable_rows(data,result)),f"WFLA-schedule-{run_id}.csv","text/csv; charset=utf-8")
        if fmt=="json":return download(json.dumps(result,ensure_ascii=False,indent=2).encode(),f"WFLA-result-{run_id}.json","application/json")
        abort(404)

    @app.post("/run/<int:run_id>/adjust")
    def adjust(run_id):
        run=get_run(run_id)
        if run["state"] not in ("OPTIMAL","FEASIBLE"):abort(400)
        data=store.get(run["dataset_id"]);result=deepcopy(run["result"])
        try:
            lesson=next(l for l in result["lessons"] if l["id"]==request.form["lesson"])
            day,period=int(request.form["day"]),int(request.form["period"])
            if not 1<=day<=data["config"]["days"] or not 1<=period<=data["config"]["periods_per_day"]:raise ValueError()
            lesson["start"]=slot(data,day,period)
            lesson["room"]=request.form["room"]
        except (ValueError,KeyError,StopIteration):abort(400)
        from .audit import audit
        issues=audit(data,result)
        if issues:
            flash("调整未保存，原方案保留："+"；".join(issues[:8]),"error")
            return redirect(url_for("run_page",run_id=run_id))
        result.update(status="FEASIBLE",message="手动调整后独立审计通过，原方案保留。",audit=[],parent_run=run_id)
        new_id=store.new_run(run["dataset_id"]);store.finish(new_id,result)
        return redirect(url_for("run_page",run_id=new_id))

    @app.get("/download/project.zip")
    def project_zip():return download(project_archive(),"WFLA-Course-Scheduling-System-v0.2.0.zip","application/zip")

    @app.get("/health")
    def health():return {"status":"ok","version":"0.2.0"}

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(exc):return render_template("error.html",error=exc),exc.code

    return app
