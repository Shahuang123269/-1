# v0.2 代码结构与设计取舍

```text
issue_agent/
  api.py              HTTP、身份边界、任务/审批入队，提供页面和 SSE
  webhooks.py         原始请求体 HMAC 验签、仓库校验、事件过滤、delivery 去重
  workflow_store.py   任务队列、方案版本、审批历史、原子业务事务
  store.py            原有任务、动作意图、事件表，兼容历史数据库
  worker.py           OS 独占锁、队列领取与恢复、唯一执行图所有者
  engine.py           LangGraph 模型→工具→方案→审批→写入执行图
  policy.py           仓库配置校验、输入快照、方案 digest
  domain.py           请求、评估、字段证据和动作的数据结构
  models.py           DeepSeek 适配器和离线协议替身
  mcp_client.py       启动独立只读 MCP 子进程，限制传入环境
  mcp_server.py       暴露限定范围的读取工具
  connectors.py       GitHub/fixture 读写与读回核验
  benchmark.py        冻结公开样本、规则/单次模型/Agent 对照
  evaluate.py         原有 40 例离线控制流程回归
  ui.html             任务列表、逐字段证据、草稿编辑与版本审批
```

## 先读这条调用链

1. `api.create` 校验 TaskRequest，把仓库和当时的规则放进请求。
2. `WorkflowStore.submit` 在一个事务里创建任务与 start job。断电后两者一起存在或一起不存在。
3. `worker_loop` 领取最早的 queued job；API 请求此时早已返回 202。
4. `Engine.start_existing` 检查是否已有 checkpoint。有则接续，没有才初始化消息。
5. 模型提出读取调用，`tools_node` 校验工具名、Issue 编号和参数，再交给 MCP。
6. `proposal_node` 校验结构、引用和字段证据，保存输入快照与不可变方案。
7. 编辑草稿调用 `edit_plan`：旧记录不修改，生成下一个版本和新的 digest。
8. `enqueue_approval` 把批准和执行指令一起提交。队列满则整个事务回滚，不能留下“批准了但没执行指令”的悬空状态。
9. `approval_node` 校验旧 checkpoint，再装载当前被批准的具体版本。用户编辑不必直接改执行图存档。
10. `execute_node` 复核 digest、持久化批准、当前规则和当前 Issue 内容，再按意图记录→写入→读回核验执行。

## 六个必须能解释的问题

**为什么 queue 和 checkpoint 都要有？**

queue 记录外部要求系统做什么，checkpoint 记录执行图走到了哪里。只保存 checkpoint，HTTP 已接收但图尚未开始的任务可能丢失；只保存 queue，重启后无法知道调查中间状态。

**为什么不是“批准这个任务”就够了？**

任务中的动作和依据会变。digest 绑定任务、方案版本、仓库、Issue、动作、输入快照及规则。用户批准的是特定版本。编辑后必须批准新版本，旧 token 不能复用。

**审批时保存 digest，为什么写前还要重新读？**

digest 只能证明本地方案没变，不能证明用户没在 GitHub 补充信息。新评论或关闭 Issue 后继续追问会打扰维护者，所以写前核对源数据。GitHub 不提供此业务的跨请求事务，核对与写入之间仍有竞争窗口，不能保证绝对实时一致。

**为什么写请求超时不自动重试？**

可能已经发布但响应丢失。评论用确定性 marker 和完整正文读回；找到相同输出则核验成功。查不到但无法证明没写入，就保留 reconciliation_needed，避免制造重复评论。

**SQLite 能不能支持多个进程？**

API 和单个 Worker 可共享本机 SQLite，事务保护队列和批准。只有 Worker 运行图，OS 锁限制同一目录只有一个 Worker。这不是多节点租约队列，不支持共享盘横向扩容。

**这些校验能证明 AI 说得对吗？**

不能。它们能检查引用确实存在、动作在权限范围、审批对得上；语义归因、是否真的缺字段、追问是否有用仍需人工金标准和试用对比。不要把 50 项测试等同于模型准确率。

## 学习顺序

先用 fixture Issue #2 操作一次完整流程；再读 domain/policy；接着跟踪 api → submit → worker → engine；最后学习事务与故障恢复。每读一个模块，做一个可观察的小实验：重复提交、编辑后用旧 digest 批准、批准前补评论、写入后模拟异常、重启恢复。

需要实际掌握的个人贡献是：能解释取舍、改动一条仓库规则、定位失败任务、重现一个恢复场景，并说明系统尚不能保证什么。单纯背名词不构成项目掌握。
