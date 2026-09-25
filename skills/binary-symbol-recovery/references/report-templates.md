# 报告模板

两个模板都是"可直接抄进报告"的形式。字段缺失时写"未获取"并说明原因，不留空。

## 符号恢复报告

```text
## Symbol Recovery Analysis: <function_address>

### Function Characteristics
- Strings:      <命中的字符串常量及地址>
- Constants:    <命中的魔数/常量表>
- Called imports: <该函数调用的已知导入>

### Cross-Reference Analysis
- Callers: <地址列表 + 调用点传参形态>
- Callees: <地址列表 + 参数如何被使用>

### Inference Result
- Suggested symbol name: <建议名称>
- Confidence: High | Medium | Low
- Reasoning: <推理链，逐步说明从证据到结论>

### Similar Open Source Implementation
- <链接或"未找到">
```

**要求**：`Reasoning` 必须能让人顺着证据独立复核。写"看起来像 MD5"不算推理。

## 结构体恢复报告

```c
/*
 * Structure Recovery Analysis
 * Source function: <func_address>
 * Analysis scope: <callers/callees 数量>
 * Functions using this struct: 0x401000(初始化) / 0x401100(字段访问) / 0x401200(析构)
 */
// Estimated size: 0x48 bytes
// Confidence: High / Medium / Low
struct suggested_name {
    /* 0x00 */ void *vtable;
    /* 0x08 */ int refcount;
    /* 0x0C */ int flags;
    /* 0x10 */ char *name;
    /* 0x18 */ void *data;
    /* 0x20 */ size_t size;
    /* 0x28 */ struct node *next;
    /* 0x30 */ struct node *prev;
    /* 0x38 */ callback_fn handler;
    /* 0x40 */ void *user_data;
};
// Field access examples:
// 0x401000: *(this + 0x08) += 1;          // refcount++
// 0x401100: printf("%s", *(this + 0x10)); // print name
```

**要求**：每个字段至少一行访问证据。没有证据的字段写 `/* 0xNN */ void *unknown_0xNN;  // 未观察到访问`。

## 证据落盘约定

产物写入 `exports/` 或 `reports/`，至少包含：

- 样本路径与 SHA-256
- 架构、位数、是否 stripped
- 使用的工具与版本
- 每个结论对应的证据位置（函数地址 / 文件行 / 导出文件名）
- 未解决的开放问题

原始样本不覆盖、不移动；分析产物落在副本与导出目录。
