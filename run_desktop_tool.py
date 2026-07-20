from __future__ import annotations

import json
import uuid
import sys
import os
import logging
import threading
from pathlib import Path


def _aitool_log_path() -> Path:
    """Return the persistent log path, never the frozen extraction directory."""

    if getattr(sys, "frozen", False):
        return Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "AiTool" / "aitool.log"
    return Path(__file__).resolve().parent / "data" / "aitool.log"


def _configure_logging() -> logging.Logger:
    """Install one persistent file handler with a stderr fallback."""

    logger = logging.getLogger("aitool")
    logger.setLevel(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    log_path = _aitool_log_path()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [pid=%(process)d] [%(module)s:%(lineno)d] "
        "[%(threadName)s] %(message)s"
    )

    for handler in logging.getLogger().handlers + logger.handlers:
        if getattr(handler, "_aitool_log_handler", False):
            return logger
        if isinstance(handler, logging.FileHandler):
            try:
                if Path(handler.baseFilename).resolve() == log_path.resolve():
                    handler.setFormatter(formatter)
                    handler.setLevel(logging.DEBUG)
                    handler._aitool_log_handler = True
                    return logger
            except Exception:
                continue

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)
        handler._aitool_log_handler = True
        logging.getLogger().addHandler(handler)
    except Exception as exc:
        # Logging must remain visible even when APPDATA/data is unavailable.
        fallback = next(
            (
                handler
                for handler in logging.getLogger().handlers
                if getattr(handler, "_aitool_stderr_handler", False)
            ),
            None,
        )
        if fallback is None:
            fallback = logging.StreamHandler(sys.stderr)
            fallback.setFormatter(formatter)
            fallback.setLevel(logging.DEBUG)
            fallback._aitool_stderr_handler = True
            logging.getLogger().addHandler(fallback)
        logger.error("Unable to configure file logging at %s: %s", log_path, exc)
    return logger


def _install_exception_hooks(logger: logging.Logger) -> None:
    """Log uncaught main-thread and worker-thread exceptions with tracebacks."""

    current_sys_hook = sys.excepthook
    if not getattr(current_sys_hook, "_aitool_exception_hook", False):
        def _sys_excepthook(exc_type, exc_value, exc_traceback):
            logger.error(
                "Unhandled main-thread exception",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
            current_sys_hook(exc_type, exc_value, exc_traceback)

        _sys_excepthook._aitool_exception_hook = True
        sys.excepthook = _sys_excepthook

    if hasattr(threading, "excepthook"):
        current_thread_hook = threading.excepthook
        if not getattr(current_thread_hook, "_aitool_exception_hook", False):
            def _threading_excepthook(args):
                logger.error(
                    "Unhandled exception in thread %s",
                    getattr(args.thread, "name", "unknown"),
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
                current_thread_hook(args)

            _threading_excepthook._aitool_exception_hook = True
            threading.excepthook = _threading_excepthook


_LOGGER = _configure_logging()
_install_exception_hooks(_LOGGER)


# 关键修复点：由于 PyInstaller 在单文件打包后，运行时会将内容解压到临时的 _MEIPASS 目录下，
# 这导致原本基于 Path(__file__).resolve().parent / "src" 的本地路径计算策略失效，无法在临时文件夹里检索到本地的 'src'。
# 解决方案：优先检测运行环境是否是 Frozen 打包状态，如果是，直接动态注入 PyInstaller 特有的 _MEIPASS 运行时变量路径，
# 并追加本地 src 目录作为模块根路径，从而 100% 消除 "No module named 'aitool_desktop'" 的错误！
if getattr(sys, "frozen", False):
    base_dir = Path(sys._MEIPASS)
else:
    base_dir = Path(__file__).resolve().parent

SRC_DIR = base_dir / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 为了让 PyInstaller 的静态分析器能无感抓取到 'src' 目录里的包，我们也额外追加路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from aitool_desktop.app import main


if __name__ == "__main__":
    raise SystemExit(main())
