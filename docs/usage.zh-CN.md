# ExpObserver 使用指南

[← 项目首页](../README.zh-CN.md) · [English](usage.md)

界面默认英文。顶部 **Interface language** 可切换为**简体中文**；窄窗口下在 **More tools** 中找到。语言选择会在刷新后保留，研究标题、正文和证据保持记录时的语言。

节点研究记录支持 Markdown 标题、列表、表格和代码块，可切换阅读与原文，或展开到独立阅读窗口；HTML 不执行，图片以可打开的链接显示。研究概览中的“研究进展”汇集各层容器里已记录的发现与纠正，可直接跳回原节点。

顶部“保存与同步”将页面保存和 Agent 记录送达分开显示。待同步、失败和未完成的记录来自已连接工作目录，失败原因持久保留；重试只重新发送冻结的记录，不重跑实验。暂未解析的节点 ID 留在队列等待，不会被当成问题标题新建；旧队列中精确的运行 ID 证据引用可恢复为其所属节点。目录检查未完成或缺少记录时，送达状态保留未知。

## 在图中推进研究

选中一个或多个节点，点击工具栏的**复制引用**，也可以点击节点详情中的复制按钮。把引用粘贴到 Agent 对话，再补充你的问题。引用包含稳定的实验／节点 ID、容器路径、简短快照；接入信息可用时，还会附上按节点读取上下文的命令。Agent 按需读取最新记录，实验不绑定该对话。

- **自由组织。** 任意类型的节点都能拥有子节点。普通父节点仍是卡片；显式容器才包围内部工作（`isContainer: true`，`group` 默认开启）。支持折叠、展开、聚焦、分组、移动和连接，包含关系与研究关系分别维护。
- **连接执行与解释。** 运行记录保留配置、事件、指标和输出；评估及决策引用证据，修订解释时保留之前的记录。
- **比较候选。** 查看配置差异，并按选定的评价规则读取有效评估及历史评估。
- **核对证据。** 登记本地文件，保留经过校验的副本，在图旁查看图片、JSON、CSV 或文本。
- **接续工作。** 搜索研究图、切换项目、查看历史，并把旧快照恢复为一个新版本。

节点状态区分**未开始**（`proposed`）、**开放中**（`active`）、**暂停**（`paused`）、**已完成**（`completed`）、**已排除**（`rejected`）和**失败**（`failed`）。绿色实心勾表示完成，虚线圆环表示未完成，暂停条、减号和 × 分别表示暂停、排除和失败。完成表示这一步研究已结束，也可以得到负结果。失败使用红色描边，暂停使用棕色描边。暂停的工作记录停止原因和恢复条件。

画布统一使用 ELK Layered，在首次打开和研究图更新时自动从上向下排布，并统一计算正交连线。真实分支横向展开；缺少研究归属的记录依据已有顺序向下安置，不新增科学关系，明确的研究父子关系优先。状态变化复用现有布局，手动拖动的位置固定保留；点击自动布局会释放固定位置，并使用同一引擎重新排布。

开放问题保持静态标识；动态轮廓表示本地观测到的命令仍持有执行锁。进程完成或中断后，动态效果停止，问题的科学结论不随之改变。该活动观测覆盖已连接的本地执行器，不代表所有 Agent 的活动。顶部动画选项提供**跟随系统 / 开启 / 关闭**；开启可覆盖系统的“减少动态效果”偏好。

`N` 新建节点，`⌘/Ctrl K` 搜索，`⌘/Ctrl G` 将选中节点分组，`F` 适配整张图。拖动节点标题移动；Shift 拖动框选；触控板或鼠标中键／右键平移画布。双击容器可聚焦其子图。

![新版对比视图：保留原始嵌套 JSON 指标的两条模拟运行记录](../docs/screenshots/comparison.png)

*并排核对配置、嵌套指标和评估。此图使用模拟演示数据；实测案例见[精确检索研究](../examples/real-study/report.md)。*

## 追溯问题来源

问题卡片的“来源”入口区分已记录来源、明确声明的独立探索和来源未记录。详情保留出处节点或证据、一句提出理由，以及是否为事后补记；跨层来源可以直接跳转，已删除的来源保留原标识并显示不可用。编辑入口支持自定义来源类型。属于同一容器不等于来自同一发现，也不自动构成先后因果。

“外部关系”同时包含当前容器与其内部节点的关系，以及通往其他子树的关系；关系类型、方向与补充说明分别显示。Agent 可在原来的问题记录调用中一起提供来源，无需增加独立研究步骤。

## 定位当前工作

研究图上方的“当前工作”可一键进入正在聚焦的节点；多个节点时，按对话或已登记的外部任务选择。跳转会进入正确容器并选中原节点。失联的对话关联与当前工作分开显示，开放问题本身不代表正在执行。

Skill 用 `focus --project my-study --node NODE_ID` 声明本对话正在维护的位置，重复 `--node` 可同时聚焦多个节点；普通记录会刷新已有的关联。不再维护该实验时调用 `unfocus --project my-study`，只结束本对话的关联，不关闭其他对话、科学问题或远程任务。旧客户端继续兼容，历史对话不会被自动标成活跃。

远程训练可用 `task start` / `task update` 保留原始任务标识、真实起止时间和状态；前端分别保留执行器报告的耗时、起止时间推算的间隔和启动命令耗时。暂时性送达失败会退避；确定性的校验错误停止自动重交，修复后可显式重试。队列会标出前置记录并按依赖补交，不重跑实验。详见 [记录参考](../skills/exp-observer/references/records.md#remote-task-lifecycle)。

## 把 Skill 交给 Agent

将 [`skills/exp-observer`](../skills/exp-observer) 复制到 Agent 宿主支持的 Skill 目录，或直接把 [`SKILL.md`](../skills/exp-observer/SKILL.md) 的路径交给 Agent。独立客户端随 Skill 分发，研究项目无需把 ExpObserver 导入为依赖。

发行包中的完整 Skill 会自动唤起已安装的平台；移植到新电脑时，可从随包运行组件直接启动。请复制整个 Skill（含 `assets/`）。只需 Python 3.10+，无需 Node 或 pip。启动受限时继续本地暂存；`--no-autostart` 或 `EXP_OBSERVER_AUTOSTART=0` 可保持离线模式，`status` 始终只读本地状态。

界面中的**连接 Agent**会复制包含实际 Skill 路径、本地服务地址和当前实验 ID 的指令。粘贴到新 Agent 对话，再补充你的研究任务即可。

可以这样下达指令：

> 使用 ExpObserver Skill 接入实验 `my-study`，按我的研究任务推进。

实验属于其持久化记录。**多个对话和 Agent 可以共同维护同一个实验。** 每次操作显式指定项目，相关操作同时指定节点；允许分别声明本对话的非独占维护关联，不存在全局“当前实验”指针。

### 读取、执行、记录

以下示例使用 macOS/Linux Shell。Windows PowerShell 中请把 `python3` 替换为 `py -3`，将续行命令合并为一行（删除行末的 `\`），并使用 `C:/research/my-study` 等 Windows 源目录。含空格的路径需要加引号，例如：

```powershell
py -3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root 'C:/research/my study'
```

```sh
python3 skills/exp-observer/scripts/exp_observer.py init --id my-study --name 'My study' --source-root /absolute/study/directory
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study
python3 skills/exp-observer/scripts/exp_observer.py context --project my-study --node NODE_ID
```

`init` 会先在本地保存实验身份，再联系服务，因此第一次接入也可以离线完成。`context` 明确区分可用记录、有日期的缓存和服务不可用；读取成功不是继续研究的前提。服务运行时，可用 `projects` 列出实验。

一条命令即可保留实际发现。显式指定实验 ID 时，也可以自动准备缺失的实验，无需单独 `init`。客户端处理编号与引用，平台安排节点位置：

```sh
python3 skills/exp-observer/scripts/exp_observer.py event --project my-study \
  --question '什么影响交付时间？' --finding '复核增加交付时间' \
  --metrics-file results.json --artifact results.json
```

主脉络就是所有容器收起后的最外层研究图。用 `event --question '新问题' --container --after '已有发现'` 建立有意义的子问题容器，针对它记录的发现归入容器内部；`--parent '容器准确标题或 ID'` 可继续嵌套。双击进入容器，使用面包屑返回，也可以临时就地展开。容器边界上的连线保留内部原始端点，可点击追溯。无需额外标记或筛选“脉络节点”。

单独使用 `event --question TEXT` 可开启一个进行中的问题，`--reason` 可说明追查原因。准确标题或已保留的 ID 可复用本地队列、祖先队列或已读取上下文中的问题。默认建议**问题、实验、发现**，也可用 `record --kind TYPE` 自定义类型。每次 `--finding` 或 `--correction` 分别创建一个普通节点，保留此前发现；`--direction` 兼容已有记录，只用于真正改变研究方法。同一调用也能同时建立问题与首条发现。标题只作准确匹配，不模糊猜测；有重名时使用 ID。

用 `--after '之前发现的标题'` 表达与已有发现的关系：发现默认 `related_to`，纠正默认 `revises`，转向默认 `leads_to`；也可用 `--relation supports` 明确支持。重复使用 `--evidence '已捕获命令的标题'` 可关联已有证据。问题与发现的关联不声明因果，`event` 不添加记录顺序边。旧版 `record` 和独立命令捕获可以保留 `recorded_after`；界面将其画为较淡的虚线，不显示科学关系标签或流动动画。科学关系需明确记录。

自然收尾时，核对实际涉及的问题：已经解决的用 `--status completed`；未解决且本轮暂不继续的用 `--status paused --next-action '之后需要验证的问题'`。这些选项可与最后一个实质发现一起提交，`--pause-reason` 和 `--resume-when` 可补充暂停原因和恢复条件。最后的本地 `status` 回执分别返回登记状态和 `researchReview`，提示核对本地已知的开放问题，不会自动修改状态或关闭其他对话的工作。

实质不同的发现分别保留，即使由同一个脚本产生。重复测量复用同一问题。用 `event --question '准确问题' --status completed` 或 `paused` 更新问题的实际状态，不另建完成节点。节点数量不是目标。旧入口 `record --node NODE_ID` 仍可用于有意替换指定字段。

完整分析保存在原生 `notes` 字段中，可用 `--notes TEXT`，或用 `--notes-file -` 从标准输入读取 UTF-8 正文。提供发现、纠正或转向时，分析归该变化；未提供变化时归问题。Skill 默认把分析留在实验内，只有用户明确要求时才另写 Markdown 报告。嵌套指标原样保存，包括数组、null 和空容器；其他 JSON 顶层类型放到 `result`。原始数据、脚本和图片继续作为本地证据保留，仅文字事件不创建运行。

一次调用即可捕获真实命令及其结果文件：

```sh
python3 skills/exp-observer/scripts/exp_observer.py execute \
  --project my-study --title 'Evaluate candidate A' \
  --artifact results.json --artifact timing.csv -- python3 experiment.py
```

包装器自动提供记录编号，捕获真实命令的退出码、墙钟时间、标准输出／错误和指定文件，**不增加模型调用**。每条实际发现可用 `event --evidence 'Evaluate candidate A'` 复用该证据。重复测量使用 `execute --question '准确问题' --title '实际测量' -- COMMAND...`，给同一问题增加运行，不创建发现；`--node NODE_ID` 也可附到已有记录。不要为了拆分发现重跑工作。观测平台不规定实验阶段、方法、测量项目或交付格式。Agent 在研究本身已经改变判断或方向时简短更新；坐标、编号和展示格式由平台处理。

`init`、`event`、`record` 和 `execute` 只在工作目录内保存待交工作。应用负责发现已接入研究目录里的队列，包含后续新建的实验子目录，也覆盖先离线研究、后启动应用的情况；客户端无需写全局登记目录。应用只补交对应本机地址的队列，不跟随目录链接越过接入范围。实验成功时，记录服务不可用也不会把它改判为失败。回执用 `pending` 和 `recordingWarnings` 表示记录状态，并返回标准输出／错误路径。可选的手动 `sync` 在原工作目录执行；补交不会重跑实验或重读已变化的原始证据。

只有运行客户端才会暂存记录；单独保存结果文件不会入队。如果宿主阻止执行客户端或写工作目录，就无法暂存，研究继续并如实说明。研究目录在应用安装／接入阶段配置，研究 Agent 不承担这项工作。应用继续兼容旧版登记目录（`EXP_OBSERVER_STATE_DIR` 可覆盖其位置），新版客户端不再依赖它。安装 Skill 不会授予沙箱权限或安装系统服务。

Skill 在最终回复前，从研究目录调用一次 `status --project my-study`。它只读取本地回执，不使用 HTTP，并反映后台接收后的最新确认；过去的网络错误不代表已确认的记录仍待同步。返回的读取范围与交付状态明确区分已登记、待交付和未知状态。

批量登记已有文件、读取保留的证据、检查记录或导出研究图：

```sh
python3 skills/exp-observer/scripts/exp_observer.py artifact --project my-study --node NODE_ID --path results.json timing.csv
python3 skills/exp-observer/scripts/exp_observer.py read --project my-study --artifact ARTIFACT_ID
python3 skills/exp-observer/scripts/exp_observer.py check --project my-study
python3 skills/exp-observer/scripts/exp_observer.py export --project my-study --output my-study.json
```

通过 `EXP_OBSERVER_URL` 或全局 `--url` 参数选择其他本地服务地址。操作、版本控制和分段证据读取见 [Skill 指南](../skills/exp-observer/SKILL.md)、[记录参考](../skills/exp-observer/references/records.md)和 [HTTP／数据契约](../docs/contract.md)。[测试说明与研究提示词](../docs/observation-test.md)将接入检查和实验任务分别验证。自动命令采集使用显式的 `execute` 包装器；安装 Skill 不会安装全局 Hook。

### 观测研究步骤

可选的 observation 为节点上的工作计时，也可以覆盖跨越多条命令的分析。需要这项测量时再使用；它不是开展研究或登记结果的前提。开始步骤，完成工作，再使用返回的 observation ID 结束：

```sh
python3 skills/exp-observer/scripts/exp_observer.py observe start --project my-study --node candidate-a --title 'Review candidate A' --request-id review-a-start
python3 skills/exp-observer/scripts/exp_observer.py observe finish --project my-study --id OBSERVATION_ID --request-id review-a-finish
```

服务记录开始、结束时间及包含等待在内的墙钟耗时。Observation 属于节点，不绑定会话。如果运行时或供应商提供本步骤的用量计数，结束时传入 `--input-tokens N`、`--output-tokens N` 和 `--usage-source SOURCE`；`--usage-ref REF` 用于标识来源记录。缺少计数时省略对应参数：**未知保留为 `null`，实测零值保留为零**。使用步骤自身的计数，避免在多个 observation 中重复填写累计用量。

界面只汇总节点及其包含的后代。已结束的时间区间按并集合并，父子计时及并行工作不会重复累计耗时；未结束的步骤保留进行中标记。命令执行墙钟时间单独展示。Token 总量汇总已知计数，缺失计数或已开展的叶子节点缺少 observation 时标记覆盖不完整；语义连线和决策复用的证据不计入用量。

在 Happy 中运行时，可选的只读适配器会从本地宿主数据库导入实测推理用量，通过实际客户端调用关联研究记录。只有完整推理区间落入唯一、明确记录的活动区间时，才归属具体节点；其余保留为关联会话用量。输入、输出与缓存计数保留宿主原值，缓存单列展示，Agent 无需维护计数。该适配器依赖宿主内部格式；数据缺失或格式不支持时，用量保持未知，不阻塞实验记录。

主研究 Agent 使用 Codex 时，原生日志适配器自动读取本机 `CODEX_HOME/sessions` 中供应商报告的逐次推理计数。采集须同时匹配实际客户端输出回执与已连接研究目录的持久记录。记录边界划分工作区间，允许多个对话贡献同一个实验，也允许一个对话切换实验。节点归属标为 `recorded-work-window`；同时涉及多个节点或最后的总结保留在项目未分配用量中。Token 计数来自宿主，区间归属是基于记录边界的分配，不是模型返回的逐节点账单。响应 ID 去重，累计事件不会重复相加，不导入对话正文或凭证。新记录自动附带宿主线程提示，无需 Agent 额外调用。 采集器跨创建日期目录查找同一线程，支持接续多日的长对话；日志按增量流式读取，并识别 Windows 的 `-X utf8 -B` 等 Python 参数。用量详情中的 **Token 采集** 可展开查看未找到日志、未匹配回执、宿主尚未报告用量等具体状态。更新后可采集已有日志，无需重跑已完成的研究。

被捕获任务也可以自动提供实测用量。研究本身需要运行 Codex 任务时，`execute ... -- codex exec --json '任务提示词'` 会保留原生 JSONL 标准输出；导入器从以 `thread.started` 开始的有效流中读取已完成 turn 的计数，并关联实际命令运行。工具也可在保留的 JSON、流事件或运行指标中输出显式的 `expObserverUsage` v1 协议。任意嵌套 `tokens` 或 `usage` 指标不会被当作用量提取。格式、身份和限制见[执行用量契约](../docs/contract.md#captured-execution-usage)。

界面将**被测任务用量**（`execution`）和**关联会话用量**（`agent`）分别列示，不相加；被测任务计数不代表主研究 Agent 的完整成本。原生 Codex 日志中的模型身份保持未知，展示时间来自整次命令的执行边界，不是逐 turn 实测时间。缺失模型、时间或计数时保留未知，不根据提示词、命令参数或登记时间猜测。

## 记录保存在本地

权威记录和增量版本历史位于 `.exp-observer/records.sqlite3`，使用 Python 内置的 `sqlite3` 模块。证据副本位于 `.exp-observer/` 下各项目的 `evidence/` 目录；需要时会编码目录名，以兼容不同系统的路径。SQLite 事务、版本检查和幂等请求 ID 支持多个 Agent 共同维护。读取证据时按登记身份校验内容。

升级前请先停止已有服务。已有的 `state.json` 工作区会自动迁移到 SQLite，同时保留历史和原始 JSON 文件；后续更新写入数据库。

先停止使用该数据目录的所有服务，再备份**整个 `.exp-observer` 目录**，一并保留数据库、历史和证据。不要在服务运行时仅复制数据库文件。研究图导出包含引用，不内嵌文件内容。服务绑定 localhost，用于本地运行。

## 示例与开发

[精确检索研究](../examples/real-study/report.md)比较三种检索方法，并在纳入索引构建成本后重新审视决策。[独立接续复核](../examples/real-study/continuation-review.md)检查推理并提出下一研究分支。[研究脚本](../examples/real-study/study.py)在本地生成输入和测量；公开源码包含代码与报告，不附带已填充的研究工作区或归档原始测量。

前端使用 React、TypeScript、React Flow 和 Tailwind CSS，后端与可移植客户端使用 Python。开发、测试和贡献流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

采用 [MIT](../LICENSE) 许可。
