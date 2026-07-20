# 项目目录重构计划 (v1.3.1)

> 目标：根目录从 ~18 项混杂(Dockerfile/entrypoint/claude-switch/wrapper/_bundle/downloads/commands/启动器/文档…)收敛为按职责分组,清晰可维护。

## 现状(根目录混乱)

根目录混杂：镜像构建输入(Dockerfile/entrypoint.sh/claude-switch/claude-wrapper/claude-settings.json/global-claude.md/mihomo-build-config.js/_bundle/downloads/commands/)、启动器入口(.bat/.sh/.command)、流水线模块(scripts/)、生成器(stage-*.sh)、文档(README/devlog/TODO)、配置(.gitignore/.gitattributes)、锁文件(skills-lock.json)。

## 目标结构

```
.
├── README.md                   # 根（GitHub 自动显示，约定根）
├── .gitignore / .gitattributes
├── 一键启动_AI工作站.bat        # 根入口（双击）→ scripts/run.ps1
├── 启动_AI工作站.sh             # 根入口 → scripts/run.sh
├── 启动_AI工作站.command        # macOS 双击 → .sh
├── skills-lock.json             # 锁文件（约定根，未被构建/启动器引用）
├── image/                       # ★ 镜像构建上下文（Dockerfile + 全部 COPY 源）
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── claude-switch
│   ├── claude-wrapper
│   ├── claude-settings.json
│   ├── global-claude.md
│   ├── mihomo-build-config.js
│   ├── commands/                # gstack 斜杠命令
│   ├── _bundle/                 # 内置插件+技能（~24MB，纳入 git）
│   └── downloads/               # mihomo+geodata（~38MB，纳入 git）
├── scripts/                     # 启动器流水线（已有，不动）
├── tools/                       # 一次性生成器
│   ├── stage-skills.sh          #   生成 image/_bundle
│   └── stage-mihomo.sh          #   生成 image/downloads
└── docs/
    ├── devlog.md
    └── TODO/                    # TODO.md + PLAN-*.md
```

根目录从 ~18 项 → **7 项**(README + 2 配置 + 3 入口 + skills-lock)。其余按 `image/`/`scripts/`/`tools/`/`docs/` 分组。

## 关键设计

- **D1 · 构建上下文 = `image/`**:Dockerfile 的 `COPY` 全是相对上下文(`_bundle/`/`commands/`/`downloads/`/`entrypoint.sh`/`claude-switch`…)。把 Dockerfile + 所有 COPY 源都搬进 `image/`,以 `image/` 为上下文 → **COPY 路径零改动**。仅构建命令加 `-f image/Dockerfile` + 上下文改 `image/`。
- **D2 · 额外收益——构建更快**:当前上下文=根(含 `.git/` + 62MB 二进制 + scripts/docs/.claude 等),`docker build` 传上下文慢。改 `image/` 后上下文仅构建输入,**传输更小更快**。
- **D3 · `.gitattributes`/`.gitignore` 不动**:模式全局(`*.sh`/`*.ps1`/`claude-switch` 按文件名匹配子目录;`.claude/`/`.deploy/` 全局忽略)。移动后仍生效。
- **D4 · 宿主侧 `.claude/mihomo/` 不动**:02 写、04 挂载的代理配置在根 `.claude/mihomo/config.yaml`(宿主运行时产物,非镜像输入),留在根。
- **D5 · 入口不动**:`.bat`/`.sh`/`.command` 留根(双击入口),引用 `scripts/`(留根)。`scripts/` 内仅 `03_build_image` 改构建命令。

## 文件移动(git mv)

搬到 `image/`:Dockerfile、entrypoint.sh、claude-switch、claude-wrapper、claude-settings.json、global-claude.md、mihomo-build-config.js、commands/、_bundle/、downloads/
搬到 `tools/`:stage-skills.sh、stage-mihomo.sh
搬到 `docs/`:devlog.md、TODO/(TODO.md + PLAN-*.md)
留根:README.md、.gitignore、.gitattributes、.bat、.sh、.command、skills-lock.json、scripts/

## 路径修改(仅 4 处 + 文档)

1. **`scripts/03_build_image.sh`**：构建命令加 `-f` + 上下文改 `image/`
   - `docker build $cache_flag --build-arg ... -t "$IMAGE" "$PROJECT_ROOT"`
   - → `docker build $cache_flag --build-arg ... -f "$PROJECT_ROOT/image/Dockerfile" -t "$IMAGE" "$PROJECT_ROOT/image"`
2. **`scripts/03_build_image.ps1`**：同上
   - `$buildArgs += @('--build-arg', $mirrorArg, ..., '-t', $Image, $ProjectRoot)`
   - → `$buildArgs += @('-f', "$ProjectRoot\image\Dockerfile", '--build-arg', $mirrorArg, ..., '-t', $Image, "$ProjectRoot\image")`
3. **`tools/stage-skills.sh`**(从根搬来)：`DST` 路径
   - `DST="$(cd "$(dirname "$0")" && pwd)/_bundle"` → `DST="$(cd "$(dirname "$0")/.." && pwd)/image/_bundle"`
4. **`tools/stage-mihomo.sh`**(从根搬来)：`DST` 路径
   - `DST="$(cd "$(dirname "$0")" && pwd)/downloads"` → `DST="$(cd "$(dirname "$0")/.." && pwd)/image/downloads"`
5. **`README.md`**：项目结构章节重写为新布局;引用更新(devlog.md → docs/devlog.md,stage-*.sh → tools/)。
6. **`docs/devlog.md`**：加 v1.3.1 条目(目录重构)。

## 不改的(已确认无引用冲突)

- **Dockerfile**:COPY 路径全相对上下文,搬 image/ 后仍生效,零改动。
- **entrypoint.sh / claude-switch / claude-wrapper / mihomo-build-config.js / global-claude.md / claude-settings.json / commands/**:仅被 Dockerfile COPY(容器内消费),无宿主脚本引用,搬 image/ 零影响。
- **scripts/ 其余模块**(01/02/04/run/_state):引用 `$PROJECT_ROOT/.claude/mihomo/`(根,不动),无 image/ 引用,零改动。
- **根入口**(.bat/.sh/.command):引用 `scripts/`(根,不动),零改动。
- **.gitattributes/.gitignore**:全局模式,零改动。

## 实施步骤(等你确认)

1. `mkdir image/ tools/ docs/` + `git mv` 批量搬迁(10 文件/目录 → image/,2 → tools/,2 → docs/)。
2. 改 `scripts/03_build_image.{sh,ps1}` 构建命令;改 `tools/stage-skills.sh`/`tools/stage-mihomo.sh` 的 DST。
3. 更新 README 结构章节 + 引用;devlog 加 v1.3.1。
4. 测试:
   - `bash -n scripts/*.sh tools/*.sh` + PS 语法。
   - `docker build -f image/Dockerfile image/` 构建成功(验证上下文+COPY)。
   - e2e:`printf 'n\n1\n' | bash 启动_AI工作站.sh`(镜像存在→run)→ docker run;Windows 同。
   - `bash tools/stage-mihomo.sh` 写到 `image/downloads/`(验证 DST)。
5. 提交 + 推送 develop。

## 风险/取舍

- **构建上下文变更**:`-f image/Dockerfile image/` 必须对(上下文=image/)。错则 COPY 找不到源→构建崩。测试覆盖。
- **大目录 git mv**:`_bundle`(24MB)+`downloads`(38MB)git mv,git 识别为 rename,历史保留。提交体积不大(rename 不重复存内容)。
- **`docs/devlog.md` 路径**:README 引用更新;devlog 内部无路径引用。
- **`skills-lock.json` 留根**:未被构建/启动器引用(疑似 skill 工具元数据),留根(锁文件约定根)。如你想挪可指定。
- **命名**:`image/`/`tools/`/`docs/` 可换(`docker/`/`bin/`/`doc/` 等),确认时说即可。
