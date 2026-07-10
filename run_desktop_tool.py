from __future__ import annotations

import json
import uuid
import sys
import os
from pathlib import Path


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
