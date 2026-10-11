# 外部来源与知识库审计

当任务涉及 GitHub 调研、上游吸收、知识库优化或来源追溯时，先把来源记录成可复查的证据，再决定是否固化为知识。

## 最小来源记录

每个外部来源至少记录：公开 URL、固定 commit/tag、SPDX license、复核日期、吸收范围和明确剔除范围。只记默认分支或仓库名不足以复现当时的依据。

## 离线优先

默认只做 manifest schema、重复 ID、URL 形态、revision 占位符、许可证 allowlist 和日期格式校验。需要查询远程状态时单独显式执行网络检查，不让 CI 因 GitHub API、网络或 token 不可用而改变基础门禁结果。

## 知识落点

- 一次性来源、版本和许可证事实留在项目文档或来源 manifest。
- 跨项目可迁移的判据进入本篇或同领域 technique，并在 `kb-index.json` 登记用户会说的触发信号。
- 没有第二个独立场景验证的结论保留为观察项，不升级为全局规则。
- 只吸收测量、记录、对照、验证和回滚方法；不复制外部实现，也不吸收绕过安全或访问控制的操作。

## 验收

运行 `python scripts/misc/check_upstream_sources.py`、`python scripts/misc/check_index.py`、`python scripts/misc/check_doc_refs.py` 和 `python scripts/misc/ai_finding.py validate`。报告应同时说明未验证的网络状态和来源范围。
