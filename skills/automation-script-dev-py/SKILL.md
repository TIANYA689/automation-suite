---
name: automation-script-dev-py
description: "创建、分析、调试和适配 Python 自动化脚本，支持青龙面板、本地 CLI、Windows 启动器与本地运维面板。用于多账号、登录授权、注册验证、邮箱/代理适配、多阶段协议工作流、并发批次、凭证生命周期、状态缓存和可观测交付。"
---


# Automation Script Developer (Python)

你是 Python 自动化脚本开发专家，擅长创建、分析和调试自动化脚本，支持青龙面板和本地运行。

## 📐 三大编程范式

| 范式 | 适用场景 | 核心特征 |
|:---|:---|:---|
| **函数式** | 简单签到、单功能脚本 | 无类，全局函数 + `main()` |
| **OOP（推荐）** | 复杂多任务、状态管理 | `Config` + `Client` + `main()` |
| **异步 OOP** | HTTP/2、高并发性能 | `httpx` + `asyncio` |

### 范式 1: 函数式骨架
```python
#!/usr/bin/env python3
ENV_NAME = "APP_TOKEN"
BASE_URL = "https://example.com/api"

def get_tokens(): return [t.strip() for t in os.environ.get(ENV_NAME,"").split('\n') if t.strip()]
def sign_in(token): ...  # 业务逻辑

def main():
    for i, token in enumerate(get_tokens(), 1):
        print(f"\n{'='*20} 账号{i} {'='*20}")
        sign_in(token)
        time.sleep(2)
if __name__ == '__main__': main()
```

### 范式 2: OOP 骨架（推荐）
```python
class Config:
    ENV_NAME = "APP_TOKEN"; BASE_URL = "..."; REQUEST_TIMEOUT = 15; MAX_RETRIES = 3; ACCOUNT_DELAY = 3

class AppClient:
    def __init__(self, token, index):
        self.session = requests.Session(); self.session.headers['Authorization'] = f'Bearer {token}'
    def request_with_retry(self, method, url, **kwargs): ...
    def sign_in(self): ...
    def run(self): ...   # 主执行流程

def main():
    tokens = [t.strip() for t in os.getenv(Config.ENV_NAME,"").replace('&','\n').split('\n') if t.strip()]
    for i, token in enumerate(tokens, 1):
        AppClient(token, i).run()
        if i < len(tokens): time.sleep(Config.ACCOUNT_DELAY)
```

### 范式 3: 异步 OOP 骨架
```python
class AsyncAppClient:
    def __init__(self, token): self.token = token
    async def _request(self, method, endpoint, payload=None):
        async with httpx.AsyncClient(http2=True) as client: ...
    async def run_all_tasks(self): ...

async def main():
    for token in os.getenv("APP_TOKEN","").split("#"):
        await AsyncAppClient(token.strip()).run_all_tasks()
asyncio.run(main())
```

---

## 🔑 核心模式索引 (Pattern Index)

> 相似模式已融合到编号更靠前的主模式中。保留编号用于稳定引用，子场景使用 `P主编号.序号`。
> 历史编号兼容映射：`旧 P12 → P1`，`旧 P13 → P2`，`旧 P33 → P2.3`，`旧 P3 → P3`，`旧 P14 → P4`，`旧 P15 → P5`，`旧 P1 → P6`，`旧 P6 → P7`，`旧 P4 → P8`，`旧 P2 → P9`，`旧 P32 → P10`，`旧 P7 → P11`，`旧 P5 → P12`。原先被融合的模式继续归入对应主模式子场景。

#### A. 代理、防封与客户端伪装

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P1 | 代理集成与代理兼容 | 代理池、健康评分、认证转发、系统代理旁路、httpx `proxy` | ✅ JS-P1.1 |
| P2 | 高级防封与客户端伪装 | `AntiDetection`、UA 设备池、账号级设备档案、高斯延迟、拟真轨迹 | ✅ JS-P2 |

#### B. 账号、登录与授权

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P3 | 多源账号配置与加载 | 环境变量、文件、来源切换、去重 | — |
| P4 | 智能登录与授权策略 | Token 优先、状态缓存、凭证转换/刷新/巡检 | ✅ JS-P3.1 |

#### C. 注册与验证

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P5 | 注册与验证码接入 | 注册阶段、邮箱/短信适配、验证码来源过滤、合规挑战处理 | ✅ JS-P4.1 |

#### D. 网络请求、协议与安全

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P6 | 网络请求、重试与协议构造 | 自动重试、快速熔断、Multipart、多阶段协议状态机 | — |
| P7 | 安全工具与签名 | RSA、UUID、设备指纹、哈希索引签名 | ✅ JS-P5.1 |

#### E. 任务编排、并发与循环

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P8 | 任务编排、并发与循环 | 条件分支、线程池、进度等待、批次运行记录、取消清理 | ✅ JS-P6 |

#### F. 配置、兼容与项目组织

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P9 | 集中配置与运行兼容 | `Config`、双源覆盖、Windows UTF-8 | — |
| P10 | 项目归集与本地操作面 | 同名文件夹、README、配置示例、本地面板、Windows 启动器 | ✅ JS-P7 |

#### G. 日志、隐私与通知

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P11 | 日志输出与敏感信息保护 | 状态卡片、汇总表、手机号/Token 脱敏 | — |
| P12 | 公告与多通知渠道 | 公告主备 URL、notify.py、PushPlus、WxPusher | — |

#### H. 既有脚本阅读、状态与经验融合

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P13 | 既有脚本 Pattern Mining、状态缓存与历史记录 | 只读扫描、CacheManager、atomic_save、脚本成熟度 | ✅ JS-P8 |

---

## 🔑 核心模式详情

**A. 代理、防封与客户端伪装**

### P1: 代理集成与代理兼容

🔗 **跨语言通用** — JS 版见 `automation-script-dev-js` P1.1

**配置区（P9.1 双源配置）**:
```python
# [选填] 代理开关 (1=开启, 0=关闭)
USER_PROXY_ENABLE = "0"
# [选填] 代理API地址 (默认品赞，返回格式: ip:port纯文本)
USER_PROXY_API = "https://proxy.example.com/extract?num=1&format=txt&secret=YOUR_PROXY_SECRET"

TASK_CONFIG = {
    "PROXY_ENABLE": os.getenv("APP_PROXY_ENABLE", USER_PROXY_ENABLE) == "1",
    "PROXY_API":    os.getenv("APP_PROXY_API",    USER_PROXY_API),
}
```

**ProxyManager（嵌入 Client 类的方法）**:
```python
def get_proxy(self) -> bool:
    """获取并设置代理IP，支持 JSON / HTML / 纯文本三种响应格式"""
    if not TASK_CONFIG["PROXY_ENABLE"] or not TASK_CONFIG["PROXY_API"]:
        return True  # 未启用，直接放行
    # ★ 每次调用前清空旧代理，防止失败后复用同一失效 IP
    self.session.proxies = {}
    try:
        logger.info("    🌐 正在获取代理IP...")
        # ★ 必须加 proxies={} 旁路系统代理；品赞等严格 API 不允许附加额外参数（会返回 422）
        resp = requests.get(TASK_CONFIG["PROXY_API"], timeout=8, verify=False, proxies={})
        if resp.status_code == 200:
            # 1. 尝试 JSON 格式 (部分平台 format=json 模式: {"code":200,"data":{"proxies":["ip:port"]}})
            try:
                res_json = resp.json()
                if res_json.get("code") == 200:
                    proxies = res_json.get("data", {}).get("proxies", [])
                    if proxies and ":" in proxies[0]:
                        proxy_url = f"http://{proxies[0]}"
                        self.session.proxies = {"http": proxy_url, "https": proxy_url}
                        self.proxy_ip = proxies[0]
                        logger.info(f"    ✅ 获取代理成功: {proxies[0]}")
                        return True
                logger.error(f"    ❌ 代理API返回错误: {res_json.get('message')}")
            except ValueError:
                pass  # JSON解析失败 → 降级纯文本

            # 2. HTML/纯文本格式 (品赞/89ip: 直接返回 ip:port 文本)
            content = resp.text.strip()
            match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)", content)
            if match:
                proxy_ip = match.group(1)
                proxy_url = f"http://{proxy_ip}"
                self.session.proxies = {"http": proxy_url, "https": proxy_url}
                self.proxy_ip = proxy_ip
                logger.info(f"    ✅ 获取代理成功: {proxy_ip}")
                return True
            logger.error(f"    ❌ 代理API返回未知格式: {content}")
        else:
            logger.error(f"    ❌ 获取代理失败: HTTP {resp.status_code} {resp.text[:60]}")
    except Exception as e:
        logger.error(f"    ❌ 获取代理异常: {e}")
    return False
```

**请求失败时自动换代理（嵌入 `_request` 方法）**:
```python
def _request(self, method, endpoint, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            resp = self.session.request(method, url, headers=self.headers,
                                        timeout=REQUEST_TIMEOUT, **kwargs)
            return resp
        except requests.RequestException as e:
            logger.warning(f"    请求失败 (尝试 {attempt+1}/{MAX_RETRIES}): {e}")
            if TASK_CONFIG["PROXY_ENABLE"]:
                logger.info("    🔄 尝试更换代理...")
                self.get_proxy()
            AntiDetection.human_delay(*DELAY_SETTINGS["ERROR_RETRY"])
    return None
```
**要点**:
- **品赞**（`format=txt`，推荐）返回纯文本 `ip:port`，正则一次提取
- JSON分支兼容 `format=json` 模式（解析 `data.proxies[0]`），代码自动降级，无需手动切换
- 代理未启用时 `get_proxy()` 直接返回 `True`，对业务逻辑无感
- 配合 P9.1 双源配置：`USER_PROXY_ENABLE/USER_PROXY_API` 本地覆盖，`APP_PROXY_ENABLE/APP_PROXY_API` 青龙环境变量
- ⚠️ **陷阱①** 拉取代理 API 时必须传 `proxies={}`，否则若本机开了系统代理，请求会走代理导致失败或拿到错误结果
- ⚠️ **陷阱②** 品赞/部分严格 API 不允许在 URL 后附加自定义参数（如 `_ts`），会返回 `422 ValidationError`；统一不附加额外参数
- ⚠️ **陷阱③** 重试前必须先 `self.session.proxies = {}` 清空旧代理，否则新 IP 拉到了但旧失效代理仍残留在 session 中

#### P1.1 系统代理旁路

```python
import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session.verify = False
session.trust_env = False  # ★ 忽略 HTTP_PROXY/HTTPS_PROXY 环境变量
# 仍可手动: session.proxies = {"http": "...", "https": "..."}
```
**症状**: `ProxyError('Unable to connect to proxy')` 或 `400 Bad Request`

#### P1.2 httpx 代理参数兼容

**症状**: `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`  
**原因**: `httpx >= 0.23.0` 将 `proxies={}` 字典形式移除，改用单字符串参数

```python
# ❌ 旧写法 (httpx < 0.23，已废弃)
client = httpx.Client(proxies={"http://": proxy, "https://": proxy})

# ✅ 新写法 (httpx >= 0.23，统一使用 proxy= 单字符串)
client = httpx.Client(proxy="http://127.0.0.1:7890")  # 同时代理 http 和 https
client = httpx.Client(proxy=None)  # 不使用代理时传 None
```
**异步版本**:
```python
async with httpx.AsyncClient(proxy="http://127.0.0.1:7890", verify=False) as client: ...
```

#### P1.3 健康感知代理池与认证转发

当代理来自文件、订阅或带认证上游时，不要把“随机选一条”当成可用性策略。维护标准化代理记录、预检结果、连续失败数、冷却时间和最近成功时间；浏览器不支持认证代理时，通过仅监听回环地址的本地转发器桥接。

读取 `references/registration-automation-patterns.md` 的“P1.3 健康感知代理池与认证转发”，按其中的失败归因和验收表实现。不得在日志、状态文件或异常文本中输出代理用户名和密码。

### P2: 高级防封与客户端伪装

🔗 **跨语言通用** — JS 版见 `automation-script-dev-js` P2

```python
class AntiDetection:
    @staticmethod
    def generate_device_id(): return hashlib.sha1(str(random.getrandbits(256)).encode()).hexdigest().upper()
    @staticmethod
    def human_delay(min_s, max_s): delay=max(random.uniform(min_s,max_s)+random.gauss(0,0.5),0.5); time.sleep(round(delay,2))
    @staticmethod
    def get_dynamic_headers(): return {"Accept-Encoding": random.choice(["gzip","gzip, deflate"])}
    @staticmethod
    def generate_random_ua():  # 详见 P2.1 独立 UA 生成器
```

**P2-Playwright 拟真鼠标轨迹（缓动曲线拖拽）**
适用于：滑块验证码、需要拖拽的 UI 操作，防止轨迹被行为检测识别为机器人。

```python
# 缓动函数（先加速后减速，值域 [0,1]）
def ease_in_out_quad(n):
    return 2*n*n if n < 0.5 else -0.5*((n*2-1)*(n*2-3)-1)
def ease_out_quad(n): return -n*(n-2)
def ease_in_out_cubic(n):
    return 4*n*n*n if n < 0.5 else 0.5*(n*2-2)**3+1

def playwright_human_drag(page, from_x, from_y, distance, easing=None):
    """Playwright 仿人鼠标拖拽（随机步数 + 缓动曲线 + XY 抖动 + 超频补偿）"""
    easing = easing or random.choice([ease_in_out_quad, ease_out_quad, ease_in_out_cubic])
    target_x = from_x + distance
    page.mouse.move(from_x, from_y)
    time.sleep(random.uniform(0.08, 0.15))
    page.mouse.down()
    steps = random.randint(22, 32)
    for i in range(steps):
        p = easing(i / steps)
        page.mouse.move(from_x + distance*p + random.uniform(-1.5,1.5), from_y + random.uniform(-2,2))
        time.sleep(random.uniform(0.004, 0.035))
    if random.random() > 0.5:  # 超频补偿（模拟人手惯性）
        page.mouse.move(target_x + random.uniform(2,5), from_y); time.sleep(random.uniform(0.04,0.09))
    page.mouse.move(target_x, from_y)
    time.sleep(random.uniform(0.12, 0.22))
    page.mouse.up()
```
> **要点**: 步数随机 22-32 | 三选一缓动函数 | Y 轴 ±2px 抖动 | 50% 概率超频补偿回退

#### P2.1 自动化注册专用 UA 生成器

**适用场景**: 仅限自动化注册流程；在每个注册流程开始时生成一次，并在该流程内固定复用。普通签到、领取、养号、已有账号登录和会话刷新不得使用本模式，必须按 P2.3 加载账号绑定的真实设备档案。
**HAR 来源**: 真实抓包特征 —  `Mozilla/5.0 (Linux; Android 15; V1936A Build/JXI6.35992; wv) AppleWebKit/537.36 ... Chrome/144.0.4911.115 Mobile Safari/537.36`

```python
# ua_generator.py
import random

# 各品牌型号池 {品牌: [(model, build_id), ...]}
_DEVICE_POOL = {
    "vivo":   [("V1936A","JXI6.35992"),("V2049A","RP1A.200720.012"),("V2118A","SP1A.210812.003")],
    "OPPO":   [("PCRT00","QKQ1.190918.001"),("PCLM10","QKQ1.191222.002"),("PBEM00","PKQ1.190519.001")],
    "Xiaomi": [("M2007J3SC","QKQ1.200830.002"),("M2102K1C","SKQ1.211006.001"),("2201123C","SKQ1.211006.001")],
    "Huawei": [("TAS-AN00","HUAWEITAS-AN00"),("ANA-AN00","HUAWEIANA-AN00"),("NOH-AN00","HUAWEINOH-AN00")],
}
_CHROME_VERSIONS = ["144.0.4911.115","116.0.5845.163","120.0.6099.144","114.0.5735.196","118.0.5993.80","122.0.6261.105"]

def generate_android_ua() -> str:
    """为一次自动化注册流程生成 Android WebView UA。"""
    android_ver = random.randint(10, 15)
    model, build = random.choice(random.choice(list(_DEVICE_POOL.values())))
    chrome = random.choice(_CHROME_VERSIONS)
    return (f"Mozilla/5.0 (Linux; Android {android_ver}; {model} Build/{build}; wv) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome} Mobile Safari/537.36")
```

**结合 httpx 的 APIClient 使用**:
```python
# core_network.py
import httpx
from ua_generator import generate_android_ua

class APIClient:
    def __init__(self, base_url="", proxy=None, user_agent=None):
        self._client = httpx.Client(proxy=proxy, verify=False)  # ⚠️ 见 P1.2
        self._user_agent = user_agent or generate_android_ua()
    def _build_headers(self, extra=None):
        h = {"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate, br"}
        if extra: h.update(extra)
        return h
    def get(self, ep, **kw): return self._client.get(f"{self.base_url}{ep}", headers=self._build_headers(), **kw)
    def post(self, ep, **kw): return self._client.post(f"{self.base_url}{ep}", headers=self._build_headers(), **kw)
```
**要点**:
- 每个自动化注册流程只调用一次 `generate_android_ua()`；同一流程的请求、重试和重定向复用该 UA
- 本模式不得用于普通签到、领取、养号、已有账号登录或会话刷新；这些长期账号场景统一使用 P2.3
- `ua_generator.py` 作为纯工具模块可直接被 `requests` / `httpx` / `aiohttp` 任意框架引入
- 设备池可按业务需求扩充：只需在 `_DEVICE_POOL` 中添加 `(model, build_id)` 元组

#### P2.2 场景化延迟配置

```python
DELAY_SETTINGS = {
    "ACTION": (3,6), "REG_LOOP": (25,36), "CHECKIN_OK": (2,4),
    "ERROR_RETRY": (3,6), "BETWEEN_ACCOUNTS": (5,10), "BETWEEN_TASKS": (2,4),
}
AntiDetection.human_delay(*DELAY_SETTINGS["ACTION"])  # 解包调用
def random_sleep(self, key="ACTION"): AntiDetection.human_delay(*DELAY_SETTINGS.get(key,(1,2)))
```

#### P2.3 账号级设备指纹持久化（旧 P33）

普通签到、领取、养号、已有账号登录和会话刷新默认都是长期账号养护，必须为每个账号使用固定的真实设备档案，不得每次运行或每次请求随机 UA。档案优先从该账号实际使用的真机抓包或受信配置中导入并原子写入 `data/device_profiles/`，后续运行持续复用。优先使用稳定、非敏感的账号 ID 作为索引；只有无法取得稳定 ID 时才使用 Token 的 SHA-256 摘要，且不得保存或记录原 Token。

读取 `references/device-profile-persistence.md`，按其中的档案 schema、导入/加载流程、UA 与 Client Hints 一致性规则、并发写入和轮换边界实现。只有自动化注册流程可以使用 P2.1 随机 UA；档案缺失、损坏、schema 不兼容或认证失败时也不得静默生成新指纹。

---

**B. 账号、登录与授权**

### P3: 多源账号配置与加载

**三种模式**:
- **统一变量**: `APP_AUTH` 格式 `token#secret#备注`，`&`或`\n`分隔多账号
- **分离变量**: `APP_TOKEN` + `APP_SECRET` 各独立，作为回退
- **编号变量**: `HKYP1`, `HKYP2`... 用 `re.compile(f"^{PREFIX}\d+$")` 扫描 `os.environ`

```python
def get_accounts(env_key="APP_AUTH"):
    raw = os.getenv(env_key, "")
    if not raw: return []
    accounts = []
    # 支持 & 或 换行 分隔多账号
    for line in re.split(r"[&\n]", raw.strip()):
        line = line.strip()
        if not line: continue
        # 支持 ---- 或 # 作为账号和密码的分割符
        parts = line.split("----") if "----" in line else line.split("#")
        if len(parts) >= 2:
            accounts.append({
                "account": parts[0].strip(),
                "password": parts[1].strip(),
                "remark": parts[2].strip() if len(parts) > 2 else f"账号{len(accounts)+1}"
            })
    return accounts
```

#### P3.1 文件与环境变量混合加载

```python
def get_accounts() -> List[Dict]:
    accounts = []
    # 1. 本地文件 (Producer输出)
    if os.path.exists(Config.ACCOUNT_FILE):
        for line in open(Config.ACCOUNT_FILE,'r',encoding='utf-8'):
            if p:=line.strip().split('#'): len(p)>=2 and accounts.append({'user':p[0],'pwd':p[1]})
    # 2. 环境变量 (青龙)
    for item in re.split(r'[&\n]', os.environ.get(Config.ENV_NAME,"")):
        if (p:=item.strip().split('#')) and len(p)>=2: accounts.append({'user':p[0],'pwd':p[1]})
    # 3. 去重
    seen=set(); return [a for a in accounts if (k:=(a['user'],a['pwd'])) not in seen and not seen.add(k)]
```
**生命周期分离**: 注册机 `append → accounts.txt`; 养号脚本 `overwrite → farm_results.txt`

#### P3.2 账号读取源切换

在账号配置基础上增加开关，决定账号信息是来源于静态文本/环境变量，还是自动扫描目录下外部工具（如注册机）导出的文本。

```python
USER_ACCOUNT_SOURCE = "file"  # file=本地文件扫描, config=配置文本解析

def parse_accounts() -> list:
    if Config.ACCOUNT_SOURCE == "config":
        # 仅从环境变量或自定义配置区提取账号
        ...
    elif Config.ACCOUNT_SOURCE == "file":
        # 扫描同路径下的特定格式 txt 文件（如包含“注册机数据”字眼）读取并合并去重
        ...
```

#### P3.3 多格式账号解析标准

适用于：接手已有青龙脚本时账号格式不统一，或需要同时兼容本地运行与青龙环境变量。

```python
def split_accounts(raw: str) -> list[str]:
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = []
    for line in raw.split("\n"):
        parts.extend([p.strip() for p in line.split("&") if p.strip()])
    return parts

def parse_account(item: str) -> dict:
    # 字段分隔优先级：---- > # > | > ,
    for sep in ("----", "#", "|", ","):
        if sep in item:
            fields = [x.strip() for x in item.split(sep)]
            break
    else:
        fields = [item.strip()]
    return {"token": fields[0], "secret": fields[1] if len(fields) > 1 else "", "remark": fields[2] if len(fields) > 2 else ""}
```

**要求**:
- 统一变量优先（如 `APP_AUTH=token#secret#remark`），分离变量作为兜底。
- 解析失败时输出格式示例，不直接抛出裸异常。
- 去重键应使用真正的身份字段，避免 remark 不同导致重复执行。

### P4: 智能登录与授权策略

🔗 **跨语言通用** — JS 版见 `automation-script-dev-js` P3.1

```python
def login(self):
    if self.token and self._validate_token(): return True   # Token 优先
    return self._password_login()                           # 账密兜底

# 变体: JSON文件缓存 (函数式)
TOKEN_CACHE_FILE = "app_tokens.json"
cache = json.load(open(TOKEN_CACHE_FILE)) if os.path.exists(TOKEN_CACHE_FILE) else {}
# 使用: cache.get(phone) → 有效则用 → 否则登录 → 写cache
```

**P4-Playwright 登录状态持久化（storage_state）**
适用于：需要反复登录的 Playwright 脚本，通过持久化浏览器 Cookie/LocalStorage 避免频繁触发登录风控。

```python
from pathlib import Path
STATE_FILE = Path(os.getenv("QL_DATA_DIR", "/ql/data")) / "scripts" / "app_state.json"

# 启动时：有缓存则复用 session，否则全新 context
storage_state = str(STATE_FILE) if STATE_FILE.exists() else None
context = browser.new_context(storage_state=storage_state)
page = context.new_page()

# 判断是否需要登录（检测 URL 或登录表单是否可见）
def is_login_required(page, login_url_keyword="login", login_selector="#username") -> bool:
    if login_url_keyword in page.url: return True
    try: return page.locator(login_selector).is_visible(timeout=3000)
    except: return False

# 登录后保存 storage_state，下次直接复用
def save_session(context, state_file: Path):
    try: context.storage_state(path=str(state_file))
    except Exception as e: print(f"⚠️ 保存登录状态失败: {e}")
```
> **要点**: `storage_state` 包含 Cookie + LocalStorage | 青龙路径统一用 `QL_DATA_DIR` | 缓存失效时自动降级重新登录

#### P4.1 两阶段授权

适用于：中转服务器获取 Code → AES 加密兑换业务 Token
```
1. auth_client.get_code() → code
2. aes_encrypt(json.dumps({"code":code,"device":"..."})) → 发送 /auth/exchange
3. aes_decrypt(response['res']) → 提取 token
```
> AES跨语言对齐: Python 使用 `Crypto.Util.Padding.pad(style='pkcs7')` + `MODE_ECB/CBC`

#### P4.2 凭证生命周期与可逆导入导出

当产物不止一个 Token，而是包含会话、访问令牌、刷新令牌和过期时间的凭证文档时，拆分 `normalize → validate → refresh → probe → export/delete`。导入前预览并判重，刷新使用原子写，健康探测限制并发，导出后删除必须是显式独立动作。

读取 `references/registration-automation-patterns.md` 的“P4.2 凭证生命周期与可逆导入导出”。所有凭证文件默认加入 `.gitignore`，列表和日志只显示脱敏标识。

---

**C. 注册与验证**

### P5: 注册与验证码接入

🔗 **跨语言通用** — JS 版见 `automation-script-dev-js` P4.1

```python
prefixes = ['138','139','150','151','152','157','188','187']
phone = random.choice(prefixes) + "".join(random.choices("0123456789",k=8))
password = "".join(random.choices("abcdef0123456789",k=10))
# 注册 → save_account() → AntiDetection.human_delay()
```

#### P5.1 邮箱接码客户端

```python
class MailboxAdapter:
    def create_address(self): ...
    def list_messages(self, mailbox): ...
    def get_message(self, mailbox, message_id): ...

def wait_for_code(adapter, mailbox, requested_at, timeout=180, interval=5):
    # 按时间、收件人、发件人/主题特征和业务格式过滤，见 P5.4。
    ...
```
**要点**: 提供方实现隔离 | 凭证不写日志 | 轮询有超时与抖动 | 验证码选择遵循 P5.4

#### P5.2 手机号接码客户端

**豪猪平台** (`SMSClient`) / **他信平台** (`TaxinClient` - api.my531.com)

```python
class SMSClient:  # / TaxinClient
    def login(self): ...      # 登录→Token→show_balance()
    def get_phone(self, project_id): ...
    def wait_code(self, sid, phone, timeout=120, interval=15): ...  # 轮询
    def cancel(self, project_id, phone): ...   # 释放号码
```

#### P5.3 合规挑战处理

```python
class ChallengeProvider:
    def acquire(self, context, timeout=120) -> Optional[str]:
        # 仅接入目标服务允许的官方验证、用户手动完成或经明确授权的提供方。
        # 返回值与当前会话、页面、出口绑定；不得伪造或跨会话复用。
        ...
```
**要点**: 记录等待/成功/过期状态 | 设置超时和并发上限 | token 单次消费 | 不实现绕过、伪造或隐藏验证行为

#### P5.4 多邮箱适配、故障切换与验证码来源过滤

统一邮箱接口为 `create_address()`、`list_messages()`、`get_message()`、`wait_code()`；只有邮箱提供方故障或域名拒绝才切换提供方，业务注册失败不得误归因到邮箱。验证码按任务开始时间、收件人、发件人/主题特征和格式共同过滤，避免取到旧信或同邮箱的其他验证码。

读取 `references/registration-automation-patterns.md` 的“P5.4 多邮箱适配、故障切换与验证码来源过滤”。

---

**D. 网络请求、协议与安全**

### P6: 网络请求、重试与协议构造

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
```

#### P6.1 重试失败后快速熔断

若 `request_with_retry` 网络请求达到最大重试次数仍然彻底失败（如代理失效断连），直接抛出异常，让外层 `run()` 方法接管阻断，直接跳过当前账号后续操作，避免产生无意义的并发和空轮询。

```python
def request_with_retry(self, method, url, **kwargs) -> dict:
    for attempt in range(Config.MAX_RETRIES):
        try:
            resp = self.session.request(method, url, **kwargs)
            return resp.json()
        except Exception as e:
            logger.error(f"❌ 请求发生异常: {e}，等待重试...")
            time.sleep(Config.RETRY_DELAY)
    # 重试全部失败后，抛出异常熔断当前账号任务流
    raise Exception("网络请求多次异常失败，跳过该账号后续任务")
```

#### P6.2 手动 Multipart 构造

```python
def build_multipart(fields: dict) -> tuple:
    boundary = '----WebKitFormBoundary'+''.join(random.choices(string.ascii_letters+string.digits, k=16))
    body = ''.join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n" for k,v in fields.items())
    return body + f"--{boundary}--\r\n", f"multipart/form-data; boundary={boundary}"

body, ct = build_multipart({"loginName":"user","password":"pwd"})
session.post(url, headers={"Content-Type": ct}, data=body.encode('utf-8'))
```

#### P6.3 双层重试：请求重试 + 代理切换

适用于代理池、接口不稳定、青龙定时任务。普通失败先本地重试，连续网络失败达到阈值后刷新代理；网络异常、HTTP 状态异常、业务失败分开处理。

```python
def request_with_proxy_retry(self, method, url, **kwargs):
    proxy_failures = 0
    while proxy_failures <= Config.MAX_PROXY_RETRIES:
        for attempt in range(1, Config.REQUEST_RETRIES + 1):
            try:
                resp = self.session.request(method, url, timeout=Config.REQUEST_TIMEOUT, **kwargs)
                if resp.status_code >= 500:
                    raise requests.RequestException(f"HTTP {resp.status_code}")
                return resp
            except requests.RequestException as e:
                logger.warning(f"⚠️ 请求失败 {attempt}/{Config.REQUEST_RETRIES}: {e}")
                time.sleep(Config.RETRY_DELAY * attempt)
        proxy_failures += 1
        if Config.PROXY_ENABLE:
            logger.info("🔄 请求连续失败，刷新代理后重试")
            self.refresh_proxy()
        else:
            break
    raise RuntimeError("网络请求多次失败，熔断当前账号")
```

**要点**:
- 代理中包含认证信息时必须脱敏。
- 刷新代理后重置请求重试计数。
- 最终失败抛给账号级 `run()`，直接跳过当前账号后续任务，避免空轮询。

#### P6.4 多阶段协议工作流

当流程跨多个域、Cookie、重定向或协议编码时，把实现拆成显式阶段，不在一个 `register()` 中混合全部请求。每阶段声明输入、输出、可重试性和失败类型；同一业务会话复用 Cookie 容器，重试不得重复提交非幂等阶段。

读取 `references/registration-automation-patterns.md` 的“P6.4 多阶段协议工作流”。仅在用户对目标系统有授权时分析或实现协议自动化；验证码和访问控制遵循 P5.3。

### P7: 安全工具与签名

```python
class SecurityProvider:
    @staticmethod
    def rsa_encrypt(content): ...  # Crypto.Cipher.PKCS1_v1_5
    @staticmethod
    def generate_signature(path, session_id, req_id, ts): return hashlib.md5(f"{path}{session_id}{req_id}{ts}".encode()).hexdigest()
    @staticmethod
    def deterministic_uuid(seed): return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))

class DeviceManager:
    POOLS = {0:("xiaomi",["23116PN5BC"]), 1:("samsung",["SM-S9280"])}
    @classmethod
    def get_ua(cls, profile): return headers_from_profile(profile)["User-Agent"]  # 已有账号使用 P2.3
```

自动化注册可以在流程开始时注入一次 P2.1 生成的 UA；已有账号不得在签名或请求阶段重新生成设备身份。

#### P7.1 哈希索引签名

🔗 **跨语言通用** — JS 版见 `automation-script-dev-js` P5.1

```python
def generate_index_sign(params: list, secret: str, keys: list) -> str:
    raw = "".join(str(p) for p in params) + secret
    h = hashlib.md5(raw.encode()).hexdigest()
    return "".join(h[i] for i in keys if i < len(h)).upper()
```

---

**E. 任务编排、并发与循环**

### P8: 任务编排、并发与循环

```python
tasks = [("📅 签到", lambda: check_in(token)), ("🎮 游戏", lambda: login_game(token))]
for name, task in tasks:
    print(f"\n📋 {name}"); task(); time.sleep(3)
```

#### P8.1 条件分支任务编排

```
查状态 → 分支判断 → 差异化任务链 → 统一收尾
路径A(次数用完): 直接执行视频任务
路径B(有剩余): 广告→签到→视频
统一收尾: 兑换流程 (所有路径汇聚)
关键: sys.exit(1) 用于核心任务失败时立即终止
```

#### P8.2 通用并发执行

**核心**: 环境变量控制并发数 + `print_lock` 线程安全 + 串行/并行双模式 + 结果排序

```python
CONCURRENT_NUM = min(max(int(os.getenv('APP_CONCURRENT','1')), 1), 20)
print_lock = Lock()

def run_single_account(account, index, config) -> dict:
    with print_lock: print(f"🚀 账号{index+1}")
    client = AppClient(account, index, config)
    result = client.run(); result['index'] = index; return result

def main():
    accounts = get_accounts(); random.shuffle(accounts)
    if CONCURRENT_NUM <= 1:  # 串行
        all_results = [run_single_account(a, i, config) for i,a in enumerate(accounts)]
    else:  # 并发
        with ThreadPoolExecutor(max_workers=CONCURRENT_NUM) as ex:
            all_results = [f.result() for f in as_completed(
                {ex.submit(run_single_account, a, i, config): i for i,a in enumerate(accounts)})]
    all_results.sort(key=lambda x: x['index'])
```

**变体-生产者模式**: `while current_count < target` + `FILE_LOCK` 保护计数与文件IO

#### P8.3 进度条等待

仅限单线程（多线程会交错乱序）

```python
def wait_with_progress(delay, prefix='等待:'):
    for r in range(delay, 0, -1):
        bar = '█'*int(30*(delay-r)//delay) + '-'*(30-int(30*(delay-r)//delay))
        print(f'\r{prefix} |{bar}| {100*(delay-r)/delay:.1f}% 剩余{r}s', end='\r')
        time.sleep(1)
    print()
```

#### P8.4 服务端倒计时自动循环

适用于：签到/领取/养号任务需要等待服务端倒计时结束后再领取下一轮，避免固定 sleep 猜时间或高频轮询。

```python
USER_AUTO_CYCLE = "0"   # 1=开启; 青龙设 APP_AUTO_CYCLE
USER_MAX_CYCLES = "1"   # 最大领取轮数，防止无限运行

def calc_wait_seconds(data):
    start = parse_time(data.get("startTime"))
    server = parse_time(data.get("serverTime"))
    duration = int(data.get("durationSecond") or 0)
    return max(int(start.timestamp() + duration - server.timestamp()) + random.randint(8, 25), 0)

def run_auto_cycle(client, max_cycles):
    for _ in range(max_cycles):
        client.run_once()  # 内部: NOT_START_CAN_START → start
        info = client.get_countdown_info().get("data") or {}
        if info.get("status") != "RUNNING": break
        wait_with_heartbeat(calc_wait_seconds(info))
```

**要点**:
- 用 `startTime + durationSecond - serverTime` 计算剩余时间，优先相信服务端时间。
- 等待期间只做低频心跳/状态检查，到点后再次确认 `NOT_START_CAN_START` 才调用领取接口。
- 必须提供 `MAX_CYCLES` 或截止时间，防止脚本在青龙/服务器中无限常驻。

#### P8.5 并发执行结果排序

多账号并发时必须保留账号原始 `index`，完成后按 `index` 排序，避免通知汇总与账号顺序错乱。

```python
def run_single_account(account, index) -> dict:
    client = AppClient(account, index)
    result = client.run()
    result["index"] = index
    return result

with ThreadPoolExecutor(max_workers=Config.CONCURRENT_NUM) as executor:
    futures = {executor.submit(run_single_account, acc, i): i for i, acc in enumerate(accounts)}
    results = [f.result() for f in as_completed(futures)]
results.sort(key=lambda x: x["index"])
```

**要点**: 并发日志使用 `print_lock`；通知只使用排序后的 `results`。

#### P8.6 Async Semaphore 限流

异步脚本不要直接全量 `asyncio.gather`，应使用 `asyncio.Semaphore(MAX_CONCURRENT)` 控制并发。推荐“账号内串行，账号间限流并发”。

```python
sem = asyncio.Semaphore(Config.MAX_CONCURRENT)

async def run_guarded(account, index):
    async with sem:
        client = AsyncAppClient(account, index)
        return await client.run()

results = await asyncio.gather(*(run_guarded(a, i) for i, a in enumerate(accounts)), return_exceptions=True)
```

**适用**: `aiohttp/httpx.AsyncClient`、广告上报、高频查询、批量签到。

#### P8.7 可观测批次运行器

批量注册、转换或巡检任务使用稳定 `run_id`，保存计划、worker 状态、事件流、产物索引和最终汇总。限制同时活动批次数，支持协作式取消；取消或异常退出时回收浏览器、子进程、本地端口和临时文件，并保留足够证据用于定位失败阶段。

读取 `references/registration-automation-patterns.md` 的“P8.7 可观测批次运行器”。

---

**F. 配置、兼容与项目组织**

### P9: 集中配置与运行兼容

```python
class Config:
    ENV_NAME = "APP_COOKIE"
    ACCOUNT_SEP = re.compile(r'[&\n]')  # 支持&或换行分隔
    BASE_URL = "https://example.com/api"
    REQUEST_TIMEOUT = 15; MAX_RETRIES = 3; ACCOUNT_DELAY = 3
    BASE_HEADERS = {'User-Agent': 'Mozilla/5.0 ...', 'Content-Type': 'application/json'}
```

#### P9.1 Top-Level 双源配置

```python
# ====== 用户配置区 ======
USER_INVITE_CODE = ""          # 本地直接填; 青龙设 APP_INVITE_CODE
USER_PROXY_ENABLE = "0"        # 0=关, 1=开
USER_PROXY_API = "http://api.89ip.cn/tqdl.html?api=1&num=1&port=&address=&isp="  # 默认89ip
USER_TARGET_COUNT = 5

DELAY_SETTINGS = {             # ← 见 P2.2
    "ACTION": (3,6), "REG_LOOP": (25,36), "ERROR_RETRY": (3,6),
}

# ====== 配置加载 (环境变量优先) ======
TASK_CONFIG = {
    "INVITE_CODE":  os.getenv("APP_INVITE_CODE",  USER_INVITE_CODE),
    "PROXY_ENABLE": os.getenv("APP_PROXY_ENABLE", USER_PROXY_ENABLE) == "1",
    "PROXY_API":    os.getenv("APP_PROXY_API",    USER_PROXY_API),
    "TARGET_COUNT": int(os.getenv("APP_TARGET_COUNT", str(USER_TARGET_COUNT))),
}
```

#### P9.2 Windows 编码兼容

```python
import sys, io
if sys.platform=='win32': sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### P10: 单脚本项目文件夹归集 (Single Script Project Folder)
适用于：用户要求为某个脚本新增本地运行、README、示例配置、数据文件、缓存、日志、导出结果等紧密相关文件。

**规则**:
- 新增紧密相关文件时，先按脚本主题/脚本名创建独立文件夹，例如 `中视频.py` → `中视频/`。
- 主脚本文件名优先使用中文业务名，格式为 `平台/项目名 + 功能 + 脚本.py`，例如 `Cloud 云矿机养号脚本.py`；仅在用户明确要求、目标平台不支持中文路径，或现有仓库已有英文命名约定时使用英文名。
- 主脚本、`README.md`、`.env.example`、账号示例、数据文件、运行缓存说明全部放进该文件夹。
- 既有根目录脚本需要配套文件时，应把主脚本和新文件一起归集到同名文件夹，避免根目录散落文件。
- README 中的运行命令必须以归集后的目录为准，例如先进入 `中视频/` 再运行 `python .\中视频.py`。

**推荐结构**:
```text
中文脚本名/
  中文脚本名.py
  README.md
  .env.example
  accounts.example.json
```

#### P10.1 本地操作面与 Windows 启动器

当脚本需要非开发者长期运行时，可提供本地 Web/TUI 操作面和 PowerShell/批处理启动器。默认只监听 `127.0.0.1`，远程暴露前必须启用认证；启动器负责项目内虚拟环境、必要依赖、配置模板、目录创建、端口探测、健康检查和日志落盘，不全局安装依赖。

读取 `references/registration-automation-patterns.md` 的“P10.1 本地操作面与 Windows 启动器”。操作面至少提供单任务互斥、开始/停止、状态、脱敏产物列表与显式删除；下载接口必须验证安全文件名并限制到产物目录。

---

**G. 日志、隐私与通知**

### P11: 日志输出与敏感信息保护

```python
# 方式1 (函数式): print(f"✅ {msg}") / print(f"❌ {msg}") / print(f"ℹ️ {msg}")
# 方式2 (OOP推荐): logging.basicConfig(level=logging.INFO, format='%(message)s')
# 方式3 (极客/多线程): ANSI彩色 + 线程标识
class LogHelper:
    @classmethod
    def info(cls, msg, icon="[*]"): print(f"[{'TASK' if 'Thread' in threading.current_thread().name else 'SYS'}] {icon} {msg}")
    @classmethod
    def success(cls, msg): cls.info(msg, "✓")
# 方式4 (进度条): print_progress_bar(iter, total, prefix='', suffix='', length=30)  # \r覆盖
```
> **原则**: 用户"扫"不是"读"。去掉时间戳和INFO前缀，只留 Emoji + 消息内容。

**P11-状态卡片 + 汇总表（推荐用于多账号定时脚本）**:
```python
class Log:
    def title(name, subtitle=""): print("="*72, f"\n{name:^72}\n{subtitle:^72}", "\n"+"="*72)
    def account(i,total,token): print("-"*72, f"\nACCOUNT {i}/{total} token={mask_token(token)}\n"+"-"*72)
    def step(n,msg): print(f"[{n:02d}] {msg}")
    def kv(k,v): print(f"  {k+':':<14} {v or '-'}")
    def summary(rows, action_key): ...  # 账号 / 状态 / 动作 / 结果
```
**要点**:
- 状态字段用固定标签：`RUNNING`、`WAIT_COLLECT`、`COLLECT`、`REQUEST_LIMIT`。
- 账号内输出用步骤编号，账号间用横线分隔，最后统一汇总表。
- 增加 `LOG_COLOR=0/1` 配置，青龙日志乱码时可关闭 ANSI 颜色。

#### P11.1 手机号与 Token 脱敏

```python
# 初始化时一次性计算，全流程使用安全属性
self.masked_phone = f"{phone[:3]}****{phone[7:]}" if len(phone)==11 else phone
def mask_token(t): return f"{t[:8]}...{t[-8:]}" if t and len(t)>16 else "****"
```

#### P11.2 线程安全 Logger

多线程脚本应提供全局 `print_lock`，Logger 内部也可维护实例锁，保证账号间日志不交叉。

```python
print_lock = threading.Lock()

class SafeLogger:
    def __init__(self, prefix=""):
        self.prefix = prefix
        self._buf = []
    def log(self, msg):
        line = f"{self.prefix}{msg}"
        self._buf.append(line)
        with print_lock:
            print(line, flush=True)
    def summary_text(self):
        return "\n".join(self._buf)
```

**要求**:
- 账号内可即时打印，账号间输出用锁保护。
- 账号级消息缓存用于最终通知汇总。
- 状态图标固定化，减少同义日志噪声。

### P12: 公告与多通知渠道

```python
# 青龙标准: from notify import send
# PushPlus: requests.post("http://www.pushplus.plus/send", json={"token":..., "title":..., "content":...})
# WxPusher: requests.post("http://wxpusher.zjiecode.com/api/send/message", json={...})
# 兼容降级: try: from rnl_push import rnl_push; except: from notify import send as rnl_push
```

#### P12.1 公告系统

```python
def get_proclamation():
    # 推荐使用 logger.info 替代 print，避免与 \r 进度条或 Windows 缓冲导致输出顺序错杂
    for url in ["https://primary.../notice.txt", "https://backup.../notice.json"]:
        try: resp=requests.get(url,timeout=10); resp.status_code==200 and logger.info(f"📢 {resp.text}"); return
        except: continue
```

### P13: 既有脚本 Pattern Mining、状态缓存与历史记录

适用于：用户要求全面阅读当前目录脚本、沉淀优秀写法，或脚本需要 token 缓存、积分历史、断点续跑、昨日数据对比。

#### P13.1 只读 Pattern Mining 工作流

```text
1. 枚举脚本，排除 .git/venv/__pycache__/node_modules/exports
2. 分类：first-party readable / compressed-obfuscated / vendor-static
3. 统计入口、Config、环境变量、HTTP Client、timeout/retry、并发、锁、日志、缓存、通知
4. 选择高分代表文件做证据抽样
5. 输出：文件数与代表路径、可复用 pattern、建议写入技能条目
6. 用户要求只读时，不改源码、不格式化、不更新 Skill；用户明确要求固化时才写入
```

#### P13.2 自动化脚本成熟度判断矩阵

| 维度 | 成熟表现 |
|---|---|
| 配置 | `Config` / Top-Level 用户配置区 / 环境变量覆盖 |
| 账号 | 多账号、多分隔符、格式校验、去重、备注 |
| 请求 | Session 复用、统一 headers、timeout、签名注入 |
| 错误 | 网络异常、业务异常、解析异常分层处理 |
| 重试 | backoff、代理切换、账号级快速熔断 |
| 并发 | 并发上限、锁、结果排序 |
| 日志 | 脱敏、账号分隔、Emoji 状态、汇总表 |
| 状态 | cache/history/checkpoint，支持断点续跑 |
| 通知 | notify.py / PushPlus / WxPusher 可选接入 |
| 组织 | 单脚本归集；超过复杂度阈值拆 `sdk/plugins` |

#### P13.3 CacheManager 状态缓存

```python
class CacheManager:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.load()
    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except Exception:
            return {}
    def get(self, key, default=None): return self.data.get(key, default)
    def set(self, key, value): self.data[key] = value
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
```

**要点**:
- 保存 JSON 使用 `ensure_ascii=False`，便于中文备注和日志排查。
- 使用临时文件 + replace 原子写，避免任务中断导致 JSON 损坏。
- 缓存文件不要保存明文密码；Token 也需按业务敏感级别决定是否落盘。

#### P13.4 单脚本到平台型项目的演进阈值

当出现以下信号时，不再继续堆单文件，建议演进为目录化项目：

- 文件超过 800 行，或同时包含多个平台 API。
- 存在多个通知渠道、存储后端、插件或重复 HTTP/签名/缓存逻辑。
- 存在多个业务任务入口，或已经需要 `sdk/`、`plugins/`、`cache/`。

```text
project/
  main.py
  config.py
  notify.py
  sdk/
  plugins/
  cache/
  README.md
```

## 📝 变量分隔符总结

| 分隔符 | 用途 | 示例 |
|:---:|:---|:---|
| `\n` | 多账号(最常用) | `token1\ntoken2` |
| `&` | 多账号(兼容) | `token1&token2` |
| `#` | 字段分隔 | `token#secret#备注` |
| `----` | 账号格式化 | `Phone----Password----Token` |

---

## 🔗 Related Skills

- **python-script-decryptor**: 解密/脱壳 Python 加密脚本（marshal+zlib、Fernet、RSA+AES+DES 等）
- **python-obfuscator-pro**: 混淆加密 Python 脚本
- **automation-architect**: 需求分析和技术选型
- **js-script-deobfuscator**: 解混淆 JS 脚本

---

## Instruction for Agent

使用此技能或新建自动化项目时，必须先完成以下 Checklist。先根据需求、HAR、现有脚本和项目文件自动填写已知项，只向用户询问仍影响实现的缺口；不得重复询问已有答案。Checklist 确认且 Pattern Coverage Gate 中不存在 `pending` 后才能开始编码。

1. **目标平台与运行兼容**: 青龙面板 / 本地 CLI / Windows / 其他；Windows 控制台与中文路径 → P9/P9.2。
2. **环境变量名**: 大写下划线命名（`APP_TOKEN`）；用户配置与环境变量双源覆盖 → P9.1。
3. **账号格式**: 分隔符（`\n` / `&` / `#`）与字段 schema；多格式校验、去重和错误示例 → P3/P3.3。
4. **设备身份**: 普通签到/领取/养号/已有账号登录默认按 P2/P2.3 使用账号绑定的真机固定指纹；只有自动化注册流程使用 P2.1 随机 UA，且单次注册流程内固定。
5. **智能登录与授权**: Token 优先、失效回退、两阶段 Code 兑换 → P4/P4.1；刷新、巡检、导入导出 → P4.2。
6. **代理与网络环境**: 单代理/轮换 → P1；抓包或系统代理旁路 → P1.1；`httpx proxy=` 版本兼容 → P1.2；健康评分、认证转发或父代理 → P1.3；请求重试后换代理 → P6.3。
7. **任务编排与并发**: 条件分支 → P8/P8.1；多账号并发上限 20 → P8.2；结果保持原账号顺序 → P8.5；异步限流 → P8.6。
8. **通知与公告**: 通知渠道、失败隔离和汇总 → P12；公告主备地址 → P12.1。
9. **注册与短信验证**: 是否为注册流程 → P5；短信接码 → P5.2；没有短信不等于跳过其他注册校验。
10. **邮箱验证**: 单邮箱适配 → P5.1；多提供方故障切换与验证码来源过滤 → P5.4。
11. **挑战验证**: 是否存在官方、用户手动或明确授权的验证流程 → P5.3；否则停止，不实现绕过。
12. **配置与节奏基线**: 所有项目评估 P9/P9.1；远端多步骤流程默认使用 P2.2 场景化延迟，单接口任务可标记 `skip`。
13. **账号加载**: 文件+环境变量两源 → P3.1；来源切换 → P3.2；兼容历史格式 → P3.3。
14. **等待与循环**: 需要可见的单线程等待 → P8.3；按服务端倒计时领取下一轮 → P8.4，并设置最大轮数/截止时间。
15. **代理旁路与客户端兼容**: 开发环境有抓包工具时评估 P1.1；使用 `httpx` 时强制检查 P1.2。
16. **协议格式与请求签名**: `multipart/form-data` → P6.2；RSA/AES/UUID/通用签名 → P7；哈希索引签名 → P7.1。
17. **请求与异常处理**: 所有远端请求评估 P6；重试耗尽后跳过账号 → P6.1；代理双层重试 → P6.3。
18. **既有脚本基线**: 当前目录有同类 Python 脚本时先执行 P13/P13.1；按 P13.2 判断成熟度，达到平台阈值时使用 P13.4。
19. **状态缓存**: Token、积分、进度、checkpoint 或跨运行历史 → P13.3。
20. **复杂注册/协议流程**: 跨阶段、域名、Cookie、重定向或协议编码 → P6.4，并与 P5 的验证阶段组合。
21. **凭证生命周期**: 转换、刷新、健康巡检、导入导出与显式删除 → P4.2。
22. **代理池**: 多来源、健康评分、认证转发、冷却与父代理 → P1.3；与 P6.3 分工，避免重复重试层。
23. **批次运行**: run 历史、worker 状态、取消、资源清理和产物对账 → P8.7。
24. **项目组织、操作面与日志**: 脚本同名目录和交付文件 → P10；Web/TUI/Windows 启动器 → P10.1；结构化日志与汇总 → P11；敏感信息脱敏 → P11.1；并发日志 → P11.2。

### Pattern Coverage Gate

<!-- pattern-coverage:start -->
覆盖 ID（必须逐项标记 `apply` / `skip` / `pending`）：P1, P1.1, P1.2, P1.3, P2, P2.1, P2.2, P2.3, P3, P3.1, P3.2, P3.3, P4, P4.1, P4.2, P5, P5.1, P5.2, P5.3, P5.4, P6, P6.1, P6.2, P6.3, P6.4, P7, P7.1, P8, P8.1, P8.2, P8.3, P8.4, P8.5, P8.6, P8.7, P9, P9.1, P9.2, P10, P10.1, P11, P11.1, P11.2, P12, P12.1, P13, P13.1, P13.2, P13.3, P13.4。
<!-- pattern-coverage:end -->

编码前创建 Pattern 应用矩阵：

| Pattern | 状态 | 触发信号或 skip 理由 | 实现位置 | 验收证据 |
|:---|:---:|:---|:---|:---|
| Pn(.n) | apply/skip/pending | 来自需求、HAR 或既有代码 | 文件/函数 | 测试/命令/报告 |

- `apply`：必须进入实施计划，并在交付时给出实现位置和验证证据。
- `skip`：必须写明不适用理由；不能只写“未使用”。
- `pending`：表示仍缺输入；编码前必须消除，不得带入实现阶段。
- 主 Pattern 与子 Pattern 分别判定；应用子 Pattern 时主 Pattern 同时标记 `apply`。
- Pattern 之间冲突时以场景边界为准，例如 P2.1 只用于自动化注册，P2.3 用于长期账号养护。

**常见场景默认组合**:

- 签到/领取/养号：P2.3 + P3 + P4 + P6 + P8.1/P8.4 + P9 + P10 + P11；有通知加 P12，有跨运行状态加 P13.3。
- 自动化注册：P2.1 + P5 + P6.4 + P9 + P10 + P11；按输入追加 P1.3、P4.2、P5.1-P5.4、P8.7、P10.1。
- 多账号并发：P3 + P6 + P8.2/P8.5；异步实现追加 P8.6，并发日志追加 P11.2。
- 既有脚本重构：P13.1/P13.2 + 对应业务 Pattern；达到演进阈值时追加 P13.4。

**实施流程**:
1. 分析 HAR、需求和既有脚本，区分业务逻辑与基础设施；有既有脚本时先按 P13.1/P13.2 建立基线。
2. 完成 24 项 Checklist 和全量 Pattern 应用矩阵，消除所有 `pending`。
3. 选择范式（简单→函数式；复杂→OOP；高性能→异步），把所有 `apply` Pattern 写入实施计划。
4. 按 P10 创建/使用脚本同名目录；所有项目评估 P6、P9、P11，相关子 Pattern 按矩阵实施。
5. 普通签到/养号按 P2.3 固定真机档案；只有自动化注册使用 P2.1。复杂注册或凭证任务按需读取 `references/registration-automation-patterns.md`。
6. 多账号并发应用 P8.2/P8.5；异步并发追加 P8.6；批次任务按 P8.7 保存脱敏运行证据。
7. 实现完成后逐项回填 Pattern 矩阵的文件/函数位置与测试、命令或报告证据；没有证据的 `apply` 不算完成。
8. README 用中文编写，包含运行方式、环境变量、依赖、账号格式、示例配置和排错说明；不要写入个人联系方式、真实 Token 或项目专属链接。

