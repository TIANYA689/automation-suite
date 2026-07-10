# 静态优先解包

对 Python `exec/eval` 与 JS `eval/Function` 包装，先提取 payload 并 dump，不直接执行未知载荷。

证据：记录每层 payload 长度、hash、转换链与最终输出。
