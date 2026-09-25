# 24mail 临时邮箱接码模块

> 基于 24mail.chacuo.net 的免费临时邮箱接码客户端 — **首选方案**

## ✨ 特点

- 🆓 **完全免费**, 无需 API Key
- 🔓 **无加密**, 纯 HTTP 明文请求
- ⏰ 邮箱有效期 **24小时**
- 🌐 支持 `chacuo.net` / `027168.com` 两个域名
- 🎯 一站式验证码获取 (生成邮箱 → 轮询 → 提取)

## 📦 依赖

```bash
pip install requests
```

## 🚀 快速开始

```python
from chacuo_mail_client import ChacuoMailClient

# 创建客户端 (无需任何认证)
client = ChacuoMailClient()

# 生成随机邮箱
email = client.generate_email()
print(f"邮箱: {email}")  # abc12345@chacuo.net

# 在目标网站使用此邮箱注册后...
# 等待并获取验证码
code = client.get_verification_code(
    subject_filter="Verification",  # 按主题过滤
    timeout=120,                     # 最长等待2分钟
)
print(f"验证码: {code}")
```

## 📖 API 参考

### `ChacuoMailClient(domain?, timeout?, proxy?)`

| 参数 | 类型 | 默认值 | 说明 |
|:---|:---|:---|:---|
| `domain` | str | `chacuo.net` | 邮箱域名 |
| `timeout` | int | `15` | HTTP 超时(秒) |
| `proxy` | dict | `None` | 代理设置 |

### 邮箱管理

| 方法 | 说明 |
|:---|:---|
| `generate_email(domain?)` | 生成随机邮箱, 返回完整地址 |
| `set_email(username, domain?)` | 自定义邮箱名, 返回是否成功 |
| `set_forward(target_email)` | 设置邮件转发 |

### 邮件操作

| 方法 | 说明 |
|:---|:---|
| `get_emails()` | 获取邮件列表 + 用户信息 |
| `get_email_content(mid)` | 读取邮件详情 (含HTML内容) |
| `get_latest_email()` | 获取最新一封邮件 |
| `delete_email(mid)` | 删除指定邮件 |

### 验证码

| 方法 | 说明 |
|:---|:---|
| `wait_for_email(...)` | 轮询等待新邮件 |
| `extract_code(email, pattern?)` | 从邮件中提取验证码 |
| `get_verification_code(...)` | 一站式: 等待 + 提取 |

## 📁 文件结构

```
24mail/
├── chacuo_mail_client.py  # 核心客户端模块
├── demo.py                # 使用示例
├── README.md              # 本文件
├── parse_har.py           # HAR 数据包解析脚本
└── 24mail.chacuo.net.har  # 原始 HAR 数据
```

## 🔄 与 SnapMail 对比

| | 24mail (首选) | SnapMail (备选) |
|:---|:---|:---|
| 费用 | 🆓 免费 | 💰 付费 |
| API Key | ❌ 不需要 | ✅ 必需 |
| 域名 | 2个 | 多个 |
| 有效期 | 24小时 | 可配置 |
| 自定义邮箱名 | ✅ | ❌ |
| 协议 | HTTP | HTTPS |
