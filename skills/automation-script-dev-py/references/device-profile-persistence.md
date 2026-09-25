# 账号级设备指纹持久化（P2.3，旧 P33）

## 触发条件

普通签到、领取、养号、已有账号登录和会话刷新均视为长期账号养护，默认使用本模式。每个账号绑定一份从该账号实际使用的真机抓包或受信配置导入的设备档案，并在后续运行中保持不变。

只有自动化注册流程可以随机选择 UA；随机值必须在单次注册流程开始时确定并在该流程的请求、重试和重定向中固定。一次性无账号任务、明确要求每次启动新设备的测试，以及目标服务不读取设备身份时可以不启用本模式。

## 不变量

- 每个账号只有一个活动档案；首次从真实设备采集结果导入，后续加载。缺少档案时明确失败，不得用随机生成值顶替。
- 优先用稳定、非敏感的账号 ID 建索引。只能取得 Token 时，可使用 Token 的 SHA-256 摘要，但 Token 轮换会形成新档案。
- 索引摘要、档案和日志中都不得包含原始 Token、密码、Cookie 或代理凭据。
- `User-Agent`、`sec-ch-ua`、Android 版本、型号、Build 和设备 ID 必须来自同一档案。
- 普通签到、领取、养号、已有账号登录和会话刷新不得调用随机 UA 生成器。
- 档案写入使用同目录临时文件加 `os.replace()`；多进程写入时再加跨进程文件锁。
- 档案损坏、schema 不兼容或认证失败时停止并报告，不得静默换新设备。轮换只能由显式操作触发。

## 推荐 schema

```json
{
  "schema_version": 1,
  "created_at": "2026-07-31T12:00:00+00:00",
  "brand": "Xiaomi",
  "model": "M2102K1C",
  "build": "SKQ1.211006.001",
  "android_version": 13,
  "chrome_version": "120.0.6099.144",
  "device_id": "A_STABLE_RANDOM_IDENTIFIER"
}
```

## 核心实现

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


class DeviceProfileStore:
    REQUIRED_FIELDS = {
        "schema_version", "created_at", "brand", "model", "build",
        "android_version", "chrome_version", "device_id",
    }

    def __init__(self, root: Path, namespace: str = "default") -> None:
        self.root = root
        self.namespace = namespace
        self._write_lock = threading.Lock()

    def _path_for(self, account_key: str) -> Path:
        if not account_key:
            raise ValueError("account_key must not be empty")
        material = f"{self.namespace}\0{account_key}".encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()[:24]
        return self.root / f"{digest}.json"

    def _validate(self, profile: Mapping[str, Any]) -> None:
        missing = self.REQUIRED_FIELDS.difference(profile)
        if missing:
            raise ValueError(f"device profile missing fields: {sorted(missing)}")
        if profile["schema_version"] != 1:
            raise ValueError("unsupported device profile schema")

    def _load(self, path: Path) -> dict[str, Any]:
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot load device profile: {path.name}") from exc
        self._validate(profile)
        return profile

    def _atomic_write(self, path: Path, profile: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(profile, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load_or_import(
        self,
        account_key: str,
        importer: Callable[[], Mapping[str, Any]],
    ) -> dict[str, Any]:
        path = self._path_for(account_key)
        with self._write_lock:
            if path.exists():
                return self._load(path)
            profile = dict(importer())
            self._validate(profile)
            self._atomic_write(path, profile)
            return profile
```

`importer` 必须读取真机抓包、设备导出或受信配置，不得生成随机型号、Build、设备 ID 或 UA。`threading.Lock` 只覆盖单进程并发。多个进程可能同时初始化同一账号时，使用项目已采用的文件锁库包住 `load_or_import()`，锁文件也必须放在 `data/device_profiles/` 下，不要自行实现无限等待。

## 请求头一致性

```python
def headers_from_profile(profile: Mapping[str, Any]) -> dict[str, str]:
    major = str(profile["chrome_version"]).split(".", 1)[0]
    ua = (
        f"Mozilla/5.0 (Linux; Android {profile['android_version']}; "
        f"{profile['model']} Build/{profile['build']}; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        f"Chrome/{profile['chrome_version']} Mobile Safari/537.36"
    )
    return {
        "User-Agent": ua,
        "sec-ch-ua": (
            f'"Not;A=Brand";v="8", "Chromium";v="{major}", '
            f'"Android WebView";v="{major}"'
        ),
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
    }
```

在 Client 初始化时调用一次 `load_or_import()`，把返回档案注入 Session。不要在每次请求、每次重试、代理切换、定时任务重启或跨天签到时重新生成设备 ID 或 UA。

## 存储与轮换

- 默认目录：脚本同名项目下的 `data/device_profiles/`。
- 将真实档案目录加入 `.gitignore`，只提交脱敏的 `device_profiles.example/`（确有文档需要时）。
- Token 轮换后仍需沿用设备身份时，必须改用稳定账号 ID，或通过显式迁移把旧档案关联到新索引。
- 只有用户明确重置、目标协议确实要求新设备，或经过显式 schema 迁移时才允许轮换。
- 删除和轮换记录档案摘要、原因和时间，不记录原始账号密钥。

## 验收

1. 同一账号连续两次加载及跨天运行得到完全相同的档案和请求头。
2. 两个不同账号使用不同档案文件；`device_id` 必须与各自导入的真机档案一致，同一真机承载多个账号时允许相同。
3. 档案文件与日志中搜索不到输入 Token。
4. 模拟写入中断后不存在被当作有效档案的半截 JSON。
5. 损坏 JSON、缺字段和未知 schema 都明确失败，不自动重建。
6. 认证失败、请求重试和代理切换不会改变设备档案。
7. 普通签到路径不调用随机 UA 生成器；自动化注册路径只在流程开始时生成一次 UA。
