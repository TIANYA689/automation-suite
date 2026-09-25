# linshiguge 临时谷歌邮箱模块

获取临时 Gmail 地址、轮询收件箱并直接提取验证码。

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 验证码模式

推荐提供项目名，程序会自动生成原词和去分隔关键词，并在主题、发件人或正文任一字段中确认相关性。默认等待 120 秒，每 10 秒刷新一次，只输出验证码：

```powershell
.\.venv\Scripts\python.exe .\linshi_guge_client.py --project "YeBlock"
.\.venv\Scripts\python.exe .\linshi_guge_client.py --project "Telegram"
```

主题和发件人可以分别过滤；同时设置时必须同时满足：

```powershell
.\.venv\Scripts\python.exe .\linshi_guge_client.py --subject-keyword "verification code" --sender-keyword "qoder"
```

还可以只按正文过滤：

```powershell
.\.venv\Scripts\python.exe .\linshi_guge_client.py --content-keyword "verify your email"
```

过滤规则：

- `--project`：自动生成项目关键词，主题、发件人或正文任一命中。
- `--keyword`：自定义通用关键词，主题、发件人或正文任一命中。
- `--subject-keyword` / `--sender-keyword` / `--content-keyword`：只约束对应字段。
- 同时设置多个过滤条件时全部满足；没有任何过滤条件时拒绝运行，避免从无关邮件提取数字。

常用参数：

```powershell
.\.venv\Scripts\python.exe .\linshi_guge_client.py --wait-timeout 180 --interval 8 --keyword "Qoder"
.\.venv\Scripts\python.exe .\linshi_guge_client.py --code-pattern "code\s*[:：]?\s*(\d{6})"
.\.venv\Scripts\python.exe .\linshi_guge_client.py --show-body
```

验证码识别会先匹配“验证码 / verification code / OTP”等语义标签后的 4-8 位数字或混合码，支持将 `2 3 5 0 5 2` 归一化为 `235052`，再回退到独立 4-8 位数字；HTML 会先转纯文本，邮件 ID 自动去重。

## 探针

只获取地址并刷新一次收件箱：

```powershell
.\.venv\Scripts\python.exe .\linshi_guge_client.py --probe
```

## 模块调用

```python
from linshi_guge_client import LinshiGugeClient

with LinshiGugeClient(timeout=15) as client:
    address = client.get_email()
    message = client.wait_for_verification_code(project="YeBlock")
    if message:
        print(message["verification_code"])
```

`get_api_address()` 可调用 `GET /v1/mail/address` 获取普通临时地址；该接口不返回 Gmail token，不替代 Gmail 主流程。客户端会保存重定向后的服务 origin，并自动轮换 Gmail token。网络层使用单一 `requests.Session` 和统一 `_request()`，与 `mail_tm(ok)` 模块保持一致。
