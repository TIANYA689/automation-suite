# 自动化模块文档索引

本目录是项目内 `tools/automation-modules/` 中**邮箱、接码、过验证码**三个模块的文档快照，用于主模块目录不可用时仍能检索模块说明。快照不包含源码、虚拟环境、缓存或 `备份文档`。

## 模块目录

| 分类 | 模块 | 文档 |
|---|---|---|
| 接码 | `haozhuma_sms` | `接码/haozhuma_sms/README.md` |
| 接码 | `sms_apifox` | `接码/sms_apifox/README.md` |
| 验证码 | `合规验证码挑战模块` | `过验证码/合规验证码挑战模块/README.md` |
| 验证码 | `通用验证码模块` | `过验证码/通用验证码模块/README.md`、`implementation_plan.md` |
| 邮箱 | `22do_free_receiver` | `邮箱/22do_free_receiver/README.md`、`implementation_plan.md` |
| 邮箱 | `24mail` | `邮箱/24mail/README.md` |
| 邮箱 | `linshiguge（谷歌）` | `邮箱/linshiguge（谷歌）/README.md` |
| 邮箱 | `shengqi_temp_email` | `邮箱/shengqi_temp_email/README.md` |

## 本地检索

优先读取项目内 `tools/automation-modules/` 的模块说明；该目录不可用时使用本快照。
只盘点和读取上述三个一级目录中的 `README.md` / `implementation_plan.md`，不执行模块脚本。

## 使用边界

这些模块涉及第三方邮箱、短信和验证码服务。使用前应确认目标、服务条款和授权范围；API Key、账号、密码、Token 等必须通过环境变量或 `.env` 提供，不能写入源码或文档快照。
