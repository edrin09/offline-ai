# 本地模型部署 — 记忆索引

> 每轮常驻，控制在 1K token 内。细节按需 Read `docs/`。

## 硬约束

- Ryzen 7 5800U / 32GB DDR4 / **无独显**（核显已实测排除）
- 内存总占用 ≤ 26GB；跑模型前关浏览器
- 上下文：16K 配置 / **12K 实用**（15K 会崩速卡死）
- 办公模型 tokenizer 效率约 Coder 一半（同文本 2x token）；长文看原文长度，不只看 token 数

## 引擎与启动

- 引擎 **ik_llama.cpp**（`main/ikllama/`，znver2-avx2）；官方 llama.cpp 已弃用（慢 2~3x）
- **可调参数全部在根 `.env`**（端口/路径/模型名/推理参数/日志），`switch-model.bat` 与 `main/log_filter.py` 同读一份；改参数只改 `.env`，不改代码
- `switch-model.bat`：按 1 = Coder，按 2 = 办公；API `http://127.0.0.1:9527/v1`（启动前自动杀进程清端口；启动前体检 .env 里指的文件是否存在）
- 参数：`--ctx-size 16384 -ctk q8_0 -ctv q8_0 -cram 2048 --jinja --slot-save-path C:\OfflineAI\main\slots`
  - **`--jinja` 不能省**，缺了带 tools 的请求直接 500
- 投机解码默认关（开放任务 -10%，仅改写类 +16%）

## 选型

- **写/改代码、补全、tool-calling、Agent → Coder（按 1）**
- **读长文、问答、总结、看图 → 办公（按 2）**
  - 正确率打平（自动判分 5/6 vs 5/6）；办公贵：token 2.43x、耗时 2.15x（思考税）
  - 长上下文办公更快：12K TG 12.45 vs 6.83（+82%），衰减平缓（-14% vs -50%）；> 4K 优先办公

## 路径（2026-10-19 重组）

引擎 `main/ikllama/llama-server.exe` ｜ 模型 `main/models/` ｜ 缓存槽 `main/slots/` ｜ 日志美化 `main/log_filter.py` ｜ 服务日志 `logs/`（`llama-YYYY-MM-DD.log` 美化版按天滚动）｜ 文档 `docs/` ｜ 配置 `.env` ｜ 根目录只留 bat + .env + README

## 按需 Read

`docs/benchmarks.md` 实测数据 ｜ `docs/architecture.md` 决策记录（ADR-1~15）｜ `docs/pitfalls.md` 已排除的坑

## 纪律

1. 动 bat / 启动参数前先读 `docs/architecture.md`
2. 只有实测结论能写进本文件和 `docs/`；矛盾时以实测为准并同步更新
3. 任务收尾或会话压缩时，新决策 / 新坑 write-back 到 `docs/`；
4. `docs/` 只留当前生效的结论——调试/迭代过程（v2/v3 演进史、脚本复现步骤）不写入
5. 每轮请求：系统+工具 2~4K + 工作区 ≤ 8K；工具输出 > 2K token 只读头尾
