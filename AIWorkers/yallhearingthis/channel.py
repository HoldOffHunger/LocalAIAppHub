import json
import subprocess
from pathlib import Path

import yt_dlp

CHANNEL = "https://www.youtube.com/@yallhearingthis"
TABS = {"videos": "Video", "streams": "Live stream", "shorts": "Short"}
QUIET = {"quiet": True, "no_warnings": True, "noprogress": True}


class RateLimited(Exception):
    """YouTube answered 429. Asking again at once only lengthens the ban, so the run backs off instead."""


def list_videos() -> list[dict]:
    """Every public video on the channel, oldest first, from all three tabs: id, title and which tab it's on."""
    found, seen = [], set()
    with yt_dlp.YoutubeDL({**QUIET, "extract_flat": True}) as ydl:
        for tab, kind in TABS.items():
            listing = ydl.extract_info(f"{CHANNEL}/{tab}", download=False) or {}
            for entry in listing.get("entries") or []:
                if entry.get("id") and entry["id"] not in seen:
                    seen.add(entry["id"])
                    found.append({"video": entry["id"], "title": entry.get("title", ""), "format": kind})
    return found[::-1]  # a tab lists newest first; the site is filled in the order the shows were made


def fetch(video: str, folder: Path) -> dict:
    """One video's metadata and thumbnail, then one English caption track (never the video itself), each fetched once;
    later runs read the files. A caption track that failed is asked for again next time, not given up on."""
    folder.mkdir(parents=True, exist_ok=True)
    info = folder / f"{video}.info.json"
    url = f"https://www.youtube.com/watch?v={video}"
    if not info.exists():
        _download(url, {"skip_download": True, "writeinfojson": True, "writethumbnail": True,
                        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg"}],
                        "outtmpl": str(folder / "%(id)s.%(ext)s")})
    data = json.loads(info.read_text(encoding="utf-8"))
    track = _track(data)
    if not track:
        # Decided from the metadata, so a translation fetched by an earlier run is passed over too
        (folder / f"{video}.nocaptions").write_text("YouTube offered no English captions for this video, only a machine "
                                                    "translation from the language it's filed under.\n", encoding="utf-8")
    elif not _captions(folder, video):
        manual, language = track
        try:
            _download(url, {"skip_download": True, "writesubtitles": manual, "writeautomaticsub": not manual,
                            "subtitleslangs": [language], "subtitlesformat": "vtt", "sleep_interval_subtitles": 3,
                            "outtmpl": str(folder / "%(id)s.%(ext)s")})
        except RateLimited:
            # The show is still worth making; its transcript is fetched on a later --deferred run
            data["_captions_deferred"] = True
    for heavy in ("formats", "requested_formats", "automatic_captions", "subtitles", "thumbnails", "heatmap"):
        data.pop(heavy, None)  # half a megabyte of stream URLs nobody here needs
    data["_no_english"] = not track
    data["_captions"] = "" if not track else _captions(folder, video)
    data["_thumbnail"] = _jpeg(folder, video)
    return data


def _track(data: dict) -> tuple[bool, str] | None:
    # Her own captions first. Otherwise the automatic track in the language spoken: YouTube's automatic "en" on an
    # English video is a machine translation of en-orig, the same words, and it's the request YouTube throttles hardest
    manual = data.get("subtitles") or {}
    automatic = data.get("automatic_captions") or {}
    for language in ("en", "en-US", "en-GB"):
        if language in manual:
            return True, language
    if "en-orig" in automatic:
        return False, "en-orig"
    if "en" in automatic and (data.get("language") or "en").startswith("en"):
        return False, "en"
    # A video YouTube files under another language (the MV's, often Korean) has only a machine translation in English:
    # the hosts' English heard as Korean and translated back, and the request YouTube throttles hardest. None is better
    return None


def _download(url: str, options: dict) -> None:
    try:
        with yt_dlp.YoutubeDL({**QUIET, **options}) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as failure:
        if "429" in str(failure):
            raise RateLimited(str(failure)) from failure
        raise


def _jpeg(folder: Path, video: str) -> str:
    # YouTube serves thumbnails as WebP, and yt-dlp's converter only runs when something is downloaded, which here
    # nothing is; so ffmpeg makes the JPEG the site's image code expects
    jpeg = folder / f"{video}.jpg"
    if not jpeg.exists():
        source = next((p for p in (folder / f"{video}.webp", folder / f"{video}.png") if p.exists()), None)
        if source:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(source), "-q:v", "2", str(jpeg)], check=False)
    return str(jpeg) if jpeg.exists() else ""


def _captions(folder: Path, video: str) -> str:
    for language in ("en", "en-US", "en-GB", "en-orig"):
        path = folder / f"{video}.{language}.vtt"
        if path.exists():
            return str(path)
    return ""
