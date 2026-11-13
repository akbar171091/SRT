"""Financial maintenance covenants, read from the covenant section(s) of a term sheet.

Only text under a financial covenant heading is read, which keeps incurrence tests in the debt,
lien and restricted payment baskets out. Within that text each named test ("Consolidated Net
Leverage Ratio", "Interest Coverage Ratio", "Minimum Liquidity") is located, and the level that
follows it is taken as the covenant. Further levels for the same test are sorted into

* a dated schedule    "4.75 to 1.00 through ..., 4.50 to 1.00 thereafter"
* an acquisition step-up   "may be increased to 4.50 to 1.00 following a Material Acquisition"
* a separate covenant   the same test at another level for a different borrower group

A figure that is not a level of the test is left out: one inside a definition ("cash netting capped
at 1.0x of EBITDA"), the level today or the borrower's own ratio ("currently 4.00x"), the level an
amendment replaces ("increased from 4.00x to 4.50x") and a ratio that another term is conditional
on ("restricted payments so long as the Total Leverage Ratio is below 3.00x"). Where that leaves a
test with a step-up or a condition only, no covenant is returned for it and a note says so.

A general "Covenants:" section is read as well. It lists baskets and their ratio conditions too,
so a level counts there only where the wording makes it a maintenance test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import COVENANT_TYPES
from .textmodel import clip, tidy
from .values import thresholds

METRIC_WORD = r"(?:ratio|leverage|coverage|liquidity|net\s+worth|capitali[sz]ation)"
# A covenant section heading, or a sub-heading that names one test and ends in a colon ("Minimum Interest Coverage Ratio:").
# A bare "Covenants:" is read as well, but only for what is worded as a maintenance test (see ``_conditional``).
LABEL = (r"(?:(?:key|principal|main|proposed)\s+)?financial\s+(?:maintenance\s+)?(?:condition\s+)?covenants?(?:\s*\([^)]{0,40}\))?"
         r"|financial\s+tests?|maintenance\s+covenants?|covenants?(?=\s*:)"
         r"|(?:minimum|maximum|max\.?|min\.?)\s+(?:[\w/.\-]+\s+){0,6}?" + METRIC_WORD + r"(?=\s*:)")
_GENERAL_LABEL_RE = re.compile(r"covenants?", re.IGNORECASE)
# Most specific first: where two patterns overlap in the text, the earlier one names the test.
TYPES = [
    ("min_fixed_charge_coverage", r"fixed\s+charges?(?:\s+coverage)?(?:\s+ratio)?"),
    ("min_collateral_coverage", r"(?:collateral|asset)\s+coverage(?:\s+ratio)?|loan[-\s]to[-\s]value(?:\s+ratio)?"),
    # debt service coverage has no type in the shared vocabulary: "other" keeps it out of the interest coverage benchmark
    ("other", r"debt\s+service\s+coverage(?:\s+ratio)?|\bdscr\b"),
    ("min_interest_coverage", r"interest\s+(?:expense\s+)?coverage(?:\s+ratio)?"
                              r"|ebitdar?\s*(?:to|/)\s*(?:consolidated\s+)?(?:cash\s+)?interest(?:\s+expense)?|\bcoverage\s+ratio"),
    ("max_debt_to_capitalization", r"(?:debt|indebtedness)\s*(?:to|/)\s*(?:total\s+)?capital(?:i[sz]ation)?(?:\s+ratio)?|capitali[sz]ation\s+ratio"),
    ("min_liquidity", r"liquidity"),
    ("min_net_worth", r"(?:tangible\s+)?net\s+worth"),
    ("max_first_lien_leverage", r"(?:\bnet\s+)?first[-\s]lien(?:\s+net)?(?:\s+[A-Za-z]+){0,2}?\s+leverage(?:\s+ratio)?"),
    ("max_secured_leverage", r"(?:senior\s+)?secured(?:\s+net)?(?:\s+[A-Za-z]+){0,2}?\s+leverage(?:\s+ratio)?"),
    ("max_net_leverage", r"\bnet(?:\s+[A-Za-z]+){0,2}?\s+leverage(?:\s+ratio)?|\bnet\s+debt\s*(?:to|/)\s*(?:[A-Za-z]+\s+){0,2}ebitdar?"),
    ("max_total_leverage", r"leverage(?:\s+ratio)?|(?:debt|indebtedness)\s*(?:to|/)\s*(?:consolidated\s+)?(?:adjusted\s+)?ebitdar?"),
]
UNITS = {"max_debt_to_capitalization": "pct", "min_liquidity": "usd_mm", "min_net_worth": "usd_mm"}
_RANK = {"max_total_leverage": 0, "max_net_leverage": 1, "max_secured_leverage": 2, "max_first_lien_leverage": 3}
# A leverage test that says which leverage it is, so never a loose reference to another leverage test.
_QUALIFIED_RE = re.compile(r"\b(?:total|net|secured|senior|first[-\s]lien)\b.*leverage", re.IGNORECASE)

_INCREASE = (r"step[-\s]?ups?\b|steps?\s+up|stepp(?:ed|ing)\s+up|increas(?:e[sd]?|ing)\s+(?:to|by|from)"
             r"|(?:may|shall|will|is)\s+(?:\w+\s+)?(?:be\s+)?(?:\w+\s+)?increased")
_ACQUISITION_KIND = (r"temporar|(?:material|qualified|permitted|significant|specified)\s+acquisition|transition\s+period"
                     r"|(?:acquisition|covenant|leverage)\s+holiday")
_ANY_ACQUISITION = (r"(?:following|after|upon)\s+(?:the\s+|an?\s+|any\s+)?(?:consummation\s+of\s+(?:the\s+|an?\s+|any\s+)?)?(?:\w+\s+)?acquisition"
                    r"(?!\s+(?:closing\s+)?date)")
_STEP_RE = re.compile("|".join((_INCREASE, _ACQUISITION_KIND, _ANY_ACQUISITION)), re.IGNORECASE)
# In front of the name of a test only a kind of acquisition marks a step-up: "Following the Acquisition, ..." is the deal being financed.
_STEP_HEAD_RE = re.compile(_ACQUISITION_KIND, re.IGNORECASE)
# "increased from A to B" is a step-up rather than a new level when the increase is optional or lasts a number of quarters.
_TEMPORARY_RE = re.compile(
    "|".join((_ACQUISITION_KIND, _ANY_ACQUISITION)) + r"|(?-i:\bmay\b)|\boption\b|\belect(?:s|ion)?\b"  # "may", not the month
    r"|for\s+(?:a\s+period\s+of\s+)?(?:up\s+to\s+)?(?:the\s+)?(?:\w+\s+){1,3}?(?:fiscal\s+)?quarters", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"thereafter|through|until|prior\s+to|on\s+or\s+(?:prior|before)|from\s+and\s+after|\bpost[-\s]|fiscal\s+quarters?\s+ending"
    r"|on\s+the\s+last\s+day|\b20\d\d\b|step(?:s|ped|ping)?[-\s]downs?|(?:reduc|decreas)(?:es|ed|ing)\s+to|anniversary"
    r"|\bafter\s+(?:\w+\s+){1,2}(?:months|years)",
    re.IGNORECASE,
)
_SPRING_RE = re.compile(
    r"springing|only\s+(?:to\s+be\s+)?tested|tested\s+(?:only\s+)?(?:when|if)|\d+%\s+of\s+(?:the\s+)?(?:facility|commitments|revolv)",
    re.IGNORECASE,
)
# "only if", "solely to the extent": a trigger when it stands in front of the test. After the name of the test it may as well
# qualify a definition ("netting cash only to the extent held in ..."), so there its clause must also speak of testing or usage.
_ONLY_RE = re.compile(r"(?:only|solely)\s+(?:if|when|to\s+the\s+extent)", re.IGNORECASE)
_USAGE_RE = re.compile(r"tested|utili[sz]|drawn|outstanding|usage", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"(?<=[a-z0-9\)\]\u201d%x])[.;]\s+(?=[A-Z(\u201c\u2022])|;\s+(?=provided)")
_HEADING_RE = re.compile(r"((?:from|post|until|through|prior\s+to|after|on\s+and\s+after)[^:\u2022]{3,70}):[^:]{0,40}$", re.IGNORECASE)
# A figure reported rather than required: the ratio the borrower has now, or had at a date.
_ACTUAL_RE = re.compile(r"\b(?:currently|presently|was|were|stood\s+at|current(?:\s+level)?(?:\s+of)?)\s*:?\s*(?:approximately\s+)?$", re.IGNORECASE)
_AS_OF_RE = re.compile(r"\bas\s+(?:of|at)\s+[^;.]{0,60}?\b(?:19|20)\d\d\b", re.IGNORECASE)
# The level in force before the one proposed ("same as existing: 4.00x" is the level itself).
_EXISTING_RE = re.compile(r"\b(?:previously|formerly|(?<!same\sas\s)existing(?:\s+(?:level|covenant|test|requirement))?(?:\s+of)?)\s*:?\s*$",
                          re.IGNORECASE)
_BOUND = r"exceed(?:s|ing)?|(?:more|greater|less|lower|higher)\s+than|at\s+least|[<>" + chr(0x2264) + chr(0x2265) + "]=?"
_BOUND_RE = re.compile(_BOUND + r"|\b(?:maximum|minimum|max|min)\b", re.IGNORECASE)
_MULTIPLE_RE = re.compile(r"\s*(?:of\s+|times\s+)?(?:the\s+)?(?:(?:consolidated|adjusted|ltm|pro\s+forma)\s+)*ebitdar?\b", re.IGNORECASE)
# What a dollar amount measures when it is not the test itself ("minimum Liquidity of $150 million; minimum EBITDA of $75 million").
_OTHER_AMOUNT_RE = re.compile(
    r"ebitdar?|capital\s+expenditures?|capex|revenues?|net\s+income|earnings|consideration|proceeds|indebtedness|\bdebt\b|dividends?"
    r"|distributions?|investments?|basket", re.IGNORECASE)
_LIMIT_RE = re.compile(r",[^,]*?(?:" + _BOUND + r")\W*$", re.IGNORECASE)
# A ratio that another term is conditional on is an incurrence test, unless its sentence says it is maintained or tested.
# The link has to run up to the name of the test: in "Subject to the Documentation Principles, a Leverage Ratio of" it does not.
_INCURRENCE_RE = re.compile(
    r"(?:so\s+long\s+as|subject\s+to|pro\s+forma|\bif|\bunless|\bwhen(?:ever)?)\s+(?:[\w'/\-" + chr(0x2019) + r"]+\s+){0,7}$"
    r"|(?:after\s+giving\s+(?:pro\s+forma\s+)?effect|permitted\s+(?:if|when|where|to\s+the\s+extent|provided)"
    r"|may\s+(?:make|incur|pay|declare|consummate))\b[^.;:]{0,100}$", re.IGNORECASE)
_MAINTENANCE_RE = re.compile(
    r"maint(?:ain|enance)|\btested\b|(?:last\s+day|end)\s+of\s+(?:each|any|every)\s+(?:fiscal\s+)?(?:quarter|year)|quarterly", re.IGNORECASE)
_LIMIT_NAME_RE = re.compile(r"\b(?:maximum|minimum|max\.?|min\.?)\s+(?:[\w/.\-]+\s+){0,5}$", re.IGNORECASE)
_BASKET_RE = re.compile(
    r"restricted\s+payments?|dividends?|distributions?|indebtedness|\bdebt\b|\bliens?\b|\binvestments?\b(?!\s+grade)|acquisitions?|\bincur"
    r"|baskets?|unlimited|permitted", re.IGNORECASE)


@dataclass
class _Finding:
    type: str
    name: str
    unit: str
    value: float
    start: int  # span of the level in the scanned text
    end: int
    anchor: int  # where the test is named
    kind: str  # "level", "step", "period" or "condition" (a level that only conditions another term: noted, never a covenant)
    lead: str  # text between the previous level and this one
    sentence: str
    relative: bool  # "increased by 0.50x": an increment rather than a level
    was: str = ""  # the level this one replaces, as written ("increased from 4.00x to 4.50x")
    text: str = ""
    page: int = 0
    general: bool = False  # read under a general "Covenants:" heading


def _mentions(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for ctype, pattern in TYPES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if not any(m.start() < e and s < m.end() for s, e, _ in spans):
                spans.append((m.start(), m.end(), ctype))
    return sorted(spans)


def _name(text: str, start: int, end: int) -> str:
    lead = re.search(r"((?:[A-Z][\w.\-/]*\s+){0,4})$", text[:start])
    name = tidy((lead.group(1) if lead else "") + text[start:end])
    while True:
        trimmed = re.sub(r"^(?:The|An?|Maximum|Minimum|Max\.?|Min\.?|Quarterly|Maintenance|Following)\s+", "", name)
        if trimmed == name:
            return name
        name = trimmed


def _opens(text: str, pos: int) -> int:
    """Where the sentence around ``pos`` begins, looking back no further than 400 characters."""
    lo = max(0, pos - 400)
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(text, lo, min(len(text), pos + 1)) if m.end() <= pos]
    return ends[-1] if ends else lo


def _closes(text: str, pos: int) -> int:
    """Where the sentence around ``pos`` ends, looking ahead no further than 400 characters."""
    hi = min(len(text), pos + 400)
    m = _SENTENCE_END_RE.search(text, pos, hi)
    return m.start() + 1 if m else hi


def _in_parenthesis(text: str) -> bool:
    """True when ``text`` stops inside a parenthesis that it opened."""
    depth = 0
    for ch in text:
        depth = depth + 1 if ch == "(" else max(depth - 1, 0) if ch == ")" else depth
    return depth > 0


def _conditional(text: str, lo: int, ms: int, end: int, own: bool, strict: bool) -> bool:
    """True when the level of the test named at ``ms`` reads as a condition for another term, not as a maintenance test.

    ``lo`` is where the words leading up to the name begin: the start of the sentence, or the previous level in
    that sentence when ``own`` is false. ``end`` is where the level ends. Under a general heading (``strict``),
    where baskets and their ratio conditions are listed too, every level needs maintenance wording of its own.
    """
    clause = re.split(r"[:;]\s", text[lo:ms])[-1][-120:]
    link = _INCURRENCE_RE.search(clause)
    if not link and not strict:
        return False
    # maintenance wording ahead of the link belongs to the test stated before it in the same sentence
    start = lo if own else ms - len(clause) + (link.start() if link else 0)
    if _MAINTENANCE_RE.search(text[start:_closes(text, end)]):
        return False
    # "a maximum Total Leverage Ratio of ..." states a covenant, except where a general section is speaking of a basket
    return not _LIMIT_NAME_RE.search(text[max(lo, ms - 80):ms]) or (strict and bool(link or _BASKET_RE.search(clause)))


def _roles(text: str, found: list[tuple[float, int, int]], ss: int, se: int, unit: str, around: str, head: str,
           has_level: bool) -> list[tuple[str, str]]:
    """What each figure of one sentence is to the test named in front of it: (kind, level it replaces) per figure.

    The kind is "level", "step" or "period", or "" for a figure that is no level of the test. ``around`` is the
    whole sentence, ``head`` its words in front of the name where the sentence opens with this test, and
    ``has_level`` says that an earlier sentence already gave the level.
    """
    n = len(found)
    before = [text[found[j - 1][2] if j else ss: found[j][1]] for j in range(n)]
    after = [text[found[j][2]: found[j + 1][1] if j + 1 < n else se][:200] for j in range(n)]
    step = [bool(_STEP_RE.search(b)) for b in before]
    if head and n and _STEP_HEAD_RE.search(head):
        step[0] = True  # "Following a Material Acquisition, the Leverage Ratio shall not exceed 4.50x"
    skip, base, replaced, earlier = _stood(before, after, step, around, head)

    def aside(j: int) -> bool:  # a figure that sits inside a definition, as far as the wording shows
        return bool(_in_parenthesis(text[ss: found[j][1]]) or _MULTIPLE_RE.match(after[j])
                    or (unit == "usd_mm" and _OTHER_AMOUNT_RE.search(before[j]))
                    or (j + 1 < n and re.match(r"\s*,", before[j]) and _LIMIT_RE.search(before[j + 1])))

    kinds = [""] * n
    level: int | None = None
    if not has_level:
        free = [j for j in range(n) if j not in skip and not step[j]]
        level = next((j for j in free if not aside(j)), free[0] if free else None)
    # once a step-up is stated, the further figures of the level's sentence belong to it; so do all of a later sentence
    stepping = has_level and bool(_STEP_RE.search(text[ss:se]))
    unworded: list[int] = []
    for j in range(n):
        if j in skip or (j in base and j != level):
            continue
        if j == level:
            kinds[j] = "level"
        elif not has_level and (level is None or j < level):
            kinds[j] = "step" if step[j] else ""
        elif _MULTIPLE_RE.match(after[j]) or (unit == "usd_mm" and _OTHER_AMOUNT_RE.search(before[j])):
            continue
        elif stepping or step[j]:
            kinds[j], stepping = "step", stepping or not has_level
        elif not has_level and _STEP_RE.search(re.split(r"[,;()]", after[j])[0]):
            kinds[j], stepping = "step", True  # "a 0.50x step-up", "4.50x following a Material Acquisition"
        elif _PERIOD_RE.search(before[j]):
            kinds[j] = "period"
        elif _PERIOD_RE.search(after[j]) and not _AS_OF_RE.match(after[j].lstrip()):
            kinds[j] = "period"  # but "(1.80x as of December 31, 2025)" on its own is where the ratio stood
        elif not has_level:
            unworded.append(j)
    last_period = max((j for j in range(n) if kinds[j] == "period"), default=-1)
    for j in unworded:
        if j < last_period:
            kinds[j] = "period"  # "4.75x, 4.50x and 4.25x for 2025, 2026 and 2027": a row of the same schedule
    if level is not None and earlier:
        replaced.setdefault(level, earlier[0])
    return [(kinds[j], tidy(text[found[replaced[j]][1]: found[replaced[j]][2]]) if j in replaced else "") for j in range(n)]


def _stood(before: list[str], after: list[str], step: list[bool], around: str, head: str) -> tuple[set[int], set[int], dict[int, int], list[int]]:
    """The figures of a sentence that say where the level stands or stood, not what it is to be.

    Returns (skip, base, replaced, earlier): the figures to leave out; the A of "from A to B" where B is a step-up
    or a later period, so that A is the level or a repeat of it; for B in an amendment, the A it replaces; and the
    other figures that give the level in force before. ``step`` is corrected in place for "from A to B".
    """
    n = len(before)
    skip: set[int] = set()
    base: set[int] = set()
    replaced: dict[int, int] = {}
    earlier: list[int] = []
    for j in range(n):
        lead = (head + before[j]) if j == 0 else ""  # only the first figure has the opening of the sentence to itself
        if _ACTUAL_RE.search(before[j]) or (_AS_OF_RE.search(lead) and not _BOUND_RE.search(lead)):
            skip.add(j)
        elif _EXISTING_RE.search(before[j]):
            skip.add(j)
            earlier.append(j)
        if not re.search(r"\bfrom\s*$", before[j], re.IGNORECASE):
            continue
        step[j] = False  # "increased from A": A is where the level stood
        if j + 1 >= n or not re.fullmatch(r"\s*to\s*", before[j + 1], re.IGNORECASE):
            skip.add(j)  # "4.50x (increased from 4.00x)"
            earlier.append(j)
        elif _TEMPORARY_RE.search(around):
            base.add(j)
            step[j + 1] = True  # A stays the level and B is the step-up
        elif _PERIOD_RE.search(after[j + 1]):
            base.add(j)  # a dated change: A is the level until then, and B is sorted by its own wording
        else:
            skip.add(j)  # an amendment: B is the level
            replaced[j + 1] = j
    return skip, base, replaced, earlier


def _has_level(findings: list[_Finding], ctype: str) -> bool:
    """True when a level was read for a test of the same family: under a general heading its step-up is then taken on trust."""
    return any(f.kind == "level" and COVENANT_TYPES[f.type][1] == COVENANT_TYPES[ctype][1] for f in findings)


def _scan(text: str, strict: bool = False) -> list[_Finding]:
    """The levels of every test named in ``text``; ``strict`` for text under a general heading (see ``_conditional``)."""
    mentions = _mentions(text)
    out: list[_Finding] = []
    pending: tuple[str, str, int] | None = None  # a test that was named without a level (a heading or a defined term)
    prev_end = 0
    for i, (ms, me, ctype) in enumerate(mentions):
        unit = UNITS.get(ctype, "x")
        seg_end = min(mentions[i + 1][0] if i + 1 < len(mentions) else len(text), me + 1500)
        cuts = [me] + [me + m.end() for m in _SENTENCE_END_RE.finditer(text[me:seg_end])] + [seg_end]
        name = _name(text, ms, me)
        opens = _opens(text, ms)
        own = prev_end <= opens  # no earlier level stands in the sentence that names this test
        lo = max(prev_end, opens)
        mine: list[_Finding] = []
        has_level = False
        for ss, se in zip(cuts, cuts[1:]):
            found = [(v, a + ss, b + ss) for v, a, b in thresholds(text[ss:se], unit)]
            if not found:
                continue
            first = ss == me
            around = text[lo if first else ss: _closes(text, found[-1][2])]
            roles = _roles(text, found, ss, se, unit, around, text[lo:ms] if first and own else "", has_level)
            for (value, a, b), (kind, was) in zip(found, roles):
                if not kind:
                    continue
                if not mine and _conditional(text, lo, ms, b, own, strict and not (kind == "step" and _has_level(out, ctype))):
                    kind = "condition"  # also where it reads as a step-up: "permitted acquisitions, subject to a Leverage Ratio of"
                mine.append(_Finding(
                    type=ctype, name=name, unit=unit, value=value, start=a, end=b, anchor=ms, kind=kind,
                    lead=text[max(prev_end, a - 320): a], sentence=text[ss:se],
                    relative=bool(re.search(r"\bby\s*$", text[max(0, a - 8): a], re.IGNORECASE)), was=was,
                ))
                prev_end = b
            has_level = has_level or any(kind == "level" for kind, _ in roles)
        if any(f.kind == "condition" for f in mine):
            mine = [f for f in mine if f.kind == "condition"]  # the other figures belong to that condition
        if not mine:
            pending = (ctype, name, ms)
            continue
        if pending and ms - pending[2] < 700 and COVENANT_TYPES[pending[0]][1] == COVENANT_TYPES[ctype][1]:
            # "Consolidated Net Leverage Ratio" as a heading, then "a ratio of Funded Debt to EBITDA of not more than ...":
            # the heading names the test, unless this one says for itself which leverage test it is.
            if pending[0] == ctype or (_RANK.get(pending[0], -1) >= _RANK.get(ctype, -1) and not _QUALIFIED_RE.search(name)):
                for f in mine:
                    f.type = pending[0]
                    f.name = pending[1] if len(pending[1]) >= len(f.name) or pending[0] != ctype else f.name
        pending = None
        out.extend(sorted(mine, key=lambda f: f.kind != "level"))  # the level first, also where a step-up is stated ahead of it
    return out


def _period(lead: str) -> str:
    m = _HEADING_RE.search(lead)
    if m:
        return tidy(m.group(1))
    tail = tidy(re.sub(r"^.*[.;:]\s", "", lead[-140:]))
    return clip(tail.strip(" ,(").rstrip(" ,("), 110)


def _note(ctx, note: str) -> None:
    if note not in ctx.notes:
        ctx.notes.append(note)


def _shown(f: _Finding) -> str:
    return tidy(f.text[f.start: f.end])


def extract_covenants(ctx) -> list[dict]:
    """``ctx`` is the rules engine context: it supplies the covenant blocks, checks quotes against the PDF text and takes notes."""
    findings: list[_Finding] = []
    seen: set[tuple] = set()
    unread: list[str] = []  # tests that a covenant section names without a level that could be read
    blocks = [(bool(_GENERAL_LABEL_RE.fullmatch(b.label)), b) for b in ctx.blocks(LABEL, 110)]
    # general sections last: a test under its own sub-heading inside "Covenants:" is read from the sub-heading
    for general, block in sorted(blocks, key=lambda item: item[0]):
        if general and block.continues:
            continue  # the second line of a longer label: "Negative" / "Covenants:"
        text = block.text
        if re.search(METRIC_WORD, block.label, re.IGNORECASE) and not re.search(r"covenant|tests?$", block.label, re.IGNORECASE):
            text = block.label + ": " + text  # "Minimum Interest Coverage Ratio:" is itself the name of the test
        if not re.search(r"\d", text):
            continue
        found = _scan(text, general)
        if not found and not general:
            unread += [f"{_name(text, ms, me)} (page {block.page})" for ms, me, _ in _mentions(text)[:1]]
        for f in found:
            key = (f.type, f.value, f.kind, tidy(f.sentence)[:80])
            if key in seen:
                continue  # a sub-heading read once on its own and once inside its parent section
            seen.add(key)
            f.text, f.page, f.general = text, block.page, general
            findings.append(f)

    if ctx.plain_comparison and len(findings) >= 2 and len(findings) % 2 == 0:
        half = len(findings) // 2
        if [f.type for f in findings[:half]] == [f.type for f in findings[half:]]:
            findings = findings[half:]  # existing terms are printed first, proposed terms second

    covenants: list[dict] = []
    by_type: dict[str, dict] = {}
    waiting: dict[str, list[_Finding]] = {}  # step-ups read before the level of their test
    left_out: list[tuple[bool, str]] = []
    for f in findings:
        if f.kind == "condition":
            left_out.append((f.general, f"{f.name} of {_shown(f)}: the text does not say that this level is maintained or tested (it reads "
                                        "as a condition for another term), so it is not listed as a financial covenant."))
            continue
        if f.type == "max_total_leverage" and f.type not in by_type and not _QUALIFIED_RE.search(f.name):
            # "the Leverage Ratio" used loosely for the one leverage test already defined (net, secured or first lien)
            specific = [t for t in by_type if t in _RANK]
            if len(specific) == 1:
                f.type = specific[0]
        cur = by_type.get(f.type)
        if cur is None:
            if f.kind == "level":
                cur = by_type[f.type] = _new(ctx, f)
                covenants.append(cur)
                for step in waiting.pop(f.type, []):
                    _step_up(cur, step)
            elif f.kind == "step":
                waiting.setdefault(f.type, []).append(f)
            continue
        step_lead = f.kind == "level" and bool(_STEP_RE.search(f.lead))
        period_lead = f.kind == "level" and bool(_PERIOD_RE.search(f.lead[-150:]))
        if f.kind == "step" or step_lead:
            _step_up(cur, f)
        elif f.kind == "period" or period_lead:
            if not cur["schedule"]:
                cur["schedule"] = [{"period": cur["_period"], "threshold": cur["threshold"]}]
            cur["schedule"].append({"period": _period(f.lead), "threshold": f.value})
        elif f.value != cur["threshold"]:
            covenants.append(_new(ctx, f))  # the same test at another level for a different scope
    # a general section lists baskets and their ratio conditions as a matter of course: three notes say enough
    for note in [n for general, n in left_out if not general] + [n for general, n in left_out if general][:3]:
        _note(ctx, note)
    for steps in waiting.values():
        _note(ctx, f"{steps[0].name}: only a step-up level ({_shown(steps[0])}) could be read, so no covenant level is given for it.")
    if not covenants and not findings:
        for name in dict.fromkeys(unread):
            _note(ctx, f"{name}: the financial covenant section names this test, but no level could be read for it.")
    for c in covenants:
        c.pop("_period", None)
    return covenants


def _step_up(cur: dict, f: _Finding) -> None:
    """Take ``f`` as the step-up of covenant ``cur`` where it loosens the test further than any step-up read before."""
    # a step of 1.00x or less on a maximum test above 1.00x can only be an increment ("a 0.50x step-up")
    relative = f.relative or (f.unit == "x" and cur["direction"] == "max" and f.value <= 1.0 < cur["threshold"])
    level = round(cur["threshold"] + f.value, 4) if relative else f.value
    higher = level > cur["threshold"] if cur["direction"] == "max" else level < cur["threshold"]
    if higher and (cur["step_up"]["threshold"] is None or level > cur["step_up"]["threshold"]):
        cur["step_up"] = {"present": True, "threshold": level, "detail": clip(f.lead[-200:] + f.text[f.start: f.end + 160], 300)}


def _springing(before: str, named: int, after: str) -> bool:
    """True when the clause of a level makes its test conditional; the test is named at ``before[named]``."""
    if _SPRING_RE.search(before) or _SPRING_RE.search(after) or _ONLY_RE.search(before[:named]):
        return True
    clauses = re.split(r"[,;()]", before[named:]) + re.split(r"[,;()]", after)
    return any(_ONLY_RE.search(c) and _USAGE_RE.search(c) for c in clauses)


def _new(ctx, f: _Finding) -> dict:
    quote, page = ctx.evidence(f.text, f.page, (max(f.anchor, f.start - 220), f.end))
    if not quote:  # the name and the level are not contiguous on the page (a label that wraps beside its value): quote the level
        quote, page = ctx.evidence(f.text, f.page, (f.start, f.end))
    scope = re.match(r"\s*\(([^)\u201c\"]{3,60})\)", f.text[f.end: f.end + 70])
    if scope and thresholds(scope.group(1), f.unit):
        scope = None  # a bracket that holds another level ("(currently 4.00x)") is not the scope of the test
    # A test is springing when its own clause says so: the words leading up to the level (within the sentence)
    # or the words after it, up to the next alternative ("... or (2) ...").
    before = _SENTENCE_END_RE.split(f.text[max(0, f.start - 600): f.start])[-1]
    after = re.split(r"\s+(?:or|and)\s+\(\w{1,3}\)|;", f.text[f.end: f.end + 260])[0]
    after = _SENTENCE_END_RE.split(after + " ")[0]
    around = f.lead[-320:] + " " + f.sentence
    springing = _springing(before, max(0, f.anchor - (f.start - len(before))), after)
    return {
        # the one test typed "other" is debt service coverage, a minimum
        "type": f.type, "name": f.name, "direction": "min" if f.type == "other" else f.type[:3], "threshold": f.value, "unit": f.unit,
        "threshold_text": tidy(f.text[f.start: f.end]), "schedule": [],
        "step_up": {"present": False, "threshold": None, "detail": ""},
        "springing": {"is_springing": springing, "trigger": clip(before[-200:] + f.text[f.start: f.end] + after, 260) if springing else ""},
        "applies_to": tidy(scope.group(1)) if scope else "",
        "test_frequency": "Quarterly" if re.search(r"quarter", around, re.IGNORECASE) else "",
        "definition_notes": "", "change_vs_existing": f"Existing level: {f.was}." if f.was else None, "quote": quote, "page": page,
        "_period": _period(f.lead),
    }
