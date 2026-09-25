# 通用验证码模块

> 整合原 `AI验证码破解模块`、`通用AI识别模块`、`通用滑块验证码模块`，统一提供 Python AI 识别、GeeTest 页面验证码处理、Node.js 服务端滑块重试封装。

## 能力概览

| 能力 | 说明 |
|---|---|
| 多 AI 服务商 | OpenAI / Gemini / Claude / ZhipuAI / OpenAI 兼容接口 |
| 图片验证码识别 | 支持 bytes、文件路径、PIL.Image、data URI |
| GeeTest 页面验证码 | 支持滑块、九宫格点选、文字点选，适配 Playwright Page |
| 滑块缺口识别 | `captcha-recognizer` 优先，`ddddocr` 降级 |
| Node.js 滑块重试 | `js/slider_captcha_manager.js` 支持 fixedOffset 和 OCR 服务 |

## Python 快速使用

```python
from captcha_unified import AIConfig, ApiType, AIVisionClient, CaptchaDispatcher

config = AIConfig(
    api_type=ApiType.OPENAI,
    api_key="sk-xxx",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    model="glm-4v-flash",
)

client = AIVisionClient(config)
print(client.recognize("captcha.png"))

dispatcher = CaptchaDispatcher(client, max_retries=3)
success = dispatcher.solve(page)
```

仅处理滑块验证码时不需要 AI Key：

```python
from captcha_unified import CaptchaDispatcher

success = CaptchaDispatcher(client=None).solve(page)
```

## Node.js 快速使用

```javascript
const SliderCaptchaManager = require('./js/slider_captcha_manager');

const manager = new SliderCaptchaManager({
  maxAttempts: 20,
  retryDelayMs: 1500,
  fixedOffset: 0.578125,
  ocrServer: process.env.OCR_SERVER
});

const result = await manager.execute(fetchCaptchaFn, verifyCaptchaFn);
```

`fetchCaptchaFn` 需要返回：

```javascript
{
  id: 'captcha-id',
  bgImageBase64: '...',
  sliderImageBase64: '...'
}
```

`verifyCaptchaFn(captchaId, offset, originalData)` 返回 `false` 或抛异常时会自动重试。

## 安装依赖

Python：

```bash
pip install -r requirements.txt
```

Node.js：

```bash
cd js
npm install
```

## 自检

```bash
python example.py
cd js
npm test
```

## 目录结构

```text
通用验证码模块/
├── captcha_unified/
│   ├── __init__.py
│   ├── adapters.py
│   ├── config.py
│   └── solver.py
├── js/
│   ├── package.json
│   └── slider_captcha_manager.js
├── example.py
├── implementation_plan.md
├── requirements.txt
└── README.md
```

## 关于我们

青龙脚本库：https://gitee.com/zhushenzhiye/wuyin.git

QQ群聊：https://qm.qq.com/q/lQnQsCcX5u
