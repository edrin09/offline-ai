# -*- coding: utf-8 -*-
"""
llama-server 日志美化器（中文版）

两种用法:
  1. 包裹模式: python log_filter.py llama-server.exe -m model.gguf ...
     -> 启动子进程, 过滤并格式化其输出
  2. 管道模式: some_log_source | python log_filter.py
     -> 直接过滤 stdin (方便测试)

美化后的内容除了打控制台, 同时落盘到 logs/ 目录:
  - 按天分文件:   logs/llama-2026-10-19.log
  - 单文件超 5MB: logs/llama-2026-10-19_1.log、_2.log ... 依次新开
  - 可用环境变量 LOG_FILTER_DIR 指定别的目录 (测试用)

可调项统一从仓库根的 .env 读取 (键: PORT / LOGS_DIR / LOG_PREFIX / LOG_MAX_MB),
环境变量优先级高于 .env; .env 缺失时用下面的兜底默认值。
"""
import os
import sys
import re
import subprocess
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # main/
ENV_FILE = os.environ.get("ENV_FILE") or os.path.join(BASE_DIR, "..", ".env")


def load_env_file(path=ENV_FILE):
    """读极简 .env (KEY=VALUE, # 注释), 只填空缺项 —— 已有环境变量优先。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            lines = fh.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            os.environ.setdefault(key, val)


load_env_file()

# 服务端口: 优先从命令行 --port/-p 取, 取不到用默认值
DEFAULT_PORT = os.environ.get("PORT", "9527")
PORT = DEFAULT_PORT


def port_from_argv(argv):
    for i, a in enumerate(argv[:-1]):
        if a in ("--port", "-p"):
            return argv[i + 1]
    return DEFAULT_PORT

# ---- 噪音行: 直接丢弃 ----
DROP = re.compile(
    r"kv cache rm"
    r"|create_check"
    r"|erased invalidated"
    r"|slot released"
    r"|slot print_timing"
    r"|all slots are idle"
    r"|slot break"
    r"|^\s*cache :"
    r"|^\s*prompt:"
    r"|<\|im_start\|>"
    r"|n_past ="
    r"|batch_pending_prompt"
    r"|log_server_request.*path=\"/health\""
    r"|print_info:"
    r"|llm_load_print_meta"
    r"|system_info:"
    r"|srv\s+init:"
    r"|chat_template"
    r"|get_model:"
    r"|warmup: "
)

# ---- API 请求行: 提取 status/method/path ----
REQ = re.compile(
    r'log_server_request.*?status=(\d+)\s+method="(\w+)"\s+path="([^"]+)"'
)

# ---- KV 缓存命中恢复（对接 slot-save-path）----
RESTORE = re.compile(
    r"restored context checkpoint took\s+([\d.]+) ms.*?n_tokens = (\d+)")

# ---- 启动阶段提示: (匹配行, 提示语), 提示只打一次, 命中后原始行不再透传 ----
READY = re.compile(r"server is listening")
PHASES = [
    (re.compile(r"llama_model_loader"), "启动 1/3 正在读取模型文件..."),
    (re.compile(r"load_tensors"), "启动 2/3 正在把模型载入内存（十几 GB，预计 10~30 秒）..."),
    (re.compile(r"warming up|warmup"), "启动 3/3 正在预热（空跑一次，几秒钟）..."),
]

# ---- 计时行的中文翻译 ----
PP_TIME = re.compile(
    r"prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens.*?([\d.]+) tokens per second")
TG_TIME = re.compile(
    r"eval time =\s*([\d.]+) ms /\s*(\d+) tokens.*?([\d.]+) tokens per second")
TOTAL_TIME = re.compile(r"total time =\s*([\d.]+) ms")

# ---- 错误行: 尽量都标出来 ----
ERROR = re.compile(r"(?i)\b(error|exception|fatal|failed)\b")

SEP = "=================================================="

def _log_dir():
    """落盘目录: 测试用 LOG_FILTER_DIR > .env 的 LOGS_DIR > <仓库根>/logs"""
    for key in ("LOG_FILTER_DIR", "LOGS_DIR"):
        val = os.environ.get(key)
        if val:
            return val
    return os.path.join(BASE_DIR, "..", "logs")


def _max_bytes():
    """单个日志文件上限, 单位 MB; 取不到或非法就退回 5MB。"""
    try:
        mb = float(os.environ.get("LOG_MAX_MB", "5"))
    except ValueError:
        mb = 5.0
    return int(mb * 1024 * 1024) if mb > 0 else 5 * 1024 * 1024


# ---- 日志落盘: 按天 + 按大小滚动 ----
LOG_DIR = os.path.abspath(_log_dir())
LOG_PREFIX = os.environ.get("LOG_PREFIX", "llama")
LOG_MAX_BYTES = _max_bytes()


class DailyLog:
    """按天 + 按大小滚动的日志写入器。

    - 每天一个文件:        llama-2026-10-19.log
    - 当天超过 5MB:        llama-2026-10-19_1.log、llama-2026-10-19_2.log ...
    - 同一天重启脚本:      接着当天最后一个没写满的文件继续追加
    - 进程跑过午夜(跨天):  自动切到新一天的文件
    - 写盘失败(权限/磁盘):  标记 disabled, 只打控制台, 不让美化器崩掉
    """

    def __init__(self, log_dir=LOG_DIR, prefix=LOG_PREFIX, max_bytes=LOG_MAX_BYTES):
        self.log_dir = log_dir
        self.prefix = prefix
        self.max_bytes = max_bytes
        self.day = None
        self.seq = 0
        self.path = None
        self.fh = None
        self.size = 0
        self.disabled = False

    @staticmethod
    def _today():
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def _path_for(self, day, seq):
        # 序号用 "_" 而不是 "."，这样按文件名排序时 0 号文件（无后缀）永远排最前
        name = f"{self.prefix}-{day}.log" if seq == 0 else f"{self.prefix}-{day}_{seq}.log"
        return os.path.join(self.log_dir, name)

    def _open_for_day(self, day):
        """打开当天最后一个还没写满的文件; 当天文件都满了就新建下一个。"""
        seq = 0
        while (os.path.exists(self._path_for(day, seq))
               and os.path.getsize(self._path_for(day, seq)) >= self.max_bytes):
            seq += 1
        self._switch(day, seq, append=os.path.exists(self._path_for(day, seq)))

    def _switch(self, day, seq, append):
        if self.fh:
            self.fh.close()
        path = self._path_for(day, seq)
        self.fh = open(path, "a" if append else "w", encoding="utf-8", errors="replace")
        self.path = path
        self.day = day
        self.seq = seq
        self.size = os.path.getsize(path) if append else 0

    def prepare(self):
        """提前建目录+开文件, 好让启动信息能报出日志路径。"""
        if self.disabled or self.fh:
            return self.path
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self._open_for_day(self._today())
        except OSError:
            self.disabled = True
        return self.path

    def write(self, text):
        if self.disabled:
            return
        self.prepare()
        if self.disabled:
            return
        day = self._today()
        try:
            if day != self.day or self.size >= self.max_bytes:
                # 两种情况都交给 _open_for_day: 跨天换新一天的文件,
                # 或当前文件写满 5MB -> 跳过已满的, 落到当天下一个文件上
                self._open_for_day(day)
            data = text + "\n"
            self.fh.write(data)
            self.fh.flush()
            self.size += len(data.encode("utf-8", "replace"))
        except OSError:
            self.disabled = True


LOG = DailyLog()


def ts():
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def emit(text):
    """同时输出到控制台和日志文件。"""
    print(text, flush=True)
    LOG.write(text)


def out(tag, msg, sep=False):
    if sep:
        emit(f"{ts()} {SEP}")
    emit(f"{ts()} [{tag}] {msg}")


def announce_logfile():
    if LOG.path:
        out("日志", f"美化日志按天落盘: {LOG.path}（单个文件超 5MB 自动开新文件）")
    else:
        out("日志", "日志文件不可写, 本次只输出到控制台")


def banner_ready():
    t = ts()
    emit(f"{t} {SEP}")
    emit(f"{t} [就绪] 模型加载完成，现在可以使用了!")
    emit(f"{t} [就绪] 对接地址 (OpenAI 兼容): http://127.0.0.1:{PORT}/v1/chat/completions")
    emit(f"{t} [就绪] 模型状态页(浏览器打开): http://127.0.0.1:{PORT}")
    emit(f"{t} {SEP}")


def process(stream):
    fired = set()
    ready = False
    for raw in stream:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        # KV 缓存命中（先于噪音过滤, 该行含 "n_past =" 会被误杀）
        m = RESTORE.search(line)
        if m:
            ms, n = m.groups()
            out("缓存", f"命中本地 KV 缓存: 直接恢复 {n} tokens（{ms}ms），这部分不用重新计算")
            continue
        if DROP.search(line):
            continue
        # 服务就绪 -> 大横幅（只打一次）
        if READY.search(line):
            if not ready:
                ready = True
                banner_ready()
            continue
        # 启动阶段提示（只提示一次，原始行吞掉）
        hit_phase = False
        for pat, hint in PHASES:
            if pat.search(line):
                hit_phase = True
                if pat.pattern not in fired:
                    fired.add(pat.pattern)
                    out("提示", hint, sep=True)
                break
        if hit_phase:
            continue
        m = REQ.search(line)
        if m:
            status, method, path = m.groups()
            if status.startswith(("4", "5")):
                out("错误", f"请求失败: {method} {path} -> HTTP {status}（看下面 [错误] 行的详情）", sep=True)
            else:
                out("API", f"请求完成: {method} {path} -> {status}", sep=True)
            continue
        # 计时行翻译成中文
        m = PP_TIME.search(line)
        if m:
            ms, n, tps = m.groups()
            out("Perf", f"读上下文: {n} tokens / {float(ms)/1000:.2f}s -> {tps} tok/s")
            continue
        m = TG_TIME.search(line)
        if m:
            ms, n, tps = m.groups()
            out("Perf", f"生成: {n} tokens / {float(ms)/1000:.2f}s -> {tps} tok/s")
            continue
        m = TOTAL_TIME.search(line)
        if m:
            out("Perf", f"本轮总耗时: {float(m.group(1))/1000:.2f}s")
            continue
        # 兜底: 错误行标红性提示, 其余原文透传
        if ERROR.search(line):
            out("错误", line.strip())
        else:
            out("llama", line.strip())


def main():
    global PORT
    argv = sys.argv[1:]
    PORT = port_from_argv(argv)
    LOG.prepare()
    if argv:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        announce_logfile()
        out("启动", "正在启动: " + " ".join(argv), sep=True)
        try:
            process(proc.stdout)
        except KeyboardInterrupt:
            pass
        finally:
            proc.terminate()
            sys.exit(proc.wait())
    else:
        # 管道模式
        announce_logfile()
        process(sys.stdin)


if __name__ == "__main__":
    main()
