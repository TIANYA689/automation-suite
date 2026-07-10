# 知识候选记录

使用以下结构保存候选，不要求每次都创建文件；复杂或跨项目变更时应落盘。

```yaml
id: KA-YYYYMMDD-01
title: 简短命题
status: proposed
source_tasks:
  - 任务或项目路径
claim:
  condition: 可观察触发条件
  action: 具体动作
  mechanism: 为什么有效
  validation: 如何验证
evidence:
  successful_cases: 0
  failed_cases: 0
  artifacts: []
generality:
  portability: pass|partial|fail
  stability: pass|partial|fail
  actionability: pass|partial|fail
  decontextualized: pass|partial|fail
  safety: pass|partial|fail
decision:
  authority: 项目或 Skill 路径
  target_type: project-doc|skill|reference|script|asset|new-skill|memory
  rejected_details: []
scope:
  files: []
  requires_checkpoint: true
verification:
  trigger_evals: []
  output_evals: []
  commands: []
rollback: 恢复方式
```

## 状态

- `observed`：只有现象，尚未形成命题。
- `proposed`：已有命题和证据，等待路由/确认。
- `accepted`：已确认并准备实施。
- `validated`：实施并通过验证。
- `rejected`：不适合固化，保留拒绝原因。
- `deprecated`：曾有效，但条件已经变化。

## 证据质量

优先级从高到低：

1. 自动化测试或可重复命令；
2. 两个独立项目的成功/失败对照；
3. 官方规范或稳定实现机制；
4. 单次任务的可复现结果；
5. 主观偏好或未验证推断。

低质量证据可以进入项目记录，但不应直接变成全局强制规则。

