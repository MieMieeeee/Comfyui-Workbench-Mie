"""media → HTML 渲染 — 从 scail2_app.py 抽出的纯函数 (无 Gradio 依赖).

迁移自 scail2_app.py:
  - _media_ext_from_url   (L1293)
  - _media_to_html        (L1333)
  - _FILE_ROUTE_PREFIX    (L1591, 模块级常量)

依赖:
  - app.config.REPO_ROOT (用于把本地绝对路径转成相对 URL)

注意: _FILE_ROUTE_PREFIX 现在是 "/gradio_api/file=" (Gradio 6 路由).
步骤 7 (下线 Gradio) 时改成 Flask 的 "/static/" 或自定义路由.
现在保持 Gradio 行为, 让 scail2_app.py re-export 后行为不变.
"""
from __future__ import annotations

from app import config

# Gradio 6 静态文件路由前缀 (Gradio 把所有 API + 静态文件挂在 /gradio_api 下).
# [迁移 TODO 步骤 7] Flask 版改成 "/static/" 或 url_for('static', filename=...)
_FILE_ROUTE_PREFIX = "/gradio_api/file="


def _media_ext_from_url(src):
    """从 URL / 路径里取文件扩展名 (含 query 参数里的 filename).
    ComfyUI /view URL 结构: /view?filename=NAME&type=output&subfolder=SUBFOLDER
    直接 endswith 在 src 上不工作 (URL 后面跟 &type=...&subfolder=...), 需解析
    query 取 filename 的扩展名. 其它 HTTP URL (http://x/clip.mp4) 走 path
    的扩展名; 本地路径走 Path.suffix.
    返回小写扩展名, e.g. ".mp4" / ".png" / "" (无法识别).
    """
    from urllib.parse import urlparse, parse_qs, unquote
    from pathlib import PurePosixPath
    if not src or not isinstance(src, str):
        return ""
    # 本地路径: 走 Path.suffix
    if not src.startswith("http"):
        from pathlib import Path as _P
        return _P(src).suffix.lower()
    # HTTP URL: 优先 path 扩展名; 若是裸端点 (如 /view), 退回 query param 里的 filename
    try:
        parsed = urlparse(src)
    except Exception:
        return ""
    path_ext = PurePosixPath(parsed.path).suffix.lower()
    if path_ext:
        return path_ext
    # query 里找 filename-like value, 按常见 key 顺序: filename (ComfyUI), f (测试用), name, file
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("filename", "f", "name", "file"):
        for v in qs.get(key, []):
            ext = PurePosixPath(unquote(v)).suffix.lower()
            if ext:
                return ext
    # 兜底: 找 query 里第一个有扩展名的 value
    for values in qs.values():
        for v in values:
            ext = PurePosixPath(unquote(v)).suffix.lower()
            if ext:
                return ext
    return ""


def _media_to_html(media, output_kind: str = "image") -> str:
    """把 run 函数 yield 的 media 转成 HTML。

    output_kind:
      - "image": image list → <img> 网格; 单 URL → <img>
      - "video": <video> (mp4/mov/webm/gif) / 兜底 file-fallback
      - "audio": <audio controls> (mp3/wav/flac) / 兜底 file-fallback

    实际渲染时按 URL / 本地路径的扩展名分桶(image_ext/video_ext/audio_ext),
    与 output_kind 配合: 例如 audio preset 配 .mp3 URL → 走 audio 分支.
    跨类型错误 (e.g. image preset 但 URL 是 .mp3) 也仍能渲染, 不死锁.

    未知 URL / 本地文件 (扩展名不在三个白名单) → 出现路径+下载链接 banner,
    让用户知道文件已生成、可以去下载 — 这是"未知输出类型"的最小可用 fallback.

    直接用 ComfyUI /view URL (浏览器同机可访问), 绕过原生 video/audio 不支持外部 URL 的限制.
    """
    if not media:
        return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"

    # image 类特化: list → 网格
    if output_kind == "image":
        if isinstance(media, list):
            if not media:
                return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"
            imgs = "".join(
                "<img src=\"" + str(u) + "\" width=\"100%\" height=\"auto\" loading=\"lazy\" style=\"max-width:32%;margin:4px;border:1px solid #2a2d33;border-radius:var(--radius-md)\"/>"
                for u in media if u
            )
            return "<div style=\"padding:8px\">" + imgs + "</div>"
        return "<div style=\"padding:8px\"><img src=\"" + str(media) + "\" width=\"100%\" height=\"auto\" loading=\"lazy\" style=\"max-width:100%;border-radius:var(--radius-md)\"/></div>"

    # video / audio: 单 URL, 扩展名分桶
    src = media[0] if isinstance(media, list) else media
    if not src or not isinstance(src, str):
        return "<div style=\"color:var(--text-faint);padding:20px\">等待结果...</div>"

    ext = _media_ext_from_url(src)
    video_ext = (".mp4", ".mov", ".webm", ".gif")
    image_ext = (".png", ".jpg", ".jpeg", ".webp")
    audio_ext = (".mp3", ".wav", ".flac", ".ogg", ".m4a")

    def _to_url(s):
        """把 http(s) URL 或本地绝对路径转成浏览器可吃的 URL."""
        if s.startswith("http"):
            return s
        from pathlib import Path as _P
        sp = _P(s)
        if sp.exists():
            try:
                rel = sp.relative_to(config.REPO_ROOT)
                return _FILE_ROUTE_PREFIX + str(rel).replace(chr(92), "/")
            except ValueError:
                return None
        return None

    # 扩展名优先; output_kind 是 hint, 不是 hard constraint
    if ext in audio_ext:
        url = _to_url(src)
        if url:
            return ('<div style=\"padding:8px\"><audio controls preload="metadata" style=\"width:100%;max-width:480px\">'
                    '<source src=\"' + url + '\"/></audio></div>')
    if ext in video_ext:
        if src.startswith("http"):
            return ("<div style=\"padding:8px\"><video controls autoplay preload=\"metadata\" width=\"100%\" height=\"auto\" style=\"max-width:100%;border-radius:var(--radius-md)\">"
                    "<source src=\"" + src + "\"/></video></div>")
        from pathlib import Path as _P
        sp = _P(src)
        if sp.exists():
            try:
                rel = sp.relative_to(config.REPO_ROOT)
                file_url = _FILE_ROUTE_PREFIX + str(rel).replace(chr(92), "/")
                return ("<div style=\"padding:8px\"><video controls preload=\"metadata\" width=\"100%\" height=\"auto\" style=\"max-width:100%;border-radius:var(--radius-md)\">"
                        "<source src=\"" + file_url + "\"/></video></div>")
            except ValueError:
                pass
    if ext in image_ext:
        url = _to_url(src) or src
        return "<div style=\"padding:8px\"><img src=\"" + url + "\" width=\"100%\" height=\"auto\" loading=\"lazy\" style=\"max-width:100%;border-radius:var(--radius-md)\"/></div>"

    # 兜底: 输出 kind 对应的 banner
    if output_kind == "audio":
        url = _to_url(src)
        if url:
            return ('<div class=\"file-fallback\">🎵 <b>音频</b> 已生成: '
                    '<a href=\"' + url + '\" download>下载播放</a> '
                    '<audio controls preload="metadata" style=\"vertical-align:middle;margin-left:8px\">'
                    '<source src=\"' + url + '\"/></audio></div>')
    if output_kind == "video":
        url = _to_url(src)
        if url:
            return ('<div class=\"file-fallback\">🎬 <b>视频</b> 已生成: '
                    '<a href=\"' + url + '\" download>下载</a></div>')
    return ("<div class=\"file-fallback\">📄 未知输出格式: <code>" + src[:80] + "</code></div>")
