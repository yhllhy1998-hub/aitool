from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from .models import CustomModule
from .storage import ModuleStorage


@dataclass
class ParsedInput:
    """纯数据容器：解析结果，不包含 UI 逻辑。"""
    modules: list[CustomModule] = field(default_factory=list)
    station_paths: list[str] = field(default_factory=list)


def parse_input(raw_data: str, paths_source=None, *, splitlist=None) -> ParsedInput | None:
    """纯识别函数 —— 不导入 tkinter/customtkinter，不执行 UI/保存副作用。

    raw_data:    原始文本数据（拖拽的 event.data 或剪贴板内容）
    paths_source: 拖拽时的 event.data（传给 splitlist），粘贴时为 None
    splitlist:    拖拽时的 tk.splitlist 可调用对象，粘贴时为 None

    返回 ParsedInput 或 None。
    - raw_data 为空 → None
    - splitlist 返回空列表 → None
    """
    if not raw_data:
        return None

    modules: list[CustomModule] = []
    station_paths: list[str] = []

    # 保留原始的无用 url_match 计算，不顺手清理
    url_match = re.search(r'(https?://[^\s"\'{}<>]+)', raw_data)

    cleaned_raw = raw_data.strip("{}'\" ")
    url_match_loose = re.search(r'(https?://[^\s"\'{}<>]+)', cleaned_raw)

    if url_match_loose:
        extracted_url = url_match_loose.group(1)
        # 名称截断完全保持 25 + "..."
        name = "打开网页 " + (extracted_url[:25] + "..." if len(extracted_url) > 25 else extracted_url)
        module = CustomModule(
            module_id=ModuleStorage.generate_id(),
            name=name,
            module_type="open-web",
            params={"url": extracted_url},
        )
        modules.append(module)
    elif cleaned_raw.lower().startswith("www."):
        full_url = "https://" + cleaned_raw
        name = "打开 " + cleaned_raw
        module = CustomModule(
            module_id=ModuleStorage.generate_id(),
            name=name,
            module_type="open-web",
            params={"url": full_url},
        )
        modules.append(module)
    elif ";" in raw_data and (raw_data.count(":") >= 2 or "/" in raw_data or "\\" in raw_data):
        parts = [p.strip() for p in raw_data.split(";")]
        valid_dirs = [p for p in parts if Path(p).exists() and Path(p).is_dir()]
        if len(valid_dirs) >= 2:
            name = "多路径覆盖复制"
            module = CustomModule(
                module_id=ModuleStorage.generate_id(),
                name=name,
                module_type="folder-copy",
                params={"source": ";".join(valid_dirs), "target": ""},
            )
            modules.append(module)
    else:
        if splitlist is not None:
            paths = list(splitlist(paths_source))
        else:
            paths = [raw_data]
        if not paths:
            return None

        for raw_path in paths:
            p = Path(raw_path)
            if p.suffix.lower() == ".url":
                try:
                    url_val = ""
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.strip().lower().startswith("url="):
                                url_val = line.split("=", 1)[1].strip()
                                break
                    if url_val:
                        name = "打开 " + p.stem
                        module = CustomModule(
                            module_id=ModuleStorage.generate_id(),
                            name=name,
                            module_type="open-web",
                            params={"url": url_val},
                        )
                        modules.append(module)
                        continue
                except Exception:
                    pass

            if not p.exists():
                # 循环路径中不存在的 www. 仍只用 raw_path.strip()，保留与顶层 cleaned_raw 的不对称
                raw_lower = raw_path.strip().lower()
                if raw_lower.startswith("www."):
                    full_url = "https://" + raw_path.strip()
                    name = "打开 " + raw_path.strip()
                    module = CustomModule(
                        module_id=ModuleStorage.generate_id(),
                        name=name,
                        module_type="open-web",
                        params={"url": full_url},
                    )
                    modules.append(module)
                    continue
                continue

            ext = p.suffix.lower()
            if ext in {".exe", ".lnk"}:
                name = "启动 " + (p.stem if ext == ".lnk" else p.name)
                module = CustomModule(
                    module_id=ModuleStorage.generate_id(),
                    name=name,
                    module_type="app-launch",
                    params={"app_path": str(p), "work_dir": "", "args": ""},
                )
                modules.append(module)
            elif ext in {".bat", ".cmd", ".py"}:
                name = "执行 " + p.name
                module = CustomModule(
                    module_id=ModuleStorage.generate_id(),
                    name=name,
                    module_type="launch-bat",
                    params={"script": str(p)},
                )
                modules.append(module)
            else:
                station_paths.append(raw_path)

    return ParsedInput(modules=modules, station_paths=station_paths)
