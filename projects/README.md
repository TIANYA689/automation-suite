# 抓包作业区

把一份抓包变成一套可用脚本的地方。**每次作业一个目录，命名 `<日期>-<项目名>`**，里面装这次作业的全部过程与结论。

## 这里和 `cases/` 的分工

两者都是"长任务"，但对象不同，不要混：

| 目录 | 装什么 | 产出是什么 | 谁在管 |
|---|---|---|---|
| `projects/` | 一次「抓包 → 脚本」作业 | 给用户用的脚本 | 本目录的索引与模板 |
| `cases/` | 套件**自身**的维护长任务（改路由、加校验器） | 套件的改动 | `validate_case_states.py` |

## 提交边界

| 内容 | 是否提交 | 为什么 |
|---|---|---|
| `projects/README.md`（本文件，索引） | 是 | 索引本身是可复用资产 |
| `projects/_template/` | 是 | 模板进版本库才能被校验，才不会烂 |
| `projects/<日期>-<项目名>/` | **否** | 含真实抓包、真实域名、可用脚本 |

因此新克隆里各作业目录**不存在**，索引里的链接会失效——这是设计如此，不是坏链。

**那知识怎么累积？** 靠回流，不靠堆作业：

- 流程性的 → `kb/<领域>/techniques/*.md`（并在同目录 `kb-index.json` 加信号）
- 零散的坑 → `kb/ai-findings/findings.jsonl`
- 反复出现的做法 → 升级成技能或技能里的 reference

这三处都是提交的。`job.json` 的 `knowledge_returned` 记的就是回流清单——**它为空说明这个作业白做了**。

## 新建一个作业

```bash
# 从模板建 projects/<今天>-<slug>/
python scripts/misc/new_project.py avalon-signin --goal "从抓包生成签到脚本"
# 指定日期、只看不写
python scripts/misc/new_project.py avalon-signin --date 20260925 --dry-run
```

建完照 `_template/README.md` 的顺序填：抓包 → 目标 → 端点取舍 → 结论 → 待人工完成 → 授权边界。

## 校验与重建索引

```bash
python scripts/misc/check_projects.py                   # 校验作业与索引是否一致
python scripts/misc/check_projects.py --rebuild-index   # 重建下面的表
```

索引表是**派生产物**，源头是各作业的 `job.json`。改作业只改 `job.json`，然后重建索引——
和路由层「只改 `routing.source.json`，再重建索引」是同一个约定。

## 作业索引

<!-- BEGIN: projects-index -->
| 日期 | 项目 | 目标 | 抓包 | 状态 | 知识回流 |
|---|---|---|---|---|---|
| 2026-09-25 | `20260925-avalon-signin` | 从抓包生成阿瓦隆签到脚本：令牌长期有效、无签名参数，脚本不需要登录流程 | 2 份 / 160 条 / 34 端点 | CONTINUE | 3 项 |
| 2026-09-25 | `20260925-avalon-register-login` | 从抓包生成阿瓦隆注册与登录脚本：注册需邮箱验证码与 reCAPTCHA 令牌，登录返回长期 Authorization，补全「注册 → 登录 → 签到」链 | 2 份 / 160 条 / 37 端点 | CONTINUE | 22 项 |
<!-- END: projects-index -->
