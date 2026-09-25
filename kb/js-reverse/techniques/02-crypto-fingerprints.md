# 加密算法指纹与还原

用途：从密文形态或代码常量反推算法，并在 Node 与 Python 两条路径上复现。

## 一、密文形态速查

| 特征 | 可能算法 | 验证方法 |
|---|---|---|
| 32 位十六进制 | MD5 | 用已知输入对比标准输出 |
| 40 位十六进制 | SHA-1 | 同上 |
| 64 位十六进制 | SHA-256 或 HMAC-SHA256 | 搜 HMAC 相关关键词区分 |
| 128 位十六进制 | SHA-512 | 同上 |
| `=` 结尾且含 `A-Za-z0-9+/` | Base64 | 直接解码看是否可读 |
| `=` 结尾且含 `A-Za-z0-9-_` | Base64url | 替换字符后解码 |
| 固定长度且为 16 字节倍数 | AES 系 | 找 key（16/24/32 字节）与 iv（16 字节） |
| 固定长度且为 8 字节倍数但非 16 | DES / 3DES | 找 8 字节 key |
| 超长数字字符串 | RSA | 找公钥或模数+指数 |
| 三段 Base64url 用点分隔 | JWT | 分别解码 header/payload/signature |

**重要**：形态匹配只给"可能性排序"，不给结论。同一个 32 位十六进制串可能是 MD5、也可能是某个自定义哈希。必须用已知输入输出对验证。

## 二、自定义变体

以下情况形态与标准算法一致，但输出不同：

- 改了初始状态字（如 MD5 的四个初值）
- 改了轮数
- 改了字符集或输出编码（如 chrsz 之类的位宽参数）
- 改了 S-Box 或置换表

**识别方法**：用相同输入对比标准实现输出；不一致即为变体。

**还原策略**：变体无法用标准库替代，必须提取原始实现并原样执行（Node 中直接跑原 JS，或 Python 中通过 JS 运行时调用）。不要试图"猜"它改了什么。

## 三、常见签名拼接模式

| 模式 | 形态 |
|---|---|
| 固定格式 | `md5("page=" + page + "&t=" + ts + "&key=" + secret)` |
| 参数排序拼接 | 按 key 排序后 `k=v` 用 `&` 连接，末尾拼 secret |
| JSON 字符串 | `md5(JSON.stringify(data) + secret)` |
| 管道分隔 | `md5(page + "\|" + ts + "\|" + secret)` |
| 嵌套哈希 | `md5(md5(password) + ts)` |

**排查顺序**：先确认参数顺序（是否排序、是否含空值、是否 URL 编码），再确认分隔符，最后确认 secret 位置（前缀/后缀/中间）。这三项任一不同都会导致签名不一致。

## 四、密钥来源分类

| 来源 | 特征 | 处理 |
|---|---|---|
| 硬编码 | 源码中可见常量串 | 直接提取；注意可能是变体编码 |
| 接口下发 | 首次请求返回 key | 复现初始化流程 |
| 动态计算 | 由时间/设备值派生 | 需还原派生算法 |
| 环境指纹 | 由浏览器环境值哈希得到 | 环境伪装或补齐环境值 |

环境指纹类最麻烦，也是走 jsdom 环境复现路径的典型触发条件。

## 五、双语言还原对照

Node 与 Python 的实现差异是常见踩坑点，重点核对：

| 关注点 | Node | Python |
|---|---|---|
| 字符串编码 | `update(str)` 默认 utf8 | 需显式 `.encode('utf-8')` |
| AES 填充 | `setAutoPadding(true)` 为 PKCS7 | 需 `pad()` / `unpad()` |
| JSON 序列化 | `JSON.stringify` 无空格 | `json.dumps` 默认含空格，需 `separators=(',', ':')` |
| JSON 键顺序 | 保持插入序 | 需 `sort_keys` 显式控制 |
| Base64 变体 | `toString('base64url')` | `urlsafe_b64encode` 且需手动去填充 |
| HMAC 参数顺序 | `(algorithm, key)` | `(key, msg, digestmod)` |

**最容易出错的是 JSON 序列化**：Node 的 `JSON.stringify` 与 Python 的 `json.dumps` 在空格、键顺序、非 ASCII 转义上默认行为都不同，直接导致签名不一致。

## 六、时间戳

| 类型 | 位数 | 说明 |
|---|---|---|
| 秒级 | 10 | `Math.floor(Date.now()/1000)` |
| 毫秒级 | 13 | `Date.now()` |

部分服务端使用**服务端时间**，需要从响应头或接口获取，不能本地生成。这类签名在离线复现时必须显式接收时间参数，否则无法验证。

## 相关条目

- 二进制层面的算法常量指纹：`skills/binary-symbol-recovery/references/algorithm-fingerprints.md`
- 混淆类型识别：`kb/js-reverse/techniques/01-obfuscation-signals.md`
