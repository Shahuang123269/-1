# MCP（Model Context Protocol）

MCP 是 Model Context Protocol（模型上下文协议）。它是一套开放协议，用来让 AI 应用以统一方式连接外部工具、数据源和提示词。

可以把它理解成 AI 工具生态中的“通用接口”：以前，每个 Agent 都可能要为文件、数据库、GitHub 或浏览器分别写一套连接方式；使用 MCP 后，这些能力可以由 MCP Server 以标准格式公开。

MCP 中有三个常见角色：

- MCP Host：承载 AI 应用的程序，例如桌面应用、编辑器或聊天程序。
- MCP Client：Host 中负责连接 MCP Server 的组件。
- MCP Server：提供工具、资源或提示词的服务，例如本项目的本地笔记搜索服务。

本项目的 `mcp_notes_server.py` 就是一个 MCP Server。它公开了 `search_learning_notes`、`list_learning_notes` 和 `calculate_expression` 三个工具；`07_mcp_learning_agent.py` 是 MCP Client 和 DeepSeek Agent 的组合。

安全原则：MCP Server 可能拥有读取文件、访问数据库或发送消息等权限。连接陌生 Server 前，要确认来源、理解其工具权限，尤其不能把密钥或敏感数据交给不可信的 Server。
