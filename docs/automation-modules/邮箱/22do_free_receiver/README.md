# 22do 免费接码模块

这是重新创建的独立 Python 项目，目录为 `22do_free_receiver`。模块基于 `../22.do网页.har` 中的 22.do 免费网页流程实现，不依赖后台 API Token，也不会修改旧 `22do` 目录。

# Set-Location -LiteralPath .\tools\automation-modules\邮箱\22do_free_receiver
# .\venv\Scripts\python.exe .\main.py --action create

## 功能

- 默认调用 22.do 新接口生成谷歌邮箱（`gmail.com` / `googlemail.com`）
- 指定账号名和域名创建邮箱
- 支持新接口随机切换邮箱
- 打开已有邮箱并读取最新邮件
- 从邮件主题或正文提取验证码
- 一站式接码流程：生成邮箱并等待验证码
- 支持主题和发件人关键词过滤
- 支持邮箱删除、延期
- 项目内独立虚拟环境和依赖文件

## 项目结构

```text
22do_free_receiver/
  main.py
  README.md
  requirements.txt
  .env.example
  implementation_plan.md
  data/
    har_summary.json
  src/
    receiver_22do_free.py
  tests/
    test_receiver_22do_free.py
  venv/
```

## 安装

```powershell
Set-Location -LiteralPath .\tools\automation-modules\邮箱\22do_free_receiver
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## 使用

默认创建谷歌邮箱：

```powershell
python .\main.py --action create
```

指定邮箱账号和域名：

```powershell
python .\main.py --action create --local test123 --domain gmail.com
```

调用新接口随机切换邮箱：

```powershell
python .\main.py --action change
```

查看最新邮件：

```powershell
python .\main.py --action latest --email test123@linshiyou.com
```

生成邮箱并等待验证码：

```powershell
python .\main.py --action get-code --timeout 180 --interval 8
```

等待验证码：

```powershell
python .\main.py --action wait-code --email test123@linshiyou.com --timeout 180 --interval 8
```

按主题过滤：

```powershell
python .\main.py --action wait-code --email test123@linshiyou.com --subject code
```

延期邮箱：

```powershell
python .\main.py --action delay --email test123@linshiyou.com
```

删除邮箱：

```powershell
python .\main.py --action delete --email test123@linshiyou.com
```

## Python 调用

```python
from src.receiver_22do_free import Receiver22DoFree

client = Receiver22DoFree()
mailbox = client.create_email()
print(mailbox["email"])

code = client.wait_for_code(mailbox["email"], timeout=180)
print(code)
```

## HAR 解析结果

HAR 中确认了免费网页模式：

- `POST /action/mailbox/gmail`，新谷歌邮箱生成接口
- `POST /action/mailbox/account`
- `POST /action/mailbox/change`
- `POST /action/mailbox/login`
- `POST /action/mailbox/message`，需要网页 Bearer Token
- `POST /action/mailbox/deleteMessage`，需要网页 Bearer Token
- `POST /action/mailbox/delete`
- `POST /action/mailbox/delay`
- `POST /action/mailbox/download`
- `GET /content/{content_id}`
- `GET /view/{view_id}`

新 HAR 的请求摘要写在 `data/` 目录下（该目录是本地派生产物，不进版本库）。新页面当前默认邮箱为 `googlemail.com`，所以模块默认也使用谷歌邮箱。

## 接码流程说明

参考 `mail_tm(ok)` 的流程，22do 模块现在也是：

```text
生成谷歌邮箱 -> 打印邮箱给注册流程使用 -> 轮询邮件列表 -> 读取邮件详情 -> 提取验证码
```

区别是 22.do 新网页的邮件列表接口 `POST /action/mailbox/message` 需要网页 Bearer Token。没有 Token 时，脚本可以生成邮箱，但无法自动轮询收件箱。

配置方式：

```dotenv
RECEIVER_22DO_BEARER=网页localStorage里的token
```

如果能拿到 Turnstile 回调 token，也可配置：

```dotenv
RECEIVER_22DO_CF_TOKEN=Turnstile返回的cfToken
RECEIVER_22DO_VISITOR_ID=浏览器localStorage里的uuid
```

配置后运行：

```powershell
python .\main.py --action get-code
```

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
```

## 注意

22.do 免费网页接口可能受 Cloudflare 或站点策略影响。如果命令返回 403、429 或跳转异常，建议降低轮询频率，或在浏览器中确认站点当前是否可用。

## 🌐 关于我们
📦 青龙脚本库：[https://gitee.com/zhushenzhiye/wuyin.git](https://gitee.com/zhushenzhiye/wuyin.git)
💬 QQ群聊：[https://qm.qq.com/q/lQnQsCcX5u](https://qm.qq.com/q/lQnQsCcX5u)
☁️  仓库：[https://pan.quark.cn/s/988b665296d7](https://pan.quark.cn/s/988b665296d7)
