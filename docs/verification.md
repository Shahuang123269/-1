# 验证记录

验证日期：2026-10-01。第一版工程验证与真实模型开发集联调已完成。

运行环境为 Windows / Python 3.13，使用项目独立 .venv，MCP 1.30.0、LangGraph 1.2.12、SQLite checkpoint 3.1.1、OpenAI SDK 2.54.0。完整依赖以锁文件为准。

| 验证 | 实际结果 |
|---|---|
| ruff check | 通过 |
| pytest | 29 passed；含权限/范围、引用反馈、审批摘要、重复审批/任务提交、重启恢复与适配器测试 |
| pip check | No broken requirements found |
| 可编辑包安装 | 通过 |
| wheel 打包 | 通过；包含工作台 HTML |
| 独立 stdio MCP | 真实服务器发现和调用；子进程 PID 与测试进程不同 |
| 重启演示 | 创建待审批任务，关闭宿主/MCP，重新打开后批准并核验，完成 |
| 固定 40 案例 | 40 个控制检查通过；36 completed、3 cancelled、1 reconciliation_needed |
| DeepSeek 40 例开发集 | 执行检查 40/40；字段与分类严格检查 38/40；36 completed、3 cancelled、1 reconciliation_needed |
| DeepSeek 使用量 | 最后一轮 81 次模型调用，输入 125,179、输出 21,849，总计 147,028 token；金额以供应商账单为准 |
| 真实 GitHub 只读连接器 | 成功读取用户仓库的 open issues，数量为 0 |
| 本地 HTTP | 页面 200；重复提交返回同一任务；拒绝后 cancelled；API 测试含 SSE |
| 页面实际交互 | 浏览器提交任务后 awaiting_approval；批准后 completed，事件显示两个 action_verified |

固定报告保存在 reports/fixture-2026-10-01.json。40 个控制检查通过不是 DeepSeek 准确率，报告工具和模型模式均为 fixture。

真实模型报告保存在 reports/deepseek-contract-2026-10-01.json，工具仍为 fixture；同一开发集经过 prompt 调试，不能写成真实工单准确率。失败记录与标注争议见 deepseek-analysis.md。

凭据保存在本地 gitignored .env，未公开。尚未在 GitHub 创建评论或添加标签；没有真实用户规模、工时节省或独立留出集的质量数据。

本机未发现 Docker。首次上传后 CI 将验证 Windows/Linux 测试，以及 Linux Docker 构建、容器内重启演示；远端结果待确认。Compose 服务启动与真实模型在容器内调用仍需另行验证。

首次 Git 推送返回 403（身份为正确仓库 owner），本地源代码已提交，远端尚未更新。待核对 fine-grained token 的目标仓库选择、Contents/Workflows 写入权限后继续上传；API 返回的 account push 权限不能代替 token 的细分授权。

用户指定仓库通过认证访问成功；本地 origin 已关联，凭据只通过临时 askpass 交给 Git，不写入远端 URL 或 Git 配置。服务当前只支持单进程、单 owner，未实现组织 RBAC 或分布式任务队列。
