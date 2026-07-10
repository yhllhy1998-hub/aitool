# AiTool Desktop UI 设计规范

> 本文档是 `src/aitool_desktop/app.py` 的 UI 设计准则。修改界面前必读，避免重蹈覆辙。

---

## 1. 框架与依赖

| 项目 | 值 | 备注 |
|------|-----|------|
| GUI 框架 | CustomTkinter + tkinterdnd2 | 不要用 pywebview |
| 外壳类 | `DesktopToolApp(ctk.CTk, TkinterDnD.DnDWrapper)` | 必须双继承 |
| 窗口模式 | `overrideredirect(False)` | 保留 Windows 原生标题栏（最小化/最大化/关闭） |
| 置顶 | `attributes("-topmost", True)` | 默认置顶，通过 📌 按钮切换 |
| 窗口尺寸 | `360x580`，min `320x420`，max `480x800` | |

---

## 2. 颜色体系（THEME）

```python
THEME = {
    "bg":        "#1a1b2e",   # 主背景
    "surface":   "#232438",   # 中转站/状态栏背景
    "elevated":  "#2a2b42",   # Toast / 弹出菜单背景
    "hover":     "#313349",   # 按钮 hover
    "card":      "#262840",   # 卡片背景（中转站条目 + 动作卡片）
    "border":    "#353755",   # 卡片边框
    "text":      "#f0f1f8",   # 主文字（高亮度）
    "text_sec":  "#b8bbd8",   # 次要文字（标题栏、状态栏）
    "text_muted":"#8a8db0",   # 辅助文字（描述、提示）
    "primary":   "#7c6ef0",   # 主按钮
    "primary_hover":"#8b7ff5",
    "danger":    "#e85a5a",   # 删除按钮
    "success":   "#4ade80",   # 状态就绪
    "warning":   "#fbbf24",   # 状态执行中
}
```

### 亮度原则
- **小字（≤11pt）必须用高亮度颜色**：`text_sec` 或 `text`，**禁止用 `text_muted` 显示需要阅读的文字**
- `text_muted` 仅用于：描述行、提示语、空状态文字
- 早期 `text_sec=#9295b0` / `text_muted=#5d6080` 太暗，中文小字糊成一片，已提亮

---

## 3. 字体规范

```python
FONT = "Microsoft YaHei UI"     # 全局 UI 字体
FONT_MONO = "Consolas"          # 参数编辑框等宽字体
```

### 字号阶梯

| 用途 | 字号 | weight |
|------|------|--------|
| 窗口标题（已移除） | — | — |
| 区域标题（中转站/快捷动作） | 11pt | bold |
| 中转站条目名称 | 12pt | normal |
| 中转站条目图标 | 16pt | — |
| 动作卡片标题 | 10pt | bold |
| 动作卡片描述 | 8pt | normal |
| 动作卡片图标 | 18pt | — |
| 提示文字（拖入收藏…） | 10pt | normal |
| 状态栏文字 | 11pt | normal |
| Toast 消息 | 12pt | normal |
| 对话框标签 | 12pt | normal |
| 对话框输入框 | 12pt | normal |
| 对话框按钮 | 12pt | normal |
| 对话框参数编辑 | 11pt mono | normal |

### 字体使用规则
- **所有 CTk 控件**：必须用 `ctk.CTkFont(family=FONT, size=N)`
- **所有原生 tk.Label**：必须用 `font=(FONT, N)` 或 `font=(FONT, N, "bold")`
- **禁止裸用 `ctk.CTkFont(size=N)` 不带 family**：会回退到默认字体，中文显示不一致

---

## 4. 布局结构

### 4.1 主窗口 Grid

```
row=0: 中转站区域（含标题栏 + 置顶按钮 + 条目列表）
row=1: 快捷动作区域（含标题栏 + 加号按钮 + 卡片滚动列表）  ← weight=1 可伸缩
row=2: 状态栏
```

### 4.2 中转站区域

```
┌─────────────────────────────────────┐
│ 中转站          拖入收藏·拖出复制  📌│  ← header（CTkFrame transparent）
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 📁  文件夹名称              ✕  │ │  ← 条目卡片
│ │ 📄  文件名称                ✕  │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### 4.3 快捷动作区域

```
┌─────────────────────────────────────┐
│ 快捷动作                        ➕  │  ← header（CTkFrame transparent）
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 📋  文件夹覆盖复制         ›  │ │  ← 动作卡片
│ │     全量覆盖目标目录           │ │
│ │ ⚡  启动脚本               ›  │ │
│ │     运行.bat/.cmd脚本          │ │
│ │ 🔄  SVN 更新              ›  │ │
│ │     svn update工作副本         │ │
│ └─────────────────────────────────┘ │
│               ↕ 可滚动               │
└─────────────────────────────────────┘
```

---

## 5. 卡片行对齐规范（最重要的规则！）

### 5.1 图标列固定宽度

中转站条目和动作卡片的图标列**必须用 `grid_columnconfigure(0, minsize=42, weight=0)`** 固定为 42px。

```python
# ✅ 正确
item.grid_columnconfigure(0, minsize=42, weight=0)
item.grid_columnconfigure(1, weight=1)
icon_label.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

# ❌ 错误——用 width / padx 自适应，emoji 宽度不同会导致名称错位
icon_label = tk.Label(frame, text="⚡", width=3, ...)  # ⚡ 比 📋 窄，错位
icon_label = tk.Label(frame, text="⚡", padx=6, ...)   # 同上
```

### 5.2 为什么不能用 width / padx

| emoji | Unicode 宽度 | tk.Label 自适应后 |
|-------|-------------|-------------------|
| 📋 | 双字节 | 列宽约 30px |
| 🔄 | 双字节 | 列宽约 30px |
| ⚡ | 单字节 | 列宽约 22px ← **偏窄，名称左移** |

用 `minsize=42` + `sticky="nsew"` 让图标在固定格子里居中，**与 emoji 宽度无关**。

### 5.3 图标垂直位置

```python
icon_label.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
```

- `sticky="nsew"`：图标在格子内拉伸居中
- `pady=(0, 8)`：上边距 0，下边距 8，视觉上图标偏上一点（emoji 基线偏低，需要补偿）

### 5.4 名称列对齐

中转站和动作卡片的名称列 grid 参数**必须一致**：

```python
# 两处都是
body.grid(row=0, column=1, sticky="ew", padx=2, pady=4)
```

---

## 6. 控件选择规范

### 6.1 什么时候用原生 `tk.Label` vs `ctk.CTkLabel`

| 场景 | 控件 | 原因 |
|------|------|------|
| 中转站图标 | `tk.Label` | 需要拖出（`drag_source_register`），CTkLabel 不触发 `<<DragInitCmd>>` |
| 中转站名称 | `tk.Label` | 同上 |
| 动作卡片图标 | `tk.Label` | 需要彩色 emoji，CTkLabel 的 Canvas 渲染会丢失颜色 |
| 动作卡片标题/描述 | `tk.Label` | 与中转站对齐（CTkLabel 有内部 padding，会导致缩进不一致） |
| 区域标题 | `ctk.CTkLabel` | 无拖放需求，样式方便 |
| 状态栏 | `ctk.CTkLabel` | 同上 |
| 空状态提示 | `ctk.CTkLabel` | 同上 |

### 6.2 tk.Label 的背景色

原生 `tk.Label` **必须手动设 `bg=THEME["card"]`**，否则是系统默认灰色。

```python
# ✅ 正确
tk.Label(frame, text="...", bg=THEME["card"], fg=THEME["text"], font=(FONT, 12))

# ❌ 错误——忘记 bg，灰底破坏卡片一致性
tk.Label(frame, text="...", fg=THEME["text"], font=(FONT, 12))
```

---

## 7. 按钮规范

### 7.1 统一按钮尺寸

所有小图标按钮**必须**用相同尺寸：

```python
width=24, height=24, corner_radius=6
```

| 按钮 | 位置 | text | fg_color | font |
|------|------|------|----------|------|
| 📌 置顶 | 中转站标题栏 | "📌"/"📍" | hover | FONT 13pt |
| ➕ 添加 | 快捷动作标题栏 | "➕" | primary | FONT 13pt |
| ✕ 移除 | 中转站条目 | "✕" | transparent | FONT 11pt |
| › 编辑 | 动作卡片 | "›" | transparent | FONT 20pt |

### 7.2 CTkButton 禁忌

```python
# ❌ 禁止使用以下参数（CTkButton 不支持，会崩溃）
ctk.CTkButton(..., padx=0, pady=0)      # 崩溃！
ctk.CTkButton(..., anchor="center")     # 可能导致按钮变高

# ✅ 居中文字用默认行为即可，CTkButton 默认居中
ctk.CTkButton(..., text="➕", width=24, height=24)
```

### 7.3 emoji 按钮 vs 文字按钮

- 小尺寸按钮（24x24）用 emoji：`📌 ➕ ✕ ›`
- **禁止用全角字符** `＋`：显示太小且偏
- **禁止用半角 `+` + 大字号**：会撑高按钮

---

## 8. 图标规范

### 8.1 动作类型图标映射

```python
ACTION_ICON_TEXT = {
    "folder-copy": "📋",
    "launch-bat": "⚡",
    "update-svn": "🔄",
}

ACTION_ICON_COLORS = {
    "folder-copy": "#60a5fa",   # 蓝
    "launch-bat": "#fbbf24",    # 黄
    "update-svn": "#4ade80",    # 绿
}
```

### 8.2 图标渲染

必须用 `tk.Label` + `fg=color` 渲染彩色 emoji：

```python
icon_label = tk.Label(frame, text=icon_text,
                      bg=THEME["card"], fg=icon_color,
                      font=(FONT, 18))
```

---

## 9. 滚动区域规范

### 9.1 禁止用 CTkScrollableFrame

`CTkScrollableFrame` 内部 Canvas 会拦截拖放事件，导致文件拖入失效。

### 9.2 正确做法：普通 Frame + Canvas + Scrollbar

```python
self._card_canvas = tk.Canvas(self.card_scroll, bg=THEME["bg"],
                              highlightthickness=0, bd=0)
scrollbar = ctk.CTkScrollbar(self.card_scroll, command=self._card_canvas.yview)
self._card_inner = ctk.CTkFrame(self._card_canvas, fg_color=THEME["bg"])
self._card_window = self._card_canvas.create_window((0, 0),
                            window=self._card_inner, anchor="nw")
self._card_canvas.configure(yscrollcommand=scrollbar.set)
```

---

## 10. 拖放规范

### 10.1 拖入（Drop）

- 全窗口注册：`self.drop_target_register(DND_FILES)`
- 全窗口绑定：`self.dnd_bind("<<Drop>>", self._on_global_drop)`
- 根据鼠标 Y 坐标判断目标区域：
  - Y < 中转站底部 → 收藏到中转站
  - Y ≥ 中转站底部 → 创建启动模块

### 10.2 拖出（Drag Out）

- 必须绑定到**原生 `tk.Label`**（CTkLabel 不触发 `<<DragInitCmd>>`）
- 返回值格式：`(COPY, DND_FILES, "{path}")`
- **路径必须用大括号包裹**：`"{" + entry.path + "}"`

```python
def _on_station_drag_out(self, entry):
    from tkinterdnd2 import COPY
    tcl_path = "{" + entry.path + "}"
    return (COPY, DND_FILES, tcl_path)
```

---

## 11. 对话框规范

### 11.1 统一样式

```python
dialog = ctk.CTkToplevel(self)
dialog.configure(fg_color=THEME["bg"])
dialog.transient(self)
dialog.grab_set()
```

### 11.2 编辑对话框必须包含

- 名称输入框
- 参数编辑区
- **删除按钮**（红色 danger，带确认弹窗）
- 保存按钮（primary 紫色）
- 快捷动作额外有：校验按钮、执行按钮

### 11.3 字体

对话框内所有控件必须用 `ctk.CTkFont(family=FONT, size=12)`，参数编辑框用 `FONT_MONO`。

---

## 12. 常见错误清单

| 错误 | 症状 | 解决 |
|------|------|------|
| 用 CTkLabel 做拖出源 | `<<DragInitCmd>>` 不触发 | 改用 tk.Label |
| 拖出返回值无大括号 | 回调触发但文件不出现 | `"{path}"` 包裹 |
| 图标用 width=N | 不同 emoji 对齐错位 | `minsize=42` + `sticky="nsew"` |
| 用 CTkScrollableFrame | 拖放事件被拦截 | 普通 Frame + Canvas |
| CTkButton 加 padx/pady | 程序崩溃 | 去掉，CTkButton 不支持 |
| 小字用 text_muted | 中文看不清 | 用 text_sec 或提亮 muted |
| 全角 ＋ 做按钮 | 显示太小 | 用 emoji ➕ |
| tk.Label 忘记 bg | 灰底破坏一致性 | `bg=THEME["card"]` |
| 字体不传 family | 中英文混排不一致 | 所有地方带 `family=FONT` |
| overrideredirect(True) | 无 Windows 标题栏 | 保持 `False` |

---

## 13. 修改检查清单

改完 UI 后逐项检查：

- [ ] 中转站和动作卡片的图标列宽度都是 `minsize=42`
- [ ] 中转站和动作卡片的名称起始 X 坐标对齐
- [ ] 所有 `tk.Label` 都设了 `bg=THEME["card"]`
- [ ] 所有字体都带 `family=FONT`
- [ ] 所有小图标按钮都是 `24x24, corner_radius=6`
- [ ] 程序能正常启动（`python -c "from src.aitool_desktop.app import main"`)
- [ ] 拖入文件到中转站正常
- [ ] 拖入文件到动作区正常
- [ ] 拖出文件到资源管理器正常
- [ ] 编辑对话框有删除按钮
