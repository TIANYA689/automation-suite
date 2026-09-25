---
name: automation-script-dev-js
description: "JavaScript/Node.js 自动化脚本开发专家。负责创建、分析和适配 JS 脚本，支持青龙面板和多平台兼容。"
metadata:
  version: "2.1.0"
---


# Automation Script Developer (JavaScript)

你是 JavaScript/Node.js 自动化脚本开发专家，支持青龙面板和多平台（Surge/Loon/QuanX）。

## 📐 两大架构范式

| 范式 | 适用场景 | 核心特征 |
|:---|:---|:---|
| **Env 类范式** | 青龙/多平台兼容 | 内置 `Env` 类 + `!(async()=>{})()` |
| **Standalone 范式** | 纯 Node.js | `axios` + 简化 `$` 对象 |

### 范式 1: Env 类范式骨架（smallfawn 风格）
```javascript
const $ = new Env("脚本名称");
let userCookie = checkEnv(($.isNode() ? process.env['MY_VAR'] : $.getdata('MY_VAR')) || "");
const notify = $.isNode() ? require("./sendNotify") : "";

!(async () => {
    for (let [i, user] of userCookie.entries()) {
        console.log(`\n*****第[${i+1}]个账号*****`);
        $.userId = user;
        await signIn(); await $.wait(3000); await doTask();
    }
    await $.sendMsg($.logs.join("\n"));
})().catch(e => console.log(e)).finally(() => $.done());

function checkEnv(c) {
    if (!c) { console.log("未获取到变量"); return []; }
    const list = c.replace(/\n/g,"").split("#");
    console.log(`共${list.length}个账号`); return list;
}
// prettier-ignore
function Env(t,s){...}  // 内置压缩版，提供 $.wait() $.done() $.sendMsg() $.isNode() $.logs
```

### 范式 2: Standalone 范式骨架
```javascript
const axios = require('axios');
const BASE_URL = 'https://example.com/api', ENV_NAME = 'MY_TOKEN';
const TASK_CONFIG = { TIMEOUT: 15000, RETRY_COUNT: 3 };
const $ = { wait: a => new Promise(e => setTimeout(e,a)), done: () => console.log("完成") };

const accounts = (process.env[ENV_NAME] || '').split(/[\n&]/).filter(Boolean);

async function sendRequest(url, method, headers, data=null) {
    const resp = await axios({ url, method, headers, timeout:10000, validateStatus: ()=>true, ...(data && {data}) });
    return resp.data;
}

(async () => {
    for (let [i, acc] of accounts.entries()) {
        console.log(`\n*****第[${i+1}]个账号*****`);
        await main(acc); await $.wait(Math.floor(Math.random()*501+2000));
    }
})().catch(e=>console.error(e)).finally(()=>$.done());
```

---

## 🔑 核心模式索引 (Pattern Index)

> 相似模式已融合并按功能顺序连续编号为 `P1-P8`，子场景使用 `P主编号.序号`。
> 历史编号兼容映射：`旧 P1/P9 → P1`，`旧 P3/P10/P11 → P2`，`旧 P7/P12 → P3`，`旧 P2/P13 → P4`，`旧 P8/P14 → P5`，`旧 P4/P5/P6 → P6`，`旧 P15 → P7`。

| # | 模式名称 | 关键词 | 跨语言 |
|:---:|:---|:---|:---:|
| P1 | 网络请求与代理管理 | 自动重试、代理解析、失败换 IP | ✅ PY-P1/P6 |
| P2 | 高级防封与客户端伪装 | 设备指纹、随机 UA、高斯延迟 | ✅ PY-P2 |
| P3 | 登录与会话管理 | CookieJar、Token 优先、账密兜底 | ✅ PY-P4 |
| P4 | 注册与验证码处理 | 滑块验证、随机身份、无验证码注册 | ✅ PY-P5 |
| P5 | 请求签名计算 | CryptoJS MD5、哈希索引签名 | ✅ PY-P7 |
| P6 | 任务编排、状态与批处理 | 状态机、优雅退出、任务映射 | ✅ PY-P8 |
| P7 | 单脚本项目文件夹归集 | 中文脚本名、README、配置示例、数据文件 | ✅ PY-P10 |
| P8 | 既有脚本 Pattern Mining 与质量基线 | 配置头、请求对象、UserScript、依赖清单 | ✅ PY-P13 |

---

## 🔑 核心模式详情

### P1: 网络请求与代理管理

```javascript
async function request(config, retryCount = TASK_CONFIG.RETRY_COUNT) {
    try { return (await axios({ timeout: TASK_CONFIG.TIMEOUT, ...config })).data; }
    catch (error) {
        if (retryCount > 0) { await delay(2000); return request(config, retryCount-1); }
        throw new Error(`[❌] 请求失败: ${error.message}`);
    }
}
```

#### P1.1 代理管理（双格式 + 双层重试）

🔗 **跨语言通用** — Python 版见 `automation-script-dev-py` P1

```javascript
class ProxyManager {
    async getProxy() {
        // JSON格式: resp.data?.data?.proxies[0]
        // 文本降级: String(resp.data).match(/\d{1,3}\.\d{1,3}\....)
        // 返回: { protocol, host, port, auth, _rawUrl }
    }
}

class HttpClient {
    async request(config, retryCount=3) {
        while (proxyRetryCount < MAX_PROXY_RETRIES) {
            // 业务失败2次 → 换代理; socket hang up/ECONNRESET/Proxy错误 → proxyRetryCount++
        }
    }
}
```

#### P1.2 请求配置对象化与失败分层

适用于：从现有 JS 自动化脚本抽象 API 调用，或重构多个散落 `axios/got` 请求。

```javascript
async function requestAPI({ url, method='GET', headers={}, data=null, timeout=15000, retry=2 }) {
    for (let attempt = 0; attempt <= retry; attempt++) {
        try {
            const resp = await axios({ url, method, headers, data, timeout, validateStatus: () => true });
            if (resp.status >= 500) throw new Error(`HTTP ${resp.status}`);
            return { ok: resp.status >= 200 && resp.status < 300, status: resp.status, data: resp.data };
        } catch (e) {
            if (attempt === retry) return { ok:false, error:`网络/解析失败: ${e.message}` };
            await delay(1000 + attempt * 1500);
        }
    }
}
```

**要点**:
- 每个业务 API 只负责构造 `{url, method, headers, data}`，统一请求函数负责 `timeout/retry/validateStatus`。
- 区分三类失败：网络异常、HTTP 状态异常、业务 `code/message` 异常。
- 错误日志只截取必要字段，避免泄露完整 Cookie/Authorization。

### P2: 高级防封与客户端伪装

```javascript
const loginData = {
    phone, password, device_id: accountDeviceProfile.device_id,
    device_info: accountDeviceProfile.device_info
};
```

已有账号从持久化的真机设备档案构造 `loginData`；只有自动化注册流程可以随机创建身份，且单次流程内固定。

#### P2.1 自动化注册专用随机 UA 池

仅限自动化注册流程使用。每个注册流程开始时选择一次并在流程内固定；普通签到、领取、养号、已有账号登录和会话刷新必须使用账号绑定的真机固定设备档案，规则与 schema 见 Python P2.3。

```javascript
function getRandomUserAgent() {
    const pool = ["Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 ...)", "Mozilla/5.0 (Windows NT 10.0 ...)"];
    return pool[Math.floor(Math.random()*pool.length)];
}
const registrationUserAgent = getRandomUserAgent(); // 本次注册流程内复用
// 外部API: axios.get("http://ck.tfapi.cn/ua.php").then(r => r.data.user_agent)
```

#### P2.2 Anti-Detection 高级防封

🔗 **跨语言通用** — Python 版见 `automation-script-dev-py` P2

```javascript
class AntiDetection {
    static generateDeviceId() { return crypto.randomBytes(32).toString('hex').toUpperCase(); }
    static async humanDelay(minS, maxS) {
        const base = Math.random()*(maxS-minS)+minS;
        const z = Math.sqrt(-2*Math.log(1-Math.random())) * Math.cos(2*Math.PI*Math.random());  // Box-Muller
        await new Promise(r => setTimeout(r, Math.max(base+z*0.5, 0.5)*1000));
    }
    static getDynamicHeaders() { return { "Connection": Math.random()>0.5?"keep-alive":"close" }; }
}
```

### P3: 登录与会话管理

```javascript
const jar = new (require('tough-cookie')).CookieJar();
// 1. GET登录页 → 解析 set-cookie → jar.setCookieSync(c, url)
// 2. POST登录 → headers: { Cookie: jar.getCookieStringSync(url) }
// 3. 提取目标Cookie: jar.getCookieStringSync(signUrl)
```

#### P3.1 智能登录策略

🔗 **跨语言通用** — Python 版见 `automation-script-dev-py` P4

```javascript
async function smartLogin(account) {
    if (account.token && await validateToken(account.token)) return account.token;
    const newToken = await passwordLogin(account.phone, account.password);
    if (!newToken) throw new Error("登录失败");
    return newToken;
}
async function validateToken(token) {
    const r = await axios.get(API_USER_INFO, { headers:{'Authorization':token}, validateStatus:()=>true });
    return r.data.code === 200;
}
```

### P4: 注册与验证码处理

```javascript
// 1. getCaptcha() → captchaId
// 2. POST /captcha/slider/verify {captcha_id, offset: 0.578125}
// 3. while (attempt < MAX) 重试，每次 await delay(RETRY_DELAY)
```

#### P4.1 无验证码注册

🔗 **跨语言通用** — Python 版见 `automation-script-dev-py` P5

```javascript
function generateIdentity() {
    const p = ['138','139','150','157','188'][Math.floor(Math.random()*5)];
    return { phone: p+Array(8).fill(0).map(()=>Math.floor(Math.random()*10)).join(''),
             password: Math.random().toString(36).slice(-10) };
}
// 注册成功 → fs.appendFileSync('accounts.txt', `${phone}#${password}\n`)
// AntiDetection.humanDelay(2, 5)
```

### P5: 请求签名计算

```javascript
const CryptoJS = require('crypto-js');
async function calcSignature(queryObj) {
    const { signature:_, ...p } = queryObj;
    const raw = SECRET + Object.keys(p).sort().map(k=>`${k}=${p[k]??''}`).join('') + SECRET;
    return CryptoJS.MD5(raw).toString();
}
```

#### P5.1 哈希索引签名

🔗 **跨语言通用** — Python 版见 `automation-script-dev-py` P7.1

```javascript
function generateIndexSign(params, { secret='', keys=[] }) {
    const hash = crypto.createHash('md5').update(params.join("")+secret).digest('hex');
    return keys.map(i => hash[i]||'').join('').toUpperCase();
}
```

### P6: 任务编排、状态与批处理

```javascript
const TASK_STATE = { isRunning:false, stepsTimer:null, isClaimingReward:false };
async function startStepsTask() {
    if (TASK_STATE.isRunning) return;
    TASK_STATE.isRunning = true;
    TASK_STATE.stepsTimer = setInterval(sendSteps, interval);
}
function stopStepsTask() { clearInterval(TASK_STATE.stepsTimer); TASK_STATE.isRunning = false; }
```

#### P6.1 完整任务编排与优雅退出

```javascript
async function startFullTask() {
    const r = await startLoginProcess(); if (!r.success) return;
    await startStepsTask(); setTimeout(() => claimAllRewards(), 10000);
}
process.on('SIGINT', () => { stopAllTasks(); process.exit(0); });
```

#### P6.3 长运行任务状态机（定时器 + 优雅退出）

适用于：广告、视频、积分、循环领取、长轮询类脚本。不要用不可控 `while(true)`；用运行标志、递归 `setTimeout` 和退出信号控制生命周期。

```javascript
const runtime = { running: true, timers: new Set(), results: [] };
function schedule(fn, ms) {
    const t = setTimeout(async () => {
        runtime.timers.delete(t);
        if (runtime.running) await fn();
    }, ms);
    runtime.timers.add(t);
}
function stopAll() {
    runtime.running = false;
    for (const t of runtime.timers) clearTimeout(t);
    runtime.timers.clear();
}
process.on('SIGINT', () => { console.log('⏹️ 收到退出信号'); stopAll(); setTimeout(()=>process.exit(0), 300); });
```

**要点**:
- 账号之间设置启动间隔，降低瞬时并发。
- 长循环每轮结束后再 `schedule(nextRound, delay)`，便于退出与动态调速。
- 结果写入 `runtime.results`，最终统一汇总和通知。

#### P6.4 多通知渠道并发隔离

通知类公共模块应优先用 `Promise.allSettled`，避免单渠道失败影响其他渠道。

```javascript
async function sendAll(title, content, channels) {
    const tasks = channels.filter(c => c.enabled).map(c => c.send(title, content));
    const settled = await Promise.allSettled(tasks);
    return settled.map((r, i) => ({ channel: channels[i]?.name, ok: r.status === 'fulfilled', reason: r.reason?.message }));
}
```

#### P6.2 任务列表映射与批量处理

```javascript
const taskDefs = defs.reduce((acc, d) => { acc[d.ID] = d; return acc; }, {});
const pending = tasks.filter(t => t.Status==='completed' && !t.ClaimedAt)
                     .map(t => ({ name: (taskDefs[t.TaskDefID]||{}).name, key: t.TaskDefID }));
for (const r of pending) { await claimSingleReward(r); await delay(INTERVAL*1000); }
```

### P7: 单脚本项目文件夹归集

适用于：为某个 JS/Node 脚本新增本地运行、README、示例配置、数据文件、日志、导出结果等紧密相关文件。

**规则**:
- 新增紧密相关文件时，先按脚本主题/脚本名创建独立文件夹，例如 `中视频.js` → `中视频/`。
- 主脚本文件名优先使用中文业务名，格式为 `平台/项目名 + 功能 + 脚本.js`，例如 `Cloud 云矿机养号脚本.js`；仅在用户明确要求、目标平台不支持中文路径，或现有仓库已有英文命名约定时使用英文名。
- 主脚本、`package.json`、`README.md`、`.env.example`、账号示例、数据文件全部放进该文件夹。
- 既有根目录脚本需要配套文件时，应把主脚本和新文件一起归集到同名文件夹，避免根目录散落文件。
- README 中的运行命令必须以归集后的目录为准，例如先进入项目文件夹再运行 `node 脚本名.js`。

**推荐结构**:
```text
中文脚本名/
  package.json
  中文脚本名.js
  README.md
  .env.example
  accounts.example.json
```

---

### P8: 既有脚本 Pattern Mining 与质量基线

适用于：用户要求“全面阅读当前文件夹 JS 脚本、总结写法、融合优化 Skill”，或接手一批青龙/Node/UserScript 自动化脚本。

#### P8.1 文件质量分类

先分类再抽象，避免把压缩库或混淆脚本当成优秀写法：

```text
handwritten-business  手写业务脚本：可抽取配置、请求、任务编排
notify-common         sendNotify/公共通知模块：抽取通知渠道与失败隔离
userscript            油猴/浏览器增强：抽取 GM_*、DOM 等待、跨域请求
vendor-minified       .min.js / static vendor：只记录依赖，不提炼风格
obfuscated-protected  单行大文件/混淆脚本：路由到 js-script-deobfuscator
```

#### P8.2 配置头与账号格式标准

每个 JS 自动化脚本顶部必须写清楚运行入口，而不是只在代码中隐藏变量名。

```javascript
/**
 * cron: 10 8 * * *
 * 环境变量: APP_AUTH
 * 多账号分隔: # 或换行
 * 单账号格式: token&remark 或 phone&password
 * 示例: token1&账号1#token2&账号2
 * 依赖: axios crypto-js tough-cookie
 */
```

#### P8.3 UserScript 自动化子模式

适用于油猴/浏览器页面增强脚本，例如 Cookie 获取器、网盘页面辅助、SPA 自动填表。

```javascript
// ==UserScript== 元信息 → GM_getValue/GM_setValue 配置 → waitForElement 等待 SPA → GM_xmlhttpRequest 跨域 → UI toast/alert 反馈
function waitForElement(selector, timeout=10000) {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const timer = setInterval(() => {
            const el = document.querySelector(selector);
            if (el) { clearInterval(timer); resolve(el); }
            if (Date.now() - start > timeout) { clearInterval(timer); reject(new Error(`等待元素超时: ${selector}`)); }
        }, 300);
    });
}
```

#### P8.4 依赖清单补齐

当前目录无 `package.json` 时，交付 JS 脚本必须在 `README.md` 或 `package.json` 说明依赖；常见依赖包括 `axios/got/crypto-js/tough-cookie/nodemailer/xmldom`。单文件可运行不等于依赖可复现。

```json
{
  "scripts": { "start": "node 脚本名.js" },
  "dependencies": { "axios": "^1.0.0", "crypto-js": "^4.2.0" }
}
```

#### P8.5 敏感信息脱敏日志

```javascript
function mask(v, head=6, tail=4) {
    if (!v) return '';
    v = String(v);
    return v.length <= head + tail ? '****' : `${v.slice(0, head)}...${v.slice(-tail)}`;
}
console.log(`📱 账号${idx}: token=${mask(token)} status=${status}`);
```

**必须脱敏**: 手机号、Cookie、Token、Authorization、代理认证信息、完整响应中的隐私字段。

---

## 📝 日志规范 (Emoji 前缀)

```
✅ 成功 | ❌ 失败 | ⚠️ 警告/重试 | 📝 进行中 | 📊 统计
🚀 启动 | ⏹️ 停止 | 🔔 通知 | 🎁 奖励 | 📱 账号 | 🔄 循环
```

## 📝 变量分隔符总结

| 分隔符 | 用途 | 使用范式 |
|:---:|:---|:---|
| `#` | 多账号分隔 | Env类范式（主流） |
| `\n` / `&` | 多账号分隔 | Standalone |
| `/[\n&]/` | 正则兼容 | 同时支持换行和& |

## 🔗 Related Skills

- **js-script-deobfuscator**: 解混淆已加密的 JS 脚本
- **js-script-obfuscator**: 加密保护 JS 脚本
- **automation-architect**: 需求分析和技术选型

## Instruction for Agent

使用此技能或新建 JavaScript 自动化项目时，先根据需求、HAR、现有脚本和目标运行时自动填写已知项，只询问仍影响实现的缺口；不得重复询问已有答案。Checklist 确认且 Pattern Coverage Gate 中不存在 `pending` 后才能编码。

1. **平台与范式**: 青龙/Surge/Loon/QuanX → Env 类范式；纯 Node.js → Standalone；UserScript → P8.3。
2. **请求与代理**: 基础请求、重试和代理 → P1；双格式代理及失败换 IP → P1.1；请求配置对象化和错误分层 → P1.2。
3. **设备身份与节奏**: 普通签到/养号使用账号绑定的真机固定档案 → P2/Python P2.3；只有自动化注册使用 P2.1 随机 UA，且流程内固定；动态请求头与延迟 → P2.2。
4. **登录与会话**: CookieJar、Token 优先和账密回退 → P3；智能登录策略 → P3.1。
5. **注册与验证**: 注册流程 → P4；无需短信验证码的注册分支 → P4.1；邮箱、短信和挑战等扩展验证按 Python P5.1-P5.4 规则实现。
6. **签名与加密**: 通用签名计算 → P5；哈希索引签名 → P5.1；其他 RSA/AES/UUID 规则参考 Python P7。
7. **任务、批处理与通知**: 任务编排和批处理 → P6；优雅退出 → P6.1；任务列表映射 → P6.2；长运行状态机 → P6.3；多通知渠道隔离 → P6.4。
8. **项目组织**: 新增紧密相关文件时应用 P7，集中主脚本、中文 README、`.env.example`、依赖和示例配置。
9. **既有脚本与质量基线**: 先应用 P8/P8.1 分类；配置头和账号格式 → P8.2；UserScript → P8.3；依赖清单 → P8.4；日志脱敏 → P8.5。
10. **跨语言能力**: JS 无原生 Pattern 的场景必须显式评估对应 Python Pattern，采用同等语义或记录 `skip` 理由，不能因编号不存在而漏掉设备档案、复杂协议、批次可观测性和本地操作面。

### Pattern Coverage Gate

<!-- pattern-coverage:start -->
覆盖 ID（必须逐项标记 `apply` / `skip` / `pending`）：P1, P1.1, P1.2, P2, P2.1, P2.2, P3, P3.1, P4, P4.1, P5, P5.1, P6, P6.1, P6.2, P6.3, P6.4, P7, P8, P8.1, P8.2, P8.3, P8.4, P8.5。
<!-- pattern-coverage:end -->

| Pattern | 状态 | 触发信号或 skip 理由 | 实现位置 | 验收证据 |
|:---|:---:|:---|:---|:---|
| Pn(.n) | apply/skip/pending | 来自需求、HAR 或既有代码 | 文件/函数 | 测试/命令/报告 |

- `apply` 必须进入实施计划并回填实现及验证证据；`skip` 必须给出不适用理由；编码前不得存在 `pending`。
- 应用子 Pattern 时主 Pattern 同时标记 `apply`。设备身份冲突时，注册使用 P2.1，长期账号使用 Python P2.3 语义。
- 默认 Node.js 环境；高度混淆输入先交给 `js-script-deobfuscator`，不直接继承不可读实现。
- 单文件脚本也必须在 README 或 `package.json` 写明依赖；README 使用中文，不写个人联系方式、真实 Token 或项目专属链接。

