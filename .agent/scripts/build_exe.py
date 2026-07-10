#!/usr/bin/env python3
"""AiTool 桌面工具 exe 打包脚本。

固化已验证的 PyInstaller 参数（H1 生死假设验证通过）。
打包前自动清理旧产物，打包后验证 exe 生成。

用法：
    python .agent/scripts/build_exe.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY_SCRIPT = REPO_ROOT / "run_desktop_tool.py"
SRC_DIR = REPO_ROOT / "src" / "aitool_desktop"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
EXE_NAME = "aitool_desktop"


def get_tcl_dir() -> Path:
    return Path(sys.base_prefix) / "tcl"


def get_tkinter_pyd() -> Path:
    return Path(sys.base_prefix) / "DLLs" / "_tkinter.pyd"


def clean_old_artifacts() -> None:
    for target in (DIST_DIR, BUILD_DIR, REPO_ROOT / f"{EXE_NAME}.spec"):
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            print(f"  已清理: {target}")


def build_exe() -> int:
    tcl_dir = get_tcl_dir()
    tkinter_pyd = get_tkinter_pyd()

    if not tcl_dir.exists():
        print(f"错误：tcl 目录不存在: {tcl_dir}")
        return 1
    if not tkinter_pyd.exists():
        print(f"错误：_tkinter.pyd 不存在: {tkinter_pyd}")
        return 1
    if not ENTRY_SCRIPT.exists():
        print(f"错误：入口脚本不存在: {ENTRY_SCRIPT}")
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", EXE_NAME,
        "--collect-submodules", "tkinter",
        "--hidden-import", "_tkinter",
        "--hidden-import", "json",
        "--hidden-import", "uuid",
        "--hidden-import", "datetime",
        "--hidden-import", "shutil",
        "--hidden-import", "subprocess",
        "--add-data", f"{tcl_dir};tcl",
        "--add-data", f"{tkinter_pyd};.",
        "--add-data", f"{SRC_DIR};aitool_desktop",
        str(ENTRY_SCRIPT),
    ]

    print("执行打包命令：")
    print("  " + " ".join(cmd[:6]) + " ...")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"打包失败，退出码: {result.returncode}")
        return result.returncode

    exe_path = DIST_DIR / f"{EXE_NAME}.exe"
    if not exe_path.exists():
        print(f"错误：exe 未生成: {exe_path}")
        return 1

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"\n打包成功：")
    print(f"  路径: {exe_path}")
    print(f"  大小: {size_mb:.1f} MB")
    return 0


def main() -> int:
    print("=== AiTool exe 打包 ===\n")

    print("[1/2] 清理旧产物...")
    clean_old_artifacts()

    print("\n[2/2] 执行打包...")
    return build_exe()


if __name__ == "__main__":
    raise SystemExit(main())
