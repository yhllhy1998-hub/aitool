# Windows Snap 隔离与顶部停靠经验

本文记录 Windows 原生标题栏、Snap 隔离和顶部自动隐藏之间的边界，供后续接手者复现判断。实现集中在 `src/aitool_desktop/app.py`。

## 1. 问题与最终行为

- 保留原生标题栏（`DesktopToolApp._init_window` 使用 `overrideredirect(False)`），但禁用原生 resize 和 Snap affordance。
- 窗口被拖到工作区顶部并稳定后，进入 `docked_expanded` 状态。
- 鼠标离开客户区后，窗口整体向上移动，只露出约 30px 的横条；窗口高度保持不变。收起后的判断应看外框 bottom，而不是把窗口高度改成 30px。

## 2. 试错中被证伪的路径

按“假设 → 为什么不够”记录：

- **只靠 Tk `<Configure>`/`geometry` 区分用户拖动、Snap、动画** → 这些来源都会产生相似的 Configure/geometry 更新，且事件可能与 Tk 自己的写入交错，无法单独确定几何的拥有者。
- **直接对 `winfo_id()` 改样式** → `winfo_id()` 可能指向 TkChild，而不是拥有可见标题栏的顶层窗口，样式改在错误 HWND 上不会改变 Snap/resize 行为。
- **只在构造期应用 Win32 样式** → 窗口 Map 或 withdraw/deiconify 时 Tk/窗口管理器可能重新调整 frame style，启动时成功不代表当前可见窗口仍满足契约。
- **负绝对 y 继续交给 Tk geometry** → Tk 把负坐标解释为右侧/底部偏移，不是屏幕绝对负坐标；收起动画会跑到无关位置。
- **只看源码契约/启动成功就宣称 GUI 完成** → 不能证明实际 EXE、实际 HWND、真实外框矩形、鼠标标题栏拖动、视觉状态或 DND 行为符合目标。

## 3. 最终根因

- `winfo_id()` 可能是 TkChild；真实可见顶层由 `GetAncestor(GA_ROOT)` 解析（`_resolve_native_window_hwnd`）。
- Tk 的负坐标语义不是绝对屏幕坐标，负的绝对 y 必须绕过 Tk geometry。
- `_dock_resize_blocked` 如果在贴顶状态永久保留，会阻断后续 `docked_expanded` 的自动收起；它只能是短暂的 resize 保护，最大化状态则仍应阻止停靠动作。
- 构建验证可能实际命中了旧 EXE 或仍占用旧 EXE 的进程；旧 EXE/进程锁会使代码、构建产物和观察到的行为错位。

## 4. 正确实现路径

1. **先找对窗口。** 通过 `_resolve_native_window_hwnd` 将 Tk HWND 解析为 `GetAncestor(GA_ROOT)` 返回的真实顶层 HWND；`_disable_native_resize_and_maximize` 在该 HWND 上清除 `WS_THICKFRAME`、`WS_SIZEBOX`、`WS_MAXIMIZEBOX`，并用 `SWP_FRAMECHANGED` 刷新非客户区。
2. **覆盖 Map 时序。** `_apply_native_window_style_once` 负责初次应用，`_schedule_native_window_style_reapply` 配合 Map/idle 调用 `_reapply_native_window_style_after_map`，避免只在构造期有效。
3. **用客户区判断鼠标。** `_is_pointer_inside_window` 在 Windows 主路径通过 `GetClientRect` + `ClientToScreen` 排除标题栏；Win32 API 失败时仍回退到 Tk/outer rect，回退不具备同样保证。
4. **隔离几何拥有者。** `_begin_native_titlebar_interaction` / `_finish_native_titlebar_interaction` 用 native quiet period 等待真实标题栏拖动或 Snap 稳定；`_set_window_geometry` 保存 expected geometry，`_configure_matches_expected_geometry` 消费动画写入的确认，避免把动画误判成用户拖动。
5. **负坐标只走 Win32。** `_set_window_outer_position` 对负的绝对 x/y 调用 `_set_native_window_position`（`SetWindowPos`）；调用失败时保持当前位置，不再把负坐标回退给 Tk geometry。收起动画因此保持原窗口尺寸，仅改变外框 y。
6. **resize 保护要有出口。** 正常窗口在样式已验证且 native quiet 结束后应释放过期 fence；样式未验证或最大化时仍可持续阻止，最大化明确不参与停靠。

## 5. 验收证据矩阵

| 证据 | 应确认的内容 | 边界 |
| --- | --- | --- |
| 源码测试 | `tests/test_gui_contract.py`、`tests/test_app_layout.py` 覆盖 HWND/style、停靠状态、几何和指针契约 | 不能代替真实窗口管理器 |
| `compileall` | 源码和入口可编译，排除语法级问题 | 不能证明 HWND 或视觉行为 |
| PyInstaller | 使用项目唯一的 `AiTool桌面工具.spec` 生成待测 EXE，并记录生成物时间戳 | 必须确认随后启动的是该生成物 |
| EXE 启动冒烟 | 实际 EXE 能启动，窗口标题栏、Snap 隔离和顶部停靠链路可继续观察 | 启动成功本身不是 GUI 完成证据 |
| Win32 rect probe | 读取真实顶层 HWND 的 `GetWindowRect`，核对动画前后 outer rect、宽高和 bottom | 不能只看 Tk `geometry()` 字符串 |

真实鼠标拖动标题栏、最终视觉效果和 DND 仍需人工验收或专门 GUI probe；源码测试、compileall、打包或启动都不能替代它们。正确的收起证据是 **height 保持不变，bottom ≈ `work_area.top + 30`**，不是 **height = 30**。

### 本次已确认

最新 EXE 为 `dist/AiTool桌面工具.exe`；构建成功；测试 `133 passed, 16 subtests passed`；Win32 rect probe 展开 `top=0 bottom=840 height=840`，收起 `top=-810 bottom=30 height=840`。这证明 native 定位/自动隐藏状态机，但不等同真实鼠标标题栏拖动全链路。

## 6. 后续排障顺序

1. 先确认正在运行的 EXE 路径、PID 和时间戳，排除旧 EXE 或进程锁。
2. 再确认实际 HWND 是 `GetAncestor(GA_ROOT)` 的顶层句柄，并读取当前 style。
3. 记录同一时刻的 `dock_state`、native interaction/quiet 状态、`_dock_resize_blocked`、pointer 判定和 outer rect。
4. 最后才修改停靠或动画算法；没有前述运行时证据时，不要根据 Tk geometry 或启动表象猜测根因。
