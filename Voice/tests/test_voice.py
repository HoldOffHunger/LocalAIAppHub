import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import system_prompt, without_name  # noqa: E402
from speech import catalogue, describe_voice, speakable, split_ready  # noqa: E402


def test_every_voice_says_its_sex_and_accent():
    assert describe_voice("af_heart") == {"id": "af_heart", "name": "Heart", "sex": "female", "accent": "American",
                                          "english": True, "favourite": True}
    assert describe_voice("bm_george")["sex"] == "male" and describe_voice("bm_george")["accent"] == "British"
    assert describe_voice("jf_alpha")["english"] is False
    ordered = [v["id"] for v in catalogue(["bm_lewis", "zf_xiaoxiao", "am_adam", "af_sky", "bf_emma"])]
    assert ordered == ["af_sky", "am_adam", "bf_emma", "bm_lewis", "zf_xiaoxiao"]  # English first, women then men


def test_only_the_words_get_spoken():
    assert speakable("*gently chuckles* Oh, hello there! 🐾 See https://x.y **now**") == "Oh, hello there! See now"
    assert speakable("<think>hmm, what to say</think>Hi Ben.") == "Hi Ben."
    assert speakable("*waves*") == ""


def test_sentences_come_off_the_front_as_they_finish():
    ready, rest = split_ready("Oh! Hello there, dear. My day was quite lovely, thank you for asking. The hal", first=True)
    assert ready == ["Oh!", "Hello there, dear. My day was quite lovely, thank you for asking."] and rest == "The hal"
    ready, rest = split_ready("Yes. No. Maybe so, if you like it that much. And", first=False)
    assert ready == ["Yes. No. Maybe so, if you like it that much."] and rest == "And"  # short ones wait for company


def test_her_name_is_not_read_out_and_she_is_told_she_is_speaking():
    assert without_name("Claudia: Oh, hello!", "Claudia") == "Oh, hello!"
    assert without_name("Claudia said hello.", "Claudia") == "Claudia said hello."
    prompt = system_prompt({"name": "Claudia", "prompt": "You are Claudia.", "examples": ["Ben: hi\nClaudia: hello!"]})
    assert prompt.startswith("You are Claudia.") and "Examples of how Claudia talks" in prompt and "spoken conversation" in prompt
