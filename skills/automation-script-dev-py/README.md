# automation-script-dev-py

Python 自动化脚本开发 Skill，支持青龙面板和本地运行。

## 当前版本

- 版本：`6.4.0`
- 主模式数量：13
- 子场景数量：37

## 模式组织原则

- 按功能域排列关联模式。
- 相似模式合并到编号更靠前的主模式。
- 被合并能力使用 `P主编号.序号` 标识，避免重复入口。
- 完整规则、代码示例和合并映射以 `SKILL.md` 为准。

## 主模式

| 功能域 | 主模式 |
| --- | --- |
| 代理与防封 | P1、P2 |
| 账号与授权 | P3、P4 |
| 注册与验证 | P5 |
| 网络与安全 | P6、P7 |
| 任务编排 | P8 |
| 配置与组织 | P9、P10 |
| 日志与通知 | P11、P12 |
| 阅读融合与状态 | P13 |

账号级设备档案按需读取 `references/device-profile-persistence.md`；复杂注册、邮箱/代理适配、多阶段协议、凭证巡检、批次运行和本地操作面按需读取 `references/registration-automation-patterns.md`。

开发前必须完成 `SKILL.md` 的 Pattern Coverage Gate：50 个主/子 Pattern 全部标记为 `apply`、`skip` 或 `pending`，编码前不得保留 `pending`，交付前所有 `apply` 必须有实现位置与验收证据。
