import random
from collections import Counter
from dataclasses import dataclass, field

from debate_turn import DebateTurn
from dump_reader import WordRow
from word_check import WordCheck

JURORS = ["mistral:7b", "dolphin-llama3:latest", "gemma3:4b"]
SPEECHES = 10  # Ben: ten chances to speak altogether before a vote is called


@dataclass
class Case:
    """One word before the jury: first votes, the debate if they split, and the final verdict."""

    row: WordRow
    votes: dict = field(default_factory=dict)  # juror -> its independent verdict
    debate: list = field(default_factory=list)
    verdict: dict = field(default_factory=dict)


class Jury:
    """Three models judge a batch of words. Votes are batched by model so each loads once; only splits are debated."""

    def __init__(self, dictionary, jurors: list[str] = JURORS, speeches: int = SPEECHES, say=print, seed: int | None = None):
        self.dictionary = dictionary
        self.jurors = jurors
        self.speeches = speeches
        self.say = say
        self.random = random.Random(seed)

    def judge(self, rows: list[WordRow]) -> list[Case]:
        cases = [Case(row) for row in rows]
        for juror in self.jurors:
            check = WordCheck(juror, self.dictionary)
            for case in cases:
                case.votes[juror] = check.check(case.row)
        split = [case for case in cases if len({v["verdict"] for v in case.votes.values()}) > 1]
        self.say(f"votes in: {len(cases) - len(split)} unanimous, {len(split)} split, debating those")
        self._debate(split)
        for case in cases:
            case.verdict = self._verdict(case)
        return cases

    def _debate(self, cases: list[Case]) -> None:
        # Speeches rotate through the jurors; each speech is one model answering every open case, so models load once per speech
        for case in cases:
            case.debate = [{"juror": j, "position": v["verdict"], "proposed": v["proposed"], "argument": v["reason"]} for j, v in case.votes.items()]
        open_cases = list(cases)
        for speech in range(self.speeches):
            if not open_cases:
                return
            turn = DebateTurn(self.jurors[speech % len(self.jurors)], self.dictionary)
            for case in open_cases:
                case.debate.append(turn.speak(case.row, case.debate))
            open_cases = [case for case in open_cases if not self._agreed(case)]

    def _agreed(self, case: Case) -> bool:
        return len({position for _, position in self._latest(case).items()}) == 1

    def _latest(self, case: Case) -> dict:
        latest = {}
        for turn in case.debate or [{"juror": j, "position": v["verdict"]} for j, v in case.votes.items()]:
            latest[turn["juror"]] = turn["position"]
        return latest

    def _verdict(self, case: Case) -> dict:
        positions = self._latest(case)
        count = Counter(positions.values())
        verdict, votes = count.most_common(1)[0]
        how = "unanimous" if not case.debate else ("agreed after debate" if self._agreed(case) else f"vote {votes}-{len(self.jurors) - votes}")
        fix = self._fix(case, [j for j, p in positions.items() if p == "suspect"]) if verdict == "suspect" else ""
        reasons = [v["reason"] for j, v in case.votes.items() if v["verdict"] == verdict]
        kinds = [v["kind"] for v in case.votes.values() if v["kind"]]
        return {"verdict": verdict, "how": how, "proposed": fix, "kind": Counter(kinds).most_common(1)[0][0] if kinds else "",
                "reason": reasons[0] if reasons else "", "dictionary": next(iter(case.votes.values())).get("dictionary", [])}

    def _fix(self, case: Case, accusers: list[str]) -> str:
        # Agreed fixes win; if they all differ, a random juror picks one of the others' fixes, never its own
        fixes = {}
        for turn in case.debate or [{"juror": j, "proposed": v["proposed"]} for j, v in case.votes.items()]:
            if turn.get("proposed"):
                fixes[turn["juror"]] = turn["proposed"].strip()
        options = [fixes[j] for j in accusers if j in fixes] or list(fixes.values())
        common = Counter(option.lower() for option in options).most_common(1)
        if not options or common[0][1] > 1:
            return next((o for o in options if o.lower() == common[0][0]), "") if options else ""
        chooser = self.random.choice(self.jurors)
        others = [fix for juror, fix in fixes.items() if juror != chooser] or options
        return DebateTurn(chooser, self.dictionary).choose(case.row, others)
