# 已排除的坑（Pitfalls）

> 这些方案已实测无效或确认不可行，**不要再试**。

## 推理性能类

| 方案 | 结果 | 原因 |
|---|---|---|
| Vega 8 核显 Vulkan offload | ❌ 跑不动 | 专用显存 496MB < 模型 18.9GB；算力墙；无独立显存无带宽增益 |
| 官方 llama.cpp 引擎 | ❌ 弃用 | ik_llama 全面 2~3.4 倍快（ADR-1） |
| ngram 投机 | ❌ 34% 接受率 | 低于 50% 红线；测试场景无素材可抄 |
| 草稿模型投机（开放任务） | ❌ -10% | 均长仅 3.4 token，CPU 上草稿 forward 开销净亏（ADR-2） |
| 草稿深度 8 | ❌ 反降 | 验证计算量翻倍盖过接受数提升 |
| 12 线程（超线程） | ❌ 负优化 | 只用 8 物理核 |
| dense 27B | ❌ 慢 3~5 倍 | 全参数激活 |
| 降量化 Q4→Q3 | ❌ 质量降 | 速度 +15~25% 不值 |
| `--mlock` | ❌ 不支持 | 该构建无此参数 |
| 虚拟内存/页面文件调优 | ❌ 无效 | 瓶颈是带宽不是缺页 |
| 满上下文 15K（Coder，16K ctx 配置） | ❌ 崩速+卡死 | 空闲内存掉到 3.5GB，mmap 模型页被系统回收，prefill 从 26 掉到 13 tok/s 且单次 >20 分钟不返回。**上限守 12K**，跑长上下文前先关 Trae/浏览器 |

## 部署运维类

| 坑 | 现象 | 规避 |
|---|---|---|
| 内存超 28GB | swap，速度 14→1~3 tok/s | 总占用 ≤ 26GB；跑模型关浏览器；SSD 持续读写=已 swap |
| 后台任务随 shell 退出被杀 | llama-server 被回收，请求 502 | 用 run_in_background 起服务，别用 `&` 挂外层 shell |
| taskkill 波及后台任务 | 杀 llama-server 时自身任务也失败 | 预期行为，忽略通知，用 health 检查确认状态 |
| Windows Python 看不到 Git Bash `/tmp` | 脚本写 /tmp 路径丢失 | 统一用 `C:/OfflineAI/.xxx` 临时路径 |
| GitHub 直连 502 | release 下载失败 | 走 `ghfast.top` 镜像前缀 |
| GitHub API 大响应被截断 | JSON 解析失败 | `-o` 落盘到 C:/OfflineAI 再解析；/tmp 不通用 |

## 模型使用类

| 坑 | 说明 |
|---|---|
| 办公模型回答偏短 | empero 蒸馏版按 8K 样本训练；且 tokenizer 效率低（同文本 2x token） |
| 办公模型直接超 16K 报错 | 长 prompt 先估算 token：办公 ≈ 字符数/1.9，Coder ≈ 字符数/4 |
| 连续负载热衰减 | Coder 单轮 14.98 → 12.96 tok/s；取 3 轮均值 |
| 冷启动 PP 低（8.6） | 首请求 warmup 干扰，不代表真实 PP |
| 给 reasoning 模型设 stop 词 | 办公模型输出 `<think>...</think>`，思考里有代码块，`"\n```\n\n"` 之类 stop 会命中思考内部 → 代码一个字都不出（实测 T3~T5 全废）。**测 reasoning 模型一律不设 stop**，靠 EOS 自然结束 |
| 模型混用选型错 | 编程正确率两者打平（5/6 vs 5/6），但办公慢 2.15x、贵 2.43x（思考税）→ 写代码用 Coder |

## 部署参数类

| 坑 | 现象 | 规避 |
|---|---|---|
| 不带 `--jinja` 启动 | `/v1/chat/completions` 带 tools 直接 **HTTP 500**（`tools param requires --jinja flag`） | 编辑器的 agent 模式（Cline/Roo/OpenCode、Continue agent）全挂。bat 两处命令已补 `--jinja`，**别再删** |
| 控制台中文乱码 | server 日志里中文变 `鐢ㄦ埛...`（UTF-8 被 GBK 误读），模型输出本身正常 | bat 已改为 `cmd /c "chcp 65001 >nul && llama-server ..."` 启动（2026-10-19），让新控制台用 UTF-8；**别改回直接 start exe** |
| `.env` 写法不对 | 键名前留空格 / 值带引号 / 值里含 `=` / 行尾有空格 → 变量读错、启动命令拆断；**换行是 LF → 整份配置读不进来**（多个键同时报缺失） | 只写 `KEY=VALUE`，注释用整行 `#`（说明写在键的上一行）；`.env` 必须与 `switch-model.bat` 同目录、**UTF-8 无 BOM + Windows(CRLF)** 换行（`.gitattributes` 已钉死）；改完看窗口顶部或日志里 `[启动] 正在启动: ...` 打印的实际命令核对 |
| 生成 token 上限 | 单次生成实测最多 ~600~1100 token 就停（`n_predict=2000` 不生效），reasoning 模型思考一长就没预算写答案 | 长代码任务拆成多轮或调小思考；别指望一次生成上千行 |

## 权限/系统类

| 坑 | 规避 |
|---|---|
| 非管理员会话改不了 Defender | 让用户在管理员 PowerShell 手动执行（已完成） |
| `Start-Process -Verb RunAs` 被安全策略拦 | 同上，走用户手动 |
| Windows sudo 被禁用 | 同上 |
