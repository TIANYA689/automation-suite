# 豪猪平台 (HaoZhuMa) 手机号接码模块

这是一个对接豪猪平台 API 的 Python 模块，支持自动化接码流程。

## 功能特性
- [x] 自动登录获取 Token
- [x] 账户余额查询
- [x] 获取手机号码（支持省份、运营商、虚拟/实卡过滤）
- [x] 异步/循环等待验证码
- [x] 释放号码
- [x] 拉黑号码

## 快速开始
1. 安装依赖：`pip install -r requirements.txt`
2. 参考 `example.py` 进行调用。

## 目录结构
- `haozhuma_client.py`: 核心客户端类
- `example.py`: 使用示例
- `constants.py`: 包含省份和运营商的代码对照表
