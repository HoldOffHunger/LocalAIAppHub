import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))

from artists import _tidy, plain  # noqa: E402
from captions import caption_lines  # noqa: E402
from quote_lines import trimmed  # noqa: E402
from records import markup, narrow, own_description, show_tags, slug, split_title  # noqa: E402


def test_plain_fields_lose_emoji_and_symbols_that_utf8mb3_cannot_hold():
    assert narrow("Billlie & NMIXX Holiday MV Reaction! 💖🦄🎄❄️") == "Billlie & NMIXX Holiday MV Reaction!"


def test_the_textbody_keeps_emoji_as_character_references():
    assert markup("MV! 💖 <3") == "MV! &#x1F496; &lt;3"


def test_a_title_splits_at_its_colon_into_title_and_subtitle():
    assert split_title("NMIXX 'Sonar' Reaction: Hypnotized by Their Stunning Performance!🦄💖") == \
        ("NMIXX 'Sonar' Reaction", "Hypnotized by Their Stunning Performance!")
    assert split_title("Twice Holiday MV Reaction!") == ("Twice Holiday MV Reaction!", "")
    assert split_title("Unboxing Ateez The World EP1 Movement #shorts #ateez #unboxing") == ("Unboxing Ateez The World EP1 Movement", "")
    assert split_title("#1 Fan Reaction") == ("#1 Fan Reaction", "")  # a hashtag that starts the title is part of it


def test_a_series_title_keeps_the_episode_after_its_colon():
    assert split_title("Artist of the Week: SHINee! Full Podcast Y'all Hearing This?!") ==         ("Artist of the Week: SHINee! Full Podcast Y'all Hearing This?!", "")
    assert split_title("K-Pop Podcast! Artist of the Week: Twice") == ("K-Pop Podcast! Artist of the Week: Twice", "")


def test_hashtags_in_the_title_and_description_become_tags():
    video = {"tags": ["nmixx", "NMIXX sonar"], "title": "Unboxing #shorts #ateez",
             "description": "Checking out NMIXX's \"Sonar\" MV! 💖\n#nmixx #nswer #kpopreaction\nWe're #1! &#39;"}
    assert show_tags(video) == ["nmixx", "NMIXX sonar", "shorts", "ateez", "nswer", "kpopreaction"]


def test_codes_are_plain_ascii():
    assert slug("Reacting to Rosé's 'Toxic Till the End'") == "reacting-to-rose-s-toxic-till-the-end"


def test_description_stops_at_the_footer_every_video_carries():
    text = "Checking out NMIXX's \"Sonar\" MV! 💖🦄\n#nmixx #nswer #kpopreaction \n\nJoin us on Twitch every Wednesday\nhttps://twitch.tv/x"
    assert own_description(text) == "Checking out NMIXX's \"Sonar\" MV!"


def test_a_quote_trim_is_kept_only_when_it_is_the_speakers_own_words():
    said = "goodness yeah they're just so good they're just so good I'm so excited I"
    assert trimmed(said, "they're just so good I'm so excited") == "they're just so good I'm so excited"
    assert trimmed(said, "they are so good and I'm excited") == said
    assert trimmed(said, "so good") == said  # too short to stand as a quote


def test_rolling_captions_are_said_once(tmp_path):
    vtt = tmp_path / "x.en-orig.vtt"
    vtt.write_text("WEBVTT\nKind: captions\nLanguage: en\n\n"
                   "00:00:14.360 --> 00:00:16.310 align:start position:0%\n[Music]\n"
                   "all<00:00:14.519><c> right</c><00:00:14.639><c> so</c>\n\n"
                   "00:00:16.310 --> 00:00:16.320 align:start position:0%\nall right so\n \n\n"
                   "00:00:16.320 --> 00:00:24.020 align:start position:0%\nall right so\nbreaker\n", encoding="utf-8")
    assert [line.text for line in caption_lines(vtt)] == ["all right so", "breaker"]


def test_names_compare_without_case_or_accents():
    assert plain("ROSÉ") == plain("Rose") == "rose"


def test_wikipedia_intro_loses_the_dropped_pronunciations_separator():
    assert _tidy("Nmixx (; Korean: 엔믹스; stylized in all caps) is a group") == "Nmixx (Korean: 엔믹스; stylized in all caps) is a group"
