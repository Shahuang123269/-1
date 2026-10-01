# 开源方案调研与采用决策

调研日期：2026-10-01。通过 GitHub 公共 REST API 核对 star、许可证、维护/归档状态，并读取官方 README/许可证。Star 是当时快照，不代表稳定性、部署成本或本项目的成功率。

| 项目 | 当日 star 约数 | 许可证/状态 | 实际采用方式 |
|---|---:|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | 42,554 | MIT，活跃 | **直接使用运行时**，图循环、SQLite checkpoint、interrupt/Command；业务记录和执行规则自行实现 |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | 29,888 | MIT，活跃 | 参考工具与审批分层；当前不引入文件系统、shell、委派与整套 harness |
| [Open SWE](https://github.com/langchain-ai/open-swe) | 10,779 | MIT，活跃开发 | 参考调查/执行/验证及研发连接器分层；不整体 fork 或采用其平台/沙箱部署 |
| [Agent Inbox](https://github.com/langchain-ai/agent-inbox) | 1,093 | MIT，**已归档** | 仅参考待审动作展示思路；不作为新项目依赖 |

另使用 [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 实现协议。本版固定 SDK v1.30.0；原 demo 的 v2 高层 API 与此不混用。

## 为什么不直接改 Open SWE 的名字

Open SWE 是完整编码 Agent，包含源码修改、沙箱、授权、GitHub/Slack 入口和交付 PR。当前用户需求是有人工审批与可靠恢复的有限 Issue 协作任务；直接整体采用会增加部署和安全边界，却让个人贡献不清晰。

其 README 明确提示项目在活跃开发，可能出现破坏性变化，并不保证正确性、稳定性或兼容性；独立 Agent Server 生产部署还涉及许可。高 star 不能把这个提示变成“生产成熟保证”。本次采用维护中的基础库与可解释的业务实现。

## 固定参考版本与来源

- LangGraph 参考 commit：`b36b1d58a8b408455b512cfad3b1b26e02927282`。[固定版本源码](https://github.com/langchain-ai/langgraph/tree/b36b1d58a8b408455b512cfad3b1b26e02927282)
- Open SWE 参考 commit：`570287c524ce8056dcac8b4cd6c10d764f7c2540`。[固定版本 README](https://github.com/langchain-ai/open-swe/blob/570287c524ce8056dcac8b4cd6c10d764f7c2540/README.md)
- Agent Inbox 参考 commit：`f1616f3e7998e7e4fd574545b9558554d88d9c49`。[固定版本源码](https://github.com/langchain-ai/agent-inbox/tree/f1616f3e7998e7e4fd574545b9558554d88d9c49)
- Deep Agents 参考官方 README 与审批实现：[源码](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py)。没有复制该项目代码。
- [LangGraph 中断](https://docs.langchain.com/oss/python/langgraph/interrupts) 与 [持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。使用当前实际锁定版本支持的 ainvoke/Command API。
- [DeepSeek 官方接入](https://api-docs.deepseek.com/) 与 [工具调用](https://api-docs.deepseek.com/guides/tool_calls/)。当前推荐 `deepseek-flash`；旧 `deepseek-v4-flash` 名称仍可接受但已不代表原模型。
- GitHub 操作契约：[Issue 评论](https://docs.github.com/en/rest/issues/comments) 与 [Issue 标签](https://docs.github.com/en/rest/issues/labels)。仅添加允许标签，不替换全部标签。

## 原 demo 的复用与升级

保留 Model → Tool → Model、MCP Schema 适配和 SQLite checkpoint 的学习基础。原代码归档到 examples/original-demo；新入口统一 DeepSeek 配置，替换跨进程 MCP 接入，增加业务状态、审批、限定工具、远端结果核验和任务评测。旧 RAG 示例不承担本项目主线，与另一个企业 RAG 项目保持分工。
