# 本地大模型推理部署（ik_llama.cpp）

Ryzen 7 5800U / 32GB / 无独显 的纯 CPU 推理方案。引擎为 Thireus fork 的 ik_llama.cpp（znver2-avx2 构建），提供 OpenAI 兼容 API 供 OpenCode 等编辑器/Agent 接入。

## 目录结构

```
C:\OfflineAI\
├── switch-model.bat    # 一键启动（唯一入口）
├── .env                # 所有可调参数（端口/路径/模型/推理参数/日志）
├── README.md           # 本文件
├── main\               # 运行主体
│   ├── ikllama\        # 引擎（llama-server.exe 及全部二进制）
│   ├── models\         # GGUF 模型权重（~37GB）
│   ├── slots\          # KV 缓存槽（重启后首轮热启动）
│   └── log_filter.py   # 控制台日志美化器（中文提示）
├── logs\               # 日志落盘（美化日志按天分文件）
└── docs\               # 文档
    ├── architecture.md # 架构决策记录 ADR（先读这个再动参数）
    ├── benchmarks.md   # 实测性能数据
    └── pitfalls.md     # 已排除的坑
```

## 改配置

**所有需要改的参数都在根目录 `.env`，不要改代码里的硬编码值。** `switch-model.bat` 和 `main/log_filter.py` 都读这一个文件。

| 想改什么 | 改哪个键 |
|---|---|
| 端口 / 监听地址 | `PORT` `HOST` |
| 装到别的盘、别的目录 | `SERVER_DIR` `MODELS_DIR` `SLOTS_DIR` `LOGS_DIR` `LOG_FILTER` `PYTHON` |
| 换模型 | `MODEL_CODER` `MODEL_OFFICE` `MMPROJ_OFFICE`（只写文件名） |
| 上下文 / 线程 / batch / KV 量化 | `CTX_SIZE` `THREADS` `BATCH` `UBATCH` `CACHE_TYPE_K` `CACHE_TYPE_V` `CRAM`（**动之前先读 `docs/architecture.md`**） |
| 日志 | `LOG_PREFIX` `LOG_MAX_MB` |
| 清端口等待秒数 | `PORT_WAIT_SEC` |

写法：每个键的上一行有一句注释说明用途；每行 `KEY=VALUE`，注释以 `#` 开头（只能整行）。值不加引号、行尾不留空格、键名前不留空格。**换行必须 Windows(CRLF)、编码 UTF-8 无 BOM** —— cmd 的 `for /f` 只认 CRLF，存成 LF 会让整份配置读不进来（`.gitattributes` 已把 `.env`/`*.bat` 钉成 CRLF）。环境变量同名时优先于 `.env`（`LOG_FILTER_DIR` 可单独覆盖日志落盘目录，测试用）。
配错不会静默失败：启动前会体检 `PYTHON`、引擎、美化器、所选模型文件，缺哪个直接报 `[error]` 并停住等按键；多个键一起报缺失时会提示换行格式问题。

## 快速开始

1. 关浏览器（省内存），运行 `switch-model.bat`：
   - 按 **1** = Coder（Qwen3-Coder-30B-A3B Q4_K_M）→ 写/改代码、tool-calling、Agent
   - 按 **2** = Office（Qwen3.8-35B-A3B Q3_K_M + mmproj）→ 读长文、问答、看图（支持视觉）
2. 等控制台出现绿色提示 **"[就绪] 模型加载完成，现在可以使用了!"**
3. 对接地址（OpenAI 兼容）：`http://127.0.0.1:9527/v1/chat/completions`
   - 浏览器状态页：`http://127.0.0.1:9527`
   - 端口固定 9527；bat 启动前先杀 llama-server 并清空占用该端口的进程，端口被占则自动等待/中止
   - 已开 `--jinja`，支持 `tools` 参数（agent 模式可用）

## 选型速查

| 场景 | 模型 | 原因 |
|---|---|---|
| 写/改代码、补全、Agent | Coder（按 1） | 无思考税，快 2.15x、省 2.4x token |
| 读长文档、问答、总结、看图 | Office（按 2） | 长上下文 TG 快 71~82%，支持视觉 |

- 上下文 16K 配置 / **12K 实用**（15K 会崩速卡死）
- 上下文预计 > 4K 时优先 Office；长上下文看**原文长度**（Office tokenizer 效率约 Coder 一半）
- 投机解码默认关（开放任务 -10%）

## 日志说明

- **控制台**：经 `main/log_filter.py` 美化，格式 `[时间] [标签] 中文消息`
  - `[提示]` 启动四步走（读模型→载内存→预热→就绪）
  - `[就绪]` 加载完成 + 对接地址
  - `[API]` / `[Perf]` / `[缓存]` 每次请求结果与耗时
  - `[错误]` HTTP 4xx/5xx 及 error/failed 行，排查先看这里
- **落盘（`logs/`）**：
  - `llama-YYYY-MM-DD.log` — `log_filter.py` 美化后的日志，内容与控制台一致
    - 每天一个新文件；单个文件写满 **5MB** 自动新开 `llama-YYYY-MM-DD_1.log`、`_2.log`…
    - 同一天重复启动会接着当天最后一个没写满的文件追加，不覆盖
    - 进程一直跑过午夜会自动切到新一天的文件

## 维护纪律

1. 动 bat / 启动参数前先读 `docs/architecture.md`（ADR-1~15）
2. 只有实测结论能写进文档；矛盾时以实测为准并同步更新
3. 任务收尾把新决策/新坑 write-back 到 `docs/`
4. 引擎二进制不要删（`main/ikllama/` 里的 bench/cli 等工具各有用处）
5. 文档只留当前生效的结论；调试/迭代过程（v2/v3 演进、脚本复现步骤）不写入
