from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aitool_desktop.app import DesktopToolApp
from aitool_desktop.models import CustomModule


class StubModuleStorage:
    """Fake ModuleStorage – only save() is called via self.module_storage."""

    @staticmethod
    def save(modules):
        pass


class StubStationStorage:
    """Fake StationStorage – only save() is called via self.station_storage."""

    @staticmethod
    def save(entries):
        pass


class StubApp:
    """Lightweight stub for DesktopToolApp without Tk root or any GUI dependency.

    Provides the attributes / methods that _process_input_data touches,
    so we can test it in pure-unittest / headless CI.
    """

    def __init__(self):
        self.custom_modules: list = []
        self.entries: list = []
        self.module_storage = StubModuleStorage()
        self.station_storage = StubStationStorage()
        self.tk = MagicMock()

    # ---- four no-op UI methods ----
    def _refresh_cards(self):
        pass

    def _refresh_station(self):
        pass

    def _toast(self, message, level=""):
        pass

    def _set_status(self, text, level="ready"):
        pass


class TestProcessInputData(unittest.TestCase):
    """Test DesktopToolApp._process_input_data without constructing the app or creating a Tk root."""

    @staticmethod
    def _make_stub():
        return StubApp()

    # ----------------------------------------------------------------
    # URL detection
    # ----------------------------------------------------------------

    def test_normal_http_url_generates_open_web_module(self):
        stub = self._make_stub()
        DesktopToolApp._process_input_data(stub, "http://example.com/foo", paths_source=None)
        self.assertEqual(len(stub.custom_modules), 1)
        mod = stub.custom_modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "http://example.com/foo")
        self.assertIn("http://example.com/foo", mod.name)

    def test_tcl_outer_brace_url_stripped_and_recognised(self):
        """TkinterDnD sometimes wraps URLs with outer curly braces like {http://...}."""
        stub = self._make_stub()
        DesktopToolApp._process_input_data(stub, "{http://example.com/page}", paths_source=None)
        self.assertEqual(len(stub.custom_modules), 1)
        mod = stub.custom_modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "http://example.com/page")

    def test_www_url_prepends_https(self):
        stub = self._make_stub()
        DesktopToolApp._process_input_data(stub, "www.example.com", paths_source=None)
        self.assertEqual(len(stub.custom_modules), 1)
        mod = stub.custom_modules[0]
        self.assertEqual(mod.module_type, "open-web")
        self.assertEqual(mod.params["url"], "https://www.example.com")

    # ----------------------------------------------------------------
    # Path branching: drag (splitlist) vs paste (single path)
    # ----------------------------------------------------------------

    def test_drag_with_paths_source_calls_tk_splitlist(self):
        """When paths_source is not None, the else-branch calls self.tk.splitlist(paths_source)."""
        stub = self._make_stub()
        stub.tk.splitlist.return_value = ["X:\\does_not_exist\\file.txt"]
        DesktopToolApp._process_input_data(
            stub, "X:\\does_not_exist\\file.txt", paths_source="drag_event_data"
        )
        stub.tk.splitlist.assert_called_once_with("drag_event_data")
        # Non-existent file, not a URL → nothing added
        self.assertEqual(len(stub.custom_modules), 0)
        self.assertEqual(len(stub.entries), 0)

    def test_paste_with_paths_source_none_uses_raw_data_as_single_path(self):
        """When paths_source is None, splitlist is NOT called; paths = [raw_data]."""
        stub = self._make_stub()
        DesktopToolApp._process_input_data(
            stub, "X:\\nonexistent\\file.txt", paths_source=None
        )
        stub.tk.splitlist.assert_not_called()
        self.assertEqual(len(stub.custom_modules), 0)
        self.assertEqual(len(stub.entries), 0)


if __name__ == "__main__":
    unittest.main()
