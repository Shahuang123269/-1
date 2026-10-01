# 开源来源与归属

本项目直接依赖 LangGraph（MIT）、LangGraph SQLite checkpoint（MIT）与官方 MCP Python SDK（MIT）；模型客户端使用 OpenAI Python SDK 的兼容接口接入 DeepSeek，许可证由各依赖发布包提供。安装发行包时应保留相应许可证文件。

工程设计参考 LangChain 的 Open SWE（MIT）、Deep Agents（MIT）以及已归档的 Agent Inbox（MIT）。本项目没有复制这些应用的整套源码或界面组件。当前代码中的 StateGraph、interrupt、Command 和 MCP ClientSession/FastMCP 调用属于对开源库公开 API 的使用；图执行与协议能力的作者是相应开源项目。

参考版本与实际采用边界见 docs/open-source-research.md。保留 docs/research-snapshot.json 便于追溯当时维护状态。未来如果直接移植代码，需在此列出源文件、commit、修改点，并保留其版权和许可证声明。

examples/original-demo 来自用户提供的 My-Ai-Project-main (1).zip，仅作为学习演进记录。其教程版本依赖独立，不由新入口加载。
