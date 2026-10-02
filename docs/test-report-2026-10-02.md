# 研发 Issue 协作 Agent 测试报告

报告日期：2026-10-02，北京时间。版本：0.1.0。

**结论：当前版本已完成单用户、单仓库、单执行器的核心业务闭环，并通过本地工程控制测试；真实模型输出质量仍需人工审查，真实 GitHub 写入和容器部署尚未完成验证。** 可以展示、复现和解释已有机制，还不能据此宣称生产系统已经验收。

本报告对应应用代码 commit `e68c6aa8325312ece686c448c454cbfc97eeac81`。本次新增报告和学习文档不修改应用代码。2026-10-02 重跑本地自动化检查；模型与 40 例回归沿用 2026-10-01 保存的实测结果，未再次调用付费模型。

## 1. 如何理解“完成度”

采用逐项状态，避免给整个项目一个没有分母依据的百分比：

| 状态 | 含义 |
|---|---|
| 已实现且已验证 | 能指出代码、测试输入、断言和实测结果；结论限定在该测试环境 |
| 已实现，部分验证 | 已有可运行实现，但真实外部系统、边界条件或质量指标仍有缺口 |
| 已配置，待验证 | 配置文件存在，尚无成功执行记录 |
| 未实现 | 当前没有对应能力，不能把设计意图当成交付 |

“29/29 测试通过”表示已有 29 项自动化用例通过，不表示全部潜在需求都被覆盖。“40/40 执行检查”表示控制流程符合预期，包括正确拒绝与正确停止核对，不表示 40 项业务写入都成功。

## 2. 环境、范围与原始证据

| 项目 | 记录 |
|---|---|
| 本机环境 | Windows，Python 3.13.14，项目独立 `.venv` |
| 核心依赖 | LangGraph 1.2.12，SQLite checkpoint 3.1.1，MCP 1.30.0，OpenAI SDK 2.54.0，FastAPI 0.142.2 |
| 本次工具 | pytest 9.1.1，Ruff 0.16.9 |
| 本次应用测试 | fixture 模型、fixture 业务系统；真实 MCP 子进程；适配器使用 HTTP Mock |
| 历史真实模型联调 | `deepseek-flash`，真实 DeepSeek API，fixture 工具与业务系统 |
| 真实 GitHub 验证 | 认证与仓库只读连接；open issues 返回 0；未发布真实评论或标签 |
| 当前部署规模 | 一个服务进程、一个 owner、一个配置仓库；任务写入由一个执行器串行处理 |

证据文件：

- [本次 29 项测试、静态检查和依赖检查原始记录](../reports/tests-2026-10-02.json)：含版本、源码 commit、每个用例名称与结果。
- [40 例离线回归原始记录](../reports/fixture-2026-10-01.json)。
- [40 例真实 DeepSeek 开发集原始记录](../reports/deepseek-contract-2026-10-01.json)。
- [模型联调过程与两例问题分析](deepseek-analysis.md)。
- [此前 CI 触发与观测记录](../reports/github-actions-2026-10-02.json)。本报告编写时再次查询 Actions API，HTTP 200，运行列表仍为空。
- [既有安装、打包、HTTP、页面交互验证记录](verification.md)。这些是此前的操作记录，不能当作本次重新运行的结果。

## 3. 本次自动化检查结果

| 检查 | 实际结果 | 能证明什么 |
|---|---|---|
| `python -m pytest -q` | **29 passed in 13.77s** | 已有用例所覆盖的控制逻辑、集成协议和接口行为通过 |
| `python -m ruff check .` | **All checks passed** | 当前配置启用的导入、未定义变量等静态规则通过 |
| `python -m pip check` | **No broken requirements found** | 当前已安装依赖的声明关系没有冲突 |

没有运行代码行覆盖率工具，因此本报告不提供“代码覆盖率 X%”。未进行并发压测、稳定性长跑、漏洞扫描或真实企业环境验收。Ruff 和 pip check 也不能证明业务逻辑正确或依赖没有安全漏洞。

### 3.1 核心执行器：22 项用例

源文件：[tests/test_engine.py](../tests/test_engine.py)。此处使用确定性模型和 `DirectTools`，重点隔离验证业务控制；MCP 传输另由集成测试验证。

| 用例名称 | 输入或故障 | 核心断言 | 结果 |
|---|---|---|---|
| `test_read_task_requires_no_approval` | 只读调查 | completed；无执行动作；完成两次必要读取 | 通过 |
| `test_no_write_before_approval_then_exact_actions` | 起草评论与标签，再批准 | 审批前零评论；批准后 1 条评论、目标标签和 verified 记录 | 通过 |
| `test_reject_has_no_side_effect_and_cannot_be_overridden` | 拒绝后再次批准 | cancelled；无评论；过去决定不可覆盖 | 通过 |
| `test_restart_pending_approval` | 待审批时关闭并新建 Engine | 保留 awaiting_approval；重启后能批准完成 | 通过 |
| `test_duplicate_approval_does_not_duplicate_comment` | 同一批准请求两次 | 仍只有 1 条评论 | 通过 |
| `test_idempotent_submission_survives_restart` | 相同请求键重提；同键改请求 | 重启后返回原任务，不重复评论；改请求冲突 | 通过 |
| `test_stale_digest_rejected` | 提交错误的动作摘要 | 拒绝审批；无评论 | 通过 |
| `test_repository_change_invalidates_old_task` | 任务建立后切换仓库配置 | 旧任务不能在新范围批准 | 通过 |
| `test_tampered_plan_cannot_reuse_approval` | 批准后篡改 checkpoint 内动作正文 | 原审批失效；不发布新正文 | 通过 |
| `test_remote_success_local_failure_reconciles_after_restart` | 模拟远端已写入，但宿主未记录成功就异常 | 重启读回已有评论，完成后仍只有 1 条评论 | 通过 |
| `test_uncertain_absent_result_is_not_retried` | 写入超时且无法读回结果，再恢复 | reconciliation_needed；写请求只发送 1 次 | 通过 |
| `test_invalid_results_fail_before_write` × 4 | 不存在的引用、伪造来源、只读任务起草动作、非法分类 | 失败并给出稳定错误码；无评论 | 4/4 |
| `test_invalid_evidence_can_be_repaired_with_bounded_feedback` | 首次引用含 JSON 包装，第二次改正 | 记录 assessment_rejected；反馈后能完成 | 通过 |
| `test_model_cannot_expand_permissions` × 3 | 删除仓库工具、其他 Issue、增加 repository 参数 | 工具白名单或范围校验拒绝；无评论 | 3/3 |
| `test_model_budget_stops_infinite_tool_loop` | 模型反复读取而不结束 | 超过预算停止 | 通过 |
| `test_tool_budget` | 工具预算设为 1 | 第二次读取前停止 | 通过 |
| `test_approval_cannot_be_bypassed_by_raw_graph_resume` | 绕过 API，直接给图 resume=approve | 没有持久审批仍不能写入 | 通过 |

其中参数化用例按实际执行次数计数，总计 22 项。错误输出不断重复时，前述无效引用用例也覆盖有限修正后失败的路径；没有无限纠错。

### 3.2 协议和外部适配器：5 项用例

源文件：[tests/test_integrations.py](../tests/test_integrations.py)。

| 用例 | 验证内容 | 测试环境 | 结果 |
|---|---|---|---|
| 独立 MCP 进程 | 发现三个读工具；子进程 PID 不等于宿主；读取 Issue；拒绝写工具 | **真实 stdio MCP 进程**，fixture 数据 | 通过 |
| GitHub 评论分页 | 100+1 条评论分两页读取，固定 API 域名 | HTTP Mock | 通过 |
| 查询重试与写入不重试 | GET 超时后再试成功；POST 超时只发送一次，报 write_uncertain | HTTP Mock | 通过 |
| 默认禁止远端写入 | 开关关闭时在发起 HTTP 之前拒绝 | HTTP Mock，断言不发生请求 | 通过 |
| DeepSeek 适配器 | URL、模型标识、非思考参数、tool_calls 解析与 token usage | HTTP Mock | 通过 |

Mock 适配器测试能验证本地请求和处理逻辑，不能替代真实供应商联调。真实 DeepSeek 联调的证据另见第 4 节。

### 3.3 HTTP API：2 项用例

源文件：[tests/test_api.py](../tests/test_api.py)。使用 FastAPI TestClient，生命周期会启动真实 Engine 与 MCP 子进程，模型和业务系统仍为 fixture。

| 用例 | 实际断言 | 结果 |
|---|---|---|
| `test_api_task_approval_events_and_sse` | health、非法编号 422、创建待审批、旧摘要 409、批准完成、SSE 包含 action_verified、不存在任务 404、页面 200、请求键去重 | 通过 |
| `test_auth_and_cross_origin_protection` | 缺失 token 返回 401；正确 Bearer token 可创建任务；其他 Origin 返回 403 | 通过 |

SSE 只验证了事件响应格式与完成任务事件内容，尚无断线重连、Last-Event-ID 精确游标回放或长连接稳定性专项测试。无 token 时仅允许 loopback 客户端的分支已有实现，但没有单独模拟远程客户端断言。

## 4. 40 例任务回归与真实模型结果

### 4.1 案例构成

固定数据：[evals/cases.json](../evals/cases.json)。共 40 例：30 例只读任务，3 例批准，3 例拒绝，1 例待审批重启，1 例重复批准，1 例远端成功后宿主异常，1 例结果不确定。

只读任务覆盖 16 种 Bug 字段组合、5 例评论补充、3 例功能建议、2 例 Unicode 标题、2 例包含注入指令的正文，以及空正文和长正文。注入场景是有限样本，不能据此宣称覆盖所有提示词攻击。

数据集字节 SHA-256：

```text
47c7aaaf57de440542a4795f48c78f4b0d335c50d963e533013b836581b3aa10
```

两个最终报告使用相同数据集和 prompt 指纹。JSON 换行按 `.gitattributes` 保留，确保仓库中的输入字节与报告指纹一致。

### 4.2 分开看流程与判断质量

| 指标 | fixture 模型 + fixture 工具 | 真实 DeepSeek + fixture 工具 |
|---|---:|---:|
| 案例数 | 40 | 40 |
| 执行控制检查全部通过的案例 | 40/40 | 40/40 |
| missing_fields 判断正确 | 40/40 | **38/40** |
| category 判断正确 | 40/40 | 40/40 |
| 字段与分类检查都通过的案例 | 40/40 | **38/40** |
| 所有自动检查都通过的案例 | 40/40 | **38/40** |
| completed 状态 | 36 | 36 |
| cancelled 状态 | 3 | 3 |
| reconciliation_needed 状态 | 1 | 1 |

离线模型是根据测试协议编写的确定性替身，其 40/40 不能当作 LLM 理解能力。真实 DeepSeek 的 38/40 = 95%，但这是调试过的合成开发集上的严格检查比例，**不能写成“真实工单准确率 95%”**，也不是独立测试集成绩。

36 个 completed 包括只读调查与批准执行。三次拒绝正确结束为 cancelled，一次不确定写入正确停在待核对；后四例没有完成原写入目标。completed 也可能包含结构化判断错误，因此状态与质量必须分开报告。

检查名还需要结合代码理解：回归里的 `no_write_before_approval` 直接比较审批前评论数量，未同时断言审批前标签保持不变。批准后的标签结果以及只读、拒绝、不确定场景的最终无副作用有检查，但审批前标签应补充单独断言。故障案例是可控连接器异常，未模拟操作系统在任意位置强制结束进程。

实际最后一轮使用 81 次模型调用、80 次读工具调用，发生 1 次引用修正；输入 125,179 token、输出 21,849 token，共 147,028 token。案例 elapsed_ms 合计 205,128，包含临时环境、MCP 启动和恢复开销，不能作为线上响应时间或压测结果。金额未核对账单，报告不估算费用。

### 4.3 两个未通过案例

| 案例 | 表现 | 判断与处理 |
|---|---|---|
| `read-fields-15` | summary 指出只缺预期结果，但 missing_fields 同时把已提供的另外三项列为缺失 | 模型结构化字段与文字解释不一致。当前引用检查无法发现这种语义错误；保留失败记录，结果需审查 |
| `read-content-2` | 正文只有重复 error 日志，gold 认为缺 actual，模型视为已有简略实际结果 | 标注口径存在争议。严格结果仍计失败，应由独立人工标注解决；没有为提高分数修改 gold |

未系统评估建议是否实用、优先级是否合理、评论草稿是否需要编辑、各结论是否被引用支持。自动逐字引用校验仅证明“引用片段存在于已读来源”，不能证明“这段引用能支持整份建议”。

## 5. 功能完成度矩阵

| 功能 | 实现和验证程度 | 证据 | 剩余边界 |
|---|---|---|---|
| 模型选择读工具、循环调查 | 已实现且在离线/真实 DeepSeek 场景验证 | 引擎、预算测试；真实模型 80 次读调用 | 不支持通用代码编写、shell、任意文件工具 |
| Issue 与评论读取 | MCP 路径已验证；GitHub 部分验证 | 独立进程发现/调用、分页 Mock、真实仓库列表 | 仓库无 open Issue，尚无真实详情/评论的任务闭环 |
| Bug 信息完整性与意图分类 | 已实现，质量部分验证 | DeepSeek 字段 38/40，分类 40/40 | 开发集调过 prompt；无真实留出集，优先级未量化 |
| 来源与逐字引用校验 | 已实现且验证拒绝/修正路径 | 伪造来源、引用不存在、有限反馈测试 | 不保证结论被引用蕴含；不做语义事实核验 |
| 固定范围与工具权限 | 已实现且已有边界测试 | 删除工具、其他 Issue、额外仓库参数均拒绝 | 非完整安全审计；单 owner 无 RBAC |
| 起草评论和添加标签 | 已实现且 fixture 流程验证 | 批准后正文、数量、标签与计划一致 | 尚未测试真实 GitHub 标签不存在等业务行为 |
| 绑定具体动作的人工审批 | 已实现且已验证 | 旧摘要、篡改计划、拒绝后改判、直接恢复绕过均拒绝 | 无编辑计划、审批人登录与多人审批 |
| 重复提交/批准去重 | 已实现且在重启场景验证 | 同键同请求返回旧任务；重复批准仅一条评论 | 省略键会创建新任务；不是多进程去重保证 |
| checkpoint 暂停与恢复 | 已实现且待审批重启验证 | 引擎重启测试和真实宿主/MCP 演示 | 未测试任意指令位置强制 kill；两套 DB 不同事务 |
| 外部副作用核对 | 已实现且故障注入验证 | 写成功后本地异常恢复；未知结果不盲目重发 | 限定操作机制；没有跨系统 exactly-once 保证 |
| 调用预算与超时 | 已实现，模型/工具次数已验证 | 两项预算测试、HTTP 超时 Mock | 上下文超限/MCP 超时无专项用例；无全任务总时限 |
| 事件、耗时、token usage | 已实现且部分验证 | API 事件、usage Mock 与真实模型报告 | 本地事件记录；无指标平台、告警与审计防篡改 |
| API 与工作台 | 已实现且 API/页面基本流程验证 | 两项 API 测试、此前浏览器批准闭环 | 无前端自动化套件；页面手动刷新事件，未接入 SSE |
| 包安装与 wheel | 已实现且本机验证 | 安装、依赖检查与既有 wheel 记录 | 未覆盖所有声明支持的 Python 版本 |
| Docker/Compose | 已配置，待验证 | Dockerfile、Compose 文件 | 本机无 Docker；尚无成功运行证据 |
| Windows/Linux CI | 已配置，待验证 | 工作流已发布；API 尚无运行记录 | 触发被接受不能记为测试通过 |
| 多用户、组织权限、后台队列、多实例 | 未实现 | 当前架构明确为单实例 | 属于后续扩展，不能写为已有功能 |

因此，当前可以写“实现并测试核心闭环、审批与故障恢复机制”，不能写“已完成企业生产部署”“全面防止幻觉/提示词攻击”或“高并发、多租户”。

## 6. 仍需补齐的验收

按对简历证据和实际可用性的影响排序：

1. **真实 GitHub 端到端验收**：在指定测试 Issue 上验证真实 DeepSeek 调查、人工批准、评论/标签写入与读回。要保留工单 URL、操作前后状态、事件与确认过程，并检查标签不存在和权限不足的表现。
2. **冻结版本后的独立质量评测**：增加未经调试的真实/脱敏工单，由人先标注；除了字段和分类，还评价建议质量、依据、优先级与人工修改率。先解决 error 日志的标注口径。
3. **完成部署验收**：得到实际 Windows/Linux CI、Docker 镜像运行和 Compose 持久卷重启记录；目前配置均不能记为通过。
4. **补足已实现边界的专项测试**：审批前标签不变、上下文预算、MCP 超时、SSE 游标回放、评论分页上限、远程客户端访问限制、标签错误以及更真实的进程中断故障。
5. **有明确使用需求后扩展运行规模**：后台任务、用户身份、队列、数据库迁移与多实例租约；扩展前不宣称具备对应能力。

以上是待办清单，本次报告没有自动发布真实 Issue 评论、没有开启远端写入，也没有再次消费模型额度。

## 7. 复现方法

在项目目录使用 README 的独立环境。以下离线命令不需要 DeepSeek 密钥；评测明确使用 fixture 工具，即使 `.env` 配置 GitHub，也不会执行真实 GitHub 写入。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m issue_agent.evaluate --model fixture --report reports/local-fixture.json
.\.venv\Scripts\python.exe -m issue_agent.demo
```

真实模型评测需要本地 DeepSeek 密钥并产生 API 费用，下面命令仅供以后有意重新评测时使用，本次未运行：

```powershell
.\.venv\Scripts\python.exe -m issue_agent.evaluate --model deepseek --report reports/local-deepseek.json
```

阅读代码与测试之间的对应关系，见 [整体结构与核心代码解读](code-guide.md)。
