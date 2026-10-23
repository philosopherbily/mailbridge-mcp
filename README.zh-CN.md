# MailBridge MCP

[![自动测试](https://github.com/philosopherbily/mailbridge-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/philosopherbily/mailbridge-mcp/actions/workflows/ci.yml)

[English](README.md) · [AI 安装指引](AI_START_HERE.md) · [客户端配置](docs/clients.md) · [安全说明](docs/security.md)

在本机运行的邮件 MCP 服务，通过 IMAP 读取邮件、通过 SMTP 发送邮件。兼容客户端可直接使用 stdio；ChatGPT 可通过 OpenAI 官方 Secure MCP Tunnel 接入。需要 Python 3.11 或以上，设计目标为 Windows、macOS 和 Linux。核心仅使用 Python 标准库，无需模型 API 密钥。

**当前为早期版本。** 官方文档确认的协议兼容性，不等于每种客户端、操作系统和邮箱组合均已通过实际测试。详见[兼容性表](docs/compatibility.md)。

## 为什么做这个项目

这个项目源于一个实际需求：希望直接在 AI 助手里使用现有公司邮箱，查找往来邮件、整理工作事项、准备回复。当所用 AI 客户端没有合适的内置邮箱连接器时，反复复制邮件到对话里，或为每个 agent 单独维护脚本，都会增加操作成本。对于允许 IMAP／SMTP 接入的邮箱，我们希望提供一套可以复用的连接方式。

MailBridge 把这套方式整理为本地 MCP 服务，并提供人和 AI 都能照着执行的安装说明。继续使用原有邮箱，登录凭据保存在本机；兼容的本地客户端按需启动服务，支持的 ChatGPT 接入可另配后台隧道。目标是完成一次配置后，日常使用无需反复打开 PowerShell。持续可用仍取决于主机、客户端和有效凭据，本版本的 OAuth 续期需由外部流程负责。

项目适合邮箱已开放 IMAP／SMTP、希望把自己的邮箱接入 ChatGPT、WorkBuddy 等兼容 MCP 客户端的用户。公开仓库提供通用实现和示例，不包含公司邮箱凭据或邮件数据。邮件桥本身无需模型 API 密钥，所选 AI 客户端和隧道仍有各自的使用条件；通过云端 AI 请求读取的邮件内容会传给该客户端／模型服务商。具体见[接入方式](docs/clients.md)和[隐私边界](docs/security.md)。

## 功能与边界

- 在指定文件夹和可选日期范围内，最多检查最近 100 封邮件的邮件头，再读取匹配邮件；读取不改变未读状态。搜索不匹配完整正文，不能把有限范围内无匹配等同于邮箱中不存在该邮件。
- 列出附件，并在大小限制内提取文本、CSV、JSON 附件。
- 生成不可变的本地邮件预览；启用发送、确认准确内容后才可发送。
- 保存发送结果及不确定状态，防止自动重复发送。
- 生成客户端配置及可选的后台服务文件。

首版不提取 PDF、Office 附件，不发送附件，不办理 OAuth 登录或自动刷新令牌，不支持 Microsoft Graph、EWS、POP3 或网页邮箱抓取。地址须为不含显示名称的 ASCII 邮箱地址；邮件主题和正文支持中文等 Unicode 文本。

### 历史邮件能查到什么程度

公开版**没有写死最早可查日期**，也没有 `2026-10-10` 这样的起始限制。调用 `search` 时传入 `after: "2023-01-01"`、`before: "2024-01-01"`，即可指定该文件夹的 2023 年日期范围，实际可见邮件以邮箱通过 IMAP 提供的内容为准。起始日期包含当天，结束日期不包含当天。

每次最多检查**该日期范围内 UID 最大的 100 封邮件**，最多返回 `limit` 条匹配结果；`limit` 默认 20，上限 100。目前没有翻页游标、历史邮件索引或可断点恢复的全量扫描。重复同一请求也不会自动进入下一页。因此，本版本不能承诺完整梳理多年邮件。判断“是否全部查过”前，须检查[搜索覆盖范围及历史邮件说明](docs/compatibility.md#search-coverage-and-historical-mail)。

## 安装

### 直接交给 AI 操作

把下面这段发给有本地终端操作能力的 AI，再补充它缺少的非敏感信息：

> 阅读 https://github.com/philosopherbily/mailbridge-mcp/blob/main/AI_START_HERE.md ，按 setup-flow.json 为我接入邮箱。使用现有实现，保留已有设置，逐步验证结果。密钥只让我在本地隐藏输入提示中输入，不要发测试邮件。

项目附带可安装的 agent skill：`skills/connect-mailbox/SKILL.md`。它引用本仓库，不包含凭据。具体步骤可减少模型误操作，但无法保证所有模型都能正确执行。实际验证范围见[验证记录](docs/validation.md)。

先安装 Python **3.11 或以上**及 Git。直接使用虚拟环境中的解释器，无需先激活环境。

**Windows PowerShell**

```powershell
git clone https://github.com/philosopherbily/mailbridge-mcp.git
cd mailbridge-mcp
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[keyring]"
$mbConfig = Join-Path $env:LOCALAPPDATA "mailbridge-mcp\config.json"
.\.venv\Scripts\python.exe -m mailbridge --config $mbConfig init
notepad $mbConfig
```

**macOS / Linux**

```sh
git clone https://github.com/philosopherbily/mailbridge-mcp.git
cd mailbridge-mcp
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install '.[keyring]'
# Linux：
mb_config="$HOME/.config/mailbridge-mcp/config.json"
# macOS 改用下面这一行：
# mb_config="$HOME/Library/Application Support/mailbridge-mcp/config.json"
.venv/bin/python -m mailbridge --config "$mb_config" init
```

若版本低于 3.11，请先更新 Python。`init` 生成不含凭证的模板，不覆盖已有文件；不指定 `--config` 时使用系统用户配置目录。配置和数据目录均应放在仓库外。

## 配置与检查

用本地编辑器修改生成的 JSON，按邮箱服务商文档填写账号、IMAP／SMTP 主机、端口及认证方式。推荐把 `secret_provider` 改为 `keyring`，首次检查保留 `allow_send: false`。JSON 中不要添加密码或令牌。

```json
{
  "schema_version": 1,
  "account_id": "personal",
  "email": "you@example.com",
  "username": "you@example.com",
  "imap": {"host": "imap.example.com", "port": 993, "security": "tls"},
  "smtp": {"host": "smtp.example.com", "port": 465, "security": "tls"},
  "auth": "password",
  "secret_provider": "keyring",
  "secret_env": "MAILBRIDGE_PASSWORD",
  "allow_send": false,
  "folders": ["INBOX"]
}
```

上面的地址和主机均为示例，须替换。使用 SMTP 587 的服务商通常要求 `security: "starttls"`，以其官方设置为准。不要关闭 TLS 证书验证。

macOS／Linux 使用 `.venv/bin/python`，Windows 改用 `.\.venv\Scripts\python.exe`。把配置路径换成实际绝对路径；全局选项 `--config` 必须放在子命令前。

```sh
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" secret set
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" doctor
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" doctor --connect --smtp
```

`secret set` 在本机终端以隐藏输入接收凭证，并存入受支持的系统原生密钥库。**不要把凭证粘贴到 AI 对话中。** 密钥库缺失或锁定时应处理错误，不应改用明文凭证文件。

普通 `doctor` 离线检查配置和凭证是否可用，不连接邮箱认证。`doctor --connect --smtp` 只检查 IMAP／SMTP 连接与认证，不发测试邮件。环境变量部署可使用 `secret_provider: "environment"`，并向实际服务进程提供 `secret_env` 指定的变量。OAuth 模式需设 `auth: "oauth2"`，令牌由外部流程提供；本版本不获取或自动刷新令牌。见[邮箱限制](docs/compatibility.md#email-providers)。

## 接入 AI 客户端

```sh
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" client-config --client claude
```

客户端选项为 `generic`、`claude`、`cursor`、`codex`、`workbuddy`。请用已安装本项目的虚拟环境解释器运行，以生成准确的绝对路径。输出包含私人配置文件的位置，不含凭证。合并到客户端现有配置，不覆盖其他 MCP 服务。具体步骤见[客户端配置](docs/clients.md)。

本地 stdio 服务由客户端管理启动和停止，通常不需要常驻后台。全局注册只表示在客户端及工作区允许的聊天／模式中可用，不能保证每个对话都能调用。

ChatGPT 另按[官方隧道指引](docs/chatgpt-tunnel.md)设置。工具使用期间，隧道主机必须保持开机、联网且进程正常运行。

## 发送流程

1. 初次保持 `allow_send: false`。确认需要开放发送时改为 `true`，并重启服务。
2. 让 AI 调用 `prepare_email`，展示完整收件人、主题和正文。
3. 对这封准确的邮件明确授权；客户端再将预览返回的 `draft_id` 和原样的 `confirmation` 传给 `send_email`，并仅在确认已有授权后设 `operation_authorized: true`。
4. 如遇超时或失败，先调用 `get_send_status`。`not_submitted` 表示确认未开始 SMTP 提交；经授权修复原因后，可在明确授权下用同一草稿及确认令牌重试，绝不自动重试。`uncertain` 表示结果不确定，须核查且不得重试。

确认令牌绑定邮件内容，不能独立证明用户已授权。仍须依赖客户端审批和操作者指令。SMTP 接受不等于最终送达；本服务不会自动向“已发送”文件夹追加副本。

## 工具与隐私

共八个工具：`mail_status`、`search`、`fetch`、`list_attachments`、`read_attachment`、`prepare_email`、`send_email`、`get_send_status`。

服务及发送记录保存在本机；工具返回的邮件内容会发送给所选 AI 客户端／模型服务商。因此不能把它理解为完全离线 AI，或“邮件内容绝不离开本机”。邮件及附件属于不可信内容，不应当作给 AI 的操作指令。

另见[排错](docs/troubleshooting.md)、[安全边界](docs/security.md)、[兼容性](docs/compatibility.md)。采用 MIT 许可，见 [LICENSE](LICENSE)。
