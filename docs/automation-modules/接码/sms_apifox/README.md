# 他信接码模块

基于 `api.my531.com` 的 Python 自动化接码实现。

## 文件列表
- `client.py`: 核心客户端类 (`TaxinClient`)。
- `main.py`: 从环境变量读取账号的集成示例。
- `requirements.txt`: 依赖清单。
- `.env.example`: 配置变量模板。

## 快速上手
1. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```
2. 复制 `.env.example` 为 `.env` 并填写账号、密码和项目 ID。
3. 运行示例:
   ```bash
   python main.py
   ```
