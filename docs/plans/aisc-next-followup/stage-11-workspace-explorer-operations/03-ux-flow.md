# Stage 11 UX 流程与交互规则

## 1. Explorer 行为

### 文件

1. 鼠标单击：设置 selected，不调用 preview；
2. 双击：调用 `workspace_open`；
3. 右键：选中当前行并打开文件菜单；
4. 长按拖拽：生成 `application/x-aisc-workspace-path` payload，拖入终端后插入路径；
5. 键盘 Enter：与双击等价，打开文件（Space 仅选中不激活，D11-19）；
6. Shift+F10/Menu key：在当前行打开右键菜单。

单击预览的移除范围仅限文件树（D11-16）：产物（Artifacts）面板行单击仍触发预览，preview pane 保留。

### 文件夹

1. 鼠标单击：展开/折叠；
2. 右键：选中当前行并打开目录菜单；
3. 可作为新建/粘贴目标；
4. 本阶段支持目录复制和重命名，以保持菜单语义一致；
5. 不支持拖入终端。

### 空白区和根目录

空白区域右键视为 workspace 根目录目标。若当前 workspace 未就绪，创建、粘贴和刷新按钮保持 disabled，并给出已有的未选择工作区状态文案。

## 2. 工具栏

Explorer header 按 VS Code Explorer 的密度提供：

```text
[文件/产物 tab]                         [新建文件] [新建文件夹] [刷新]
```

- 新建文件、新建文件夹和刷新使用 `.ui-icon-button`；
- 每个按钮都有 `aria-label`、`title` 和 disabled 状态；
- 新建按钮的目标目录跟随当前选中节点（目录→其中；文件→父目录；无选中→根，D11-17）；
- Compact 宽度下只显示图标，不让按钮挤压 tab；
- 右键菜单仍是完整动作入口，工具栏不成为唯一入口。

## 3. 右键菜单

菜单根据 target 类型和 clipboard 状态动态展示：

| target | 菜单项 |
|---|---|
| 空白/根目录 | 新建文件、新建文件夹、粘贴、刷新 |
| 目录 | 打开/展开、在文件管理器中显示、新建文件、新建文件夹、粘贴、复制文件夹、重命名、刷新 |
| 文件 | 打开、在文件管理器中显示、复制文件、复制路径、重命名 |

菜单项顺序固定，危险/失败不通过颜色单独表达。不可用的粘贴使用 disabled 并保留 tooltip/aria-disabled 原因，避免用户点击后无反馈。

## 4. 名称输入

新建和重命名使用 Explorer 内部的受控名称输入：

- 新建：在目标目录首行插入 inline input，默认聚焦并选中文件名；
- 重命名：原行切换为 inline input，默认选中 basename，保留 extension；
- Enter 提交，Escape 取消，失焦提交仅在输入非空且无校验错误时允许；
- 名称只允许 basename；前端做即时校验，Rust 做最终校验；
- conflict、非法名称、权限错误在输入行附近显示稳定错误，不关闭输入；
- 成功后刷新父目录并选中新节点/新名称；
- 失败时不改变旧树节点和 Explorer clipboard。

## 5. 复制/粘贴

复制文件动作只更新应用内文件剪贴板，并在 Explorer 中显示短时“已复制”反馈；不把路径文本写入系统文本剪贴板。复制路径仍继续写入系统文本剪贴板。

粘贴成功后：

1. 目标目录刷新；
2. 选中新复制的节点；
3. 关闭菜单；
4. 显示短时成功反馈。

粘贴冲突不覆盖，不自动生成 `(1)` 后缀；用户需要自行重命名或选择其他目标。

## 6. 拖入终端

用户从文件行按住鼠标左键拖动：

1. 行进入 dragging 状态，名称和图标保持可识别；
2. 终端区域在 `dragenter/dragover` 时显示轻量 drop target 状态；
3. drop 时只插入路径，不提交 Enter；
4. 终端没有 live session、没有 active pane 或 drop payload 无效时拒绝；
5. drop 后终端重新获得焦点，后续键入继续接在路径后；
6. Escape 或离开终端区域取消 drop 状态。

路径 quoting 规则按宿主策略表实现为纯函数（三种均有单测）：

| 宿主 | 插入形式 |
|---|---|
| PowerShell | 单引号包裹，内部单引号按 PowerShell 规则转义 |
| cmd.exe | 双引号包裹，内部特殊字符按 cmd 规则处理 |
| Unix shell | 单引号包裹，单引号使用标准拼接转义 |

宿主选择以现有 session/runtime 契约为准（D11-14）：当前所有会话都是 Linux 容器 shell，恒选 Unix 策略；插入的是容器内路径 `/root/app/<relative>`（D11-15），不是宿主路径。不依据用户界面语言猜测。

## 7. 视觉规则

- 文件夹使用展开/折叠状态图标；文件按扩展名映射到少量稳定类型图标；
- 不复制 VS Code 的品牌资源或引入新的图标包；
- 图标使用本地受控 SVG/现有 CSS token，尺寸固定，不推动行高变化；
- 图标颜色只作辅助，不用颜色作为唯一类型信息；
- 所有新图标按钮提供 tooltip 和 `aria-label`；
- 右键菜单、inline input 和 drop highlight 复用现有 surface、focus、motion、CSS zoom 规则。

