# -*- coding: utf-8 -*-
"""AISC v2.1.9 开发周报 PDF 生成脚本(一次性,输出到桌面)"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, KeepTogether,
)

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "AISC-v2.1.9-开发周报.pdf")

pdfmetrics.registerFont(TTFont("YaHei", r"C:\Windows\Fonts\msyh.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("YaHei-Bold", r"C:\Windows\Fonts\msyhbd.ttc", subfontIndex=0))
registerFontFamily("YaHei", normal="YaHei", bold="YaHei-Bold", italic="YaHei", boldItalic="YaHei-Bold")

INK = colors.HexColor("#1a2433")
ACCENT = colors.HexColor("#1f3864")
ACCENT2 = colors.HexColor("#2e5395")
MUTED = colors.HexColor("#5b6b7f")
LINE = colors.HexColor("#c9d3e0")
ZEBRA = colors.HexColor("#eef2f8")
HEADBG = colors.HexColor("#1f3864")

S = {
    "title": ParagraphStyle("title", fontName="YaHei-Bold", fontSize=20, leading=28,
                            textColor=ACCENT, spaceAfter=2),
    "subtitle": ParagraphStyle("subtitle", fontName="YaHei", fontSize=9.5, leading=15,
                               textColor=MUTED, spaceAfter=10),
    "h1": ParagraphStyle("h1", fontName="YaHei-Bold", fontSize=13, leading=19,
                         textColor=ACCENT, spaceBefore=14, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="YaHei-Bold", fontSize=10.5, leading=16,
                         textColor=ACCENT2, spaceBefore=8, spaceAfter=3),
    "body": ParagraphStyle("body", fontName="YaHei", fontSize=9.5, leading=15.5,
                           textColor=INK, spaceAfter=4, wordWrap="CJK"),
    "bullet": ParagraphStyle("bullet", fontName="YaHei", fontSize=9.5, leading=15.5,
                             textColor=INK, spaceAfter=2.5, wordWrap="CJK",
                             leftIndent=14, firstLineIndent=-9),
    "cell": ParagraphStyle("cell", fontName="YaHei", fontSize=8.8, leading=13,
                           textColor=INK, wordWrap="CJK"),
    "cellc": ParagraphStyle("cellc", fontName="YaHei", fontSize=8.8, leading=13,
                            textColor=INK, wordWrap="CJK", alignment=1),
    "hcell": ParagraphStyle("hcell", fontName="YaHei-Bold", fontSize=8.8, leading=13,
                            textColor=colors.white, wordWrap="CJK", alignment=1),
}


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def B(t):
    return "<b>" + esc(t) + "</b>"


def bullets(items):
    return [Paragraph("• " + it, S["bullet"]) for it in items]


def h1(text):
    return [Paragraph(esc(text), S["h1"]),
            HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=6)]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.setFont("YaHei", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9.5 * mm, "AISC v2.1.9 开发周报 · 2026-08-30 ~ 2026-09-07")
    canvas.drawRightString(A4[0] - 18 * mm, 9.5 * mm, "第 %d 页" % doc.page)
    canvas.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4,
                      leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=20 * mm,
                      title="AISC v2.1.9 开发周报", author="AISC")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])

story = []
story.append(Paragraph("AISC v2.1.9 开发周报", S["title"]))
story.append(Paragraph("周期 2026-08-30 ~ 2026-09-07 ｜ v2.1.9-dev Preview 已发布(2026-09-07)", S["subtitle"]))
story.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=8))

# ── 一、周期概览 ──────────────────────────────────────────────
story += h1("一、周期概览")
overview = Table([
    [Paragraph("版本", S["hcell"]), Paragraph(esc("v2.1.9.dev0(tag v2.1.9-dev @ f59cb98,prerelease 已发布)"), S["cell"]), "", Paragraph("周期", S["hcell"]), Paragraph(esc("2026-08-30 ~ 09-07(9 天)"), S["cell"])],
    [Paragraph("提交", S["hcell"]), Paragraph(esc("develop 分支 133 个提交"), S["cell"]), "", Paragraph("CI", S["hcell"]), Paragraph(esc("五 lane 全绿(cli-sidecar / Workbench ×2 / Bundle / NSIS)"), S["cell"])],
    [Paragraph("测试门禁", S["hcell"]), Paragraph(esc("pytest 1146 ｜ vitest 433+ ｜ cargo 293+ ｜ vue-tsc 干净 ｜ 版本一致性门 6 项"), S["cell"]), "", Paragraph("发布物", S["hcell"]), Paragraph(esc("NSIS 安装包 125MB + sha256(GitHub Release)"), S["cell"])],
], colWidths=[18 * mm, 62 * mm, 3 * mm, 18 * mm, 73 * mm])
overview.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (0, -1), HEADBG), ("BACKGROUND", (3, 0), (3, -1), HEADBG),
    ("GRID", (0, 0), (-1, -1), 0.5, LINE),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("SPAN", (1, 0), (1, 0)),
]))
story.append(overview)
story.append(Spacer(1, 4))
story.append(Paragraph(
    esc("本周期为 2.1.9 完整迭代周期,六条主线全部收官:挂账清偿 + 线上根因修复、优化批次 O1-O9、"
        "Provider 管理页重设计(PP 批)、两大新功能(F1 SSH 远程工作区 / F2 宿主工具 MCP)、"
        "低配机性能专项 PERF P1-P9 及其审查修复批,最终冻结版本并发布 v2.1.9-dev Preview。"), S["body"]))

# ── 二、主要工作 ──────────────────────────────────────────────
story += h1("二、主要工作")

def section(title, items):
    block = [Paragraph(esc(title), S["h2"])] + bullets(items)
    story.append(KeepTogether(block))

section("1. 四挂账清偿批(T1-T6,D-0~D-6)", [
    B("#53") + esc(" 隔离测试假象根治:全 suite 环境泄漏致 7 模块误报,钉第二 tempdir 双模式转绿;"),
    B("#50") + esc(" ble.sh 移除(vendor + 门控 + 镜像重建),幽灵文本统一由 zsh 原生交付;"),
    B("#3") + esc(" 文件变更归因:落地容器内 aisc shim 登记桥(env 回填 + 存量工作区补配),呈现层经用户裁决降级为平铺列表 + 类型徽章 + 模糊/正则搜索;"),
    B("#28") + esc(" VM 终端振荡三轮收敛:探针仅首屏引导 + sticky 1s 冷却 + 整格校正阈值,fit 遥测自诊断浮层留作安全网,VM + 真机双验 PASS;"),
    B("#59") + esc(" 订阅解析 IncompleteRead 不再裸崩,统一走既有回退链。"),
])
section("2. nairong #61 线上崩溃根因链(三轮热修,D-7)", [
    esc("现象为 bash 终端零输出退出。逐层排除 fit 假说后,真凶定位:zh-CN 系统下 docker-py "
        "from_env() 读 docker context meta.json 不带 encoding → GBK 解码崩溃 → sidecar 静默 exit 1。"),
    esc("三层修复:docker.from_env 安全工厂(任意异常回退默认命名管道端点)、sidecar stderr 入流可见、"
        "session 生命周期落时间线;外加 PYTHONUTF8=1 进程级兜底。用户 VM 中文用户名路径复现 PASS。"),
])
section("3. 构建网络韧性 + 教学补齐(T7-T8,D-8/D-9)", [
    esc("Dockerfile 全动作审查出 CN 网络五个无兜底点,全部硬化:apt 重试 ×3、pip 清华源兜底、"
        "npm file-manifest + alias 离线方案(离线重装实证通过)、yazi 预设 ghproxy 链、geodata 清理;"),
    esc("宿主侧镜像链预拉(本地命中跳过 → 三镜像链 600s → 失败给 registry-mirrors 三段指引);中毒链演练 + 离线全量重装验证;"),
    esc("zsh 默认 shell 化后的 help 教学补齐:heredoc 逐字节复刻 + SSOT 防漂移测试三连;"),
    esc("CI Windows Docker 冷启动竞态改就绪门(30×10s),其后四 lane 稳定绿。"),
])
section("4. 优化批次 O1-O9(D-11,规格冻结 + 三轮手测)", [
    B("O1") + esc(" 分屏关闭按钮 × z 序修复(让出滚动条带 + 恒可点,几何契约钉进测试);"),
    B("O2") + esc(" 终端输出不再截断:磁盘 spool 全量落盘 + 「加载更早」按需回放(≤2MiB/页),offset/committed 分离防半写错位;"),
    B("O3") + esc(" 渲染路径三态遥测:WebGL 激活/构造失败/context-loss 落共享时间线,软渲染(SwiftShader/llvmpipe)低配信号可观测;"),
    B("O4") + esc(" Provider 切换链重构:在线 /models 抓取移出主路径 + 幂等快路径 + 舞步重排,端到端 8.5s → 2.2s;"),
    B("O5") + esc(" cc-switch daemon 60s 健康巡检自愈(kill -9 注入验证,60s 窗内自动恢复);"),
    B("O6") + esc(" 轮询自适应退避状态机(慢刷新升档 5s→10s→20s)+ doctor WSL 内存检查引导;"),
    B("O7") + esc(" build cache 清理产品化:设置页「磁盘与缓存」组,df 摘要 + 一键清理(绝不 system prune / -a,<1h 拒绝);"),
    B("O8") + esc(" 冷启动两刀:出厂资产增量同步(cp -ru 只写新增/更新,用户自建不动)+ mihomo 探测收紧;"),
    B("O9") + esc(" 懒布局取消,重开工作区恒全新默认单 bash tab(用户裁决);"),
    esc("手测反馈批同轮落地:agent 原子写 rename 误报「⇄ 移动」根治(TempRenameTracker 1s 窗配对)、"
        "codex 新文件误标「修改」修复(批次内类型格合并)、窄列 TUI 守卫扩展至 bash、手动唤起 agent 即清屏。"),
])
section("5. Provider 管理页重设计(PP 批,P1-P4 + r2-r8 七轮手测,D-12)", [
    esc("对标 cc-switch 桌面端整体重做:P1 数据契约(上游格式/显示列/映射目录双侧透出 + 舞步保留)、"
        "P2 专属编辑页(简易/高级两档 + 双侧映射编辑器 + 预设快速添加)、P3 完全卡片化(ProviderCard 替换表格)、P4 打磨与死代码清除;"),
    esc("手测连修:cc-switch 静默降级事故根治、官方卡置顶、切换进度底部悬浮卡、按模型用量表(映射生效铁证)、"
        "codex catalog stale 接管 + op_fetch_models 补 codex 分支、裸 Ctrl+C/V 复制粘贴接管。"),
])
section("6. F1 SSH 远程工作区(新功能,D-10,2026-09-03~05)", [
    esc("基于 mutagen v0.16.4 的远程开发双向同步(v0.17+ 转 SSPL,裁决锁定 MIT 末系列并四平台 sha256 pin);"),
    esc("影子目录 = 真工作区,工作区身份链 11 触点零改动;受管 ~/.ssh/config 别名段替代 wrapper(实测 1GiB/123s ≈ 8.4MB/s,与裸管道持平);"),
    esc("超大内容三层策略:排除规则 SSOT + 超量警示 + 按需拉取(远端路径点击浏览,钉根 containment 含 .. 段归一化防穿越);"),
    esc("取消同步即时化(先标停用清内容,后台再终止会话/daemon);磁盘防护三层(容量警示 + 2GiB 低磁盘自动暂停 + 恢复/新建门槛);"),
    esc("两个深坑根治:mutagen agent 包(78MB tar.gz)必须与二进制共位——vendor 链丢包曾致 beta 拨号全灭、四会话永久 connecting;单测污染真实 ~/.ssh/config——路径注入式隔离。"),
])
section("7. F2 宿主工具 MCP(新功能,D-10,三轮手测 PASS)", [
    esc("host_mcp.rs:Rust 后端首个本地监听服务(127.0.0.1 动态端口 + 每进程 token);"),
    esc("安全模型:宿主命令白名单三级解析(program/name/basename)+ git 只读筛 + cwd containment;"),
    esc("注入链:start_runtime --host-mcp-url → 容器内注册脚本对 claude(.mcp.json)/codex(config.toml)幂等注入;mihomo TUN 场景对策(dns-hijack 收窄 + docker.internal DIRECT);"),
    esc("设置页白名单管理 UI + socket 级端到端测试;MCP 信封(tools/call 必须 {content,isError})两轮翻车后钉死。"),
])
section("8. PERF P1-P9 低配机性能专项(D-13,2026-09-05~06)", [
    esc("背景:8GB + 弱 CPU/慢盘复合低配机全场景卡顿。以探针事实为基线(aisc.log 实测轮询链海量 spawn),九个子项全交付:"),
    B("P1") + esc(" tick 合并:5s 轮询 2 次 spawn → 1 次(runtime status 单命令,best-effort services 不拖垮 snapshot);"),
    B("P2") + esc(" 会话税根治:EOF 驱动退出,每会话常驻 5 次 Docker API/s + 10 次文件读/s → ≈0,resize 感知不迟滞;"),
    B("P3") + esc(" 容器内 spawn 三件套:历史 TSV 批量 flush、env-inject 缓存、巡检快检;"),
    B("P4") + esc(" SDK 执行器进命令层:热读面进程内 named pipe,docker.exe 子进程链归零(CLI 回退保底);"),
    B("P5a/P5b") + esc(" 锁互操作实验(Python 文件锁 ↔ Rust fs4 双向互斥实证)+ lease 心跳 Rust 直写,每工作区 -240 spawn/h;"),
    B("P6a") + esc(" 热轮询 Rust 直连 named pipe(docker_api.rs):稳态 tick 0 spawn,空闲卡顿根治;"),
    B("P7") + esc(" 轮询退避扩展:后台 60s / 失焦 30s / provider 挂梯子;"),
    B("P8") + esc(" 低配模式:≤8.5GB 自动开启 + 一次性通知,docker --memory/--cpus 容器限额,.wslconfig 保键合并;"),
    B("P9") + esc(" daemon 就绪等待去 spawn(pgrep + 退避,实测 1775ms)+ preset --agent all 双合一。"),
])
section("9. PERF 审查修复批(7 项:2 Blocker / 2 High / 2 Medium / 1 Low)", [
    B("R1") + esc("(最重要语义 bug)P6a light 快照失败被误折叠为 Ok(unknown+stale),降级链断 → 改 Err 由前端回退 CLI;"),
    esc("R2 exec demux(stdout/stderr 分离 + timeout/input 回退 CLI)、R3 ps 模板(sparse=True 免逐行 inspect 隐藏往返)、"
        "R4 零 CLI 泄漏断言、R5 低配 memory 双端校验(拒「3gg」类多后缀)、R6 --agent all 明示 best-effort、R7 丢失窗口文档化;"),
    esc("另自查修复 P3a:TSV _unescape 顺序替换真 bug(字面 \\t 序列损坏),单遍成对消费根治。"),
])
section("10. 发布收口(2026-09-06~07)", [
    esc("发布前手测三轮连修:设置页卡死根治(P8 漏性能组键致渲染断链,CDP 远程调试取证)、"
        "P7 provider 梯子失败/未就绪 tri-state 语义 + GuidePane 自动开会话、"
        "P6a light 快照双未命中自报 not_found 覆写刚启动 running 状态——修复三层:light 双未命中返 Err 走全量、"
        "启动后 15s not_found 宽限、provider 稳定门 3s×8 专用重试,端到端验证 claude 页 1s configured 会话自动开;"),
    esc("provider probe/skip 原因遥测转正进 aisc.log;"),
    esc("f59cb98 四件套冻结(VERSION / tauri.conf / fixture / release notes)+ plans 归档 + tag v2.1.9-dev "
        "→ GitHub Release「AISC v2.1.9-dev Preview」发布(NSIS 125MB + sha256)。"),
])

# ── 三、性能优化成效 ──────────────────────────────────────────
story += h1("三、性能优化成效(实测数据)")
perf_rows = [
    ["指标", "改造前", "改造后"],
    ["活跃单工作区稳态进程 spawn", "约 555~609 次/小时", "稳态 tick 归零(P1/P4/P5b/P6a 叠加)"],
    ["每会话 Docker API 常驻调用", "5 次/秒 + 10 次文件读/秒", "≈0(EOF 驱动,P2)"],
    ["lease 心跳开销", "240 次 spawn/小时/工作区", "Rust 直写,0 spawn(P5b)"],
    ["Provider 切换端到端", "8.5~9.7s(p95 双峰)", "2.2s(O4 舞步重排 + 主路径零网络)"],
    ["单次 aisc.exe spawn 固定开销", "约 750ms(onefile 解包 + Python 启动)", "热路径进程内直连,不再 spawn(P4/P6a)"],
    ["容器二次冷启动", "全量复制(首启 22.6s)", "1.9s(出厂资产增量同步,O8)"],
    ["daemon 就绪探测", "每轮 spawn 探测", "pgrep + 退避 1775ms 实测(P9)"],
]
perf = Table(
    [[Paragraph(esc(c), S["hcell"] if r == 0 else S["cell"]) for c in row] for r, row in enumerate(perf_rows)],
    colWidths=[52 * mm, 60 * mm, 62 * mm], repeatRows=1)
perf.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), HEADBG),
    ("GRID", (0, 0), (-1, -1), 0.5, LINE),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
]))
story.append(perf)

# ── 四、质量保障 ──────────────────────────────────────────────
story += h1("四、质量保障")
story += bullets([
    esc("本地门先行:每项独立 commit 前跑 vitest / vue-tsc / cargo / pytest 全量,最终门禁 pytest 1146;"),
    esc("手测轮次:O 批三轮、PP 批七轮、F1/F2 各三轮、PERF 三轮,均按「先本地手测 PASS 再推送」工作流执行;"),
    esc("用户执行 PERF 审查清单,回流 7 项修复(含 2 个 Blocker 级),审查文档与决策记录全量入库;"),
    esc("五 lane CI 全绿(cli-sidecar / Workbench ×2 / Bundle / NSIS),版本一致性门 6 项通过;"),
    esc("全程决策留痕:decisions.md D-0~D-13 + 各批规格文档归档至 docs/archive/2.1.9-dev-plans/。"),
])

# ── 五、遗留与下周期计划 ──────────────────────────────────────
story += h1("五、遗留事项与下周期(2.1.10)计划")
story += bullets([
    B("P6b") + esc(":Docker /events 流式订阅 + resize 第二通道(进一步替代轮询);"),
    B("P10") + esc(":sidecar onedir 打包评估,削减单次 spawn 约 750ms 解包开销;"),
    esc("F2 host_exec 远端执行版;SSH 冲突双副本列表投影(待真实冲突形状);远端 rsync 缺失引导实测;"),
    esc("长对话恢复(独立 bug,待复现样本);镜像更新对已存在容器的可见性(启动比对 image id 提示重建);"),
    esc("用户侧小项:SSH keyPath 带引号存量数据建议去引号重存。"),
])
story.append(Spacer(1, 6))
story.append(Paragraph(esc("汇报人:Claude(结对开发)｜ 2.1.10 周期待开池"), S["subtitle"]))

doc.build(story)
print("OK ->", OUT)
