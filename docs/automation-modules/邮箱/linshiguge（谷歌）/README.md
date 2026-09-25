# linshiguge 临时谷歌邮箱模块

基于 `linshiguge.com` 网页解析获取临时 Gmail/Googlemail 邮箱地址，用于自动化注册或验证码接收场景。

## 环境

```bash
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 快速测试

```bash
.\venv\Scripts\python.exe linshi_guge_client.py
```

脚本会先获取一个临时邮箱地址，然后轮询收件箱等待邮件。

## 兼容说明

- 默认优先使用 `curl_cffi` 模拟浏览器指纹访问站点。
- 如果当前网络环境下 `curl_cffi` 被远端重置连接，会自动切换到标准 `requests` 会话重试。
- 邮件接收测试需要外部服务向生成的邮箱发送邮件；仅生成邮箱和拉取空收件箱可作为基础可用性检测。
