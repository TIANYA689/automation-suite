# 合规验证码挑战模块

该模块用于**已获授权目标**中的验证码/挑战流程编排：把挑战交给用户手动完成，或接入目标服务明确允许的官方提供方。它不会识别缺口、模拟拖动、伪造证明、隐藏自动化行为，也不会跨会话复用挑战结果。

## 已实现

- 显式授权标记与授权依据
- 精确主机或 `*.example.com` 子域白名单
- 非本地目标强制 HTTPS
- 可扩展 `ChallengeProvider` 协议
- 内置线程安全的人工完成适配器
- 等待、成功、失败、过期、取消、已消费状态
- 超时、活动任务并发上限
- 结果绑定到原会话和完整页面 URL
- 结果只能读取一次，之后立即清除
- JSONL 脱敏审计，不记录响应值和 URL 查询参数

## 目录

```text
合规验证码挑战模块/
├── captcha_challenge/
│   ├── providers/
│   │   ├── base.py
│   │   └── manual.py
│   ├── audit.py
│   ├── coordinator.py
│   ├── errors.py
│   ├── models.py
│   └── policy.py
├── examples/manual_flow.py
├── tests/test_challenge_flow.py
├── .gitignore
├── pyproject.toml
└── README.md
```

## 运行自检

模块只使用 Python 标准库，无需安装第三方依赖：

```powershell
Set-Location -LiteralPath '.\tools\automation-modules\过验证码\合规验证码挑战模块'
python -m unittest discover -s tests -v
```

交互示例仅指向本机授权测试地址：

```powershell
python -m examples.manual_flow
```

## 基本接入

```python
from captcha_challenge import (
    AuthorizationPolicy,
    ChallengeContext,
    ChallengeCoordinator,
    ChallengeKind,
    ManualChallengeProvider,
)

target_url = "https://auth.example.test/challenge"
provider = ManualChallengeProvider()
coordinator = ChallengeCoordinator(
    [provider],
    AuthorizationPolicy(("auth.example.test",)),
    timeout_seconds=120,
    max_active=4,
)

context = ChallengeContext(
    session_id="browser-session-id",
    target_url=target_url,
    kind=ChallengeKind.INTERACTIVE,
    authorized=True,
    authorization_reference="ticket-or-owner-approval",
)

ticket = coordinator.start(context)

# 用户在同一授权流程中完成挑战后，由界面层提交结果。
provider.submit(ticket.ticket_id, user_response)
coordinator.wait(ticket.ticket_id)

# 只能由原会话、原页面读取一次。
proof = coordinator.consume(
    ticket.ticket_id,
    session_id=context.session_id,
    target_url=context.target_url,
)
```

## 扩展官方提供方

实现 `captcha_challenge.providers.ChallengeProvider` 的 `supports`、`start`、`poll` 和 `cancel` 四个方法，再注入 `ChallengeCoordinator`。适配器必须满足：

1. 仅调用目标服务文档允许的官方验证接口，或用户明确授权的内部接口。
2. 不把 API Key、Cookie、验证码响应或授权 URL 写入日志。
3. `poll()` 返回的响应必须与当前 ticket 对应，不能缓存后跨任务复用。
4. `cancel()` 必须清除尚未消费的响应和提供方临时状态。

敏感配置应从环境变量读取并放在 `.env`；本目录已忽略 `.env`，不要提交凭据。

## 边界

本模块不是验证码“破解/绕过”工具。若目标没有明确授权或官方接入方式，应停留在人工操作，不应增加规避访问控制、反自动化或风控检测的逻辑。
