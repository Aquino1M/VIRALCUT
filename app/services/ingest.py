from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"} or host.endswith(".youtube.com")


def _detect_chromium_browser() -> Path | None:
    """Find a Chromium-family browser that the WPC PO-token provider can launch."""
    roots = [
        os.getenv("PROGRAMFILES"),
        os.getenv("PROGRAMFILES(X86)"),
        os.getenv("LOCALAPPDATA"),
    ]
    rel_paths = [
        Path("BraveSoftware/Brave-Browser/Application/brave.exe"),
        Path("Google/Chrome/Application/chrome.exe"),
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Chromium/Application/chrome.exe"),
    ]
    for root in filter(None, roots):
        base = Path(root)
        for rel in rel_paths:
            candidate = base / rel
            if candidate.exists():
                return candidate

    for exe in ("brave", "brave.exe", "chrome", "chrome.exe", "msedge", "msedge.exe", "chromium", "chromium.exe"):
        found = shutil.which(exe)
        if found:
            return Path(found)
    return None


def _browser_cookie_profile_available(browser: str) -> bool:
    """Only ask yt-dlp for a browser session that exists on this machine."""
    browser = (browser or "").strip().lower()
    home = Path.home()
    if browser == "firefox":
        roots = [home / ".mozilla/firefox", home / "AppData/Roaming/Mozilla/Firefox/Profiles", home / "Library/Application Support/Firefox/Profiles"]
        return any(root.is_dir() and any(root.glob("*/cookies.sqlite")) for root in roots)
    local = Path(os.getenv("LOCALAPPDATA") or home / "AppData/Local")
    mac = home / "Library/Application Support"
    names = {
        "brave": ("BraveSoftware/Brave-Browser/User Data", "BraveSoftware/Brave-Browser"),
        "chrome": ("Google/Chrome/User Data", "Google/Chrome"),
        "edge": ("Microsoft/Edge/User Data", "Microsoft Edge"),
        "chromium": ("Chromium/User Data", "Chromium"),
        "vivaldi": ("Vivaldi/User Data", "Vivaldi"),
        "opera": ("Opera Software/Opera Stable", "com.operasoftware.Opera"),
    }.get(browser)
    if not names:
        return False
    roots = [local / names[0], home / ".config" / names[0], mac / names[1]]
    return any(root.is_dir() and any(root.glob("**/Cookies")) for root in roots)


def _automatic_cookie_browsers() -> list[str]:
    """Use only browser sessions physically available to this worker."""
    return [browser for browser in ("brave", "chrome", "edge", "firefox", "chromium", "vivaldi", "opera") if _browser_cookie_profile_available(browser)]


def _managed_cookie_file() -> Path | None:
    """Return the operator-managed YouTube session, when mounted on this worker."""
    raw_path = os.getenv("YTDLP_COOKIES_FILE", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    return path if path.is_file() and path.stat().st_size else None


def _po_token_provider_args() -> dict:
    """Use the private BgUtils provider only when the operator configured it."""
    base_url = os.getenv("YTDLP_BGUTIL_BASE_URL", "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return {}
    return {"youtubepot-bgutilhttp": {"base_url": [base_url]}}


def _js_runtimes() -> dict:
    deno = shutil.which("deno")
    if deno:
        return {"deno": {"path": deno}}
    node = shutil.which("node")
    if node:
        return {"node": {"path": node}}
    return {}


def _base_opts(dest_dir: Path) -> dict:
    opts = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        # YouTube 2026 requires the external JS challenge solver for full support.
        # The [default] yt-dlp extra installs yt-dlp-ejs; remote-components is a
        # fallback so the app can still obtain a matching EJS bundle if needed.
        "remote_components": {"ejs:github"},
    }
    runtimes = _js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts


def _find_result_path(info: dict, dest_dir: Path) -> Path | None:
    requested = info.get("requested_downloads") or []
    for item in requested:
        filepath = item.get("filepath") if isinstance(item, dict) else None
        if filepath:
            p = Path(filepath)
            if p.exists():
                return p
    for p in dest_dir.glob("source.*"):
        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"} and p.is_file():
            return p
    return None


def _cleanup_partial(dest_dir: Path) -> None:
    for pattern in ("source.*.part", "source.part", "source.*.ytdl"):
        for p in dest_dir.glob(pattern):
            try:
                p.unlink()
            except OSError:
                pass


def _download_once(url: str, dest_dir: Path, extra_opts: dict | None = None) -> Path:
    from yt_dlp import YoutubeDL

    opts = _base_opts(dest_dir)
    if extra_opts:
        # extractor_args may contain nested dictionaries; replace as one unit.
        opts.update(extra_opts)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    result = _find_result_path(info, dest_dir)
    if result:
        return result
    raise RuntimeError("O downloader terminou, mas o arquivo de vídeo não foi encontrado.")


def _clean_download_error(exc: Exception) -> str:
    return _ANSI_RE.sub("", str(exc)).strip()


def ingest_url(url: str, dest_dir: Path) -> Path:
    """Download a public URL with YouTube 2026 compatibility fallbacks.

    Strategy for YouTube:
      1. Normal yt-dlp + EJS + Deno/Node.
      2. On 403/bot challenge, retry using mweb + an installed PO-token provider
         (yt-dlp-getpot-wpc). It mints a token using a local Chromium browser.
      3. Retry with the operator-managed session file, when one is mounted.
      4. When running beside a browser session, automatically try its cookies.
    """
    from yt_dlp.utils import DownloadError

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _download_once(url, dest_dir)
    except DownloadError as first_exc:
        first_msg = _clean_download_error(first_exc)
        if not _is_youtube_url(url) or not any(token in first_msg.lower() for token in ("403", "forbidden", "not a bot", "sign in to confirm")):
            raise RuntimeError(first_msg) from first_exc

    browser_path = _detect_chromium_browser()
    extractor_args = {}
    for player_client in ("mweb", "web"):
        _cleanup_partial(dest_dir)
        extractor_args = {"youtube": {"player_client": [player_client]}, **_po_token_provider_args()}
        if browser_path:
            extractor_args["youtubepot-wpc"] = {"browser_path": [browser_path.as_posix()]}
        try:
            return _download_once(url, dest_dir, {"extractor_args": extractor_args})
        except DownloadError:
            continue

    managed_cookie_file = _managed_cookie_file()
    if managed_cookie_file:
        _cleanup_partial(dest_dir)
        try:
            return _download_once(
                url,
                dest_dir,
                {"cookiefile": str(managed_cookie_file), "extractor_args": extractor_args},
            )
        except DownloadError as cookie_exc:
            second_msg = _clean_download_error(cookie_exc)

    for browser in _automatic_cookie_browsers():
        _cleanup_partial(dest_dir)
        try:
            return _download_once(
                url,
                dest_dir,
                {
                    "cookiesfrombrowser": (browser, None, None, None),
                    "extractor_args": extractor_args,
                },
            )
        except DownloadError as cookie_exc:
            final_msg = _clean_download_error(cookie_exc)
            continue

    raise RuntimeError(
        "O modo automático do YouTube tentou os métodos disponíveis neste processamento, mas a importação não foi liberada agora. "
        "Tente novamente em alguns minutos ou envie o arquivo de vídeo diretamente."
    )


def ingest_upload(upload_path: str | Path, dest_dir: Path) -> Path:
    src = Path(upload_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ("source" + (src.suffix or ".mp4"))
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest
