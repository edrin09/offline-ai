# 架构决策记录（ADR）

> 每条决策附实测依据。新决策追加在末尾，注明日期。

## ADR-1：引擎用 ik_llama.cpp，弃官方 llama.cpp（2026-10-18）

- **背景**：官方 b11707 冷 PP 仅 13.9 tok/s（4K prompt 等 4.6 分钟），长上下文 TG 崩塌到 5.3
- **决策**：切换 Thireus fork（build 5481，znver2-avx2 构建，Zen2 专用）
- **依据**：冷 PP 3.4x、TG@4K 2.1x、短 TG +16%（详见 benchmarks.md 第一节）
- **回退**：如需换回官方版，重新下载 build 放 `main/` 并改 bat 路径
- **注意**：参数语法不同（`-ctk/-ctv` vs `--cache-type-k/v`）；ik 无 `--swa-full`/`--cache-reuse`

## ADR-2：默认不用投机解码（2026-10-18）

- **背景**：桌面文档预期草稿模型 +30~50%
- **决策**：bat 默认无投机；草稿模型文件保留备用
- **依据**：开放式编码任务实测 -10%（接受率 88% 但均长仅 3.4 token，草稿 forward 开销盖过收益）；仅改写/模板类任务 +16%
- **如未来启用**：`--spec-type draft-simple -md models\Qwen3-0.6B-Q4_0.gguf --spec-draft-n-max 5 --spec-draft-p-min 0.75`，只对改写类任务开

## ADR-3：上下文固定 16K，不加倍（2026-10-18）

- **背景**：GGUF 声明 262K，但办公模型实际 8K 训练 + tokenizer 效率低；且满上下文 TG 腰斩（6 vs 14.5）
- **决策**：`--ctx-size 16384` 固定；纯问答场景如需提速可临时降 8K
- **配套**：上下文控制纪律（AGENTS.md 第 4 条）+ 客户端压缩（见 ADR-4）

## ADR-4：上下文管理三层架构（2026-10-18）

- **背景**：16K 上限下，agent 的 system/工具定义/工具输出快速吃满；ik_llama prompt 缓存只按 4K token 分段复用，长上下文每轮 prefill 5~6 分钟
- **决策**：三层管理
  1. **常驻层**：`C:\OfflineAI\AGENTS.md`（< 2K token，硬约束+路径+索引，每轮加载）
  2. **按需层**：`docs/` 三个专题文件（需要时 Read，不预载）
  3. **会话层**：客户端自动压缩（OpenCode compaction）+ 单条工具输出截断
- **write-back 机制**：压缩/收尾时把新决策追加回 docs/——否则记忆退化，这是体系不腐烂的关键
- **待办**：OpenCode compaction 参数配置（`limit.context` + `keep.tokens 4000` + `buffer 3000` + `prune true`），注意用户实际走 15799 网关，需确认网关后端模型 ctx 后定值

## ADR-5：KV 缓存 q8_0 + slot 存盘（2026-10-18）

- **决策**：`-ctk q8_0 -ctv q8_0`（KV 读取量砍半，长上下文提速）；`--slot-save-path C:\OfflineAI\slots`（每天切模型重启后第一轮即热）
- **依据**：benchmarks.md 第五节；slot save/restore 均 < 200ms

## ADR-6：不用 GPU offload（2026-10-18）

- **依据**：Vega 8 核显专用显存 496MB/共享 15.7GB < 模型 18.9GB → 全 offload OOM；算力墙（同款核显社区实测 7B 仅 3~6 tok/s）；无独立显存带宽无增益；官方无 win x64 Vulkan 预编译包
- **结论**：ik_llama CPU 方案已接近该机物理极限（有效带宽达理论峰值 53%）；质变需换 NVIDIA 独显或云 GPU

## ADR-7：Defender 排除（2026-10-18）

- 已用 `Add-MpPreference -ExclusionPath`（管理员终端）对引擎与模型目录加排除
- 2026-10-19 重组后实际路径为 `main\`；如遇实时扫描卡顿，补加 `C:\OfflineAI\main`

## ADR-8：长上下文默认切办公模型（2026-10-18）

- **背景**：3×3 矩阵实测（benchmarks.md 第六节）发现两模型的长上下文性能不在一个量级
- **决策**：上下文预计 > 4K 时优先用**办公模型**（switch-model.bat 按 2）；Coder 只用于短上下文 + tool-calling / Agent 场景
- **依据**：
  - TG @8K：办公 12.87 vs Coder 7.51（**+71%**）；@12K：12.45 vs 6.83（**+82%**）
  - PP @8K：49.9 vs 25.8（1.9x）；12K 冷 prefill 5.7 分钟 vs 8.4 分钟
  - 衰减：办公 14.48→12.45（-14%），Coder 13.67→6.83（-50%）
- **代价**：办公模型 tokenizer 效率约为 Coder 一半（同文本 2x token），其 12K token 对应文本量约等于 Coder 的 6K——**长上下文要看原文长度而不只看 token 数**
- **补充**：任务复杂度（简单/中等/复杂）对 TG 无实质影响（±5% 内属噪声），不需要按任务难度选模型，只按上下文长度选

## ADR-9：编程任务默认 Coder，办公模型留给长文阅读（2026-10-18）

- **背景**：ADR-8 只看速度会误导——办公模型长上下文虽快，但它是 reasoning 模型，编程时产生"思考税"
- **决策**：按**任务类型**选模型，不再按上下文长度一刀切
  - 写/改代码、补全、Agent tool-calling → **Coder**（bat 按 1）
  - 读长文档、问答、总结 → **办公**（bat 按 2）
- **依据**（benchmarks.md 第八节，6 道自动判分题）：
  - 正确率打平 5/6 vs 5/6，失败点相同（都是"修改入参"这一条）
  - 成本：办公 token **2.43x**、耗时 **2.15x**
  - 根因：办公模型 `<think>` 在中等/难任务上吃 1238~2557 字符，Coder 为 0
  - 折算到 8K/12K 上下文，办公劣势缩到 1.34x/1.26x（仍未反超）
- **配套修复**：bat 两处命令加 `--jinja`——否则 `tools` 参数直接 500，所有编辑器的 agent 模式不可用

## ADR-10：不设 stop 词（2026-10-18）

- **背景**：给办公模型设 `"\n```\n\n"` 作 stop 时，编程题 T3~T5 全部输出 0 字符代码（思考过程中的代码块触发了 stop）
- **决策**：调 reasoning 模型一律不传 stop，靠 EOS / n_predict 自然结束
- **副作用**：可能多输出一段解释文本，客户端需自行剥离 `<think>` 并提取 ``` 代码块

## ADR-11：llama-server 日志走 log_filter.py 美化（2026-10-19）

- **背景**：slot checkpoint / kv cache rm / slots_idle 等内部日志刷屏，看不出每次请求的耗时
- **决策**：`switch-model.bat` 启动 llama-server 前包一层 `log_filter.py`（Python wrapper），输出 `[时间] [标签] 中文消息`
- **丢弃**：apply_checkp / create_check / kv cache rm / release_slots / slots_idle / print_timing / cache dump / print_info / llm_load_print_meta / system_info 等噪音行
- **保留**：API 请求行（含 status）、Perf 计时（译成"读上下文/生成/总耗时"）、启动阶段提示（读模型→载内存→预热→就绪，各打一次）；就绪为三行横幅（模型加载完成 + `/v1/chat/completions` + 状态页）
- **高亮**：slot 恢复行（KV 命中）在噪音过滤前识别并标 `[缓存]`；HTTP 4xx/5xx 及含 error/exception/fatal/failed 的行标 `[错误]`；未识别行以 `[llama]` 透传，不吞报错
- **落盘**：控制台内容同步写 `logs/llama-YYYY-MM-DD.log` 按天分文件，单文件满 5MB 滚动为 `_1`/`_2`…；同日重启追加不覆盖，跨午夜自动换天；每行 flush，写盘失败降级为只打控制台
- **测试**：管道模式 `xx | python log_filter.py`（可用 `LOG_FILTER_DIR` 改落盘目录）验证过滤与滚动，不用真起模型

## ADR-12：目录重组（2026-10-19）

- **决策**：根目录只留 `switch-model.bat` + `README.md`（+ IDE 注入的 AGENTS.md 与 .git 等）
  - `main/`：运行主体——ikllama 引擎、models 权重、slots 缓存槽、log_filter.py
  - `logs/`：服务日志落盘（`log_filter.py` 美化后的 `llama-YYYY-MM-DD.log`，按天滚动）
  - `docs/`：文档
- **影响**：所有路径改用 `main\` 前缀；slots 内容不受目录搬移影响；控制台过滤规则不变

## ADR-13：可调参数外置到 .env（2026-10-19）

- **背景**：端口、路径、模型文件名、推理参数全部硬编码在 `switch-model.bat` 的启动命令里，改一个端口要动整条命令
- **决策**：可调项集中到仓库根 `.env`（`KEY=VALUE`，`#` 注释）
  - `switch-model.bat`：`for /f "usebackq eol=# tokens=1,* delims=="` 逐行读入当环境变量
  - `main/log_filter.py`：`load_env_file()` 读同一文件，用 `os.environ.setdefault` 只填空缺项
- **键清单**：`SERVER_DIR` `SERVER_EXE` `MODELS_DIR` `SLOTS_DIR` `LOGS_DIR` `LOG_FILTER` `PYTHON`｜`MODEL_CODER` `MODEL_OFFICE` `MMPROJ_OFFICE`｜`HOST` `PORT` `CTX_SIZE` `THREADS` `BATCH` `UBATCH` `FLASH_ATTN` `CACHE_TYPE_K` `CACHE_TYPE_V` `CRAM`｜`PORT_WAIT_SEC` `LOG_PREFIX` `LOG_MAX_MB`
- **优先级**：环境变量 > `.env` > 代码兜底默认；`LOG_FILTER_DIR` 仍可单独覆盖落盘目录（管道模式测试用）
- **顺带加固**：启动前体检 `PYTHON`/引擎/美化器/所选模型文件，缺失即报错 + `pause`（不再开个窗口一闪而过）；路径统一加引号，路径含空格也能跑
- **行为不变**：参数值与原硬编码一一对应，端口仍固定 9527（`docs/` 里的实测数字不受影响）
- **注意**：`.env` 纳入版本管理（不含密钥）；每个键的上一行都有一句注释说明用途；键名前不要留空格、值不要加引号、值里不要放 `=`；`.env` 必须和 bat 同目录、**UTF-8 无 BOM + CRLF 换行**（cmd 的 `for /f` 只认 CRLF，LF 会让整份配置读不进来；`.gitattributes` 已把 `*.bat`/`.env` 钉成 `eol=crlf`）；键同时缺失时 bat 会直接提示换行格式问题

## ADR-14：固定端口 9527 + 启动前清端口（2026-10-19）

- **背景**：8080 是常用端口易被别家服务占用；旧实例没退干净时新实例绑不上端口，只能手工找 PID 杀
- **决策**：端口固定 **9527**（`.env` 里 `PORT=9527`，等待上限 `PORT_WAIT_SEC=15`）；`switch-model.bat` 启动前 `call :freeport` 清端口（详见 ADR-13 的 `.env` 抽离）
  - 先 `taskkill /IM %SERVER_EXE% /F`，再 `netstat -ano | findstr ":9527 " | findstr LISTENING` 取 PID 逐个 `taskkill /PID /F`（兜住 python wrapper 等其它占用者）
  - 轮询确认端口真空闲，最多等 15s；仍占用则中止并报错，避免新实例绑不上端口却看不出来
- **依据**：实测两例——端口空闲时立即通过；用 python 占住 9527 后运行，占用进程被自动杀掉、端口确认释放后才进入启动流程
- **配套**：`log_filter.py` 就绪横幅不再硬编码端口——按「命令行 `--port` > `.env` 的 `PORT` > 9527」取值，避免改端口后横幅与实际不符
- **注意**：`switch-model.bat` 必须**纯 ASCII + CRLF**。实测：bat 里写 UTF-8 中文时，切换器窗口默认 GBK(cp936) 代码页会把字节串解码错位、吞掉换行与括号，导致 cmd 把中文残片当命令执行（报一串"不是内部或外部命令"）；故 bat 提示一律英文，中文界面交给 `log_filter.py`（它自己 chcp 65001）

## ADR-15：取消 llama-server 原始日志落盘（2026-10-19）

- **背景**：bat 一直带 `--log-file logs\llama-server`，它与 `log_filter.py` 美化日志是同一条日志流的两个出口
- **实测**：同一会话原始 564 行 vs 美化 288 行——多出来的正是 ADR-11 主动丢弃的噪音（`kv cache rm` / `slot print_timing` / cache dump / `print_info` / `llm_load_print_meta`）+ `tid=`/`timestamp=` 原始字段；且该文件每次启动截断重写（整份只有 1 行 `build info`），不追加、不按天滚动
- **决策**：bat 去掉 `--log-file`（连带 `RAW_LOG` 变量），`.env` 去掉 `LOG_RAW_NAME`；`logs/` 只留 `llama-YYYY-MM-DD.log`
- **依据**：全仓无任何脚本/流程消费该文件（只有 bat 写入 + 文档提及）；它不滚动、不带时间戳前缀，作为事后证据基本无用，信息量是美化日志的超集（被丢掉的只是噪音行）
- **回退**：现场排深坑若要看被过滤的原始行，临时在启动命令后加回 `--log-file C:\OfflineAI\logs\llama-server` 即可
