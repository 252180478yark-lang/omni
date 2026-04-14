"""追更 knowledge-engine 日志并写入 E:\\agent\\测试日志（快照 + 实时）。"""
from __future__ import annotations

import time
from pathlib import Path

DEST_DIR = Path(r"E:\agent\测试日志")
ERR_LOG = Path(r"E:\agent\omni\.dev-logs\knowledge-engine.log.err")
OUT_LOG = Path(r"E:\agent\omni\.dev-logs\knowledge-engine.log")
POLL_SEC = 0.4
TAIL_LINES = 600


def _tail_lines(path: Path, label: str, n: int) -> list[str]:
    if not path.exists():
        return [f"[{label}] (文件不存在) {path}"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"[{label}] 读取失败: {e}"]
    lines = text.splitlines()
    out = lines[-n:] if len(lines) > n else lines
    return [f"[{label}] {line}" for line in out]


def main() -> None:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = DEST_DIR / f"knowledge-harvest-{stamp}.log"
    (DEST_DIR / "latest-harvest-log.txt").write_text(str(dest), encoding="utf-8")
    (DEST_DIR / "monitor-python.pid").write_text(str(__import__("os").getpid()), encoding="utf-8")

    header = (
        f"========== Omni 知识采集监控 (Python) ==========\n"
        f"开始: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"输出: {dest}\n"
        f"stderr: {ERR_LOG}\n"
        f"stdout: {OUT_LOG}\n"
        f"===============================================\n\n"
    )
    dest.write_text(header, encoding="utf-8")

    with dest.open("a", encoding="utf-8") as w:
        w.write("--- 快照 stdout (末行) ---\n")
        for line in _tail_lines(OUT_LOG, "stdout", TAIL_LINES):
            w.write(line + "\n")
        w.write("\n--- 快照 stderr (末行) ---\n")
        for line in _tail_lines(ERR_LOG, "stderr", TAIL_LINES):
            w.write(line + "\n")
        w.write("\n--- 实时 stderr (轮询追加) ---\n")
        w.flush()

    pos = ERR_LOG.stat().st_size if ERR_LOG.exists() else 0

    with dest.open("a", encoding="utf-8") as w:
        while True:
            time.sleep(POLL_SEC)
            if not ERR_LOG.exists():
                continue
            try:
                sz = ERR_LOG.stat().st_size
            except OSError:
                continue
            if sz < pos:
                w.write(f"\n[{time.strftime('%H:%M:%S')}] (日志文件被截断/轮转，重新从 0 读)\n")
                w.flush()
                pos = 0
            if sz <= pos:
                continue
            try:
                with ERR_LOG.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
            except OSError:
                continue
            if chunk:
                prefix = time.strftime("%H:%M:%S.%f")[:-3]
                for line in chunk.splitlines(keepends=True):
                    if line.endswith("\n"):
                        w.write(f"{prefix} {line}")
                    else:
                        w.write(f"{prefix} {line}\n")
                w.flush()
                pos = sz


if __name__ == "__main__":
    main()
