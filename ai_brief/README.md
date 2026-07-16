# ai_brief - AI 每日简报（5 源 · 3 分类）

聚合 5 个信息源，**按类别分组**（新工具 / 工作流 / 行业），注入容器启动头；亦可单独 CLI 输出。stdlib-only，零安装。

## 数据源

| 源 | 类别 | 取法 | 频率 |
|---|---|---|---|
| Simon Willison | 工具 / 工作流 | Atom `simonwillison.net/atom/everything/` | 日更 |
| Changelog | 工具 | RSS `changelog.com/news/feed` | 日更 |
| HN Show HN | 工具（AI/dev 过滤） | RSS `hnrss.org/show` | 实时 |
| TLDR AI | 行业 | RSS 拿期次 + issue 页 HTML 解析 | 日更（工作日） |
| The Rundown AI | 行业 | sitemap + post 页 HTML 解析 | 日更 |

HN Show HN 经关键词过滤（`ai/llm/agent/tool/cli/dev/claude/gpt/cursor/...`），只保留 AI 与开发工具相关条目。

## 用法

```bash
# 全部 5 源，每源 Top 5，规则分类英文
python3 ai_brief/brief.py

# --ai 跨源中文分三类（🛠️新工具 / 🔧工作流 / 📰行业），每类最多 4 条
python3 ai_brief/brief.py --ai

# 只看工具类（Simon + Changelog + HN）
python3 ai_brief/brief.py --source tools

# 看指定源
python3 ai_brief/brief.py --source tldr,simon --top 3

# 保存 + 跳过缓存
python3 ai_brief/brief.py --ai --save --no-cache
```

## flags

| flag | 说明 |
|---|---|
| `--source {all,tools,industry,workflow,tldr,simon,...}` | 源选择，默认 `all`；逗号分隔可组合 |
| `--top N` | 每源 Top N（默认 5）；`--ai` 模式限每类最多 4 条 |
| `--ai` | LLM **跨源分类中文精选**（🛠️新工具 / 🔧工作流 / 📰行业），读 cs 后端 env（haiku/flash 档），失败回退规则英文分类 |
| `--date YYYY-MM-DD` | 指定日期 |
| `--days N` | 取最近 N 期（默认 1） |
| `--save` | 另存 `cache/` |
| `--no-cache` | 跳过 latest 缓存 |
| `--strict` | 失败时非零退出（调试用） |

## 分类

| 分类 | 源 |
|---|---|
| 🛠️ 新工具 | Simon Willison、Changelog、HN Show HN |
| 🔧 工作流 | Simon Willison（流程/方法类条目）、Changelog |
| 📰 行业 | TLDR AI、The Rundown AI |

`--ai` 模式下由 LLM **动态分类**（根据条目内容而非来源），输出更精准。

## 缓存

`latest` 路径同日缓存命中即复用。宿主单跑时缓存落 `ai_brief/cache/` 持久生效；容器为 `--rm`，缓存随容器销毁，故每次 `docker run` 启动头会重新抓取+LLM 摘要（约 15s）。`cache/` 已 gitignore。

## 集成进启动头

`image/entrypoint.sh` §3.6：**有 cs 后端配置**（`BASE_URL`+`AUTH`）才调用 `brief.py --ai --top 5`（跨源分类中文精选），非空则嵌入 `📰 今日 AI 简讯` 块；**无后端**（临时作用域/cc/全新）-> 一行「简讯跳过」提示。BRIEF 空（timeout 杀/全失败）打印诊断行，不阻断启动。

## 取舍

- **stdlib-only**（urllib + xml.etree + re）：Py3.11/3.14 双端零安装（绕 PEP 668 / uvloop / DrvFs 无 exec 位）。
- **Atom/RSS 优先**：Simon/Changelog/HN 走标准 feed 解析（含 Atom 命名空间兼容 + Python 3.14 ElementTree 适配）；TLDR/Rundown 仍走 HTML 网页抓取（无标准 feed）。
- **启动头 `--ai` 分类中文**：按类别分组显更有信息量；haiku/flash 档控延迟/成本（~15s）。后端未配/超时 -> 回退规则英文分类 + 提示。
- **HN Show HN 关键词过滤**：HN 火龙，不过滤会大量非相关条目；关键词覆盖 `ai/llm/agent/tool/cli/dev/claude/gpt/cursor/coder/vibe/mcp/rag` 等。
