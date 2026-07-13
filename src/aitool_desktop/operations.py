from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .models import ActionReview, StationEntry


BAT_EXTENSIONS = {".bat", ".cmd"}
BAT_LAUNCH_TIMEOUT = 120


def _normalize_path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def _safe_resolve(path: Path) -> Path:
    return path.resolve()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def collect_station_entries(
    raw_paths: Iterable[str],
    existing: list[StationEntry],
) -> tuple[list[StationEntry], list[str], list[str]]:
    entries = list(existing)
    known = {_normalize_path_key(Path(item.path)): item for item in entries}
    added: list[str] = []
    skipped: list[str] = []

    for raw in raw_paths:
        candidate = Path(raw).expanduser()
        if not candidate.exists():
            skipped.append(f"{candidate} 不存在")
            continue

        key = _normalize_path_key(candidate)
        if key in known:
            skipped.append(f"{candidate.name or candidate} 已在中转站中")
            continue

        entry = StationEntry.from_path(candidate)
        entries.append(entry)
        known[key] = entry
        added.append(entry.display_name)

    entries.sort(key=lambda item: (item.kind != "folder", item.display_name.casefold()))
    return entries, added, skipped


def copy_station_entry_to_directory(entry: StationEntry, target_dir: Path) -> tuple[bool, str]:
    source = Path(entry.path)
    if not source.exists():
        return False, "所选入口已不存在。"
    if not target_dir.exists() or not target_dir.is_dir():
        return False, "目标目录不可用。"

    destination = target_dir / source.name
    if destination.exists():
        return False, "目标位置已存在同名内容，当前版本不会覆盖。"

    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)

    return True, f"已复制到 {destination}"


def _scan_tree(root: Path) -> tuple[int, int]:
    directory_count = 0
    file_count = 0
    for item in root.rglob("*"):
        if item.is_dir():
            directory_count += 1
        else:
            file_count += 1
    return directory_count, file_count


def _count_overlaps(source: Path, target: Path) -> int:
    overlaps = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if (target / relative).exists():
            overlaps += 1
    return overlaps


def _validate_folder_copy_paths(source: Path | None, target: Path | None) -> tuple[Path | None, Path | None, list[str]]:
    """校验来源与目标路径，返回 (resolved_source, resolved_target, errors)。"""
    errors: list[str] = []

    if source is None:
        errors.append("来源目录不能为空。")
    elif not source.exists():
        errors.append(f"来源目录不存在: {source}")
    elif not source.is_dir():
        errors.append(f"来源路径不是目录: {source}")

    if target is None:
        errors.append("目标目录不能为空。")
        return None, None, errors

    resolved_source = _safe_resolve(source) if source is not None else None
    resolved_target = _safe_resolve(target)

    if resolved_source is not None and resolved_source == resolved_target:
        errors.append("来源目录与目标目录不能相同。")

    if resolved_source is not None and (
        _is_relative_to(resolved_target, resolved_source) or _is_relative_to(resolved_source, resolved_target)
    ):
        errors.append("来源目录与目标目录存在包含关系，不允许复制。")

    if errors:
        return None, None, errors
    return resolved_source, resolved_target, []


def build_folder_copy_dry_run(source: Path | None, target: Path | None) -> ActionReview:
    details = ["当前版本只输出 dry-run 评审结果，不执行真实覆盖复制。"]

    resolved_source, resolved_target, errors = _validate_folder_copy_paths(source, target)
    if errors:
        return ActionReview("folder-copy", "blocked", "dry-run", errors[0], details)

    source_dirs, source_files = _scan_tree(source)
    details.append(f"来源目录包含 {source_dirs} 个子目录、{source_files} 个文件。")

    if target.exists():
        if not target.is_dir():
            return ActionReview("folder-copy", "blocked", "dry-run", "目标路径不是目录。", details)
        overlap_count = _count_overlaps(source, target)
        details.append(f"目标目录已存在，按相对路径估计将命中 {overlap_count} 个同名项。")
        details.append("真实执行前需要明确覆盖策略、确认提示和回滚方式。")
        return ActionReview(
            "folder-copy",
            "warning",
            "dry-run",
            "路径已通过校验，可进入覆盖复制评审。",
            details,
        )

    details.append("目标目录当前不存在，真实执行前仍需确认是否允许自动创建。")
    return ActionReview(
        "folder-copy",
        "warning",
        "dry-run",
        "路径已通过校验，可进入覆盖复制评审。",
        details,
    )


def preview_folder_copy(source: Path | None, target: Path | None) -> ActionReview:
    """受控执行前置预览：返回覆盖命中清单，供用户二次确认。"""
    details: list[str] = []

    resolved_source, resolved_target, errors = _validate_folder_copy_paths(source, target)
    if errors:
        return ActionReview("folder-copy", "blocked", "preview", errors[0], details)

    source_dirs, source_files = _scan_tree(source)
    details.append(f"来源目录包含 {source_dirs} 个子目录、{source_files} 个文件。")

    target_exists = target.exists() and target.is_dir()
    if target_exists:
        overlap_count = _count_overlaps(source, target)
        details.append(f"目标目录已存在，将覆盖 {overlap_count} 个同名项。")
    else:
        details.append("目标目录不存在，将自动创建。")

    return ActionReview(
        "folder-copy",
        "warning" if target_exists else "ready",
        "preview",
        "路径已通过校验，确认后执行真实覆盖复制。",
        details,
    )


def execute_folder_copy(source: Path | None, target: Path | None, source2: Path | None = None, target2: Path | None = None) -> ActionReview:
    """执行真实文件夹全量覆盖复制，原生支持最多两组独立的来源和目标路径。"""
    details: list[str] = []

    pairs = []
    if source and target:
        pairs.append((Path(str(source).strip()), Path(str(target).strip())))
    if source2 and target2:
        pairs.append((Path(str(source2).strip()), Path(str(target2).strip())))

    if not pairs:
        return ActionReview("folder-copy", "blocked", "execute", "路径配置不能为空。", details)

    success_count = 0
    for idx, (src, tgt) in enumerate(pairs):
        details.append(f"--- 正在执行第 {idx + 1} 组复制 ---")
        resolved_src, resolved_tgt, errors = _validate_folder_copy_paths(src, tgt)
        if errors:
            details.append(f"第 {idx + 1} 组校验失败: {errors[0]}")
            continue

        src_dirs, src_files = _scan_tree(resolved_src)
        tgt_existed = resolved_tgt.exists() and resolved_tgt.is_dir()
        overlap_count = _count_overlaps(resolved_src, resolved_tgt) if tgt_existed else 0

        details.append(f"来源：{resolved_src} ({src_dirs}个子目录、{src_files}个文件)")
        details.append(f"目标：{resolved_tgt}")
        if tgt_existed:
            details.append(f"目标已存在，覆盖 {overlap_count} 个同名项。")
        else:
            details.append("目标不存在，自动创建。")

        try:
            shutil.copytree(resolved_src, resolved_tgt, dirs_exist_ok=True)
            success_count += 1
            details.append(f"第 {idx + 1} 组复制完成。")
        except Exception as exc:
            details.append(f"第 {idx + 1} 组复制中断: {exc}")

    details.append(f"--- 汇总结果 ---")
    details.append(f"总计配对：{len(pairs)} 组，成功完成：{success_count} 组。")

    if success_count == len(pairs):
        return ActionReview("folder-copy", "ready", "execute", f"全部 {success_count} 组目录覆盖已完成。", details)
    elif success_count > 0:
        return ActionReview("folder-copy", "warning", "execute", f"部分覆盖完成 ({success_count}/{len(pairs)})。", details)
    else:
        return ActionReview("folder-copy", "blocked", "execute", "覆盖复制全部执行失败。", details)


def validate_bat_launch_path(script_path: Path | None) -> ActionReview:
    details = ["当前版本只校验路径，不直接启动外部脚本。"]

    if script_path is None:
        return ActionReview("launch-bat", "blocked", "validate-only", "脚本路径不能为空。", details)
    if not script_path.is_absolute():
        details.append("建议使用绝对路径，避免启动目标漂移。")
        return ActionReview("launch-bat", "blocked", "validate-only", "脚本路径必须是绝对路径。", details)
    if script_path.suffix.lower() not in BAT_EXTENSIONS:
        return ActionReview("launch-bat", "blocked", "validate-only", "只允许 `.bat` 或 `.cmd` 文件。", details)
    if not script_path.exists():
        return ActionReview("launch-bat", "blocked", "validate-only", "脚本文件不存在。", details)

    details.append("真实启动前需要补上确认流、失败回报和执行日志。")
    return ActionReview(
        "launch-bat",
        "warning",
        "validate-only",
        "脚本路径存在，可进入受控启动设计。",
        details,
    )


def launch_bat_script(script_path: Path | None) -> ActionReview:
    """受控启动外部 .bat 脚本，捕获退出码与输出。"""
    details: list[str] = []

    validation = validate_bat_launch_path(script_path)
    if validation.status == "blocked":
        return ActionReview("launch-bat", "blocked", "execute", validation.summary, validation.details)

    details.append(f"脚本：{script_path}")
    details.append(f"超时：{BAT_LAUNCH_TIMEOUT} 秒")

    try:
        result = subprocess.run(
            ["cmd", "/c", str(script_path)],
            capture_output=True,
            text=True,
            timeout=BAT_LAUNCH_TIMEOUT,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        details.append(f"脚本执行超时（{BAT_LAUNCH_TIMEOUT}秒），已终止。")
        return ActionReview("launch-bat", "blocked", "execute", "脚本执行超时。", details)
    except Exception as exc:
        details.append(f"启动失败：{exc}")
        return ActionReview("launch-bat", "blocked", "execute", "脚本启动失败。", details)

    details.append(f"退出码：{result.returncode}")

    stdout_lines = [line for line in result.stdout.strip().splitlines() if line]
    stderr_lines = [line for line in result.stderr.strip().splitlines() if line]

    if stdout_lines:
        details.append(f"输出（{len(stdout_lines)} 行）：")
        details.extend(f"  {line}" for line in stdout_lines[:10])
        if len(stdout_lines) > 10:
            details.append(f"  ...（共 {len(stdout_lines)} 行）")
    if stderr_lines:
        details.append(f"错误输出（{len(stderr_lines)} 行）：")
        details.extend(f"  {line}" for line in stderr_lines[:10])

    if result.returncode == 0:
        return ActionReview("launch-bat", "ready", "execute", "脚本执行成功。", details)
    return ActionReview("launch-bat", "blocked", "execute", f"脚本执行失败（退出码 {result.returncode}）。", details)


def _find_svn_executable() -> tuple[str | None, str]:
    """探测可用的 svn 工具，返回 (可执行路径, 工具类型)。

    优先级：
    1. PATH 中的 svn.exe（命令行客户端，可捕获输出）
    2. TortoiseSVN 安装目录下的 TortoiseProc.exe（GUI 客户端，异步弹窗）
    """
    import shutil as _shutil

    svn_path = _shutil.which("svn")
    if svn_path:
        return svn_path, "svn-cli"

    for base in (
        r"C:\Program Files\TortoiseSVN\bin",
        r"C:\Program Files (x86)\TortoiseSVN\bin",
    ):
        candidate = Path(base) / "TortoiseProc.exe"
        if candidate.exists():
            return str(candidate), "tortoise"

    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\TortoiseSVN", 0, winreg.KEY_READ)
                install_dir, _ = winreg.QueryValueEx(key, "Directory")
                winreg.CloseKey(key)
                candidate = Path(install_dir) / "bin" / "TortoiseProc.exe"
                if candidate.exists():
                    return str(candidate), "tortoise"
            except OSError:
                pass
    except ImportError:
        pass

    return None, "none"


def validate_svn_document_update_path(workspace_path: Path | None) -> ActionReview:
    details: list[str] = []

    if workspace_path is None:
        return ActionReview("update-svn-doc", "blocked", "validate-only", "工作目录不能为空。", details)
    if not workspace_path.is_absolute():
        return ActionReview("update-svn-doc", "blocked", "validate-only", "工作目录必须是绝对路径。", details)
    if not workspace_path.exists():
        return ActionReview("update-svn-doc", "blocked", "validate-only", "工作目录不存在。", details)
    if not workspace_path.is_dir():
        return ActionReview("update-svn-doc", "blocked", "validate-only", "工作目录不是文件夹。", details)

    svn_marker = workspace_path / ".svn"
    if svn_marker.exists():
        details.append("检测到 `.svn` 目录，路径看起来像工作副本。")
    else:
        details.append("未检测到 `.svn` 目录，仍需人工确认该路径是否对应工作副本。")

    exe_path, exe_type = _find_svn_executable()
    if exe_path is None:
        details.append("未找到 svn.exe 或 TortoiseProc.exe，请安装 svn 客户端。")
        return ActionReview("update-svn-doc", "blocked", "validate-only", "svn 客户端不可用。", details)

    if exe_type == "svn-cli":
        details.append(f"命令行客户端：{exe_path}")
    else:
        details.append(f"GUI 客户端：{exe_path}（将弹出 TortoiseSVN 更新窗口）")

    return ActionReview(
        "update-svn-doc",
        "warning",
        "validate-only",
        "路径已校验，可执行更新。",
        details,
    )


def execute_svn_commit(workspace_path: Path | None, message: str = "") -> ActionReview:
    """对 svn 工作目录执行 svn commit。"""
    details: list[str] = []

    validation = validate_svn_document_update_path(workspace_path)
    if validation.status == "blocked":
        return ActionReview("commit-svn-doc", "blocked", "execute", validation.summary, validation.details)

    exe_path, exe_type = _find_svn_executable()
    if exe_path is None:
        details.append("未找到 svn.exe 或 TortoiseProc.exe。")
        return ActionReview("commit-svn-doc", "blocked", "execute", "svn 客户端不可用。", details)

    details.append(f"工作目录：{workspace_path}")
    details.append(f"工具：{exe_path}")

    # 对于 TortoiseProc.exe，采用 /command:commit，能完美呼出精美的 SVN 提交图形配置面板，符合最佳用户习惯
    if exe_type == "tortoise" or exe_type == "none":
        details.append("操作：TortoiseProc /command:commit")
        try:
            cmd_args = [exe_path, "/command:commit", f"/path:{workspace_path}", "/closeonend:0"]
            if message:
                cmd_args.append(f"/logmsg:{message}")
            proc = subprocess.Popen(cmd_args, shell=False)
            details.append(f"TortoiseSVN 提交窗口已启动（PID {proc.pid}）。")
            return ActionReview("commit-svn-doc", "ready", "execute", "SVN 提交窗口已启动。", details)
        except Exception as exc:
            details.append(f"启动失败：{exc}")
            return ActionReview("commit-svn-doc", "blocked", "execute", "SVN 提交窗口启动失败。", details)
    else:
        # CLI 模式
        details.append("操作：svn commit")
        try:
            commit_args = [exe_path, "commit"]
            if message:
                commit_args.extend(["-m", message])
            else:
                commit_args.extend(["-m", "AiTool auto commit"])
            result = subprocess.run(
                commit_args,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
            details.append(f"退出码：{result.returncode}")
            if result.returncode == 0:
                return ActionReview("commit-svn-doc", "ready", "execute", "SVN 提交已完成。", details)
            
            stderr_lines = [line for line in result.stderr.strip().splitlines() if line]
            if stderr_lines:
                details.append("错误信息：")
                details.extend(f"  {line}" for line in stderr_lines[:10])
            return ActionReview("commit-svn-doc", "blocked", "execute", "SVN 提交失败。", details)
        except Exception as exc:
            details.append(f"执行失败：{exc}")
            return ActionReview("commit-svn-doc", "blocked", "execute", "SVN 提交执行异常。", details)


def execute_open_web(url: str) -> ActionReview:
    """使用默认浏览器打开指定的网页 URL。"""
    details: list[str] = [f"配置 URL：{url}"]
    if not url:
        return ActionReview("open-web", "blocked", "execute", "网页地址不能为空。", details)

    # 规范化 URL 协议头
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    try:
        import webbrowser
        webbrowser.open(url)
        details.append("已成功调用默认浏览器发起网页跳转。")
        return ActionReview("open-web", "ready", "execute", "已调用默认浏览器打开网页。", details)
    except Exception as exc:
        details.append(f"浏览器唤醒失败：{exc}")
        return ActionReview("open-web", "blocked", "execute", "无法打开指定网页。", details)


def execute_svn_update(workspace_path: Path | None) -> ActionReview:
    """对 svn 工作目录执行 svn update。"""
    details: list[str] = []

    validation = validate_svn_document_update_path(workspace_path)
    if validation.status == "blocked":
        return ActionReview("update-svn-doc", "blocked", "execute", validation.summary, validation.details)

    exe_path, exe_type = _find_svn_executable()
    if exe_path is None:
        details.append("未找到 svn.exe 或 TortoiseProc.exe。")
        return ActionReview("update-svn-doc", "blocked", "execute", "svn 客户端不可用。", details)

    details.append(f"工作目录：{workspace_path}")
    details.append(f"工具：{exe_path}")

    if exe_type == "svn-cli":
        details.append("操作：svn update --non-interactive")
        try:
            result = subprocess.run(
                [exe_path, "update", "--non-interactive"],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            details.append("svn update 超时（180秒），已终止。")
            return ActionReview("update-svn-doc", "blocked", "execute", "svn update 超时。", details)
        except FileNotFoundError:
            details.append("svn 命令不可用。")
            return ActionReview("update-svn-doc", "blocked", "execute", "svn 客户端不可用。", details)
        except Exception as exc:
            details.append(f"启动失败：{exc}")
            return ActionReview("update-svn-doc", "blocked", "execute", "svn update 启动失败。", details)

        details.append(f"退出码：{result.returncode}")

        stdout_lines = [line for line in result.stdout.strip().splitlines() if line]
        if stdout_lines:
            details.append(f"输出（{len(stdout_lines)} 行）：")
            details.extend(f"  {line}" for line in stdout_lines[:15])
            if len(stdout_lines) > 15:
                details.append(f"  ...（共 {len(stdout_lines)} 行）")

        stderr_lines = [line for line in result.stderr.strip().splitlines() if line]
        if stderr_lines:
            details.append(f"错误输出（{len(stderr_lines)} 行）：")
            details.extend(f"  {line}" for line in stderr_lines[:10])

        if result.returncode == 0:
            return ActionReview("update-svn-doc", "ready", "execute", "svn update 已完成。", details)
        return ActionReview("update-svn-doc", "blocked", "execute", f"svn update 失败（退出码 {result.returncode}）。", details)

    # TortoiseProc.exe：异步弹出 GUI 更新窗口
    details.append("操作：TortoiseProc /command:update")
    try:
        proc = subprocess.Popen(
            [exe_path, "/command:update", f"/path:{workspace_path}", "/closeonend:0"],
            shell=False,
        )
        details.append(f"TortoiseSVN 更新窗口已启动（PID {proc.pid}）。")
        details.append("请在弹出的窗口中完成更新操作。")
        return ActionReview("update-svn-doc", "ready", "execute", "svn 更新窗口已启动。", details)
    except FileNotFoundError:
        details.append("TortoiseProc.exe 不可用。")
        return ActionReview("update-svn-doc", "blocked", "execute", "svn 客户端不可用。", details)
    except Exception as exc:
        details.append(f"启动失败：{exc}")
        return ActionReview("update-svn-doc", "blocked", "execute", "svn update 启动失败。", details)


def execute_app_launch(app_path: Path | None, work_dir: str = "", args: str = "") -> ActionReview:
    """启动外部应用 (exe/lnk/lnk关联的目标程序)。"""
    details: list[str] = []
    if app_path is None:
        return ActionReview("app-launch", "blocked", "execute", "应用路径为空。", details)

    app_path = Path(app_path)
    if not app_path.exists():
        details.append(f"路径不存在：{app_path}")
        return ActionReview("app-launch", "blocked", "execute", "找不到该应用程序或快捷方式。", details)

    details.append(f"目标：{app_path}")
    if args:
        details.append(f"启动参数：{args}")
    
    cwd_dir = work_dir.strip() if work_dir else str(app_path.parent)
    if cwd_dir:
        details.append(f"工作目录：{cwd_dir}")

    try:
        # 使用 os.startfile 启动 (对于 Windows 平台非常安全，自动解析快捷方式 .lnk 并且无需阻塞等待进程)
        import os
        if args:
            # 有参数时，采用 subprocess.Popen 启动更好处理
            cmd = [str(app_path)]
            if args:
                # 简单解析参数列表，或作为一个字符串传入 (shell=True)
                subprocess.Popen(f'"{app_path}" {args}', cwd=cwd_dir if cwd_dir else None, shell=True)
            details.append("已使用参数命令启动进程。")
        else:
            # 无参数时，采用最稳定的 Windows startfile 启动
            os.startfile(str(app_path))
            details.append("已通过 Windows Explorer 成功拉起程序。")

        return ActionReview("app-launch", "ready", "execute", "应用已成功启动。", details)
    except Exception as exc:
        details.append(f"启动失败：{exc}")
        return ActionReview("app-launch", "blocked", "execute", "无法拉起程序。", details)
