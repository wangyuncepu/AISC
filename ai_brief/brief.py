#!/usr/bin/env python3
"""ai_brief/brief.py - 多源 AI 资讯聚合：工具 + 工作流 + 行业。

stdlib-only（urllib + xml.etree + re），Py3.11/3.14 通用，零安装。
- 5 源：TLDR AI + The Rundown AI（行业）+ Simon Willison（工具/工作流）+ Changelog（工具）+ HN Show HN（工具）
- --ai：读 cs 后端 env，调 /v1/messages 按类别（新工具/工作流/行业）跨源中文精选；失败回退规则输出。
- 规则模式：按类别分组，终端纯文本格式。
- 失败静默 exit 0（除非 --strict），避免阻断 entrypoint 启动。
"""
import argparse
import html as ihtml
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

# ==========================================
# 配置
# ==========================================
TLDR_RSS = "https://tldr.tech/api/rss/ai"
TLDR_ISSUE = "https://tldr.tech/ai/{date}"
RUNDOWN_SITEMAP = "https://www.therundown.ai/sitemap.xml"
SIMON_ATOM = "https://simonwillison.net/atom/everything/"
CHANGELOG_RSS = "https://changelog.com/news/feed"
HN_SHOW_RSS = "https://hnrss.org/show"
UA = "Mozilla/5.0 (ai_brief fetcher)"
TIMEOUT = 12  # 单请求超时（秒）

# 赞助/广告域名 blocklist（TLDR 赞助 + Rundown 赞助/CTA）
SPONSOR_DOMAINS = (
    "doubleclick.net", "links.tldrnewsletter.com", "granola.ai",
    "humansecurity.com", "strandsagents.com", "awscloud.com",
    "pages.awscloud.com", "typeform.com", "teamtailor.com",
    "advertise.tldr.tech", "sparkloop.app", "googletagmanager.com",
    "cloudflare.com", "turnstile", "rundown.ai/advertise",
    "rundown.ai/tools", "rundown.ai/guides", "rundown.ai/workshops",
    "rundown.ai/certificates", "rundown.ai/ai-university",
    "app.therundown.ai", "videoask.com",
)

# HN Show HN 过滤关键词（只保留 AI/开发工具相关）
HN_KEYWORDS = [
    "ai", "llm", "agent", "tool", "cli", "dev", "code", "gpt", "claude",
    "model", "api", "open source", "terminal", "workflow", "automate",
    "cursor", "claw", "fable", "opus", "sonnet", "haiku", "deepseek",
    "gemini", "openai", "anthropic", "prompt", "coder", "vibe",
    "mcp", "rag", "vector", "embedding", "langchain", "llama",
]

# 分类元数据
SOURCE_CATEGORIES = {
    "tldr": "industry", "rundown": "industry",
    "simon": "tools", "changelog": "tools", "hn": "tools",
}
CATEGORY_META = {
    "tools": ("🛠️", "新工具"),
    "workflow": ("🔧", "工作流"),
    "industry": ("📰", "行业"),
}

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache")


# ==========================================
# 通用工具
# ==========================================
def http_get(url, timeout=TIMEOUT):
    """GET + 单次重试，缓解间歇网络/限流抖动。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if attempt == 0:
                time.sleep(1)
    raise last


def strip_tags(s):
    return ihtml.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def is_sponsor(url):
    u = url.lower()
    return any(d in u for d in SPONSOR_DOMAINS)


def cache_valid(path):
    """latest 模式缓存：同日有效（新闻是日级）。"""
    if not os.path.isfile(path):
        return False
    try:
        mt = time.localtime(os.path.getmtime(path))
        now = time.localtime()
        return mt.tm_year == now.tm_year and mt.tm_yday == now.tm_yday
    except OSError:
        return False


# ==========================================
# RSS/Atom 通用抓取
# ==========================================
def rss_fetch(url, top=5, item_filter=None):
    """拉 RSS/Atom feed，返回 [{title, url, summary}]，可选过滤。兼容 Atom <entry> + 命名空间。"""
    xml = http_get(url)
    root = ET.fromstring(xml)
    items = []
    # 尝试 RSS <item>，否则 Atom <entry>（可能带命名空间前缀或无前缀）
    els = root.findall(".//item")
    if not els:
        els = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not els:
        els = root.findall(".//entry")
    # 检测子元素是否需要命名空间前缀
    ns = ""
    if els and "}" in els[0].tag:
        ns = els[0].tag.split("}")[0] + "}"
    for el in els:
        title = (el.findtext(f"{ns}title") or el.findtext("title") or "").strip()
        link_el = el.find(f"{ns}link")
        if link_el is None:
            link_el = el.find("link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href", "") or "").strip()
        if not link:
            link = (el.findtext(f"{ns}link") or el.findtext("link") or "").strip()
        desc = (el.findtext(f"{ns}description") or el.findtext(f"{ns}summary")
                or el.findtext("description") or el.findtext("summary") or "").strip()
        if not title or not link:
            continue
        if item_filter and not item_filter(link, title):
            continue
        summary = strip_tags(desc)[:200] if desc else ""
        items.append({"title": title, "url": link, "summary": summary})
    return items[:top]


def hn_filter(url, title):
    text = (title + " " + url).lower()
    return any(kw in text for kw in HN_KEYWORDS)


# ==========================================
# Simon Willison（Atom）
# ==========================================
def fetch_simon(top, date=None, days=1):
    items = rss_fetch(SIMON_ATOM, top=max(top, 8))
    return "Simon Willison", items[:top]


# ==========================================
# Changelog News（RSS）
# ==========================================
def fetch_changelog(top, date=None, days=1):
    items = rss_fetch(CHANGELOG_RSS, top=max(top, 5))
    return "Changelog", items[:top]


# ==========================================
# HN Show HN（RSS，AI/dev 过滤）
# ==========================================
def fetch_hn(top, date=None, days=1):
    # 拉更多条再过滤，保证过滤后够 top 条
    items = rss_fetch(HN_SHOW_RSS, top=max(top * 3, 10), item_filter=hn_filter)
    return "HN Show HN", items[:top]


# ==========================================
# TLDR AI（现有逻辑，不动）
# ==========================================
def tldr_list_issues():
    """RSS -> [{date,title,url}], 最新在前。"""
    root = ET.fromstring(http_get(TLDR_RSS))
    out = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = re.search(r"/ai/(\d{4}-\d{2}-\d{2})", link)
        out.append({
            "date": m.group(1) if m else "",
            "title": (item.findtext("title") or "").strip(),
            "url": link,
        })
    return out


def tldr_parse_issue(url):
    """issue 页 -> [{title,url,summary}]，已去赞助。"""
    html = http_get(url)
    items = []
    for art in re.findall(r'<article class="mt-3">(.*?)</article>', html, re.S):
        am = re.search(r'<a class="font-bold"[^>]+href="([^"]+)"', art)
        hm = re.search(r"<h3[^>]*>(.*?)</h3>", art, re.S)
        sm = re.search(r'<div class="newsletter-html">(.*?)</div>', art, re.S)
        if not (am and hm):
            continue
        link = am.group(1)
        if is_sponsor(link):
            continue
        title = strip_tags(hm.group(1))
        title = re.sub(r"\s*\([\d-]+\s*minute read\)\s*$", "", title).strip()
        if not title:
            continue
        items.append({"title": title, "url": link,
                      "summary": strip_tags(sm.group(1)) if sm else ""})
    return items


def fetch_tldr(top, date=None, days=1):
    """返回 (label, [items])。"""
    issues = tldr_list_issues()
    if not issues:
        return None
    if date:
        picked = [i for i in issues if i["date"] == date][:1]
    else:
        picked = issues[:max(1, days)]
    items = []
    label_dates = []
    for iss in picked:
        label_dates.append(iss["date"])
        items.extend(tldr_parse_issue(iss["url"]))
    if not items:
        return None
    label = "TLDR AI · " + (date or "~".join(label_dates[:3]))
    return label, dedupe(items)[:top]


# ==========================================
# The Rundown AI（现有逻辑，不动）
# ==========================================
def rundown_list_posts():
    """sitemap -> [(lastmod, url)], 最新在前。"""
    xml = http_get(RUNDOWN_SITEMAP)
    posts = []
    for m in re.finditer(r"<loc>([^<]*?/p/[^<]*)</loc>\s*<lastmod>([^<]*)</lastmod>", xml):
        posts.append((m.group(2), m.group(1)))
    posts.sort(reverse=True)
    return posts


def rundown_parse_post(url):
    """post 页 -> {title, lead, url, items:[{title,url}]}。"""
    html = http_get(url)
    h1m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = strip_tags(h1m.group(1)) if h1m else "The Rundown AI"
    lead = ""
    pm = re.search(r"</h1>(.*?)(?:<h2|<h3)", html, re.S)
    if pm:
        for p in re.findall(r"<p[^>]*>(.*?)</p>", pm.group(1), re.S):
            t = strip_tags(p)
            if len(t) > 30:
                lead = t
                break
    nav_paths = ("/login", "/terms", "/privacy", "/terms-privacy", "/auth",
                 "/signup", "/subscribe", "/account", "/advertise")
    items, seen = [], set()
    for am in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        u = am.group(1)
        txt = strip_tags(am.group(2))
        if is_sponsor(u) or len(re.findall(r"[A-Za-z]{3,}", txt)) < 3:
            continue
        path = urlsplit(u).path.lower()
        if path.strip("/") == "" or any(path.endswith(p) for p in nav_paths):
            continue
        if u in seen:
            continue
        seen.add(u)
        if word_overlap(txt, title) >= 4:
            continue
        items.append({"title": txt, "url": u, "summary": ""})
    return {"title": title, "lead": lead, "url": url, "items": items}


def word_overlap(a, b):
    aw = set(re.findall(r"[A-Za-z]{3,}", a.lower()))
    bw = set(re.findall(r"[A-Za-z]{3,}", b.lower()))
    return len(aw & bw)


def fetch_rundown(top, date=None, days=1):
    posts = rundown_list_posts()
    if not posts:
        return None
    if date:
        picked = [(lm, u) for (lm, u) in posts if lm.startswith(date)][:1]
        if not picked:
            return None
    else:
        picked = posts[:max(1, days)]
    lead_title, lead, lead_url, lead_date = "", "", "", ""
    items = []
    for (lm, u) in picked:
        post = rundown_parse_post(u)
        if not lead_title:
            lead_title, lead, lead_url, lead_date = post["title"], post["lead"], post["url"], lm
        items.extend(post["items"])
    if not lead_title:
        return None
    label = "The Rundown AI · " + (date or lead_date)
    return label, {
        "title": lead_title, "lead": lead, "url": lead_url,
        "items": dedupe(items)[:top],
    }


# ==========================================
# 去重
# ==========================================
def dedupe(items):
    """按 URL 去重；再按标题词集相似度去近重复。"""
    out, seen_url, seen_keys = [], set(), []
    for it in items:
        if it["url"] in seen_url:
            continue
        key = frozenset(re.findall(r"[A-Za-z]{4,}", it["title"].lower()))
        if any(len(key & k) >= 3 for k in seen_keys):
            continue
        seen_url.add(it["url"])
        seen_keys.append(key)
        out.append(it)
    return out


# ==========================================
# 源注册表
# ==========================================
SOURCE_FETCHERS = {
    "tldr": fetch_tldr,
    "rundown": fetch_rundown,
    "simon": fetch_simon,
    "changelog": fetch_changelog,
    "hn": fetch_hn,
}

# --source 快捷值
SOURCE_GROUPS = {
    "all": ("simon", "changelog", "hn", "tldr", "rundown"),
    "tools": ("simon", "changelog", "hn"),
    "industry": ("tldr", "rundown"),
    "workflow": ("simon", "changelog"),
}


def resolve_sources(arg):
    """解析 --source 参数。'all' / 'tools' / 'tldr,simon' / 'tldr'"""
    arg = arg.lower().strip()
    if arg in SOURCE_GROUPS:
        return list(SOURCE_GROUPS[arg])
    # 兼容旧值 'both' -> 'tldr,rundown'
    if arg == "both":
        return ["tldr", "rundown"]
    return [k.strip() for k in arg.split(",") if k.strip() in SOURCE_FETCHERS]


# ==========================================
# 渲染（分类、终端纯文本）
# ==========================================
def render_categorized(results, source_keys):
    """results: {key: (label, items)}; 按类别分组渲染。Rundown 特殊处理。"""
    # group by category
    cats = {}
    for key in source_keys:
        if key not in results or not results[key]:
            continue
        val = results[key]
        cat = SOURCE_CATEGORIES.get(key, "tools")
        cats.setdefault(cat, []).append((key, val))

    lines = []
    order = ("tools", "workflow", "industry")
    for cat_key in order:
        if cat_key not in cats:
            continue
        emoji, name = CATEGORY_META[cat_key]
        lines.append(f"{emoji} {name}")
        for key, val in cats[cat_key]:
            if key == "rundown":
                # Rundown 特殊：lead + items
                label, info = val[0], val[1]
                lines.append(f"  {label}")
                if info.get("lead"):
                    lines.append(f"    头条：{info['title']} - {info['lead']}")
                else:
                    lines.append(f"    头条：{info['title']}")
                for i, it in enumerate(info["items"], 1):
                    lines.append(f"    {i}. {it['title']}")
                    lines.append(f"       {it['url']}")
            else:
                label, items = val[0], val[1]
                lines.append(f"  {label} · {len(items)} 条")
                for i, it in enumerate(items, 1):
                    lines.append(f"    {i}. {it['title']}")
                    if it.get("summary"):
                        lines.append(f"       {it['summary'][:140]}")
                    lines.append(f"       {it['url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ==========================================
# --ai：LLM 分类中文摘要
# ==========================================
def ai_summarize(results, top=3):
    """读 ANTHROPIC_* env，POST /v1/messages 让模型分类+中文一句话总结。"""
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", "")
    # 用 haiku/flash 档（快+省），简讯摘要无需大模型
    model = (os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
             or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"))
    if not base or not token:
        raise RuntimeError("未配置 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN（先用 cs 切后端）")

    # 拼素材
    material = []
    source_display = {"simon": "Simon Willison", "changelog": "Changelog",
                      "hn": "HN Show HN", "tldr": "TLDR AI", "rundown": "The Rundown AI"}
    for key in ("simon", "changelog", "hn", "tldr", "rundown"):
        if key not in results or not results[key]:
            continue
        val = results[key]
        if key == "rundown":
            info = val[1]
            material.append(f"[{source_display[key]}] 头条：{info['title']}。{info.get('lead','')}")
            for it in info.get("items", []):
                material.append(f"- {it['title']}  🔗 {it['url']}")
        else:
            label, items = val[0], val[1]
            material.append(f"[{source_display[key]} · {label}]")
            for it in items:
                material.append(f"- {it['title']}  🔗 {it['url']}")
    if not material:
        raise RuntimeError("无素材")

    prompt = (
        "下面是来自多个信息源的内容。按类别精选最重要的条目，每类最多"
        f" {top} 条，分组输出：\n"
        "  🛠️ 新工具 — AI/开发新工具、开源项目、产品、CLI\n"
        "  🔧 工作流/方法 — LLM 工作流、工程方法、最佳实践\n"
        "  📰 行业动态 — 公司/融资/模型发布/政策\n"
        "格式：每类 emoji 头独占一行，下面每一条格式为：\n"
        "  `- 标题（中文一句话总结，保留关键产品名/公司名/工具名/人名，不要英文）`\n"
        "  下一行 `  🔗 原始链接url`（保留素材中提供的 🔗 后的 url，不要编造）\n"
        "该分类没有合适条目就不输出该分类头。"
        "不要额外寒暄。\n\n"
        + "\n".join(material)
    )

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    body = __import__("json").dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": token,
            "authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = __import__("json").loads(r.read().decode("utf-8", "replace"))
    # 跳过 thinking 块，取首个 text 块（兼容 GLM）
    try:
        for block in resp["content"]:
            if block.get("type") == "text" and block.get("text"):
                return block["text"].strip()
    except (KeyError, TypeError):
        pass
    # 兼容部分中转返回 OpenAI 格式
    try:
        return resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"无法解析 LLM 响应: {str(resp)[:200]}")


# ==========================================
# main
# ==========================================
def main():
    ap = argparse.ArgumentParser(
        description="多源 AI 资讯聚合：工具 + 工作流 + 行业（TLDR/Rundown/Simon Willison/Changelog/HN Show HN）")
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD（默认最新）")
    ap.add_argument("--days", type=int, default=1, help="取最近 N 期（默认 1）")
    ap.add_argument("--top", type=int, default=5, help="每源 Top N（默认 5）")
    ap.add_argument("--source", default="all",
                    help="源选择：all / tools / industry / workflow / tldr,simon,...（逗号分隔，默认 all）")
    ap.add_argument("--ai", action="store_true", help="LLM 按类别跨源中文精选")
    ap.add_argument("--save", action="store_true", help="另存 cache/ 下文件")
    ap.add_argument("--no-cache", action="store_true", help="跳过 latest 缓存")
    ap.add_argument("--strict", action="store_true", help="失败时非零退出（调试用）")
    args = ap.parse_args()

    source_keys = resolve_sources(args.source)
    if not source_keys:
        print("（无匹配数据源）")
        return 1 if args.strict else 0

    use_cache = (not args.no_cache) and (not args.date) and args.days == 1
    cache_key = f"categorized_{args.source}_{args.top}_ai{int(args.ai)}"
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.md")

    if use_cache and cache_valid(cache_path):
        try:
            sys.stdout.write(open(cache_path, encoding="utf-8").read())
            return 0
        except OSError:
            pass

    # 拉取各源（每源独立 try，部分成功仍渲染）
    results = {}
    errs = []
    for key in source_keys:
        try:
            results[key] = SOURCE_FETCHERS[key](args.top, args.date, args.days)
        except Exception as e:
            if args.strict:
                print(f"❌ {key} 抓取失败: {e}", file=sys.stderr)
                return 1
            errs.append(f"{key}: {e}")
    if not results:
        if args.strict:
            print(f"❌ 全部源失败: {errs}", file=sys.stderr)
            return 1
        print("（简讯获取失败，已跳过）")
        return 0

    try:
        if args.ai:
            out = ai_summarize(results, top=min(args.top, 4))
            # 提取日期
            date_str = ""
            for rk, rv in zip(source_keys, results.values()):
                if rk in ("tldr", "rundown"):
                    if rk == "rundown":
                        label = rv[0]  # "The Rundown AI · 2026-07-13"
                    else:
                        label = rv[0]  # "TLDR AI · 2026-07-13"
                    m = re.search(r"\d{4}-\d{2}-\d{2}", label)
                    if m:
                        date_str = m.group(0)
                        break
            hdr = "📰 AI 每日简报"
            if date_str:
                hdr += f" · {date_str}"
            out = f"{hdr}\n\n{out}"
        else:
            out = render_categorized(results, source_keys)
    except Exception as e:
        if args.strict:
            print(f"❌ 渲染/LLM 失败: {e}", file=sys.stderr)
            return 1
        # --ai 失败 -> 回退规则输出
        out = render_categorized(results, source_keys)
        if out:
            out += f"\n\n（AI 摘要失败，已回退规则输出: {e}）"
        else:
            out = "（简讯获取失败，已跳过）"
            print(out)
            return 0

    if not out.strip():
        print("（今日暂无简讯）")
        return 0

    sys.stdout.write(out.rstrip() + "\n")

    if args.save or use_cache:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(out.rstrip() + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
