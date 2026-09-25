# Shengqi 自建临时邮箱模块

此模块对接自建的 Cloudflare 临时邮箱服务：

- 服务根地址：`https://temp-email-shengqi.lianxiang.workers.dev`
- 管理后台：`https://temp-email-shengqi.lianxiang.workers.dev/admin`

它使用服务已提供的 HTTP API，不包含部署工程，也不会自动打开后台或尝试登录。

## 配置

客户端会自动加载同目录的 `.env`。该文件基于 `.env.example` 配置：

- `SHENGQI_TEMP_EMAIL_JWT`：地址 JWT，用于读取该地址的收件箱。
- `SHENGQI_TEMP_EMAIL_ADMIN_AUTH`：管理员密码，仅用于创建地址。
- `SHENGQI_TEMP_EMAIL_SITE_PASSWORD`：仅在站点启用了全局访问密码时填写。

地址 JWT 与管理员密码是不同的凭据。前者以 `Authorization: Bearer <JWT>` 访问 `/api/*`，后者以 `x-admin-auth` 访问 `/admin/new_address`。

## 使用

```python
from shengqi_temp_email_client import ShengqiTempEmailClient

client = ShengqiTempEmailClient()

# 需要 SHENGQI_TEMP_EMAIL_ADMIN_AUTH
mailbox = client.create_address(name="run001", domain="example.com")

# 将 mailbox.credential 保存到安全的运行时配置后，设置 SHENGQI_TEMP_EMAIL_JWT。
settings = client.get_settings()
code = client.wait_for_verification_code(subject_contains="验证码")
```

`create_address()` 返回的地址 JWT 不会被写入日志或文件。轮询接口为 `/api/parsed_mails`，默认每 5 秒一次，超时 180 秒；请按服务限流策略调整配置。

## API 范围

- `POST /admin/new_address`：创建地址，需要 `x-admin-auth`。
- `GET /api/settings`：验证地址 JWT 并读取地址信息。
- `GET /api/parsed_mails`：读取服务端已解析的邮件列表。

不提供用户注册、管理员数据查询、邮箱删除或后台配置操作。
