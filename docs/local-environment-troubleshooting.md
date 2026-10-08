# 本机连接问题处理记录

## DeepSeek（已修复）

2026-10-08 的初始错误为 APIConnectionError，尚未收到模型服务 HTTP 响应。DNS 正常；沿用系统代理失败，不沿用时访问官方 models 地址返回未认证的 401，说明直连通路可用。

在项目的模型客户端增加可配置项，当前本地 .env 已设置：

```dotenv
IA_HTTP_TRUST_ENV=false
```

该选项仅作用于 DeepSeek 使用的 HTTP 客户端，不更改 Windows 系统代理。TLS 校验保持启用，但不再沿用环境中的代理及自定义证书配置。需要企业代理或企业 CA 的机器应保持 true 并修复相应代理/证书。

修改后，两个公开工单快照的单次模型与 Agent 调查均完成。因此这次故障不需要通过换密钥、充值、重装 Python 来处理。未来其他 401、402、429 等错误需按其实际原因另行诊断。

## Codex 浏览器工具（待重启后复验）

当前已读到的沙盒日志显示：内置 cua_node 的 node_repl.exe 被其他进程占用，Windows 错误 32，导致运行时读/执行权限检查失败；上层显示 `helper_unknown_error: setup refresh had errors`。

项目 API、测试和模型已经可以运行；这个错误发生在 Codex 工具启动阶段。

处理顺序：

1. 保存工作，完全退出所有 Codex 窗口并退出应用，再重新打开原任务。
2. 若仍是同一错误，重启 Windows 以释放占用，然后重试浏览器验证。
3. 若仍失败，检查最新 `.codex/.sandbox/` 日志，按官方沙盒排障指引继续定位。不要直接删除整个 .codex，或批量修改用户目录权限。

参考：https://learn.chatgpt.com/docs/windows/windows-sandbox （Troubleshooting and FAQ）。

本轮没有修改 Codex 全局配置、系统代理、系统 Python 或用户目录 ACL，也没有结束其他用户程序。临时测试服务在核实进程命令行后关闭。

## Windows-MCP 替代验证（已完成）

用户安装并授权使用 Windows-MCP 后，插件能够读取桌面和操作 Chrome。2026-10-08 已用它完成本地工作台的提交调查、编辑评论、保存 v2、批准执行、拒绝另一方案和刷新后查询；详情见 [升级验收报告](upgrade-verification-2026-10-08.md)。

这使本次页面验收可以继续进行，但不代表原 Codex 内置浏览器工具的文件占用问题已经修复。若继续使用 Windows-MCP，无需为本次验收重装 Python 或更改权限；需要原浏览器工具时，再按上述步骤释放占用并复验。
