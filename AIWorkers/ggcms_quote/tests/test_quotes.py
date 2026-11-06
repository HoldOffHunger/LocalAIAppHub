import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))

from quote_candidates import candidates  # noqa: E402
from site_texts import SiteText  # noqa: E402


def test_only_whole_standalone_sentences_are_offered():
    found = candidates(["A chain always useless and dangerous; a chain always intolerable, it must be smashed. "
                        "It has but one aim -- to secure power and hold it, at any cost.",
                        "But we will never recognize the institutions; we will take or win all possible reforms.",
                        "See https://example.org/page for the full text of the speech, which was given in 1921.",
                        "Chapter 4 begins here with a long and winding introduction to the matter at hand.",
                        "In 1917 there were 1,204,331 members across 4,512 branches of the union.",
                        "and so the workers, having seen all this, went on to the next town without stopping."])
    assert found == ["A chain always useless and dangerous; a chain always intolerable, it must be smashed."]


def test_long_texts_are_sampled_evenly():
    paragraphs = [f"Sentence number {word} is long enough to be offered as a quote here." for word in ("one two three four".split() * 20)]
    found = candidates(paragraphs, most=10)
    assert len(found) == 10 and found[0] == paragraphs[0]


def test_paragraph_breaks_end_sentences_and_source_is_ben_style():
    text = SiteText(5, "Chapter 1", "The Conquest of Bread", "Peter Kropotkin", "<p>One paragraph here</p><p>Another one</p>")
    assert text.paragraphs() == ["One paragraph here", "Another one"]
    assert text.source() == "\"The Conquest of Bread,\" by Peter Kropotkin"
