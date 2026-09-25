# 注册与凭证自动化模式

本 reference 只在任务涉及复杂注册、邮箱/代理适配、协议状态机、批次运行、凭证巡检或本地操作面时读取。简单签到和单接口脚本不要加载或照搬这些结构。

## 目录

- [共同架构](#共同架构)
- [P1.3 健康感知代理池与认证转发](#p13-健康感知代理池与认证转发)
- [P4.2 凭证生命周期与可逆导入导出](#p42-凭证生命周期与可逆导入导出)
- [P5.4 多邮箱适配、故障切换与验证码来源过滤](#p54-多邮箱适配故障切换与验证码来源过滤)
- [P6.4 多阶段协议工作流](#p64-多阶段协议工作流)
- [P8.7 可观测批次运行器](#p87-可观测批次运行器)
- [P10.1 本地操作面与 Windows 启动器](#p101-本地操作面与-windows-启动器)
- [交付验收](#交付验收)

## 共同架构

把浏览器流、纯 HTTP 流和本地操作面视为不同入口，共享基础设施和产物模型：

```text
Config
  -> MailboxAdapter / ProxyPool / ChallengeProvider
  -> RegistrationFlow (browser or protocol)
  -> SessionArtifact
  -> CredentialService (convert / refresh / probe)
  -> ArtifactStore
  -> BatchRunner / LocalOperatorUI
```

要求：

- 基础设施适配器不包含站点业务步骤。
- 流程阶段只通过类型化结果传递状态，不读取其他模块的全局变量。
- 敏感产物与公开配置分离；示例文件只使用占位符。
- 浏览器流与协议流输出同一 `RegistrationResult`，下游转换和汇总不关心入口。
- 每个失败记录 `stage`、`category`、脱敏消息和是否可重试。

## P1.3 健康感知代理池与认证转发

### 触发条件

- 代理来自多条文本、订阅或远端 API。
- 上游代理带用户名密码，而浏览器不支持直接注入认证。
- 需要区分代理故障、目标服务错误和本地网络错误。

### 数据模型

```python
@dataclass
class ProxyState:
    url: str
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_success_at: float = 0.0
    last_error_category: str = ""

    @property
    def available(self) -> bool:
        return time.time() >= self.cooldown_until
```

选择顺序为“未冷却、失败少、最近成功新”，而不是永久随机。预检只验证 TCP/TLS 或无副作用健康端点；业务请求结果由调用方通过 `report_outcome()` 回写。

### 失败归因

| 类别 | 示例信号 | 动作 |
| --- | --- | --- |
| `proxy_connect` | 连接拒绝、认证失败、CONNECT 超时 | 代理计失败并冷却 |
| `target_http` | 目标返回明确 4xx/5xx | 按业务策略处理，不立即污染代理 |
| `local_config` | 代理格式错误、父代理端口未监听 | 配置错误，停止当前批次 |
| `unknown_network` | TLS/读超时且证据不足 | 有限重试后轻度降权 |

日志只输出 `scheme://host:port` 或不可逆短指纹。异常清洗同时处理 URL userinfo 和结构化字段。

### 认证转发

本地转发器仅监听回环地址，使用系统分配端口或经过占用检测的固定端口。生命周期绑定到账号/worker，`finally` 中关闭；父代理认证头只在 CONNECT 上游时生成，不转发给目标站点。

验证：错误账密返回明确分类；停止后端口释放；日志和状态 JSON 不出现用户名、密码或完整 URL。

## P4.2 凭证生命周期与可逆导入导出

### 流程

```text
discover -> normalize -> validate -> dedupe -> refresh -> probe -> persist
                                      \-> export -> explicit delete
```

- `normalize`：把多种输入转换为内部 `CredentialDocument`，保留未知字段。
- `validate`：检查必需字段、时间格式和文档类型，不触网。
- `dedupe`：使用稳定身份字段或内容指纹，不用文件名作为唯一依据。
- `refresh`：只在存在刷新材料且接近过期时执行；成功后临时文件 + replace。
- `probe`：调用低成本、无副作用端点；限制并发并分类 `healthy/expired/unauthorized/network/unknown`。
- `export`：先生成 ZIP/JSON 预览；删除远端或本地原件必须由独立显式动作触发。

```python
@dataclass
class CredentialDocument:
    subject: str
    access_token: str = ""
    refresh_token: str = ""
    expires_at: datetime | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)
```

列表接口只返回 `subject_masked`、过期状态、健康状态和短指纹。完整内容仅用于用户明确请求的下载或导出响应。

验证：刷新失败不覆盖旧凭证；并行巡检保持输入顺序或返回稳定索引；重复导入有 `skip/rename/replace` 明确策略。

## P5.4 多邮箱适配、故障切换与验证码来源过滤

### 适配器协议

```python
class MailboxAdapter(Protocol):
    def create_address(self) -> "MailboxSession": ...
    def list_messages(self, box: "MailboxSession") -> list["MailSummary"]: ...
    def get_message(self, box: "MailboxSession", message_id: str) -> "MailMessage": ...

@dataclass
class MailboxSession:
    address: str
    credential: str
    created_at: datetime
    provider: str
```

`credential` 只保存在运行内存或被忽略的本地池文件中，日志使用脱敏邮箱。

### 验证码选择

候选邮件必须满足：

1. 收件时间不早于本次请求验证码前的允许偏差。
2. 收件人匹配当前邮箱。
3. 发件人、主题或正文具有当前业务特征。
4. 验证码格式符合该业务规则。
5. 同一消息和验证码未被当前运行消费。

先对 HTML 转文本，再从主题与正文提取；不要把“出现任意 4-8 位数字”作为唯一判断。

### 故障切换

只对 `provider_unavailable`、`domain_rejected`、`mailbox_create_failed` 和轮询超时切换邮箱提供方。验证码错误、注册请求被拒和代理失败属于其他阶段，不触发盲目换邮箱。

验证：准备两封不同业务邮件，必须选择当前任务的新邮件；提供方 A 创建失败时切换 B；业务提交失败时保留同一邮箱用于诊断。

## P6.4 多阶段协议工作流

### 阶段合同

```python
class Stage(str, Enum):
    SESSION = "session"
    REQUEST_CODE = "request_code"
    VERIFY_CODE = "verify_code"
    CHALLENGE = "challenge"
    CREATE_ACCOUNT = "create_account"
    ESTABLISH_SESSION = "establish_session"
    EXCHANGE_CREDENTIAL = "exchange_credential"
    PERSIST = "persist"

@dataclass
class StageResult:
    stage: Stage
    ok: bool
    retryable: bool
    data: dict = field(default_factory=dict)
    error_category: str = ""
```

每阶段定义：前置状态、请求副作用、成功证据、允许重试次数、输出字段。非幂等提交前检查上一阶段是否已有成功证据，避免网络超时后重复创建。

### 协议注意事项

- 同一 `Session` 维护 Cookie、重定向和必要请求头；切换域名时显式验证允许列表。
- gRPC-Web、multipart 或流式响应使用对应解析器，状态可能在响应头、trailer 或 body。
- 重定向逐跳验证目标 host 和最大次数，不把任意返回 URL 当作可信跳转。
- 浏览器与 HTTP 流共享阶段名和产物模型，但不共享内部页面对象或网络会话。
- 访问控制或挑战验证只使用目标服务允许的官方流程、用户手动完成或明确授权的提供方；不伪造证明，不复用过期/跨会话结果。

验证：为每阶段提供成功、可重试失败和不可重试失败用例；断点恢复从最近已确认阶段继续；最终产物字段通过 schema 校验。

## P8.7 可观测批次运行器

### 运行目录

```text
runs/<run_id>/
  plan.json
  events.jsonl
  workers/<worker_id>.json
  artifacts.json
  summary.json
```

状态写入使用临时文件 + replace；事件流追加写。`plan.json` 保存脱敏配置快照、目标数量和并发上限，不保存秘密。

### 运行规则

- 同一工作目录默认只允许一个活动批次。
- worker 状态至少包含 `pending/running/succeeded/failed/cancelled` 和当前阶段。
- 取消使用 `Event`/取消令牌协作传播；外层仍设置总超时并回收无响应子进程。
- 每个 worker 独立产物，批次结束再按原始索引汇总，避免并发写同一敏感文件。
- 浏览器任务设置按账号重启或按次数/内存阈值回收；退出时清理孤儿子进程和本地代理端口。
- 失败汇总按阶段和类别聚合，保留代表错误，不重复打印完整堆栈。

验证：并发上限可观测；取消后无活动 worker/浏览器/监听端口；历史运行可读取；成功计数能与产物索引对账。

## P10.1 本地操作面与 Windows 启动器

### 操作面

- Web 服务默认 `127.0.0.1`，不使用 `0.0.0.0` 作为默认值。
- 远程绑定时要求强认证、CSRF/Origin 检查和反向代理 TLS；未配置则拒绝启动。
- 提供 `/health`、配置读取/校验、开始/停止、当前状态、历史运行和脱敏产物列表。
- 开始接口执行单任务互斥；停止接口幂等。
- 下载/预览/删除通过 `Path.resolve()` 验证仍位于产物根目录，并使用文件名允许列表。
- 默认不开启自动删除；批量删除前返回将删除的脱敏清单。

### Windows 启动器

```text
定位项目根目录
-> 检查项目 Python / 创建 .venv
-> 在 .venv 安装锁定的必要依赖
-> 从 example 生成缺失配置（不覆盖现有配置）
-> 创建 logs/data/output
-> 探测配置端口与常见本地依赖端口
-> 启动服务并轮询 /health
-> 成功后打开浏览器；失败时保留窗口并指向日志
```

PowerShell 和批处理只负责启动，不包含业务逻辑。所有路径使用脚本所在目录解析；包含空格和中文路径时仍可运行。环境变量覆盖配置文件，但秘密只从 `.env` 或进程环境读取。

验证：全新目录首次启动；二次启动不重建配置；端口占用有可执行错误；服务未健康时不打开页面；关闭后子进程退出。

## 交付验收

| 维度 | 必须证据 |
| --- | --- |
| 配置 | example 无秘密，环境变量覆盖，未知字段有错误提示 |
| 邮箱 | 适配器契约测试、旧信/错信过滤、故障切换测试 |
| 代理 | 格式校验、失败归因、冷却恢复、日志脱敏 |
| 协议 | 阶段合同、幂等边界、允许的重定向、失败分类 |
| 凭证 | schema 校验、原子刷新、巡检并发上限、导出/删除分离 |
| 批次 | run_id、worker 状态、取消清理、计数与产物对账 |
| 操作面 | 回环监听、单任务互斥、路径限制、健康检查 |
| 安全 | `.gitignore` 覆盖秘密与产物，日志/异常/报告均脱敏 |
