# 本地大模型推理部署（ik_llama.cpp）

Ryzen 7 5800U / 32GB / 无独显 的纯 CPU 推理方案。引擎为 Thireus fork 的 ik_llama.cpp（znver2-avx2 构建），提供 OpenAI 兼容 API 供 OpenCode 等编辑器/Agent 接入。

> 2026-10-22 定版汇总（原 benchmarks / architecture / pitfalls / 3x3-test / hardware 五份 + 根 README 合并为本文）。只保留当前生效结论，测试过程与历史迭代不保留。
> **现役模型**：Coder-30B-A3B Q4_K_M（按 1：写/改代码、补全、tool-calling、Agent）+ Ling-mini-2.0 Q4_K_M（按 2：读长文、问答、总结、改写）。
> 所有数字均在现行 `.env` 配置下实机测得（3 轮取均值，热衰减 ±10%，对比看相对值）。

## 目录结构

```
C:\OfflineAI\
├── switch-model.bat    # 一键启动（唯一入口）
├── .env                # 所有可调参数（端口/路径/模型/推理参数/日志）
├── README.md           # 本文件（定版汇总：数据 + 红线 + 复测方法）
├── main\               # 运行主体
│   ├── ikllama\        # 引擎（llama-server.exe 及全部二进制）
│   ├── models\         # GGUF 模型权重（~26.5GB：Coder-30B + Ling-mini-2.0）
│   ├── slots\          # KV 缓存槽（重启后首轮热启动）
│   └── log_filter.py   # 控制台日志美化器（中文提示）
└── logs\               # 日志落盘（美化日志按天分文件）
```

## 快速开始

1. 关浏览器（省内存），运行 `switch-model.bat`：
   - 按 **1** = Coder（Qwen3-Coder-30B-A3B Q4_K_M）→ 写/改代码、tool-calling、Agent
   - 按 **2** = Office（Ling-mini-2.0 Q4_K_M，纯文本）→ 读长文、问答、总结、改写
2. 等控制台出现绿色提示 **"[就绪] 模型加载完成，现在可以使用了!"**
3. 对接地址（OpenAI 兼容）：`http://127.0.0.1:9527/v1/chat/completions`
   - 浏览器状态页：`http://127.0.0.1:9527`
   - 端口固定 9527；bat 启动前先杀 llama-server 并清空占用该端口的进程，端口被占则自动等待/中止
   - 已开 `--jinja`，支持 `tools` 参数（agent 模式可用）

## 改配置

**所有需要改的参数都在根目录 `.env`，不要改代码里的硬编码值。** `switch-model.bat` 和 `main/log_filter.py` 都读这一个文件。

| 想改什么 | 改哪个键 |
|---|---|
| 端口 / 监听地址 | `PORT` `HOST` |
| 装到别的盘、别的目录 | `SERVER_DIR` `MODELS_DIR` `SLOTS_DIR` `LOGS_DIR` `LOG_FILTER` `PYTHON` |
| 换模型 | `MODEL_CODER` `MODEL_OFFICE` `MMPROJ_OFFICE`（只写文件名） |
| 上下文 / 线程 / batch / KV 量化 | `CTX_SIZE` `THREADS` `BATCH` `UBATCH` `CACHE_TYPE_K` `CACHE_TYPE_V` `CRAM` |
| 日志 | `LOG_PREFIX` `LOG_MAX_MB` |
| 清端口等待秒数 | `PORT_WAIT_SEC` |

写法：每个键的上一行有一句注释说明用途；每行 `KEY=VALUE`，注释以 `#` 开头（只能整行）。值不加引号、行尾不留空格、键名前不留空格。**换行必须 Windows(CRLF)、编码 UTF-8 无 BOM** —— cmd 的 `for /f` 只认 CRLF，存成 LF 会让整份配置读不进来（`.gitattributes` 已把 `.env`/`*.bat` 钉成 CRLF）。环境变量同名时优先于 `.env`（`LOG_FILTER_DIR` 可单独覆盖日志落盘目录，测试用）。
配错不会静默失败：启动前会体检 `PYTHON`、引擎、美化器、所选模型文件，缺哪个直接报 `[error]` 并停住等按键；多个键一起报缺失时会提示换行格式问题。

## 选型速查

| 场景 | 模型 | 原因 |
|---|---|---|
| 写/改代码、补全、Agent | Coder（按 1） | 无思考税，编程正确率 5/6 |
| 读长文档、问答、总结、改写 | Office（按 2 = Ling-mini-2.0） | 比 Coder 快 2.3~3.6x、无思考税；纯文本无视觉 |

- 上下文 16K 配置 / **12K 实用**（15K 会崩速卡死）；上下文预计 > 4K 的纯文本任务优先 Office，长 prompt 先估算 token 数
- 任务复杂度（简单/中等/复杂）对 TG 无实质影响（±5% 内噪声）——选模型只看上下文长度和任务类型，不看难度
- 投机解码默认关（开放任务 -10%）

## 机器与硬红线

- HP 战66 四代 / Ryzen 7 5800U 8C16T / 2×16GB DDR4-3200 / Vega 8 核显 496MB（无独显）/ 512GB NVMe / Win11
- **内存总占用 ≤ 26GB**，跑模型前关浏览器（超了会 swap，速度 14→1~3 tok/s）
- **满上下文守 12K**（15K 触发内存页回收，崩速卡死）
- 有效带宽 ~27GB/s ≈ DDR4-3200 双通道理论峰值 53%——CPU 方案已近物理极限，质变需 NVIDIA 独显或云 GPU

## 实测数据

### 引擎

ik_llama build 5481（znver2-avx2）vs 官方 llama.cpp：冷 PP **3.4x**、TG@4K **2.1x**、短 TG +16%。官方版已弃用；ik 参数语法 `-ctk/-ctv`，无 `--swa-full`/`--cache-reuse`。

### 缓存

- prompt 缓存命中：二次请求 19s → 73ms（`prompt_n=1`）
- slot 存盘：4K save 111ms / 205MB，restore 55ms，重启后第一轮即热
- ⚠️ prompt 缓存按 **4096 token 分段**复用：13K 上下文每请求重算 ~9K——agent 多轮长上下文每轮 prefill 5~6 分钟，**当前最大痛点**，靠上下文控制缓解

### 3×3 速度矩阵（TG tok/s；测法见「换模型复测」）

| 上文档位 | Coder TG | Ling-mini TG | Coder PP(冷) | Ling-mini PP(冷) |
|---|---|---|---|---|
| short ~1.5-3K | 13.67 | 29.7~33.8 | 68.5 | 148~171 |
| mid ~8K | 7.51 | 26.3~27.0 | 25.8 | 117~119 |
| full ~12K | 6.83 | 22.8 | 26.1 | 97~98 |

- Ling-mini 快 **2.3~3.6x（TG）/ 3.7x（PP）**；12K 冷 prefill 从 8.4 分钟降到 ~2 分钟
- 衰减：Ling-mini **-32%** vs Coder **-50%**；内存 ~10.5GB vs 18.5GB
- 调参结论：T8/b2048/ub512（= 现行 .env）即最优，ub256/T6/T10/b4096ub1024 全部更差

### 编程/Agent 质量（temp=0、pass@1、6 题自动判分）

| | Coder | Ling-mini |
|---|---|---|
| 正确率 | **5/6** | **2/6** |
| tool-calling 两轮闭环 | PASS | PASS |

Ling-mini 四个 FAIL：`+86` 前缀丢首位、正则方括号转义写成 `$$`、`nonlocal` 作用域错、合并只 append 不替换。结论：**Ling-mini 只配纯文本；写代码/Agent 一律 Coder**。

### 元数据

- 估 token 防超限：办公类 ≈ 字符/1.9，Coder 类 ≈ 字符/4；超 16K 直接报错
- Ling-mini 下载走 ModelScope（稳定 9MB/s；hf-mirror 波动 0.3MB/s），bartowski 仓库文件名带 `inclusionAI_` 前缀
- 单次生成上限 ~600~1100 token（`n_predict=2000` 不生效），长代码任务拆多轮

## 决策红线（当前生效）

**引擎与参数**

- 引擎 ik_llama（官方弃用）；启动参数 `--ctx-size 16384 -ctk q8_0 -ctv q8_0 -cram 2048 --jinja --slot-save-path C:\OfflineAI\main\slots`
- **`--jinja` 不能省**——缺了带 `tools` 的请求直接 HTTP 500
- 8 物理线程（写 12 超线程负优化）；投机解码默认关（仅改写类 +16%；草稿模型已删，启用时重新下载 Qwen3-0.6B 并加 `--spec-type draft-simple`）
- reasoning 模型不设 stop 词（stop 会命中思考内部的代码块，输出全废）

**运维**

- 目录：引擎 `main/ikllama/`、模型 `main/models/`、槽 `main/slots/`
- Defender 已对引擎/模型目录加排除（实时扫描会造成卡顿）
- 后台服务用持久后台任务起，别用 shell `&` 挂（随会话回收）；taskkill 杀 llama-server 会波及同 shell 任务，属预期；脚本临时文件用 `C:/OfflineAI/.xxx`，别用 `/tmp`（Windows Python 看不到 Git Bash 的 /tmp）；GitHub 直连 502，走镜像前缀

**选型**

- 写/改代码、补全、Agent → Coder（按 1）；读长文、问答、总结、改写 → Ling-mini（按 2）
- 视觉能力已放弃（核显 offload 不可行 + 无多模态模型）

**不要再试（已实测排除）**

- Vega 8 核显 offload（显存 < 模型，无带宽增益）；官方 llama.cpp；ngram 投机（34% 接受率低于红线）；草稿模型投机跑开放任务（-10%）；草稿深度 8（验证开销反噬）；12 线程；dense 大模型（每 token 读全权重，慢 1.4~3.3x）；Q4→Q3 降量化（质量降不值）；`--mlock`（构建不支持）；页面文件调优（瓶颈是带宽不是缺页）
- 已淘汰：办公-35B（思考税 token 2.43x/耗时 2.15x，长上下文位已被 Ling-mini 接管）；Qwen3.5-9B 密集（全面慢，优势仅内存 7GB）；Aider 本地 agent（本地 PP 太低，注入压到 1.6K 首轮 ~1 分钟是可用边界）

## 换模型复测（3×3 方法）

**是什么**：三档上下文（short ~1.5K / mid ~8K / full ~12K）× 三档任务（简单/中等/复杂）。每格两轮：R1 冷启动（计 PP 冷 + TG）、R2 同 prompt 重发（缓存命中，纯 TG）。满档定 12K 不是 15K；素材用**真实记忆层内容**（AGENTS.md + README + 一段代码），不用编造文本——测的是挂记忆后的真实形态。

**纪律**：关浏览器、内存 ≤26GB；每档 3 任务取均值；统一 `n_predict=300 / temp=0 / top_k=1`；对比只看相对值。

**判读**（基线见「实测数据」）：TG full ≥ 6.83 → 长上下文速度合格；衰减 3K→12K 超 -50% → 只配短上下文；替换 Coder 需补 6 题判分 ≥ 5/6 + tool-calling PASS；替换 Ling-mini 门槛为速度快 + 无思考税；内存峰值 > 18.5GB 基本无缘；12K 冷 prefill ≈ 12000÷PP，> 5 分钟则长文场景不可用。

**步骤**：GGUF 放 `main/models/` → `.env` 的 `MODEL_OFFICE` 指向它 → `switch-model.bat` 启动 → 跑下面的 `bench_3x3.py`（存为 `main/bench_3x3.py`）→ 数据写回本文「实测数据」。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_3x3.py - 3x3 速度矩阵：三档上下文 x 三档任务 x (R1 冷启动 + R2 缓存命中)
用法: python main\bench_3x3.py [--filler x.md] [--cpt 1.9]   # 在 C:\OfflineAI 下运行
"""
import argparse, glob, json, os, urllib.request

DEFAULT_URL = "http://127.0.0.1:9527/v1/completions"
N_PREDICT = 300
TIERS = [("short", 1500), ("mid", 8000), ("full", 12000)]
TASKS = ["simple", "medium", "complex"]
QUESTIONS = {
    "simple":  "用一句话概括下面资料的主题。",
    "medium":  "列出资料中提到的三个关键约束，各用一句话说明理由。",
    "complex": "假设要按这份资料在本机搭建一套本地推理环境，写出分步计划，并指出每步最容易踩的坑。",
}

def load_filler(path):
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    parts = []
    for p in ["AGENTS.md", "README.md"] + sorted(glob.glob("*.md")):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                parts.append(f.read())
    return "\n\n".join(parts)

def complete(opener, url, prompt):
    body = json.dumps({
        "prompt": prompt, "n_predict": N_PREDICT,
        "temperature": 0.0, "top_k": 1, "cache_prompt": True,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=7200) as r:
        d = json.load(r)
    t = d.get("timings", {})
    return t.get("prompt_n", 0), t.get("prompt_per_second", 0.0), t.get("predicted_per_second", 0.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--filler", default=None, help="上下文填充素材（默认 AGENTS.md + README）")
    ap.add_argument("--cpt", type=float, default=4.0, help="字符/token 估算比：Coder 类 ~4，办公类 ~1.9")
    a = ap.parse_args()
    filler = load_filler(a.filler)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过本机 HTTP_PROXY

    print("| 上文档位 | 任务 | prompt_n | PP(冷) | TG R1 | TG R2(缓存命中) |")
    print("|---|---|---|---|---|---|")
    for tier, tok in TIERS:
        ctx = filler[: int(tok * a.cpt)]
        for task in TASKS:
            prompt = QUESTIONS[task] + "\n\n资料如下：\n" + ctx
            pn, pp, tg1 = complete(opener, a.url, prompt)   # R1 冷启动：计量 PP
            _, _, tg2 = complete(opener, a.url, prompt)     # R2 同 prompt：缓存命中，纯 TG
            print(f"| {tier} ~{tok // 1000}K | {task} | {pn} | {pp:.1f} | {tg1:.2f} | {tg2:.2f} |")

if __name__ == "__main__":
    main()
```

**要点**：`cache_prompt=True` 两轮都传——R1 是该 prompt 首次出现仍是全额 prefill（真冷数据），R2 命中缓存；`--cpt` 按 tokenizer 效率调（Coder 类 ~4、办公类 ~1.9），不调 12K 档会灌进 24K token 直接报错；换模型重启后第一遍是冷数据。

**常见异常**：R2 没命中（prompt_n 仍≈全量）→ 用 R1 的 TG（实测两轮一致）；连本机 502/代理错 → 脚本已绕过代理，用别的客户端设 `NO_PROXY=127.0.0.1,localhost`；速度骤降 → 内存在 swap，关浏览器重测。

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

1. 动 bat / 启动参数前先读本文「决策红线」和「实测数据」
2. 只有实测结论能写进本文档；矛盾时以实测为准并同步更新
3. 任务收尾把新决策/新坑 write-back 到本 README
4. 引擎二进制不要删（`main/ikllama/` 里的 bench/cli 等工具各有用处）
5. 文档只留当前生效的结论；调试/迭代过程（v2/v3 演进、脚本复现步骤）不写入
