# 本机凭据配置

不要把密钥发到聊天或提交到仓库。项目根目录 `.env` 已加入 `.gitignore`。如果需要新建文件，复制 `.env.example` 为 `.env`。

## DeepSeek

打开 [DeepSeek 控制台](https://platform.deepseek.com/)，登录后在 API keys 页面创建密钥。将值填入 `.env` 中的 `IA_DEEPSEEK_API_KEY=` 后面。当前默认模型为 deepseek-flash，接口为 https://api.deepseek.com；见 [官方接入说明](https://api-docs.deepseek.com/)。

## GitHub

打开 [Fine-grained token 创建页](https://github.com/settings/personal-access-tokens/new)：

1. Token name 例如 issue-agent-dev，有效期建议先设置 30 天。
2. Resource owner 选择 Shahuang123269。
3. Repository access 选择 Only select repositories，只选 -1。
4. Repository permissions：Contents、Issues 选择 Read and write；Workflows 开启写权限（官方权限级别为 write，按界面选择 Write 或 Read and write）。如果未列出这些权限，先通过 Add permissions 添加对应项。
5. 创建后将 token 填到 `.env` 的 IA_GITHUB_TOKEN。

Contents/Workflows 用于上传项目代码和工作流；仅运行 Issue 业务时应使用另一份只授权 Issues 的 token，缩小运行凭据权限。细粒度 token 的仓库与权限限制见 [GitHub 官方说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。

只替换 `.env` 的两个现有空值，不需要将示例文字当作真实密钥。保存后通知助手“配置完成”，再进行认证和小规模模型联调。

当前 IA_MODEL_MODE/IA_TOOL_MODE 默认 fixture；单独保存密钥不会让正在运行的离线服务开始计费或写入远端。切换服务模式需要重新启动，并仍受具体动作审批限制。
