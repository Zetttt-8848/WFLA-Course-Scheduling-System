import argparse
import json
from pathlib import Path
from .demo import demo_dataset
from .io import import_bytes,workbook_bytes,schedule_xlsx
from .validation import validate


def main():
    parser=argparse.ArgumentParser(description="WFLA local timetable CLI")
    sub=parser.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("demo");p.add_argument("output");p.add_argument("--per-grade",type=int,default=12)
    p=sub.add_parser("template");p.add_argument("output")
    p=sub.add_parser("validate");p.add_argument("input")
    p=sub.add_parser("solve");p.add_argument("input");p.add_argument("output");p.add_argument("--seconds",type=int,default=60)
    p=sub.add_parser("audit");p.add_argument("input");p.add_argument("result")
    p=sub.add_parser("export");p.add_argument("input");p.add_argument("result");p.add_argument("output")
    args=parser.parse_args()
    if args.cmd=="demo":
        if not 1<=args.per_grade<=300:parser.error("per-grade must be 1..300")
        data=demo_dataset(args.per_grade)
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(workbook_bytes(data) if output.suffix==".xlsx" else json.dumps(data,ensure_ascii=False,indent=2).encode())
        return 0
    if args.cmd=="template":Path(args.output).write_bytes(workbook_bytes());return 0
    source=Path(args.input);data=import_bytes(source.read_bytes(),source.name)
    if args.cmd=="validate":
        issues=validate(data);print(json.dumps(issues,ensure_ascii=False,indent=2));return bool(issues)
    if args.cmd=="solve":
        from .solver import solve
        result=solve(data,max(1,args.seconds))
        Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(result["status"],result.get("message",""));return 0 if result["status"] in ("OPTIMAL","FEASIBLE") else 2
    result=json.loads(Path(args.result).read_text(encoding="utf-8"))
    from .audit import audit
    issues=audit(data,result)
    if args.cmd=="audit":print(json.dumps(issues,ensure_ascii=False,indent=2));return bool(issues)
    if issues:print(json.dumps(issues,ensure_ascii=False));return 2
    Path(args.output).write_bytes(schedule_xlsx(data,result));return 0


if __name__=="__main__":
    raise SystemExit(main())
