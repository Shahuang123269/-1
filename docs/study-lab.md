# 项目掌握练习：从运行到解释、修改和排错

**掌握标准是能够预测程序行为、找到控制代码、修改一处需求，并用失败案例验证边界。** 阅读文档后能复述名词只是起点。以下练习按能力验收推进，不承诺若干天后就一定能应对所有面试问题。

完整模块说明见 [code-guide.md](code-guide.md)，测试事实见 [测试报告](test-report-2026-10-02.md)。这份练习先假设会基础 Python；如果语法仍不熟，先把第一节的小例子写通。

你已说明会基础 Python，但不熟悉 async、FastAPI 和数据库。建议先完成第 1 节的三项入门实验，再从第 2 节开始，不必立刻通读整份模块文档。

## 1. 最少需要的基础

| 基础 | 本项目中要理解的具体地方 | 达标动作 |
|---|---|---|
| 字典、列表、函数、类 | request、messages、Assessment、Engine | 能打印/修改嵌套 JSON，解释对象方法 |
| JSON 和 HTTP | tool arguments、API 请求/响应 | 能指出 body、header、状态码分别是什么 |
| 类型与 Pydantic | TaskRequest、Action | 能解释为什么非法编号或额外字段被拒绝 |
| async/await、async with | 模型/MCP/连接器、Engine 生命周期 | 能解释等待网络和资源关闭；知道不自动等于并行 |
| SQLite 与事务 | Store.create、approve、intent | 能理解主键、唯一约束、提交和回滚 |
| pytest | 测试断言、tmp_path、故障替身 | 能运行单个测试，读懂失败断言 |

无需先读完所有框架源码。遇到一个概念时，回到它在本项目里的实际调用和测试。

已提供可运行的 [scripts/foundation_lab.py](../scripts/foundation_lab.py)，显式使用 fixture 模式、临时数据和空凭据。按以下顺序一次学一项：

```powershell
.\.venv\Scripts\python.exe scripts/foundation_lab.py async
.\.venv\Scripts\python.exe scripts/foundation_lab.py api
.\.venv\Scripts\python.exe scripts/foundation_lab.py sqlite
```

**async 实验：** 普通函数调用会立即运行，调用 `async def` 函数会得到一个协程对象，需要 await 或交给 asyncio.run。实验中先打印读取开始，在 await 处等待，再打印读取完成和调用方拿到数据。对照 Engine.tools_node 的 `await self.tools.call(...)`，知道什么时候真正取得工具结果。`await` 会让出事件循环，不自动把这个顺序流程改成并行流程；`async with` 则用于管理异步资源的进入与退出。

**API 实验：** TestClient 在本地模拟 HTTP，不需要开浏览器。GET /health 返回 200；非法 Issue 编号得到 422；合法任务返回 awaiting_approval；拒绝后为 cancelled。GET 用于取数据，POST 提交 JSON 请求；FastAPI 把 HTTP 请求交给 Python 函数，Pydantic 在执行前校验 JSON。分清 HTTP 成功与任务 completed：创建请求成功也可以返回待审批。

**SQLite 实验：** 用内存库创建一张以 task_id 为主键的表。在同一事务里先写 approve，再用重复主键写 reject，第二条触发异常，整个事务回滚，因此查询为空；之后单独写 approve 并提交，可以查到一行。对照 Store.approve，理解为什么过去决定不能覆盖，以及事务为什么需要包住检查与插入。事务仅保护该数据库，不能同时回滚已发布的 GitHub 评论。

每个实验先预测输出再运行。能不看解释讲明结果后，再阅读对应项目代码，而不是把运行成功本身当作已经掌握。

## 2. 练习一：不看代码先运行并预测

在项目目录运行离线重启演示：

```powershell
.\.venv\Scripts\python.exe -m issue_agent.demo
```

它使用临时目录和 fixture 模式，不读取本地 `.env`。输出包含 before_approval 与 after_restart_and_approval 两阶段。先写下预测，再核对：

- 第一阶段状态是什么？有建议草稿时是否已经发布评论？
- 两段 `async with Engine` 为什么仍能找到同一个任务？
- 第二阶段哪些动作是 verified？评论为什么有 marker？

练习工作台时，在单独 PowerShell 窗口设置临时模式，保留原来的凭据文件：

```powershell
$env:IA_MODEL_MODE='fixture'
$env:IA_TOOL_MODE='fixture'
$env:IA_DATA_DIR='data/study-lab'
$env:IA_ALLOW_REMOTE_WRITES='false'
.\.venv\Scripts\python.exe -m uvicorn issue_agent.api:create_app --factory --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，配置过 API token 时按工作台要求填写。窗口关闭后这些临时环境变量不再作用于其他窗口。

分别创建 Issue #1 的只读任务、#2 的待审批任务、#3 的功能建议任务。对 #2 先拒绝；点击“新建任务”再创建并批准。保存任务 ID，退出服务后用相同 data/study-lab 重启并查询另一个待审批任务。

**验收：** 无需看文档，可以准确解释 running、awaiting_approval、completed、cancelled 与 reconciliation_needed 的含义，且不会把 completed 当作模型判断必然正确。

## 3. 练习二：画一条实际调用链

对照实际请求，把以下调用用自己的话写成一页纸：

```text
ui.html 提交 JSON 与请求键
  → api.py 校验输入
  → Engine.create 创建/复用任务
  → model_node 请求模型
  → tools_node 校验 tool_calls
  → MCPTools → 独立 mcp_server → connector 读取
  → proposal_node 检查结果与原文引用
  → approval_node 暂停
  → API 保存具体摘要的决定，恢复图
  → execute_node 写入并读回
  → Store / API / 工作台显示结果
```

逐个回答：

- 谁选择要读哪个工具？谁真正调用工具？
- submit_assessment 为什么不属于远端 MCP 工具？
- 为什么模型不能通过读工具直接发评论？
- UI/API/Engine/MCP/连接器分别在哪个进程运行？
- 真正的 DeepSeek 调用发生在什么位置？FixtureModel 是否也调用 API？

**验收：** 可以从浏览器点击“开始调查”追踪到连接器读取，再追踪到建议返回。解释中必须出现具体函数，不仅是框架名称。

## 4. 练习三：读懂消息与数据契约

阅读 [domain.py](../issue_agent/domain.py)、[models.py](../issue_agent/models.py)，再看 [tools_node](../issue_agent/engine.py#L150)。

把一条模型调用请求拆成：`role / tool_calls / id / function.name / function.arguments`。找到宿主返回的 `role=tool`、匹配的 `tool_call_id` 和序列化 content。说明模型选择函数名不等于已经执行函数。

手写一个合法 Assessment，再分别构造：非法 category、伪造 source、原文没有的 quote、只读任务却包含 comment、读取其他 Issue 编号。对每种输入，指出拒绝发生在哪个层，而不是笼统说“Pydantic 会拦”。

四字段语义要能区分：完全没有提供与已经提供但太简略。标题用于意图分类，不计入四字段完整性；enhancement 的 missing_fields 为 []。Prompt 和 Schema 描述帮助模型理解规则，宿主的结构校验不会自动解决所有语义错误。

**验收：** 能解释实际两例 DeepSeek 未通过案例为何能经过结构/引用检查，却仍在字段评测中出错。

## 5. 练习四：理解图状态和两个数据库

阅读 [State 与图构建](../issue_agent/engine.py#L22)、[Store](../issue_agent/store.py)。

把五张业务表画在纸上，给每张表写一句“它解决哪个问题”：tasks、submissions、approvals、actions、events。再给 checkpoints.sqlite 写另一句用途。

从代码找出以下关系：

- `thread_id = task_id` 怎样关联暂停与恢复。
- messages 的 `operator.add` 怎样追加消息，为什么计数不是同一种更新。
- Store 记录的审批为何不能被图里的 approved=True 替代。
- checkpoint 能说明执行位置，为何不能说明远端评论一定不存在。
- SQLite 业务库、图检查点和 GitHub 三者是否同一个事务。

**验收：** 给出一个具体故障顺序说明为什么不能承诺 exactly-once，并指出当前实现提供了哪些限定恢复能力。

## 6. 练习五：从已有测试学习故障

先阅读测试、预测结果，再运行单项测试。例如：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_engine.py::test_tampered_plan_cannot_reuse_approval
.\.venv\Scripts\python.exe -m pytest -q tests/test_engine.py::test_remote_success_local_failure_reconciles_after_restart
.\.venv\Scripts\python.exe -m pytest -q tests/test_engine.py::test_uncertain_absent_result_is_not_retried
```

| 故障练习 | 需要独立解释的因果链 |
|---|---|
| 重复创建 | 请求键 → 绑定完整请求 → 返回旧任务 → 避免重新推理 |
| 重复批准 | 同一摘要/决定可重提 → 已完成任务直接返回 → 不重复评论 |
| 计划被改 | 重新算摘要 → 与持久批准不符 → 禁止新动作 |
| 远端已写、本地未记成功 | inflight 记录 → 重启先读回 marker → 核对旧动作后继续 |
| 超时且查不到结果 | 旧请求可能迟到 → 没有可确认回执 → 停在待核对 |
| 模型反复调用 | 计数达到预算 → 失败终止，避免无限循环 |
| 试图删除仓库 | 工具名不在白名单 → 执行前拒绝 |

当前崩溃用例是连接器抛异常模拟，不是操作系统在任意指令位置强制结束进程。运行这些测试不会向真实 GitHub 写入。不要在有真实凭据的执行流程中通过删除安全校验来做练习。

**验收：** 遮住测试答案后，能写出每项的输入、期望状态、副作用数量和理由，并知道未测的故障还有哪些。

## 7. 练习六：亲手审查真实工单

打开 [真实数据起步](real-data-starter.md)。先使用本地 A01、A08 快照，自己填写 category、四字段依据与 missing_fields；再检查 A03 的“没有复现步骤”是否存在标注争议，A06 为什么不应照抄 bug 标签。

先写自己的判断，再看后续 Agent 结果。现有候选都待人工标注，采集工具没有替你运行真实模型。对每条结果记录“哪里正确、哪里要修改、原文依据在哪里”，不能只保存漂亮截图。

评测使用独立的新案例时，不能先看输出再为该模型修改 gold。现有 38/40 是合成开发集结果；新案例和样本哈希要独立记录。历史评论中后来给出的答案会改变任务难度，需要明确回放时间与可读材料。

**验收：** 能解释工程测试、质量评测、真实 API 联调分别验证什么，并主动说清楚当前没有证据的能力。

## 8. 练习七：独立完成一个改动

建议先做一个范围小、贯穿几层的需求：**增加分页任务列表，让工作台能够找到以前的任务。** 当前只有按 ID 查询，这个练习尚未实现。

先写清楚输入、排序、分页、输出字段、认证和空结果行为，再定位 Store → API → UI。自己完成后演示任务创建、列表查询、重启后查询以及非法输入处理。测试应验证行为，不只检查返回了某个固定字符串。

随后可以挑战更深入的需求：**审批前编辑评论草稿，更新完整动作摘要，并使旧摘要失效。** 这需要考虑业务记录、图状态和审批的关系；当前版本没有此功能，不能直接改一下页面文字就宣称完成。

这些是学习任务，本次没有实施。通过小需求的代码 diff、验证记录和自己的设计说明，可以逐步形成你能解释的个人贡献。

**验收：** 不照抄现成方案，能说明影响哪些模块、什么条件下失败、如何证明原有审批边界没有被绕过。

## 9. 面试追问清单

先回答问题，再用“机制 → 代码 → 实测 → 限制”检查自己的回答。表格给的是回答要点，不是保证命中的题库。

| 问题 | 应覆盖的要点 | 代码或证据 |
|---|---|---|
| 项目解决什么问题？ | 指定 Issue 的调查、信息检查、草稿审批和写入核验；明确使用者与任务范围 | TaskRequest、整体流程 |
| 模型能自主做什么？ | 根据观察选择有限读工具、形成建议；不能自主授权写入 | model_node、tools_node |
| 为什么使用 LangGraph？ | 循环/分支、图状态和 checkpoint；业务授权仍由宿主控制 | build_graph、approval_node |
| 只有几个工具，MCP 是否必要？ | 跨进程协议发现与契约；小规模也可用本地函数，需要承认引入的复杂度 | MCPTools、进程测试 |
| 如何防止提示词扩大权限？ | 固定配置、工具白名单、精确参数、有限动作与审批；有限测试不等于全面防护 | scope / permission 测试 |
| 为什么批准要带 digest？ | 绑定仓库、Issue 和完整动作参数；旧批准不能执行修改后的正文 | action_digest、execute_node |
| digest 是加密或登录吗？ | 内容指纹；不是签名，不验证审批人的真实身份 | domain.py、固定 owner |
| 为什么有两个数据库？ | 执行位置与业务决定/动作事实不同；不是同一个原子事务 | checkpoint、Store |
| 重启后评论会不会重复？ | marker、操作状态、先核对；仅有限定机制，无法普遍保证只写一次 | 故障测试、verify_action |
| 写入超时怎么办？ | 传输超时可能已发生；先核对，未知则停，不盲目重发 | write_uncertain 路径 |
| 评论成功但标签失败呢？ | 动作记录分别保存；没有跨系统回滚，failed 不代表零副作用 | execute_node |
| 为什么模型结果引用存在仍会错？ | 子串存在只证明引用可追溯，不证明结论和字段判断正确 | 两例模型失败 |
| 29 项测试、40/40、38/40 分别是什么？ | 自动化控制用例、fixture 回归、真实模型合成开发集严格检查；分母和环境不同 | 原始报告 |
| 页面实时流式吗？ | 后端有 SSE；页面目前调用事件查询，没有逐 token 输出 | API、ui.html |
| 当前支持多少用户/worker？ | 一个 owner、一个进程执行器；锁不协调多进程，创建请求等待执行 | Engine.lock、API |
| 如何扩大规模？ | 从持久队列、领取租约、恢复语义与身份需求出发，再考虑数据库迁移 | 当前架构边界 |
| 自己做了什么？ | 区分原 demo、开源运行时、业务控制和自己理解/修改/验证的部分 | 来源说明、Git diff、实验记录 |

LangGraph 官方 [interrupt 文档](https://docs.langchain.com/oss/python/langgraph/interrupts) 说明暂停、持久 checkpoint 和恢复语义。阅读时重点验证节点恢复会重新进入这一点，避免把外部写入放在可重复执行却没有业务核对的地方。

## 10. 最后的自测

当你能完成以下动作，就具备了一组可展示的掌握证据：

1. 三分钟内清楚介绍使用场景、输入输出、技术选择、自己的工作和当前结果。
2. 不看稿画出调用链与模型、工具、审批、执行节点。
3. 现场定位审批摘要、写入去重、恢复和范围校验的代码。
4. 独立复现两个故障，预测并解释最终状态和副作用。
5. 完成一个需求修改，用实际验证说明没有破坏关键边界。
6. 能解释失败案例，并诚实区分已验证结果与计划中的能力。

这是学习验收标准，不是面试通过保证。你的目标是建立能够被代码、操作记录和推理过程支持的回答。
