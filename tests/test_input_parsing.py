from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aitool_desktop.input_parsing import ParsedInput, parse_input


class TestParseInput(unittest.TestCase):
    """纯函数测试 parse_input —— 不创建 Tk root，不用 storage/UI stub。"""

    # ----------------------------------------------------------------
    # 空输入 & 空 splitlist
    # ----------------------------------------------------------------

    def test_empty_raw_data_returns_none(self):
        self.assertIsNone(parse_input(""))

    def test_empty_splitlist_returns_none(self):
        """拖拽时 splitlist 返回空列表应返回 None。"""
        self.assertIsNone(
            parse_input("some_data", paths_source="data", splitlist=lambda x: [])
        )

    # ----------------------------------------------------------------
    # http(s) URL 识别
    # ----------------------------------------------------------------

    def test_http_url_generates_open_web_module(self):
        result = parse_input("http://example.com/foo")
        self.assertIsNotNone(result)
        self.assertEqual(len(result.modules), 1)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "http://example.com/foo")
        self.assertIn("http://example.com/foo", mod.name)
        self.assertEqual(len(result.station_paths), 0)

    def test_https_url_generates_open_web_module(self):
        result = parse_input("https://secure.example.com/path")
        self.assertIsNotNone(result)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "https://secure.example.com/path")

    def test_tcl_outer_brace_url_stripped_and_recognised(self):
        """Tkinter 拖拽可能用 {URL} 包裹，strip("{}'\" ") 后仍识别。"""
        result = parse_input("{http://example.com/page}")
        self.assertIsNotNone(result)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "http://example.com/page")

    def test_long_url_name_truncated_at_25(self):
        """URL 名称超过 25 字符时截断为 25 + '...'。"""
        long_path = "/" + "x" * 30
        result = parse_input("http://example.com" + long_path)
        self.assertIsNotNone(result)
        mod = result.modules[0]
        url = mod.params["url"]
        self.assertGreater(len(url), 25)
        # 名称应为 "打开网页 " + url[:25] + "..."
        expected_name = "打开网页 " + url[:25] + "..."
        self.assertEqual(mod.name, expected_name)

    def test_short_url_name_not_truncated(self):
        result = parse_input("http://a.co")
        self.assertIsNotNone(result)
        mod = result.modules[0]
        self.assertEqual(mod.name, "打开网页 http://a.co")

    # ----------------------------------------------------------------
    # 顶层 www. 识别
    # ----------------------------------------------------------------

    def test_top_level_www_prepends_https(self):
        result = parse_input("www.example.com")
        self.assertIsNotNone(result)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "https://www.example.com")
        self.assertEqual(mod.name, "打开 www.example.com")

    def test_top_level_www_with_outer_brace(self):
        """www. 在 cleaned_raw (strip 后) 检测，不受外层括号影响。"""
        result = parse_input("{www.example.com}")
        self.assertIsNotNone(result)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "https://www.example.com")

    # ----------------------------------------------------------------
    # 路径循环中不存在的 www.
    # ----------------------------------------------------------------

    def test_www_in_loop_nonexistent_path(self):
        """循环中路径不存在但以 www. 开头（用 raw_path.strip()）。"""
        result = parse_input(
            "dummy_data",
            paths_source="www.foobar.com",
            splitlist=lambda x: ["www.foobar.com"],
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result.modules), 1)
        mod = result.modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "https://www.foobar.com")
        self.assertEqual(mod.name, "打开 www.foobar.com")
        self.assertEqual(len(result.station_paths), 0)

    # ----------------------------------------------------------------
    # 分号多路径 (folder-copy)
    # ----------------------------------------------------------------

    def test_semicolon_two_dirs_generates_folder_copy(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            raw = f"{d1};{d2}"
            result = parse_input(raw)
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 1)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "folder-copy")
            self.assertEqual(mod.name, "多路径覆盖复制")
            self.assertIn(d1, mod.params["source"])
            self.assertIn(d2, mod.params["source"])

    def test_semicolon_one_valid_dir_returns_empty_result(self):
        """命中分号分支但目录不足两个时，不创建模块也不进入路径循环。"""
        with tempfile.TemporaryDirectory() as d1:
            raw = f"{d1};X:\\nonexistent_dir"
            result = parse_input(raw)
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 0)
            self.assertEqual(result.station_paths, [])

    def test_semicolon_with_two_existing_dirs_via_drag(self):
        """拖拽场景：分号分隔的两个存在目录。"""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            raw = f"{d1};{d2}"
            # 拖拽时 paths_source 非 None，但分号检测发生在 else 之前
            result = parse_input(raw, paths_source="drag_data", splitlist=lambda x: [d1, d2])
            self.assertIsNotNone(result)
            # 由于 raw 包含 ";" 且有 ":"，会走 semicolon 分支，不是 else
            self.assertEqual(len(result.modules), 1)
            self.assertEqual(result.modules[0].module_type, "folder-copy")

    # ----------------------------------------------------------------
    # 拖拽 splitlist 与粘贴（无 splitlist）
    # ----------------------------------------------------------------

    def test_drag_calls_splitlist(self):
        """拖拽时 paths_source 非 None，应调用 splitlist(paths_source)。"""
        called = []

        def fake_splitlist(data):
            called.append(data)
            return ["X:\\does_not_exist\\file.txt"]

        result = parse_input(
            "drag_text", paths_source="event_data_here", splitlist=fake_splitlist
        )
        self.assertIsNotNone(result)
        self.assertEqual(called, ["event_data_here"])
        # 路径不存在 → modules 和 station_paths 都为空
        self.assertEqual(len(result.modules), 0)
        self.assertEqual(len(result.station_paths), 0)

    def test_paste_no_splitlist_uses_raw_data(self):
        """粘贴时 paths_source=None / splitlist=None，paths = [raw_data]。"""
        result = parse_input("X:\\nonexistent\\file.txt")
        self.assertIsNotNone(result)
        # 文件不存在 → 无模块无 station
        self.assertEqual(len(result.modules), 0)
        self.assertEqual(len(result.station_paths), 0)

    # ----------------------------------------------------------------
    # .url 文件
    # ----------------------------------------------------------------

    def test_url_file_generates_open_web_module(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".url", delete=False, encoding="utf-8"
        ) as f:
            f.write("[InternetShortcut]\nURL=http://example.com/target\n")
            url_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [url_path],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 1)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "open-web")
            self.assertEqual(mod.params["url"], "http://example.com/target")
            self.assertEqual(mod.name, "打开 " + Path(url_path).stem)
        finally:
            Path(url_path).unlink(missing_ok=True)

    def test_url_file_without_url_skips(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".url", delete=False, encoding="utf-8"
        ) as f:
            f.write("[InternetShortcut]\nSomething=else\n")
            url_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [url_path],
            )
            self.assertIsNotNone(result)
            # URL 没提取到 → 文件存在但后缀 .url 已经在上面处理过了
            # 实际上：.url 后缀匹配，但 url_val 为空，不会 continue
            # 然后 p.exists() 为 True，ext = ".url"，既不在 {.exe,.lnk} 也不在 {.bat,.cmd,.py}
            # → 进入 else → added to station_paths
            self.assertEqual(len(result.modules), 0)
            self.assertEqual(len(result.station_paths), 1)
        finally:
            Path(url_path).unlink(missing_ok=True)

    # ----------------------------------------------------------------
    # .exe / .lnk 文件
    # ----------------------------------------------------------------

    def test_exe_file_generates_app_launch(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            exe_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [exe_path],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 1)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "app-launch")
            self.assertEqual(mod.params["app_path"], exe_path)
            self.assertIn(Path(exe_path).name, mod.name)
        finally:
            Path(exe_path).unlink(missing_ok=True)

    def test_lnk_file_generates_app_launch_with_stem(self):
        with tempfile.NamedTemporaryFile(suffix=".lnk", delete=False) as f:
            lnk_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [lnk_path],
            )
            self.assertIsNotNone(result)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "app-launch")
            self.assertEqual(mod.params["app_path"], lnk_path)
            # .lnk 用 p.stem 而非 p.name
            self.assertIn(Path(lnk_path).stem, mod.name)
            self.assertNotIn(".lnk", mod.name)
        finally:
            Path(lnk_path).unlink(missing_ok=True)

    # ----------------------------------------------------------------
    # .bat / .cmd / .py 文件
    # ----------------------------------------------------------------

    def test_bat_file_generates_launch_bat(self):
        with tempfile.NamedTemporaryFile(suffix=".bat", delete=False) as f:
            bat_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [bat_path],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 1)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "launch-bat")
            self.assertEqual(mod.params["script"], bat_path)
            self.assertIn(Path(bat_path).name, mod.name)
        finally:
            Path(bat_path).unlink(missing_ok=True)

    def test_cmd_file_generates_launch_bat(self):
        with tempfile.NamedTemporaryFile(suffix=".cmd", delete=False) as f:
            cmd_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [cmd_path],
            )
            self.assertIsNotNone(result)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "launch-bat")
        finally:
            Path(cmd_path).unlink(missing_ok=True)

    def test_py_file_generates_launch_bat(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            py_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [py_path],
            )
            self.assertIsNotNone(result)
            mod = result.modules[0]
            self.assertEqual(mod.module_type, "launch-bat")
        finally:
            Path(py_path).unlink(missing_ok=True)

    # ----------------------------------------------------------------
    # 目录 → station
    # ----------------------------------------------------------------

    def test_directory_added_to_station_paths(self):
        with tempfile.TemporaryDirectory() as d:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [d],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 0)
            self.assertEqual(len(result.station_paths), 1)
            self.assertEqual(result.station_paths[0], d)

    # ----------------------------------------------------------------
    # 普通文件 → station (.txt 等)
    # ----------------------------------------------------------------

    def test_txt_file_added_to_station_paths(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            txt_path = f.name

        try:
            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [txt_path],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 0)
            self.assertEqual(len(result.station_paths), 1)
            self.assertEqual(result.station_paths[0], txt_path)
        finally:
            Path(txt_path).unlink(missing_ok=True)

    # ----------------------------------------------------------------
    # 混合多个拖拽路径
    # ----------------------------------------------------------------

    def test_mixed_drag_paths(self):
        """同时拖入 .exe、.bat 和普通目录。"""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f_exe, \
             tempfile.NamedTemporaryFile(suffix=".bat", delete=False) as f_bat, \
             tempfile.TemporaryDirectory() as d:
            exe_path = f_exe.name
            bat_path = f_bat.name

            result = parse_input(
                "dummy",
                paths_source="drag_data",
                splitlist=lambda x: [exe_path, bat_path, d],
            )
            self.assertIsNotNone(result)
            self.assertEqual(len(result.modules), 2)
            types = {m.module_type for m in result.modules}
            self.assertIn("app-launch", types)
            self.assertIn("launch-bat", types)
            self.assertEqual(len(result.station_paths), 1)
            self.assertEqual(result.station_paths[0], d)

        Path(exe_path).unlink(missing_ok=True)
        Path(bat_path).unlink(missing_ok=True)

    # ----------------------------------------------------------------
    # ParsedInput 数据结构
    # ----------------------------------------------------------------

    def test_parsed_input_defaults(self):
        pi = ParsedInput()
        self.assertEqual(pi.modules, [])
        self.assertEqual(pi.station_paths, [])


if __name__ == "__main__":
    unittest.main()
