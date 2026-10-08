# v0.2 升级验收记录（2026-10-08）

本报告区分工程机制验证、真实模型连通性与业务效果。当前完成工程升级，尚无依据保证“8 分”或写出效率提升比例。

## 已执行结果

| 检查 | 结果 | 能说明什么 |
|---|---|---|
| 升级前原有测试 | 29/29 通过 | 原版本基线 |
| 升级后自动化测试 | 50/50 通过 | 执行控制、接口、队列、版本审批、事件安全与评测边界 |
| 固定离线场景回归 | 40/40 通过 | fixture 控制流程；不是模型准确率 |
| Ruff | 通过 | 当前检查规则下无错误 |
| foundation_lab.py api | 通过 | 422 输入校验，202 接收，等待审阅，拒绝后 cancelled |
| DeepSeek 公开快照对照 | A01/A02，rules/single/agent 六组完成 | 真实模型与回放工具链可运行；无远程写入 |
| GitHub 凭据与仓库读取 | 成功 | 账号可访问目标仓库 |
| 本地真实 HTTP 验收 | 通过 | 排队、重复提交、编辑版本、旧摘要拒绝、批准后核验 |
| 浏览器点击验收 | 通过 | Windows-MCP 操作 Chrome，完成本地草稿编辑、版本保存、批准、拒绝和刷新后查询 |
| 本机 Docker | 未运行 | 未检测到 docker 命令；容器验证交由 GitHub CI |
| 真实 GitHub 发布闭环、维护者试用 | 未执行 | 不能声称生产可用或实际节省工时 |

最新代码验收 CI 已完成：**Windows、Ubuntu 均成功**。

- CI：https://github.com/Shahuang123269/-1/actions/runs/37711149546
- 验证代码 commit：`19b2da9ecc3a6a1b1d39b5bcdc1eebe8a1d21dee`。
- 两个平台均完成代码检查、50 项测试和 40 例离线回归。
- Linux 额外完成 Docker 构建、镜像内演示、Compose 独立 API/Worker 真实 HTTP 验收。
- Worker 收到停止信号后在 15 秒停止窗口内正常退出，容器退出码为 0；此验证确认正常停机，不等于证明所有中断点都不会失败。
- 本报告后续提交只补验收记录，没有改变以上代码。

## 本轮新增的关键验收

- 相同 Webhook delivery 不重复建任务；不同内容复用 delivery 返回冲突。
- 错误签名、其他仓库、PR、Bot 和非触发事件不能进入调查队列。
- 两个并发领取者不会拿到同一 queued job；第二个 Worker 不能持有同一目录锁。
- 创建任务与 job 原子入库；审批与执行 job 原子入库；队列满时批准记录回滚。
- 模拟领取后进程丢失，再启动可接续调查和已批准执行。
- 编辑草稿生成 v2，v1 摘要拒绝审批，执行内容精确匹配 v2。
- 审批已入队后不能再编辑同一方案；重复批准不生成第二条 job。
- 新评论、规则变动、批准后关闭工单使旧方案失效，避免继续发布。
- 已发布但本地未记录成功的评论可读回核对；未知写入不会盲目重试。
- 旧数据库保留；缺少输入快照的旧审批拒绝继续执行，需要重新调查。
- 原文引用被伪造时拒绝；字段状态与缺失列表必须一致。
- 评测快照篡改、无法重建的历史正文、未来编辑评论和不匹配 gold 被识别。

具体断言位于 tests/test_workflow.py、test_benchmark.py 和原有 engine/API/integrations 测试。自动化回归没有覆盖所有并发交错、所有供应商故障或浏览器视觉交互。

## 浏览器实际操作记录

2026-10-08 18:46–18:53，通过 Windows-MCP 实际操作 Chrome 中的本地工作台。使用单独的 `.test-runs/windows-mcp-ui` 数据目录、fixture 模型和工具，远程写入关闭；没有操作真实 GitHub 工单。机器可读摘要：[upgrade-browser-click-summary.json](../reports/upgrade-browser-click-summary.json)。

| 实际操作 | 观察与核对结果 |
|---|---|
| 提交 Issue #2 调查 | 页面轮询至等待审阅，显示逐字段信息和引用 |
| 修改评论但不保存 | 显示未保存提示，批准按钮禁用 |
| 保存为新版本 | 从 v1 生成 v2，摘要发生变化 |
| 批准 v2 | 页面轮询至已完成；审批历史记录绑定 v2 摘要 |
| 查看历史 | v1 与 v2 均保留，v1 原文没有被覆盖 |
| 刷新浏览器，点击刷新任务并重新选择 | 已完成任务及结果仍可查询；口令没有持久保存 |
| 创建第二次调查并拒绝 | 状态为 cancelled（页面显示已拒绝），执行动作数为 0 |
| 只读检查 API 与演示数据库 | 第一条任务两项动作均 verified；只产生一条评论，正文为编辑后的内容和系统标记，包含 needs-info 标签 |

这些点击属于人工式端到端验收，不是已建立的自动浏览器回归套件。未覆盖移动端、多浏览器、全部错误提示或真实 GitHub 发布。原 Codex 浏览器工具仍有文件占用问题，本轮使用 Windows-MCP 完成验证，没有改变系统权限。

## 真实模型对照记录

冻结数据来自先前只读采集的公开工单，按快照采集时的内容评估，不冒称历史初次分诊。机器可读摘要：reports/upgrade-public-replay-summary.json；含建议正文的本地报告：reports/local-upgrade-public-replay-direct.json（不上传）。

| 样本 | 方法 | 模型调用 | token | 总耗时 |
|---|---|---:|---:|---:|
| A01 | 规则 | 0 | 0 | 1ms |
| A01 | 单次 DeepSeek | 1 | 4369 | 5709ms |
| A01 | Agent | 2 | 6723 | 6410ms |
| A02 | 规则 | 0 | 0 | 0ms |
| A02 | 单次 DeepSeek | 1 | 5791 | 4947ms |
| A02 | Agent | 2 | 8057 | 6091ms |

模型标识 deepseek-flash；审核过的 gold 数量 **0**，因此准确率不计算。Agent 消耗更高，不能仅凭“多次工具调用”宣称优于单次模型。本次只证明连接与协议链路，不证明统计收益。

第一次尝试失败为 APIConnectionError。诊断发现沿用系统代理时连接失败，直连能收到服务端响应。增加模型客户端 IA_HTTP_TRUST_ENV 开关，本机 .env 设为 false 后六组完成。没有修改系统代理、全局权限或 Python 安装。

## 可复现命令

在项目根目录执行；临时目录名每次用新的值，以保留旧结果：

```powershell
New-Item -ItemType Directory -Force .test-runs\runtime | Out-Null
$env:TEMP=(Resolve-Path .test-runs\runtime).Path
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --basetemp .test-runs\my-run-1
.\.venv\Scripts\python.exe -m issue_agent.evaluate --report reports/local-fixture.json
.\.venv\Scripts\python.exe scripts\foundation_lab.py api
```

真实模型回放需已采集快照和本地密钥，命令见 README。Webhook 的当前证据是签名请求注入测试，尚未登记实际 GitHub Webhook；不能写成已上线接收真实事件。

## 完成度与后续门槛

工程主体已实现：事件入口、持久队列、可配置规则、字段证据、版本化审阅、输入过期保护、恢复与三组回放评测。

待补实证：独立人工标注验收集、真实维护者试用、真实事件/发布闭环。另需根据使用量决定是否补 Worker 存活监控、组织身份体系和多节点队列。目前不以这些未完成事项包装简历成绩。
