# Ben's movies: the recommender's export in E:\MovieTheaterWithClaudia\data\movies.json when it's there, otherwise his start.txt.
# Tiers are the "9/10 Movies" headings; a line indented two tabs, before the tier's first movie, is its description; "Comments:" belongs to the movie above it.

import json
import os
import re

TIER_HEADING = re.compile(r"^\s*(?:(\d+)/10|(TO WATCH)) MOVIES\s*$", re.IGNORECASE)
DASHES = re.compile(r"^\s*-{10,}\s*$")
YEAR = re.compile(r"\((\d{4})\)\s*$")
LEADING_ARTICLE = re.compile(r"^(the|a|an) ")


def simplified(title):
    # "The.Fisher.King.1991.BluRay" and "Fisher King (1991)" both become "fisher king ..."
    words = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return LEADING_ARTICLE.sub("", words)


def subtitle_names(folder):
    try:
        return [simplified(os.path.splitext(name)[0]) for name in os.listdir(folder) if name.lower().endswith(".srt")]
    except OSError:
        return []


def has_subtitles(title, subtitles):
    wanted = simplified(YEAR.sub("", title))
    return bool(wanted) and any(name == wanted or name.startswith(wanted + " ") for name in subtitles)


def new_tier(match):
    rating = int(match.group(1)) if match.group(1) else None
    return {"id": "r%d" % rating if rating is not None else "towatch", "rating": rating,
            "label": "%d/10" % rating if rating is not None else "To Watch", "description": "", "movies": []}


def read_line(tier, line):
    # One line of a tier's section: the description, a comment, or a movie
    text = line.strip()
    if not text or DASHES.match(line):
        return
    if line.startswith("\t\t") and not tier["movies"]:
        tier["description"] = text
    elif text.lower().startswith("comments:") and tier["movies"]:
        comment = text[len("comments:"):].strip()
        tier["movies"][-1]["comments"] = "" if comment in ("", "--") else comment
    else:
        year = YEAR.search(text)
        tier["movies"].append({"title": text, "year": int(year.group(1)) if year else None, "comments": ""})


def parse_list(text):
    tiers = []
    for line in text.splitlines():
        heading = TIER_HEADING.match(line)
        if heading:
            tiers.append(new_tier(heading))
        elif tiers:
            read_line(tiers[-1], line)
    return tiers


NOTES = (("recommendations", "recommendations.md"), ("taste", "taste_profile.md"))


def read_notes(folder):
    # The recommender's write-ups, once its data folder is copied to E:\MovieTheaterWithClaudia\data
    notes = {}
    for key, name in NOTES:
        try:
            with open(os.path.join(folder, "data", name), encoding="utf-8", errors="replace") as handle:
                notes[key] = handle.read()
        except OSError:
            notes[key] = ""
    return notes


def read_database(folder):
    # The recommender's export (data/movies.json): films, Claudia's script reads, and her picks
    try:
        with open(os.path.join(folder, "data", "movies.json"), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("films") else None


def json_list(text):
    # The export keeps strengths, weaknesses and themes as JSON text
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def describe_analysis(analysis):
    if not analysis:
        return None
    return {"score": analysis.get("script_score"), "summary": analysis.get("summary") or "",
            "strengths": json_list(analysis.get("strengths")), "weaknesses": json_list(analysis.get("weaknesses")),
            "themes": json_list(analysis.get("themes"))}


def describe_film(film, analyses, subtitles):
    title = film.get("title_as_written") or film.get("title") or film["film_id"]
    analysis = analyses.get(film["film_id"])
    return {"id": film["film_id"], "title": title, "year": film.get("year"), "comments": film.get("comment_verbatim") or "",
            "subtitles": bool(analysis) or has_subtitles(title, subtitles), "analysis": describe_analysis(analysis)}


def tier_order(label):
    rating = re.match(r"^(\d+)/10$", label)
    return -int(rating.group(1)) if rating else 1  # best first, To Watch last


def tier_descriptions(folder):
    # Ben's own words under each heading, from his ratings list
    for path in (os.path.join(folder, "data", "ratings_original.txt"), os.path.join(folder, "start.txt")):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return {tier["label"]: tier["description"] for tier in parse_list(handle.read())}
        except OSError:
            continue
    return {}


def tiers_from_database(data, folder):
    analyses = {analysis["film_id"]: analysis for analysis in data.get("analyses", [])}
    subtitles = subtitle_names(os.path.join(folder, "_srt_for_claudia"))
    descriptions = tier_descriptions(folder)
    grouped = {}
    for film in data["films"]:
        grouped.setdefault(film.get("tier_label") or "TO WATCH", []).append(describe_film(film, analyses, subtitles))
    tiers = []
    for label in sorted(grouped, key=tier_order):
        tier = new_tier(TIER_HEADING.match(label + " MOVIES"))
        tier.update({"description": descriptions.get(tier["label"], ""), "movies": grouped[label]})
        tiers.append(tier)
    return tiers


def describe_pick(pick):
    return {"id": pick.get("film_id", ""), "title": pick.get("title", ""), "year": pick.get("year"), "director": pick.get("director") or "",
            "round": pick.get("round"), "why": pick.get("why_ben") or "", "risk": pick.get("risk") or "", "status": pick.get("status", "")}


def tiers_from_text(folder):
    with open(os.path.join(folder, "start.txt"), encoding="utf-8", errors="replace") as handle:
        tiers = parse_list(handle.read())
    subtitles = subtitle_names(os.path.join(folder, "_srt_for_claudia"))
    for tier in tiers:
        for movie in tier["movies"]:
            movie.update({"id": "", "subtitles": has_subtitles(movie["title"], subtitles), "analysis": None})
    return tiers


def load_movies(folder):
    # The recommender's export when it's there; otherwise Ben's start.txt, read fresh
    data = read_database(folder)
    try:
        tiers = tiers_from_database(data, folder) if data else tiers_from_text(folder)
    except OSError:
        return {"error": "Can't find movies.json or start.txt in " + folder, "tiers": [], "picks": [], "notes": read_notes(folder)}
    picks = [describe_pick(pick) for pick in data.get("recommendations", [])] if data else []
    return {"source": "movies.json" if data else "start.txt", "tiers": tiers, "picks": picks, "notes": read_notes(folder)}
