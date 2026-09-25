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
- **声明式人工交接**：把「哪几步要人工、每步是什么类型的挑战、值能否跨运行复用」
  写成数据，按声明依次收集并交付到指定槽位

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
│   ├── handoff.py
│   ├── models.py
│   └── policy.py
├── examples/manual_flow.py
├── tests/test_challenge_flow.py
├── tests/test_handoff.py
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

## 声明式交接

`ChallengeCoordinator` 负责**一个**挑战的绑定、过期与一次性消费；它不知道一个工作流
**需要哪些**挑战。那份知识如果只写在散文里（「记得每次运行前重新取一次令牌」），
就是最容易被执行环节跳过的东西。`captcha_challenge.handoff` 把它变成一份可评审、
可 diff、可做覆盖性校验的声明。

```python
from captcha_challenge import (
    AuthorizationPolicy,
    ManualHandoff,
    apply_to_environ,
    parse_challenge_requests,
)

challenges = parse_challenge_requests([
    {"env_name": "TARGET_WIDGET_TOKEN", "label": "第三方组件令牌",
     "kind": "official_widget", "fresh_per_run": True},
    {"env_name": "TARGET_EMAIL_CODE", "label": "邮箱验证码",
     "kind": "email_otp"},
])

handoff = ManualHandoff(
    AuthorizationPolicy(("target.example.test",)),
    session_id="run-1",
    authorization_reference="owner-approval-2026-09-25",
    target_url="https://target.example.test/register",
)

proofs = handoff.collect(challenges, submit=lambda request: input(f"{request.label}: "))
apply_to_environ(proofs)
```

`submit` 是**注入**的人工环节：它拿到声明，返回操作者在自己的会话里完成的结果。
注入是为了让策略、绑定、过期、一次性消费这一整条链能在没有浏览器、没有人的情况下
被测试覆盖——见 `tests/test_handoff.py`。

三条设计约束：

1. **未知的 `kind` 直接拒绝，不取默认值。** 给一个默认值等于替操作者决定他面对的是
   什么类型的挑战；类型错了，提供方看起来能用、实际不能。
2. **`fresh_per_run` 是一等字段。** 一次性挑战的真正代价在这里：一个需要三次调用的
   工作流需要三份**新鲜**的值。把它写成数据，才不会在运行时才发现。
3. **值只交付一次，且不进审计。** `collect()` 返回一次，`summarize()` 只报长度，
   `export_lines()` 是唯一带值的地方——终端是交付通道，审计文件不是。

作业侧的完整接入例子见 `projects/20260925-avalon-register-login/` 下的
`fetch_manual_inputs.py`（作业目录不进版本库，故只点名目录）。

## 扩展官方提供方

实现 `captcha_challenge.providers.ChallengeProvider` 的 `supports`、`start`、`poll` 和 `cancel` 四个方法，再注入 `ChallengeCoordinator`。适配器必须满足：

1. 仅调用目标服务文档允许的官方验证接口，或用户明确授权的内部接口。
2. 不把 API Key、Cookie、验证码响应或授权 URL 写入日志。
3. `poll()` 返回的响应必须与当前 ticket 对应，不能缓存后跨任务复用。
4. `cancel()` 必须清除尚未消费的响应和提供方临时状态。

敏感配置应从环境变量读取并放在 `.env`；本目录已忽略 `.env`，不要提交凭据。

## 边界

本模块不是验证码“破解/绕过”工具。若目标没有明确授权或官方接入方式，应停留在人工操作，不应增加规避访问控制、反自动化或风控检测的逻辑。

具体到「谁来回答这个挑战」，本模块只接受两种来源：**操作者本人**（`ManualChallengeProvider`），
或目标服务文档明确允许的**官方**验证接口。把挑战外包给第三方打码服务不在此列——
那是由别人代替目标站点本要确认的那个人来回答，属于让校验不生效，不是把它编排清楚。
同目录下的 `tools/automation-modules/过验证码/2Captcha/captcha_solver.py` 是这条路线的
历史实现，已标注弃用，仅作留档。
