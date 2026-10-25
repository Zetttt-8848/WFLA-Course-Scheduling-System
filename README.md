# WFLA Course Scheduling System

面向上海一所开设 IBDP 课程的学校，为 10—12 年级设计的可复用自动排课系统。

**项目状态：可运行的本机 MVP v0.1.0。** 已提供中文交互网页、真实 CP-SAT 求解、独立硬约束审计、数据维护、Excel 导入与四视图导出。完整设计中的后续功能不等于本版本已经实现，详见下方范围说明。

## 下载与启动

[下载最新源码 ZIP](https://github.com/Zetttt-8848/WFLA-Course-Scheduling-System/archive/refs/heads/main.zip)。解压后运行，不要直接在压缩包内打开启动脚本。

Windows：安装 Python 3.11—3.13（已实测 3.13.5），安装时勾选 **Add Python to PATH**，然后双击 `start.bat`。首次启动会创建隔离环境并下载开源依赖，随后打开 **http://127.0.0.1:5000**。无需域名、数据库服务或 Microsoft Excel。关闭运行终端即可停止服务，数据仍保存在本机 `instance/`。首次安装需要网络；安装完成后排课无需外部服务。

也可在项目目录手动运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 run.py --open
```

macOS/Linux 可用 `python3 -m venv .venv`，再以 `.venv/bin/python` 执行相同命令；这两个平台尚未实测。5000 端口被占用时，可运行 `python run.py --port 5001` 并访问对应地址。

## 第一次完整体验

1. 打开首页，点击“载入虚构演示数据”，默认共 36 人，包含三个年级。
2. 点击“校验与排课”查看结果，再点击“开始排课”。页面会显示后台任务状态。
3. 完成后进入学生、教师、教室或教学班视图，切换对象查看课表；学生页可看到全部六个区块的选课。
4. 回到任务页导出 Excel/CSV，或展开“简单手动调课”，选择课次、时段和房间。冲突修改会被拒绝并说明原因。
5. 使用真实数据时，新建空白学期，下载模板并填写；也可在“数据维护”逐条增删改。学生添加后点击“六门选课”录入课程。

演示数据包含预设区块和分班，以便快速体验；具体时段、教师和教室确实由求解器生成。新数据可以省略预设教学班、分班和区块时段，由求解器联合选择。完全自动模式比有预设条件的演示更难，不能以演示耗时保证任意输入性能。

Excel 上传先成为独立草稿，错误按表、原始行号、字段显示；校验通过才允许求解。在线修改和重新上传均创建新版本，不覆盖旧数据。可随时切回旧版本。

## Project description

A locally hosted timetabling website for grades 10–12 at an IB school. It uses student choices, teacher availability and room data to generate conflict-free schedules across six compulsory blocks, with data validation, four timetable views and Excel/CSV exports.

## 项目目标

每学期由老师通过 Excel 模板或中文网页提供学生选课、师资、教室及固定活动数据，系统完成校验、教学班分配和排课。下一学期更新数据即可复用，不预置真实学生、教师或班级信息。

首版在普通笔记本本机运行，运行时不依赖付费云服务或外部 API。开发重点是数据模型、约束求解、资源与区块分配、校验、诊断及导出；前端使用朴素表格和表单。

## 已确认的学校规则

| 项目 | 规则 |
|---|---|
| 六区块 | 严格使用六个区块，每名学生的六门课恰好覆盖全部六块；每个教学班只属一块，其课次不得跨区块 |
| 排课单位 | 学科教学班，而非行政班；同科平行教学班可分属不同区块 |
| 10 年级 | 不分 HL/SL，使用独立“不分层”标记；不开设 English A；其余课程结构与排课规则沿用 |
| 11、12 年级 | 默认 3 HL＋3 SL；成绩达标且获校方批准者可选 4 HL＋2 SL，批准按学生、学期记录 |
| 学科组替代 | 支持 G6 由额外的 G3/G4 课程替代；高年级双 G1 语言路径按政策校验 |
| 资源 | 教师、学生、教室不得同时冲突；教室类型和容量、禁排、周课时与必需连堂均为硬约束 |
| 年级规模 | 11、12 年级各 6 个行政班，平均每班 22 人，即各约 132 人；实际人数以导入为准 |

10 年级演示规模暂按约 132 人规划，三年级约 396 人仅为容量测试假设。实际教学班数量由选课和资源约束决定，不能由行政班数量直接推定。

严格六区块全覆盖不表示每个区块中的所有课次必须同步：例如同块 HL 与 SL 课时不同，分别排满各自规定课时，不能为填满时段虚增 SL 课时。跨年级教师和教室统一检查，年级区块表是否同步由学校配置。

## 设计文档

完整方案见 [IBDP 自动排课系统设计文档 v0.2](docs/设计文档.md)，包括：

- 数据模型、ER 图、输入版本与结果审计。
- Excel 模板字段、选课政策、年级差异与四门 HL 特批校验。
- 严格六区块、自动分班、教师与房间分配的硬约束模型。
- 两阶段法与统一 CP-SAT 比较，区块分析引导统一求解的方案。
- 中文无解诊断、修复建议、超时与已证明无解的区分。
- Web/CLI 分层、四类视图、导入导出、测试与性能验收。
- 手动调课、锁课重排、软约束、A/B 双周及 TOK 编组路线。

## 实现与范围

使用 Python、Google OR-Tools CP-SAT、SQLite、Flask/Jinja2、openpyxl、Waitress 和 pytest。运行依赖版本见 `requirements.txt`；MVP 使用标准库 SQLite 保存不可变 JSON 输入快照及结果，尚未实现设计稿的完整关系表和 SQLAlchemy 迁移层。

| 已实现 | 当前限制与后续功能 |
|---|---|
| 10—12 年级政策、四门 HL 特批记录、严格六区块全覆盖 | 特批记录由老师登记，不自动评估成绩；尚无完整的 IB 特殊课程互斥目录 |
| 学生/教师/房间/课程等表格 CRUD、六门选课表单 | 不同年级使用同一节次表；暂不处理日期级节假日 |
| Excel 空模板、Excel/JSON 完整导入、版本切换与行号错误清单 | CSV 当前支持导出，不支持输入；上传最大10 MB |
| 自动或预设分班、教师分配、课次、房间、固定活动、禁排及必需连堂 | `max_sections=0` 时使用容量下限＋1的有限候选班数；无解时可手动提高上限重试，不能宣称更高班数也无解 |
| 独立检查器、中文数据错误和求解状态、基础资源核查建议 | 尚无最小冲突核心与经重算证明的最小松弛；核查建议不等于保证可修复 |
| 四类课表、Excel/CSV/JSON 导出、打印、简单手调与另存 | 手调只移动整段课次或换房间，教师随班固定；锁课重排仍待实现 |
| 快速返回第一份有效课表，报告班数目标是否证明最优 | 六项完整软评分、A/B 双周、TOK 自动编组尚未实现 |

`OPTIMAL`/`FEASIBLE` 仅在独立硬约束审计通过后可查看和导出；`UNKNOWN` 明确表示本次搜索未得出结论。`INFEASIBLE` 的结论限于输入与列出的候选班数上限。完整规则及剩余路线见[设计文档](docs/设计文档.md)。

## 命令行

下面以 Windows 隔离环境为例：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m wfla demo demo.xlsx --per-grade 12
.\.venv\Scripts\python.exe -X utf8 -m wfla validate demo.xlsx
.\.venv\Scripts\python.exe -X utf8 -m wfla solve demo.xlsx result.json --seconds 60
.\.venv\Scripts\python.exe -X utf8 -m wfla audit demo.xlsx result.json
.\.venv\Scripts\python.exe -X utf8 -m wfla export demo.xlsx result.json schedule.xlsx
```

生成空模板：`python -m wfla template template.xlsx`。`--per-grade 132` 生成三届约 396 人的虚构样例。验证或审计失败返回非零退出码；求解没有可交付结果时返回退出码 2。

## 测试与模块

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

在中文 Windows 用户目录下，若系统临时目录权限异常，可指定项目内的独立临时目录，例如 `--basetemp=instance/pytest-run`。该指定目录只供测试使用，pytest 会清空它，不要指向数据存放目录。

- `schema.py`：Excel、网页和 CLI 共用的数据契约。
- `validation.py`：年级、选课、资格、资源、固定活动与格式校验。
- `solver.py`：统一 CP-SAT 模型与有限候选班数范围。
- `audit.py`：从输出重新计算硬约束，不读取求解器内部表达式。
- `io.py`：模板、导入及四视图共享的导出投影。
- `storage.py`：SQLite 输入版本、后台任务和结果。
- `web.py`、`templates/`：中文网页；`__main__.py`：独立 CLI。

实测记录与范围见[验收记录](docs/验收记录.md)。

## 开发路线

- [x] 需求分析与设计文档。
- [x] 明确严格六区块、三个年级政策和本机交付范围。
- [x] 可运行闭环：合成数据 → 导入 → 校验 → 求解 → 独立零硬冲突审计 → 四视图 → 导出。
- [x] 输入版本、结果记录与简单手动调课。
- [ ] 完善完整设计中的自动增班搜索、锁课重排及其他剩余能力。
- [ ] 完整无解诊断、经复算验证的修复建议及软约束评分。
- [ ] A/B 双周轮换与 TOK 自动编组。
- [ ] 安装与操作说明、命令行示例、性能报告和完整验收。

## 数据与贡献

欢迎通过 Issues 或 Pull Requests 讨论数据模型、算法和验收用例。请使用完全虚构的数据复现问题，不在公开仓库、Issues 或附件中提交真实学生名单、教师安排或学校内部数据。运行数据和数据库文件已列入 `.gitignore`。

默认只监听 `127.0.0.1`，无公网登录或多人权限系统。不要把这个本机版本直接转发到公网。程序下载 ZIP 使用源文件白名单，不包含 `instance/` 数据、日志、虚拟环境或个人配置。

## License

本仓库以 [MIT License](LICENSE) 开源。第三方资料链接所指向的内容仍遵循其各自许可。
