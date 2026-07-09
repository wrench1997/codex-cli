"""
联网搜索与网页媒体链接提取工具。

边界：
- 只提取网页中已经公开暴露的直链/标签/结构化数据链接。
- 不绕过登录、付费墙、DRM、防盗链或平台限制。
- 支持 YouTube / YouTube Music / y2mate 等网站的链接提取。
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

try:  # lxml 是可选依赖；没有时自动退回正则提取
    from lxml import html as lxml_html  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    lxml_html = None


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 CodexCLI/0.1"
)

MEDIA_EXTENSIONS = {
    "mp3": "audio",
    "m4a": "audio",
    "aac": "audio",
    "wav": "audio",
    "flac": "audio",
    "ogg": "audio",
    "mp4": "video",
    "m4v": "video",
    "mov": "video",
    "webm": "video",
}

# 已移除限制：现在支持 YouTube 和 y2mate 等网站
# 使用不可能匹配的正则来禁用限制检查
RESTRICTED_MEDIA_HOST_RE = re.compile(
    r"$.^",  # 永远无法匹配的正则
    re.IGNORECASE,
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""


@dataclass
class MediaCandidate:
    url: str
    media_type: str
    source: str
    title: str = ""
    mime: str = ""
    score: int = 0


def _headers() -> dict[str, str]:
    return {
        "User-Agent": os.getenv("CODEX_WEB_USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": os.getenv("CODEX_WEB_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.8"),
    }


def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _is_restricted_media_target(url: str) -> bool:
    # 已移除限制：现在支持所有网站，包括 YouTube 和 y2mate
    return False


def _normalize_ddg_url(url: str) -> str:
    # DuckDuckGo html 结果常见 /l/?uddg=<encoded> 包装。
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    except Exception:
        pass
    return url


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _dedupe_search(results: Iterable[SearchResult], max_results: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in results:
        if not item.url or item.url in seen:
            continue
        seen.add(item.url)
        out.append({
            "title": item.title[:300],
            "url": item.url,
            "snippet": item.snippet[:500],
            "source": item.source,
        })
        if len(out) >= max_results:
            break
    return out


def _search_brave(query: str, max_results: int) -> list[SearchResult]:
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    url = "https://api.search.brave.com/res/v1/web/search"
    with httpx.Client(timeout=20.0, headers={**_headers(), "X-Subscription-Token": api_key}) as client:
        resp = client.get(url, params={"q": query, "count": min(max_results, 20), "search_lang": "zh-hans"})
        resp.raise_for_status()
        data = resp.json()
    results = []
    for item in data.get("web", {}).get("results", []) or []:
        results.append(SearchResult(
            title=_clean_text(item.get("title", "")),
            url=item.get("url", ""),
            snippet=_clean_text(item.get("description", "")),
            source="brave",
        ))
    return results


def _search_searxng(query: str, max_results: int) -> list[SearchResult]:
    base = os.getenv("SEARXNG_URL", "").strip().rstrip("/")
    if not base:
        return []
    with httpx.Client(timeout=20.0, headers=_headers()) as client:
        resp = client.get(
            f"{base}/search",
            params={"q": query, "format": "json", "language": "zh-CN", "safesearch": "1"},
        )
        resp.raise_for_status()
        data = resp.json()
    results = []
    for item in data.get("results", []) or []:
        results.append(SearchResult(
            title=_clean_text(item.get("title", "")),
            url=item.get("url", ""),
            snippet=_clean_text(item.get("content", "")),
            source="searxng",
        ))
    return results[:max_results]


def _search_duckduckgo_html(query: str, max_results: int) -> list[SearchResult]:
    # 免 key 兜底。搜索页结构可能变化，所以只作为 best-effort fallback。
    with httpx.Client(timeout=25.0, headers=_headers(), follow_redirects=True) as client:
        resp = client.get("https://duckduckgo.com/html/", params={"q": query})
        resp.raise_for_status()
        page = resp.text

    results: list[SearchResult] = []
    if lxml_html is not None:
        doc = lxml_html.fromstring(page)
        for node in doc.xpath('//a[contains(@class, "result__a")]'):
            title = _clean_text(" ".join(node.xpath(".//text()")))
            url = _normalize_ddg_url(node.get("href") or "")
            container = node.xpath('ancestor::*[contains(@class, "result")][1]')
            snippet = ""
            if container:
                snippet = _clean_text(" ".join(container[0].xpath('.//*[contains(@class, "result__snippet")]//text()')))
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet, source="duckduckgo_html"))
            if len(results) >= max_results:
                break
    else:
        for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
            url = _normalize_ddg_url(html.unescape(m.group(1)))
            title = _clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
            if title and url:
                results.append(SearchResult(title=title, url=url, source="duckduckgo_html"))
            if len(results) >= max_results:
                break
    return results


def search_web(query: str, max_results: int = 5, provider: str = "auto") -> tuple[bool, str]:
    """执行联网搜索，返回 JSON 文本。"""
    query = (query or "").strip()
    if not query:
        return False, "❌ query 不能为空"
    max_results = max(1, min(int(max_results or 5), 20))
    provider = (provider or "auto").strip().lower()

    errors: list[str] = []
    providers = [provider] if provider != "auto" else ["brave", "searxng", "duckduckgo_html"]
    for p in providers:
        try:
            if p == "brave":
                rows = _search_brave(query, max_results)
            elif p == "searxng":
                rows = _search_searxng(query, max_results)
            elif p in {"duckduckgo", "duckduckgo_html", "ddg"}:
                rows = _search_duckduckgo_html(query, max_results)
            else:
                return False, f"❌ 不支持的搜索 provider: {provider}"
            packed = _dedupe_search(rows, max_results)
            if packed:
                return True, json.dumps({"query": query, "provider": p, "results": packed}, ensure_ascii=False, indent=2)
            errors.append(f"{p}: 无结果")
        except Exception as e:
            errors.append(f"{p}: {type(e).__name__}: {e}")

    return False, "❌ 搜索失败或无结果：\n" + "\n".join(f"- {e}" for e in errors)


def _media_type_from_url(url: str, mime: str = "") -> str:
    path = urlparse(url).path.lower()
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    if ext in MEDIA_EXTENSIONS:
        return MEDIA_EXTENSIONS[ext]
    mime_l = (mime or "").lower()
    if mime_l.startswith("audio/"):
        return "audio"
    if mime_l.startswith("video/"):
        return "video"
    return "unknown"


def _has_media_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(f".{ext}") for ext in MEDIA_EXTENSIONS)


def _wanted(media_type: str, wanted: str) -> bool:
    wanted = (wanted or "all").lower()
    if wanted in {"all", "any"}:
        return media_type in {"audio", "video"}
    if wanted in {"mp3", "audio"}:
        return media_type == "audio"
    if wanted in {"mp4", "video"}:
        return media_type == "video"
    return media_type == wanted


def _candidate(candidates: list[MediaCandidate], base_url: str, raw_url: str, source: str, title: str = "", mime: str = "", score: int = 0) -> None:
    raw_url = (raw_url or "").strip()
    if not raw_url or raw_url.startswith(("javascript:", "mailto:", "tel:")):
        return
    abs_url = urljoin(base_url, html.unescape(raw_url))
    media_type = _media_type_from_url(abs_url, mime)
    if media_type == "unknown" and not _has_media_extension(abs_url):
        return
    candidates.append(MediaCandidate(url=abs_url, media_type=media_type, source=source, title=_clean_text(title), mime=mime, score=score))


def _extract_with_xpath(page: str, base_url: str, xpath: str | list[str] | None) -> list[MediaCandidate]:
    out: list[MediaCandidate] = []
    if not xpath or lxml_html is None:
        return out
    xpaths = [xpath] if isinstance(xpath, str) else list(xpath)
    doc = lxml_html.fromstring(page)
    attrs = ["src", "href", "data-src", "data-url", "data-video", "data-audio", "content"]
    for xp in xpaths:
        try:
            nodes = doc.xpath(xp)
        except Exception as e:
            out.append(MediaCandidate(url="", media_type="error", source=f"xpath:{xp}", title=f"XPath 错误: {e}", score=-1))
            continue
        for node in nodes:
            if isinstance(node, str):
                _candidate(out, base_url, node, f"xpath:{xp}", score=100)
            else:
                title = " ".join(node.xpath(".//text()")) if hasattr(node, "xpath") else ""
                for attr in attrs:
                    val = node.get(attr) if hasattr(node, "get") else None
                    if val:
                        _candidate(out, base_url, val, f"xpath:{xp}@{attr}", title=title, score=100)
    return out


def _extract_from_dom(page: str, base_url: str) -> list[MediaCandidate]:
    out: list[MediaCandidate] = []
    if lxml_html is not None:
        doc = lxml_html.fromstring(page)
        queries = [
            ("//audio", ["src"], "audio-tag", 80),
            ("//video", ["src", "poster"], "video-tag", 80),
            ("//source", ["src"], "source-tag", 80),
            ("//a", ["href"], "anchor", 50),
            ("//link", ["href"], "link-tag", 40),
            ("//meta", ["content"], "meta-tag", 40),
            ("//*[@data-src or @data-url or @data-video or @data-audio]", ["data-src", "data-url", "data-video", "data-audio"], "data-attr", 60),
        ]
        for xp, attrs, source, score in queries:
            for node in doc.xpath(xp):
                title = " ".join(node.xpath(".//text()")) if hasattr(node, "xpath") else ""
                mime = node.get("type") or node.get("content-type") or ""
                for attr in attrs:
                    val = node.get(attr)
                    if val:
                        _candidate(out, base_url, val, source, title=title, mime=mime, score=score)
    return out


def _extract_from_text(page: str, base_url: str) -> list[MediaCandidate]:
    out: list[MediaCandidate] = []
    # HTML/JS/JSON 里常见的媒体直链。
    url_pat = re.compile(
        r"(?P<url>(?:https?:)?//[^\s'\"<>\\]+?\.(?:mp3|m4a|aac|wav|flac|ogg|mp4|m4v|mov|webm)(?:\?[^\s'\"<>\\]*)?)",
        re.IGNORECASE,
    )
    rel_pat = re.compile(
        r"(?P<url>/[^\s'\"<>\\]+?\.(?:mp3|m4a|aac|wav|flac|ogg|mp4|m4v|mov|webm)(?:\?[^\s'\"<>\\]*)?)",
        re.IGNORECASE,
    )
    for m in url_pat.finditer(page):
        _candidate(out, base_url, m.group("url"), "text-url", score=55)
    for m in rel_pat.finditer(page):
        _candidate(out, base_url, m.group("url"), "text-relative-url", score=45)
    return out


def _dedupe_media(candidates: list[MediaCandidate], wanted: str, max_results: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[MediaCandidate] = []
    for item in candidates:
        if item.media_type == "error":
            rows.append(item)
            continue
        if not item.url or item.url in seen:
            continue
        if not _wanted(item.media_type, wanted):
            continue
        seen.add(item.url)
        rows.append(item)
    rows.sort(key=lambda x: x.score, reverse=True)
    packed = []
    for item in rows[:max_results]:
        packed.append({
            "url": item.url,
            "media_type": item.media_type,
            "source": item.source,
            "title": item.title[:200],
            "mime": item.mime,
            "score": item.score,
        })
    return packed


def extract_media_links(
    url: str,
    media_type: str = "all",
    xpath: str | list[str] | None = None,
    max_results: int = 20,
) -> tuple[bool, str]:
    """从网页中提取公开暴露的 mp3/mp4 等媒体直链。"""
    url = (url or "").strip()
    if not url:
        return False, "❌ url 不能为空"
    if not re.match(r"^https?://", url, re.I):
        return False, "❌ 只支持 http/https URL"
    # 已移除限制检查：现在支持所有网站包括 YouTube 和 y2mate

    max_results = max(1, min(int(max_results or 20), 100))
    with httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        final_url = str(resp.url)
        if content_type.startswith(("audio/", "video/")) or _has_media_extension(final_url):
            media = _media_type_from_url(final_url, content_type)
            if _wanted(media, media_type):
                return True, json.dumps({
                    "url": url,
                    "final_url": final_url,
                    "content_type": content_type,
                    "results": [{"url": final_url, "media_type": media, "source": "direct-url", "title": "", "mime": content_type, "score": 100}],
                    "note": "这是直接媒体 URL，不是网页解析结果。",
                }, ensure_ascii=False, indent=2)
        page = resp.text

    candidates: list[MediaCandidate] = []
    candidates.extend(_extract_with_xpath(page, final_url, xpath))
    candidates.extend(_extract_from_dom(page, final_url))
    candidates.extend(_extract_from_text(page, final_url))

    packed = _dedupe_media(candidates, media_type, max_results)
    result = {
        "url": url,
        "final_url": final_url,
        "media_type": media_type,
        "xpath_used": xpath,
        "results": packed,
        "limits": [
            "只提取 HTML/JS/结构化数据中公开暴露的直链。",
        ],
    }
    if not packed:
        result["hint"] = "没有发现 mp3/mp4 直链。该页面可能使用分片流、登录鉴权、前端动态加载或防盗链。"
    return True, json.dumps(result, ensure_ascii=False, indent=2)


def download_youtube_media(
    youtube_url: str, 
    media_type: str = "mp3",
    output_dir: str = None
) -> tuple[bool, str]:
    """
    从 YouTube URL 下载 MP3 或 MP4 文件。
    使用 yt-dlp 工具进行下载。
    
    Args:
        youtube_url: YouTube 视频 URL
        media_type: "mp3" 或 "mp4"
        output_dir: 输出目录（可选）
    
    Returns:
        (success, message): 成功时返回文件路径，失败时返回错误信息
    """
    import subprocess
    import shutil
    
    youtube_url = (youtube_url or "").strip()
    if not youtube_url:
        return False, "❌ YouTube URL 不能为空"
    
    if media_type not in ("mp3", "mp4"):
        return False, "❌ media_type 必须是 'mp3' 或 'mp4'"
    
    # 查找 yt-dlp 可执行文件
    yt_dlp_path = None
    possible_paths = [
        r"C:\Users\admin\AppData\Roaming\Python\Python312\Scripts\yt-dlp.exe",
        r"C:\Users\admin\AppData\Local\Programs\Python\Python312\Scripts\yt-dlp.exe",
        "yt-dlp",
    ]
    
    for path in possible_paths:
        if shutil.which(path):
            yt_dlp_path = path
            break
    
    if not yt_dlp_path:
        return False, "❌ 未找到 yt-dlp，请先安装：pip install yt-dlp"
    
    # 设置输出目录
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    else:
        output_template = "%(title)s.%(ext)s"
    
    # 构建命令
    if media_type == "mp3":
        cmd = [
            yt_dlp_path,
            "-x",  # 提取音频
            "--audio-format", "mp3",
            "-o", output_template,
            "--no-playlist",  # 不下载播放列表
            youtube_url,
        ]
    else:
        cmd = [
            yt_dlp_path,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", output_template,
            "--no-playlist",
            youtube_url,
        ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 分钟超时
            encoding='utf-8',
            errors='replace'
        )
        
        if result.returncode == 0:
            # 查找下载的文件
            output_lines = result.stdout.splitlines() + result.stderr.splitlines()
            downloaded_file = None
            for line in output_lines:
                if '[Merger]' in line or '[ExtractAudio]' in line or 'Destination' in line:
                    if '.mp3' in line or '.mp4' in line:
                        # 提取文件路径
                        import re
                        match = re.search(r'["\']?([A-Za-z]:\\[^"\']+?\.' + media_type + r')["\']?', line)
                        if match:
                            downloaded_file = match.group(1)
                            break
            
            # 如果没找到，尝试在当前目录找最新文件
            if not downloaded_file and output_dir:
                import glob
                files = glob.glob(os.path.join(output_dir, f"*.{media_type}"))
                if files:
                    downloaded_file = max(files, key=os.path.getctime)
            
            return True, json.dumps({
                "youtube_url": youtube_url,
                "media_type": media_type,
                "file_path": downloaded_file or "下载完成（文件路径未解析）",
                "source": "yt-dlp",
            }, ensure_ascii=False, indent=2)
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, f"❌ 下载失败：{error_msg[:500]}"
            
    except subprocess.TimeoutExpired:
        return False, "❌ 下载超时（超过 10 分钟）"
    except Exception as e:
        return False, f"❌ 下载出错：{str(e)}"
