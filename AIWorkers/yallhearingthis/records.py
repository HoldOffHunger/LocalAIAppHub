import html
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from captions import Line, paragraphs, stamp

SITE = "Y'all Hearing This?!"
LANGUAGES = {"en": "English", "ko": "Korean", "ja": "Japanese"}
WIDE = re.compile(r"[\U00010000-\U0010FFFF]")  # emoji and the rest of the astral planes
JOINERS = re.compile(r"[‍︎️]")  # what holds an emoji together, left behind when it's taken out
SERIES = re.compile(r"artist of the week", re.I)  # a running series' name, before the colon of every episode
FOOTER = re.compile(r"twitch\.tv|patreon|join us on|please consider|subscribe|instagram|tiktok|business inquir|https?://", re.I)


def narrow(text: str) -> str:
    """For a plain field. Every text column on yallhearingthis is utf8mb3, which can't hold an emoji at all; the
    symbols that can (a snowflake, a heart) go too, or a title keeps "❄" from the middle of a run of emoji."""
    text = "".join(c for c in WIDE.sub("", text or "") if unicodedata.category(c) != "So")
    return re.sub(r"[ \t]+", " ", JOINERS.sub("", text)).strip()


def markup(text: str) -> str:
    """For the textbody, which is HTML: escaped, and an emoji kept as a character reference, which utf8mb3 can hold."""
    escaped = html.escape(JOINERS.sub("", text or ""), quote=False)
    return WIDE.sub(lambda m: f"&#x{ord(m.group(0)):X};", escaped)


def slug(text: str, most: int = 80) -> str:
    folded = unicodedata.normalize("NFKD", narrow(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", folded)).strip("-")[:most].strip("-")


def split_title(title: str) -> tuple[str, str]:
    # "NMIXX 'Sonar' Reaction: Hypnotized by Their Stunning Performance!" is a title and a subtitle. A short's trailing
    # hashtags (#shorts #ateez) are its tags, which are saved as tags, not part of its name
    title = re.sub(r"(?:\s+#[^\s#]+)+\s*$", "", narrow(title)).strip() or narrow(title)
    head, colon, tail = title.partition(": ")
    if SERIES.search(head):
        return title, ""  # "Artist of the Week: SHINee! Full Podcast": the series name alone would be 147 shows' title
    return (head.strip(), tail.strip()) if colon and head.strip() and tail.strip() else (title, "")


def own_description(description: str) -> str:
    """The lines written for this video, before the footer every video carries (Twitch, Patreon, socials). The footer
    and the rest still go into the textbody, whole; Description is a 512-character column."""
    kept = []
    for block in re.split(r"\n\s*\n", description or ""):
        if FOOTER.search(block):
            break
        lines = [line for line in block.splitlines() if line.strip() and not re.fullmatch(r"(?:\s*#\S+)+\s*", line)]
        if lines:
            kept.append(" ".join(narrow(line) for line in lines))
    text = " ".join(kept).strip()
    return text if len(text) <= 512 else text[:509].rsplit(" ", 1)[0] + "..."


def plain_fields() -> dict:
    # The channel's own casing stays: smart title case would make NMIXX "Nmixx" and aespa "Aespa"
    return {"title-smart-title-case": "", "subtitle-smart-title-case": "", "listtitle-smart-title-case": "", "Publish": "1"}


def show_record(video: dict, lines: list[Line], quote: dict | None, artist_ids: list[int], images: Path, kind: str) -> dict:
    title, subtitle = split_title(video.get("title", ""))
    code = video["_code"]
    fields = {**plain_fields(), "Title": title[:255], "Subtitle": subtitle[:255], "Code": code}
    own = own_description(video.get("description", ""))
    if own:
        fields |= {"Description": [own], "description_Source": ["YouTube"], "description_Language": ["en"]}
    if quote:
        fields |= {"Quote": [narrow(quote["quote"])[:2048]], "quote_Source": [f"\"{title},\" by {SITE}"], "quote_Language": ["en"]}
    fields |= {"Text": [show_text(video, lines, kind)], "textbody_Source": ["YouTube"], "textbody_Language": ["en"],
               "textbody_StripURLs": [""], "textbody_AmericanizeVocabulary": ["1"]}
    tags = show_tags(video)
    if tags:
        fields |= {"Tag": tags, "tag_Language": ["en"] * len(tags)}
    fields |= {"link_Title": ["Watch on YouTube"], "URL": [video["webpage_url"]], "link_Language": ["en"]}
    when = video.get("upload_date", "")
    if when:
        label = {"Live stream": "Streamed live on YouTube", "Short": "Published as a YouTube Short"}.get(kind, "Published on YouTube")
        fields |= {"EventDate": [f"{when[:4]}-{when[4:6]}-{when[6:8]}"], "EventTime": [""], "eventdate_Title": [label],
                   "eventdate_Description": [""], "eventdate_Language": ["en"]}
    if artist_ids:
        fields |= {"ChosenEntryid": [str(n) for n in artist_ids], "association_Type": ["Role"] * len(artist_ids),
                   "association_SubType": ["Artist"] * len(artist_ids)}
    record = {"fields": fields}
    if video.get("_thumbnail"):
        picture = images / f"{code}.jpg"
        picture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video["_thumbnail"], picture)
        fields |= {"image_Title": ["Thumbnail from YouTube"], "image_FileName": [picture.name], "image_Description": [""]}
        record["files"] = {"Image": [str(picture)]}
    return record


def show_tags(video: dict) -> list[str]:
    """YouTube's own tags, then every hashtag in the title and description (#nmixx #nswer #kpopreaction), without the
    #, once each however it's cased."""
    found = list(video.get("tags") or [])
    found += re.findall(r"(?<![\w&])#([^\s#.,!?;:()\[\]\"']+)", f"{video.get('title', '')}\n{video.get('description', '')}")
    kept = {}
    for tag in found:
        tag = narrow(tag)[:255]
        key = re.sub(r"\s+", " ", tag.lower())
        if tag and not tag.isdigit() and key not in kept:  # "#1" is a ranking, not a tag
            kept[key] = tag
    return list(kept.values())


def show_text(video: dict, lines: list[Line], kind: str) -> str:
    """Everything YouTube says about the video that has no field of its own, as labelled lines, then the full
    description, then the transcript."""
    facts = [("Format", kind), ("Published", _published(video)), ("Duration", video.get("duration_string", "")),
             ("Views", _count(video.get("view_count"), video)), ("Likes", _count(video.get("like_count"), video)),
             ("Comments", _count(video.get("comment_count"), video)), ("Category", ", ".join(video.get("categories") or [])),
             ("Language", LANGUAGES.get(video.get("language") or "", video.get("language") or "")), ("Location", video.get("location") or ""),
             ("Live", "Yes, streamed live" if video.get("was_live") else ""),
             ("Age restriction", f"{video['age_limit']}+" if video.get("age_limit") else ""),
             ("Best quality", f"{video['height']}p" if video.get("height") else ""),
             ("YouTube", video.get("webpage_url", ""))]
    parts = [f"<p><b>{label}:</b> {markup(str(value))}</p>" for label, value in facts if value]
    chapters = video.get("chapters") or []
    if chapters:
        listed = "".join(f"<li>{stamp(c.get('start_time', 0))} {markup(c.get('title', ''))}</li>" for c in chapters)
        parts.append(f"<p><b>Chapters:</b></p><ul>{listed}</ul>")
    description = (video.get("description") or "").strip()
    if description:
        blocks = [markup(block).replace("\n", "<br>") for block in re.split(r"\n\s*\n", description) if block.strip()]
        parts.append("<p><b>YouTube description:</b></p>" + "".join(f"<p>{block}</p>" for block in blocks))
    said = paragraphs(lines)
    if said:
        parts.append("<p><b>Transcript:</b> (YouTube's automatic captions)</p>" + "".join(f"<p>{markup(p)}</p>" for p in said))
    return "\n\n".join(parts)


def artist_record(artist: dict, wiki: dict | None, quote: dict | None, quote_show: str, images: Path, picture: Path | None) -> dict:
    code = artist["code"]
    fields = {**plain_fields(), "Title": narrow(artist["name"])[:255], "Code": code}
    if wiki:
        short = narrow(wiki.get("short", ""))
        if short:
            fields["Subtitle"] = (short[:1].upper() + short[1:])[:255]
        first = _first_sentence(wiki["intro"][0]) if wiki.get("intro") else ""
        if first:
            fields |= {"Description": [first], "description_Source": ["Wikipedia.org"], "description_Language": ["en"]}
        if wiki.get("intro"):
            body = "".join(f"<p>{markup(p)}</p>" for p in wiki["intro"]) + "<p>(Source: Wikipedia.org.)</p>"
            fields |= {"Text": [body], "textbody_Source": ["Wikipedia.org"], "textbody_Language": ["en"],
                       "textbody_StripURLs": ["1"], "textbody_AmericanizeVocabulary": ["1"]}
        links = [(f"{narrow(artist['name'])} on Wikipedia", wiki.get("url", "")), ("Official website", wiki.get("website", ""))]
        links = [(t, u) for t, u in links if u and len(u) <= 255]
        if links:
            fields |= {"link_Title": [t for t, _ in links], "URL": [u for _, u in links], "link_Language": ["en"] * len(links)}
        dates = [(label, day) for label, day in (("Birth Day", wiki.get("born", "")), ("Formed", wiki.get("formed", "")))
                 if len(day) == 10]  # a date known only to the year has no day to store
        if dates:
            fields |= {"EventDate": [d for _, d in dates], "EventTime": [""] * len(dates), "eventdate_Title": [t for t, _ in dates],
                       "eventdate_Description": [""] * len(dates), "eventdate_Language": ["en"] * len(dates)}
    if artist.get("group"):
        fields |= {"Tag": [narrow(artist["group"])], "tag_Language": ["en"]}
    if quote:
        fields |= {"Quote": [narrow(quote["quote"])[:2048]], "quote_Source": [f"\"{quote_show},\" by {SITE}"], "quote_Language": ["en"]}
    record = {"fields": fields}
    if picture:
        fields |= {"image_Title": ["Image from Wikipedia.org"], "image_FileName": [picture.name],
                   "image_Description": ["From Wikimedia Commons, via the artist's Wikipedia page."]}
        record["files"] = {"Image": [str(picture)]}
    return record


def _first_sentence(paragraph: str) -> str:
    # Wikipedia opens with the sentence that says who someone is; its brackets (Korean names, romanisations) are dropped
    text = narrow(re.sub(r"\s*\([^()]*\)", "", paragraph))
    match = re.match(r"(.+?[.!?])(?:\s+[A-Z]|$)", text)
    sentence = match.group(1) if match else text
    return sentence if len(sentence) <= 512 else sentence[:509].rsplit(" ", 1)[0] + "..."


def _published(video: dict) -> str:
    if video.get("timestamp"):
        moment = datetime.fromtimestamp(video["timestamp"], timezone.utc)
        return f"{moment.day} {moment:%B %Y, %H:%M} UTC"
    when = video.get("upload_date", "")
    return f"{when[:4]}-{when[4:6]}-{when[6:8]}" if when else ""


def _count(value, video: dict) -> str:
    if value is None:
        return ""
    on = datetime.fromtimestamp(video["epoch"], timezone.utc) if video.get("epoch") else None
    return f"{value:,}" + (f" (as of {on.day} {on:%B %Y})" if on else "")
