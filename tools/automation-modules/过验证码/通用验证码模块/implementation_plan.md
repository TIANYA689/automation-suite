# 通用验证码模块整合计划

## 目标

将 `AI验证码破解模块`、`通用AI识别模块`、`通用滑块验证码模块` 整合为一个统一目录，减少重复代码和依赖污染。

## 已执行

- 保留 Python 多服务商 AI 识别能力：OpenAI、Gemini、Claude、ZhipuAI。
- 保留 GeeTest 三类页面验证码策略：滑块、九宫格点选、文字点选。
- 保留 Node.js 服务端滑块验证码重试管理器，放入 `js/` 子目录。
- 删除旧模块中的重复单文件版本、旧 Python 包和提交的 `node_modules`。

## 目录设计

```text
通用验证码模块/
├── captcha_unified/          # Python 包
├── js/                       # Node.js 滑块管理器
├── example.py                # Python dry-run 自检和示例
├── requirements.txt          # Python 依赖
├── implementation_plan.md    # 本整合记录
└── README.md                 # 使用文档
```
