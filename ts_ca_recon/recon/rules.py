"""Offline, deterministic TS-vs-CA check.

Two complementary checks, both explainable and reproducible without an API key:

1. Headline attributes: each attribute is located in the term sheet (by its
   label in the two-column term-sheet layout, or by keyword as a fallback) and in
   the credit agreement (by its defined term, section heading, pricing table or
   cover page). The values found on each side are normalised and compared.
2. Figure traceability: every amount, percentage, ratio and date in the term
   sheet is looked up across the whole credit agreement.

This is a screening tool: it flags candidates for review. The Claude engine and
the agent-verified results provide the full semantic reconciliation."""
from __future__ import annotations

import bisect
import re
from collections import Counter
from dataclasses import dataclass, field

from . import values as V


# --------------------------------------------------------------------------- text model
class Doc:
    """Whitespace-collapsed text of a PDF with a position -> page map."""

    def __init__(self, pages: list[str]):
        self.pages = pages
        flat_pages = [re.sub(r"\s+", " ", p).strip() for p in pages]
        self.flat_pages = flat_pages
        self.starts: list[int] = []
        pos = 0
        for fp in flat_pages:
            self.starts.append(pos)
            pos += len(fp) + 1
        self.flat = " ".join(flat_pages)
        self._index: dict[tuple, list[int]] | None = None

    def page_of(self, pos: int) -> int:
        return max(1, bisect.bisect_right(self.starts, pos))  # 1-based page number

    def snippet(self, pos: int, before: int = 80, after: int = 220) -> str:
        return self.flat[max(0, pos - before): pos + after].strip()

    @property
    def index(self) -> dict[tuple, list[int]]:
        """All normalised values in the document -> pages where they occur."""
        if self._index is None:
            idx: dict[tuple, list[int]] = {}

            def add(v: V.Value, page: int):
                pages = idx.setdefault(v.key, [])
                if page not in pages:
                    pages.append(page)

            for v in V.parse(self.flat):
                add(v, self.page_of(v.start))
            for pno, text in enumerate(self.flat_pages, 1):  # pricing tables quoted in bare bps / % figures
                if is_grid_page(text):
                    bare = V.parse_bare_bps(text) if V.BPS_HEADER_RE.search(text) else (
                        V.parse_bare_pct(text) if V.PCT_HEADER_RE.search(text) else [])
                    for v in bare:
                        add(v, pno)
            self._index = idx
        return self._index


@dataclass
class Window:
    text: str
    page: int
    source: str  # e.g. 'label "Maturity Date"', 'definition "Maturity Date"', 'cover page'


_GRID_CUE = re.compile(
    r"pricing\s+(?:grid|schedule|level|matrix)|applicable\s+(?:margin|rate|spread|percentage)|facility\s+fee|commitment\s+fee|"
    r"level\s+(?:i|1)\b|ratings?\s+level", re.IGNORECASE)


def is_grid_page(text: str) -> bool:
    if not _GRID_CUE.search(text):
        return False
    if len(V.parse_pct(text)) >= 4:
        return True
    return bool(V.BPS_HEADER_RE.search(text) or V.PCT_HEADER_RE.search(text)) and len(V.parse_bare_bps(text)) >= 4


_TABLE_ROW = re.compile(r"\blevel\b|\btier\b|\bcategory\b|\bpricing\b|[≥≤<>]|\b(?:A|BBB|BB|Baa|Ba|Aa)[123+\-]?\b|leverage|rating", re.IGNORECASE)


def grid_windows(doc: Doc) -> list[Window]:
    """The pricing TABLE on a grid page: lines that carry two or more figures, or level/rating row labels,
    plus the header lines (so a '(bps)' or '(%)' unit header is kept). Narrative text on the same page is dropped."""
    out = []
    for i, flat in enumerate(doc.flat_pages, 1):
        if not is_grid_page(flat):
            continue
        raw_lines = doc.pages[i - 1].splitlines()
        keep = []
        for ln in raw_lines:
            nums = len(V.parse_pct(ln)) + len(V.parse_bare_bps(ln))
            if nums >= 2 or (nums >= 1 and _TABLE_ROW.search(ln)) or V.BPS_HEADER_RE.search(ln) or V.PCT_HEADER_RE.search(ln) \
                    or re.search(r"applicable\s+(?:margin|rate)|facility\s+fee|commitment\s+fee", ln, re.IGNORECASE) and len(ln.split()) <= 25:
                keep.append(re.sub(r"\s+", " ", ln).strip())
        text = " | ".join(k for k in keep if k)
        if text:
            out.append(Window(text, i, "pricing table"))
    return out


def window_values(w: Window, kinds: tuple[str, ...]) -> list[V.Value]:
    vals = V.parse(w.text, kinds)
    if "pct" in kinds and w.source == "pricing table":
        if V.BPS_HEADER_RE.search(w.text):
            vals += V.parse_bare_bps(w.text)
        elif V.PCT_HEADER_RE.search(w.text):
            vals += V.parse_bare_pct(w.text)
    return vals


# --------------------------------------------------------------------------- term sheet parsing
def parse_term_sheet_entries(pages: list[str]) -> list[tuple[str, str, int]]:
    """Split a two-column term sheet into (label, value, page) entries."""
    entries: list[tuple[str, str, int]] = []
    split_re = re.compile(r"^(\s{0,14})(\S(?:.*?\S)?)\s{3,}(\S.*)$")
    for pno, page in enumerate(pages, 1):
        lines = page.splitlines()
        cols = Counter()
        for ln in lines:
            m = split_re.match(ln)
            if m and len(m.group(2)) <= 45:
                cols[m.start(3)] += 1
        if not cols:
            continue
        col, freq = cols.most_common(1)[0]
        if freq < 3:
            continue
        cur_label: list[str] = []
        cur_value: list[str] = []
        prev_left = False

        def flush():
            if cur_label and cur_value:
                label = " ".join(cur_label).strip(" :")
                if 1 < len(label) <= 80:
                    entries.append((label, " ".join(cur_value).strip(), pno))

        for ln in lines:
            if not ln.strip():
                continue
            indent = len(ln) - len(ln.lstrip())
            if indent >= col - 2:  # line sits entirely in the value column
                left, right = "", ln.strip()
            else:
                left, right = ln[:col].strip(), ln[col:].strip()
                cuts_word = len(ln) > col and ln[col - 1] != " " and ln[col] != " "
                if cuts_word or len(left) > 45:  # full-width paragraph, not a label
                    left, right = "", ln.strip()
            label_closed = bool(cur_label) and cur_label[-1].endswith(":")
            if left and (not prev_left or label_closed):
                flush()
                cur_label, cur_value = [left], []
            elif left:
                cur_label.append(left)
            if right:
                cur_value.append(right)
            prev_left = bool(left)
        flush()
    return entries


def _char_w(s: str, size: float) -> float:
    upper = sum(c.isupper() for c in s)
    return (upper * 0.66 + (len(s) - upper) * 0.47) * size


def _join_runs(items: list) -> str:
    """Join text runs. Items are plain strings or (x, text, font_size) tuples.
    Small caps ("ADM" + "INISTRATIVE") and kerning splits ("Facilit" + "y") are glued when the
    next run starts where the previous one ends; separate words get a space."""
    out, prev, prev_sz = "", "", None
    for it in items:
        _x, t, sz = (it if isinstance(it, (tuple, list)) else (None, it, None))
        s = t.strip()
        if not s:
            out += " "
            continue
        if out and not out[-1].isspace() and out[-1].isalnum() and s[0].isalnum():
            small_caps = (sz and prev_sz and abs(sz - prev_sz) / max(sz, prev_sz) > 0.08
                          and prev[-1].isupper() and s[0].isupper())
            glue = (len(prev) == 1 and prev.isupper()) or (s[0].islower() and (len(s) <= 2 or len(prev) <= 2)) or small_caps
            if not glue:
                out += " "
        elif out and (t[:1].isspace() or (out[-1] in "),;:" and s[0].isalnum())):
            out += " "
        out += s
        prev, prev_sz = s, sz
    return re.sub(r"\s+", " ", out).strip()


_INLINE_LABEL = re.compile(r"^((?:[A-Z][\w/&’'\-]*|of|and|or|the|to|for|in|on|a|an|with)(?:[ ,]+(?:[A-Z(][\w/&’'\-)]*|of|and|or|the|to|for|in|on|a|an|with)){0,7}):\s+(\S.*)$")


def parse_term_sheet_layout(layout: list[dict]) -> list[tuple[str, str, int]]:
    """Pair term-sheet labels with their values using text POSITIONS rather than text lines.

    A label (short text in the left column) owns every value-column line from its own
    baseline down to the next label, including lines that carry over onto the next page.
    This avoids the misalignment that line-based layout text produces when a left-column
    label is printed beside the tail of the previous paragraph."""
    lines = []  # (page_no, y, height, [(x, text, size)])
    # Running headers/footers: identical left-margin text repeated on many pages.
    rep = Counter()
    for pg in layout:
        seen = {re.sub(r"\W+", "", "".join(str(p[1]) for p in parts)).lower() for _y, parts in pg["lines"]}
        rep.update(s for s in seen if s)
    repeated = {s for s, n in rep.items() if len(layout) >= 3 and n >= max(3, 0.4 * len(layout))}
    for pno, pg in enumerate(layout, 1):
        h = pg.get("height") or 792.0
        for y, parts in pg["lines"]:
            if y > 0.935 * h or y < 0.065 * h:  # page margins: headers, footers, page numbers
                continue
            if re.sub(r"\W+", "", "".join(str(p[1]) for p in parts)).lower() in repeated:
                continue
            lines.append((pno, y, h, [(float(p[0]), str(p[1]), float(p[2]) if len(p) > 2 else 10.0) for p in parts]))
    if not lines:
        return []
    starts = Counter(round(parts[0][0] / 4) * 4 for _, _, _, parts in lines)
    left_margin = min(x for x, n in starts.items() if n >= max(3, len(lines) * 0.05)) if starts else 0
    # Value column: where text starts after a gap following a short left-column label, or where indented lines start.
    cand = Counter()
    for _, _, _, parts in lines:
        x0 = parts[0][0]
        if x0 > left_margin + 60:
            cand[round(x0 / 4) * 4] += 1
        elif abs(x0 - left_margin) <= 6:
            for x, _t, _sz in parts[1:]:
                if x > left_margin + 60:
                    cand[round(x / 4) * 4] += 3  # value start beside a label: strongest evidence
                    break
    if not cand:
        return []
    top = cand.most_common(1)[0][1]
    if top < 5:
        return []
    # Nested list items are indented further than the value column; take the leftmost strong column.
    value_col = min(x for x, n in cand.items() if n >= 0.25 * top)

    entries: list[tuple[str, str, int]] = []
    label: list[str] = []
    label_page = 0
    value: list[str] = []
    last_label_y = None
    prev_page = None
    value_after_label = False
    label_has_inline_value = False

    def flush():
        if label:
            text = " ".join(label).strip(" :")
            if 1 < len(text) <= 90 and value:
                entries.append((text, _join_runs(value), label_page))

    for pno, y, h, parts in lines:
        at_margin = parts[0][0] <= left_margin + 6
        left = [(x, t, sz) for x, t, sz in parts if x < value_col - 8]
        right = [(x, t, sz) for x, t, sz in parts if x >= value_col - 8]
        left_text = _join_runs(left)
        # Estimated right edge of the left-column text: a "label" that runs up to the value column
        # is really the start of a full-width paragraph line.
        est_end = parts[0][0] + sum(len(t) * sz * 0.48 for x, t, sz in parts if x < value_col - 8)
        full_width = bool(left_text) and bool(right) and est_end >= value_col - 14
        if left_text and (len(left_text) > 55 or full_width or not re.search(r"[A-Za-z]", left_text)):
            if re.search(r"[A-Za-z]", left_text):  # full-width body line, not a label
                right = left + right
            left_text = ""
        # Inline "Label: value" paragraphs that start at the left margin (single-column term sheets).
        if at_margin and not left_text:
            m = _INLINE_LABEL.match(_join_runs(right))
            if m and len(m.group(1)) <= 60:
                flush()
                label, value, label_page = [m.group(1)], [m.group(2)], pno
                label_has_inline_value, value_after_label, last_label_y, prev_page = True, True, y, pno
                continue
        if left_text:
            continues = (label and not label[-1].endswith(":") and last_label_y is not None
                         and (not label_has_inline_value or left_text.endswith(":"))
                         and ((pno == prev_page and 0 < last_label_y - y <= 30 and not value_after_label)
                              or (pno != prev_page and not value)))
            if continues:
                label.append(left_text)
            else:
                flush()
                label, value, label_page = [left_text], [], pno
            label_has_inline_value = bool(right)
            value_after_label = False
            last_label_y = y
            prev_page = pno
        if right:
            value.append(_join_runs(right))
            if not left_text:
                value_after_label = True
    flush()
    return entries


# --------------------------------------------------------------------------- credit agreement anchors
_DEF_TAIL = r"[”\"]\s*(?:shall\s+)?(?:means|mean|has\s+the\s+meaning|shall\s+have\s+the\s+meaning)"
_NEXT_DEF = re.compile(r"[“\"][A-Z][^”\"]{1,70}" + _DEF_TAIL)


def definition_windows(doc: Doc, terms: list[str], max_len: int = 2500) -> list[Window]:
    out = []
    for term in terms:
        rx = re.compile(r"[“\"]\s*(" + term + r")\s*" + _DEF_TAIL, re.IGNORECASE)
        for m in rx.finditer(doc.flat):
            nxt = _NEXT_DEF.search(doc.flat, m.end(), m.end() + max_len)
            end = nxt.start() if nxt else m.end() + max_len
            out.append(Window(doc.flat[m.start():end], doc.page_of(m.start()), f'definition "{m.group(1).strip()}"'))
    return out


_TOC_ENTRY = re.compile(r"\b\d{1,2}\.\d{2}\s+[A-Z\[][^.;:]{0,90}?\s\d{1,3}\s+(?=(?:Section\s+)?\d{1,2}\.\d{2}\b)")


def _looks_like_toc(text: str) -> bool:
    """Table-of-contents text: dotted leaders, or 'section heading page' entries back to back.
    (Counting decimals is wrong: ratio operands such as '3.75 to 1.00' look like section numbers.)"""
    head = text[:400]
    if re.search(r"\.{5,}|(?:\.\s){5,}", head):
        return True
    return len(_TOC_ENTRY.findall(head)) >= 2


_NEXT_SECTION = re.compile(r"(?:SECTION|Section)\s+\d{1,2}\.\d{1,2}\.?\s+[A-Z]|\s\d{1,2}\.\d{2}\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,5}\.\s")


def section_windows(doc: Doc, headings: list[str], max_len: int = 3500) -> list[Window]:
    """Body sections whose heading matches. A heading is a section number followed by the title and a
    full stop or capitalised text (cross-references such as 'Section 2.14 hereof' are skipped).
    Each window ends at the next section heading."""
    out = []
    for h in headings:
        rx = re.compile(r"(?:Section\s+)?\d{1,2}\.\d{1,2}(?:\.\d+)?(?:\([a-z]\))?\.?\s+(?:[A-Z][\w/\-]*\s+){0,4}?(?:" + h + r")\b\.?", re.IGNORECASE)
        for m in rx.finditer(doc.flat):
            after = doc.flat[m.end(): m.end() + 3]
            if not (m.group(0).endswith(".") or re.match(r"\s*(?:\(|[A-Z]|$)", after)):
                continue
            text = doc.flat[m.start(): m.start() + max_len]
            if _looks_like_toc(text):
                continue
            nxt = _NEXT_SECTION.search(text, (m.end() - m.start()) + 10)
            if nxt:
                text = text[: nxt.start()]
            out.append(Window(text, doc.page_of(m.start()), f'section "{m.group(0).strip()[:60]}"'))
    return out


def cover_window(doc: Doc, pages: int = 3) -> Window:
    end = doc.starts[pages] if len(doc.starts) > pages else len(doc.flat)
    return Window(doc.flat[:end], 1, "cover page")


def cap_windows(doc: Doc, subject: str) -> list[Window]:
    """Operative cap language, e.g. 'the aggregate amount of Swingline Loans ... shall not exceed $350,000,000'."""
    rx = re.compile(r"(?:" + subject + r")[^.;]{0,160}?(?:shall\s+not\s+exceed|not\s+to\s+exceed|exceeding|in\s+excess\s+of|not\s+exceed|up\s+to|sublimit\s+of)\s+(?:the\s+(?:lesser|least)\s+of\s+[^$]{0,80})?(?:U\.S\.\s*)?\$[\d,.]+(?:\s*(?:million|billion))?", re.IGNORECASE)
    return [Window(doc.flat[max(0, m.start() - 60): m.end() + 40], doc.page_of(m.start()), "cap clause") for m in rx.finditer(doc.flat)][:6]


_ROLE_NOISE = re.compile(r"party hereto|parties hereto|from time to time|[“\"]lender|\blenders\b|\bguarantors?\b,?$|^\s*(?:the\s+)?(?:borrowers?|guarantors?)\s*$"
                         r"|amendment|agreement|dated|\(the\b|^\(?\d|^\([a-z]+\)|documents|shall\b|received"
                         r"|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d", re.IGNORECASE)
_ROLE_PREFIX = re.compile(r"^.*?\b(?:Borrowers?|Guarantors?|Lenders?|hereto|Issuing Banks?|(?:Co-)?(?:Syndication|Documentation) Agents?)\s*,\s*", re.IGNORECASE)


def _clean_party(part: str) -> str:
    part = re.sub(r"^(?:and|AND)\s+", "", part).strip(" ,;")
    part = re.sub(r",?\s*\beach\b$", "", part, flags=re.IGNORECASE).strip(" ,")
    while _ROLE_PREFIX.match(part) and len(_ROLE_PREFIX.sub("", part, count=1)) >= 3:
        part = _ROLE_PREFIX.sub("", part, count=1).strip(" ,")
    part = re.split(r"\s*\((?:in such capacit|together with|the\s+[“\"])", part)[0].strip(" ,")
    return part


_DEFINED_PARTY = re.compile(
    r"([A-Z](?:[A-Za-z0-9.,&'’\- ]|\([A-Z]{2,6}\)){2,90}?),?\s+(?:an?\s+[^()]{2,90}?)?\(\s*(?:together with[^()]{0,80},\s*)?(?:in such capacit[^()]{0,40},\s*)?(?:the\s+|each\s+a\s+|collectively,?\s+the\s+)?[“\"](?:{role})[”\"]")


def cover_roles(pages: list[str], role: str, max_pages: int = 4) -> list[str]:
    """Read the parties named 'as <role>' on the cover page(s), e.g. 'CITIBANK, N.A., as Administrative Agent',
    falling back to defined-party language such as 'Acme Inc., a Delaware corporation (the "Borrower")'."""
    names: list[str] = []
    rx = re.compile(r"\bas\s+(?:the\s+)?(?:an?\s+)?(?:" + role + r")\b", re.IGNORECASE)
    stop = re.compile(r"^(as\s|among\b|between\b|by\s+and|dated\b|.*credit agreement|.*facility agreement|exhibit\b|execution|conformed|the\s+lenders|table of contents)", re.IGNORECASE)

    def add(text: str):
        for part in re.split(r",?\s+\band\b\s+|;\s*", text, flags=re.IGNORECASE):
            part = _clean_party(part)
            if (len(re.sub(r"[^A-Za-z]", "", part)) >= 3 and not part[0].islower() and not _ROLE_NOISE.search(part)
                    and part not in names and len(part) <= 90):
                names.append(part)

    # Cover pages: the first pages, plus any embedded agreement cover (e.g. the conformed credit
    # agreement attached as an exhibit to an amendment).
    cover_rx = re.compile(r"(?:CREDIT|FACILITY|LOAN)\s+AGREEMENT", re.IGNORECASE)
    candidates = list(pages[:max_pages]) + [pg for pg in pages[max_pages:]
                                            if cover_rx.search(pg[:2500]) and re.search(r"dated\s+as\s+of", pg[:3000], re.IGNORECASE)
                                            and rx.search(pg)][:3]
    for page in candidates:
        lines = [l.strip() for l in page.splitlines()]
        for i, line in enumerate(lines):
            m = rx.search(line)
            if not m:
                continue
            before = re.sub(r",?\s*\beach\b\s*$", "", line[: m.start()].strip(" ,"), flags=re.IGNORECASE)
            chunk = [before] if before and not stop.match(before) else []
            if len(re.sub(r"[^A-Za-z]", "", before)) < 15:  # name wraps onto earlier lines
                j, blanks = i - 1, 0
                while j >= 0 and len(chunk) < 8:
                    prev = lines[j]
                    if not prev:
                        blanks += 1
                        if blanks > 1:
                            break
                        j -= 1
                        continue
                    if stop.match(prev) or rx.search(prev) or re.search(r"\bas\s+(?:an?\s+|the\s+)?[A-Z]", prev):
                        break
                    chunk.insert(0, prev)
                    j -= 1
            add(" ".join(chunk))
        if names:
            return names
    flat = re.sub(r"\s+", " ", " ".join(pages[:max_pages]))
    for m in re.finditer(_DEFINED_PARTY.pattern.replace("{role}", role), flat):
        add(re.split(r"\b(?:among|between|by and among|by|AMONG)\b", m.group(1))[-1])
    return names


# --------------------------------------------------------------------------- attribute specs
@dataclass
class Spec:
    rid: str
    name: str
    kind: str  # money | pct | ratio | date | agent | party | law | security | extension | set
    ts_include: str = ""
    ts_exclude: str = ""
    ts_keywords: list[str] = field(default_factory=list)
    ca_defs: list[str] = field(default_factory=list)
    ca_sections: list[str] = field(default_factory=list)
    ca_cover: bool = False
    extra_kinds: tuple[str, ...] = ()
    mode: str = "all"  # all = every TS figure must be found; any = one confirmed figure suffices; max = compare the headline (largest)
    grids: bool = False
    ca_caps: str = ""  # subject regex for operative cap clauses ("Swingline Loans ... shall not exceed $X")
    near: str = ""  # TS figures must sit in the same clause as this keyword (sublimits inside a facility description)


SPECS = [
    Spec("R01", "Facility amount / commitments", "money",
         r"type and amount|amount of (the )?facilit|^amounts?$|facilit(y|ies) (size|amounts?)|^size|^(the )?((senior |secured |unsecured |revolving |credit |term )*)facilit(y|ies)$|^(aggregate |total )?commitments?$|^revolving (credit )?facility|^\d+-(day|year) facility|credit facilit(y|ies)$",
         r"fee|incremental|accordion|increase|letter|swing|sublimit|prepay|reduct|terminat|extension|purpose|agent|lender|document|borrower|availab|cost|currency",
         ["facility", "aggregate commitments", "total commitments"],
         ["Aggregate Commitments?", "Total Commitments?", "Aggregate Revolving (?:Credit )?Commitments?", "Revolving Credit Commitment Amount",
          "Revolving Facility Commitments?", "Total Revolving (?:Credit )?Commitments?", "Aggregate Term Commitments?", "Maximum Credit Amount",
          "Revolving Commitments?", "Facility Amount", "Commitment Amount"],
         ca_cover=True, mode="max"),
    Spec("R02", "Maturity date", "date",
         r"maturity|tenor|termination date",
         r"early|springing|extension of credit",
         ["maturity", "tenor"],
         ["Maturity Date", "Termination Date", "Revolving (?:Credit )?Maturity Date", "Commitment Termination Date", "Revolving Facility Maturity Date",
          "Scheduled Commitment Termination Date", "Facility Termination Date", "Original Termination Date", "Revolving Termination Date",
          "Initial Revolving Credit Maturity Date", "Term Loan Maturity Date", "Revolving Commitment Termination Date"],
         mode="any"),
    Spec("R03", "Letter of credit sublimit", "money",
         r"letters? of credit|\bl/?cs?\b|lc sublimit|l/c sublimit",
         r"fee|fronting|participation|cost|issuer|issuing|lender|bank|agent",
         ["letter of credit sublimit", "lc sublimit", "l/c sublimit", "letters of credit", "letter of credit"],
         ["Letter of Credit Sublimit", "L/C Sublimit", "LC Sublimit", "Letter of Credit Commitment", "LC Commitment", "L/C Commitment",
          "Aggregate LC Commitment", "Revolving L/C Sublimit", "Total LC Commitment", "LC Exposure Sublimit", "Letter of Credit Limit",
          "L/C Obligations Sublimit", "Maximum LC Amount"],
         ["Letters? of Credit", "L/C Facility", "Letter of Credit Facility"],
         mode="any", ca_caps=r"(?:LC|L/C|Letter of Credit)\s+(?:Exposure|Obligations|Sublimit|Usage)|Letters?\s+of\s+Credit",
         near=r"letters?\s+of\s+credit|\bl/?c\b|\blcs?\b"),
    Spec("R04", "Swingline sublimit", "money",
         r"swing\s?line",
         r"fee|cost|pricing|lender|bank|agent",
         ["swingline", "swing line"],
         ["Swingline Sublimit", "Swing Line Sublimit", "Swingline Commitment", "Swing Line Commitment", "Swingline Loan Sublimit",
          "Swing Line Loan Sublimit", "Aggregate Swing Line Commitment", "Swing Line Sublimit Amount", "Swingline Limit", "Swingline Cap",
          "Swing ?Line Facility"],
         ["Swing ?line Loans?", "Swing ?line Facility", "Swing ?line Advances"],
         mode="any", ca_caps=r"Swing\s?line\s+(?:Loans?|Exposure|Advances|Sublimit|Commitments?)", near=r"swing\s?line"),
    Spec("R05", "Accordion / incremental capacity", "money",
         r"incremental|accordion|increase|uncommitted",
         r"cost|yield|fee",
         ["accordion", "increase in commitments", "incremental revolving", "incremental facilit", "increase option", "commitment increase"],
         ["Incremental Amount", "Maximum Incremental (?:Facilities )?Amount", "Incremental Cap", "Permitted Incremental Amount",
          "Incremental Facility Amount", "Maximum Increase Amount", "Incremental Limit"],
         ["Increase in (?:the )?(?:Aggregate )?Commitments", "Incremental Facilit(?:y|ies)", "Commitment Increases?", "Incremental (?:Revolving )?Commitments",
          "Increase of (?:the )?Commitments", "Accordion", "Optional Increase", "Increases? in (?:the )?Revolving Commitments", "Incremental Loans"],
         mode="any", ca_caps=r"(?:increase|incremental)[^.;$]{0,120}?(?:Commitments?|Facilit(?:y|ies)|Loans)"),
    Spec("R06", "Extension option / term-out", "extension",
         r"extension|extend|term[- ]out",
         r"credit",
         ["extension option", "term-out", "term out", "extend the maturity"],
         ["Term[- ]Out Option", "Term Loan Election", "Extension Date", "Extended (?:Maturity|Termination) Date", "Extension Request", "Extending Lenders?",
          "Extension Option", "Maturity Date Extension Request"],
         ["Extension of (?:the )?(?:Facility )?(?:Maturity|Termination|Commitment Termination) Dates?", "Extension Options?", "Maturity (?:Date )?Extension",
          "Term[- ]Out", "Extension of (?:Revolving )?Commitments", "Extensions? of (?:the )?(?:Revolving )?(?:Credit )?(?:Commitments|Maturity)",
          "Optional Extension", "Extended Maturity", "Conversion to Term Loans?", "Term Loan Conversion"]),
    Spec("R07", "Applicable margin / pricing grid", "pct",
         r"pricing|interest rates?|applicable (margin|rate)|^margin|^interest$|spread",
         r"period|payment|default|day count|calculation|benchmark|replacement|swap",
         ["applicable margin", "applicable rate", "pricing grid", "interest rate"],
         ["Applicable Margin", "Applicable Rate", "Applicable Percentage", "Applicable Spread", "Applicable Pricing", "Pricing Grid", "Pricing Schedule",
          "Applicable Term SOFR Margin", "Applicable SOFR Margin", "Eurocurrency Margin"],
         grids=True),
    Spec("R08", "Commitment / facility fee", "pct",
         r"commitment fee|facility fee|unused|^fees$|undrawn",
         r"upfront|arrang|agency|fronting|ticking|letter",
         ["commitment fee", "facility fee", "unused fee", "undrawn fee", "undrawn"],
         ["Commitment Fee(?: Rate| Percentage)?", "Facility Fee(?: Rate| Percentage)?", "Unused (?:Commitment )?Fee(?: Rate)?", "Applicable Commitment Fee",
          "Applicable Facility Fee", "Applicable Fee Rate"],
         grids=True),
    Spec("R09", "Financial covenants", "ratio",
         r"financial (maintenance )?covenants?|leverage|interest coverage|liquidity|coverage ratio",
         r"",
         ["financial covenant", "leverage ratio", "interest coverage"],
         [],
         ["Financial Covenants?", "(?:Maximum |Consolidated )?(?:Total |Net |First Lien |Secured )?(?:Net )?Leverage Ratio", "(?:Minimum )?(?:Consolidated )?Interest Coverage Ratio",
          "Financial Condition Covenants?", "Debt to Capitali[sz]ation", "Indebtedness/Capitali[sz]ation Ratio", "Minimum Liquidity", "Total Liquidity",
          "Asset Coverage Ratio", "Fixed Charge Coverage Ratio", "Maintenance of Ratios?", "Consolidated Leverage"],
         extra_kinds=("pct", "money")),
    Spec("R10", "Administrative agent", "agent",
         r"administrative agent|^agents?$|admin(istrative)? agent|^administrative$",
         r"fee|counsel",
         ["administrative agent"]),
    Spec("R11", "Borrower(s)", "party",
         r"^(the )?borrowers?\b|^company$",
         r"designated|additional|sublimit|joinder|affiliate|option",
         ["borrower"]),
    Spec("R12", "Governing law", "law",
         r"governing law",
         r"",
         ["governing law", "governed by"]),
    Spec("R13", "Security (secured vs unsecured)", "security",
         r"security|collateral|ranking|^guarant",
         r"release|fall|reinstat|securities|document"),
    Spec("R14", "Benchmark rates", "set"),
    Spec("R15", "Currencies", "set"),
]

_BENCHMARKS = {
    "Term SOFR": r"\bterm\s+sofr\b",
    "Daily Simple SOFR": r"\bdaily\s+(?:simple\s+)?sofr\b",
    "SONIA": r"\bsonia\b",
    "EURIBOR": r"\beuribor\b|\beuribo\s+rate\b|euro\s+interbank\s+offered\s+rate",
    "CORRA": r"\bcorra\b",
    "TIBOR": r"\btibor\b",
    "BBSY": r"\bbbsy\b",
    "€STR": r"€str|\bestr\b",
    "SORA": r"\bsora\b",
    "HIBOR": r"\bhibor\b",
    "SARON": r"\bsaron\b",
}
_CURRENCIES = {
    "EUR": r"\beuros?\b|€|\beur\b",
    "GBP": r"\bsterling\b|£|\bgbp\b",
    "JPY": r"\byen\b|\bjpy\b",
    "CAD": r"\bcanadian dollars?\b|\bcad\b",
    "AUD": r"\baustralian dollars?\b|\baud\b",
    "CHF": r"\bswiss francs?\b|\bchf\b",
    "SGD": r"\bsingapore dollars?\b|\bsgd\b",
    "MXN": r"\bmexican pesos?\b|\bmxn\b",
    "SEK": r"\bswedish kron(?:a|or)\b|\bsek\b",
    "NOK": r"\bnorwegian kron(?:e|er)\b|\bnok\b",
    "DKK": r"\bdanish kron(?:e|er)\b|\bdkk\b",
    "HKD": r"\bhong kong dollars?\b|\bhkd\b",
    "CNY": r"\brenminbi\b|\bcny\b",
}
_JURISDICTIONS = ["New York", "England", "Delaware", "Ireland", "Bermuda", "Illinois", "Texas", "California", "Norway", "Germany", "Luxembourg", "Ontario"]
_PARTY_STOP = {"the", "n", "a", "na", "national", "association", "inc", "llc", "ltd", "limited", "plc", "co", "corp", "corporation", "as",
               "bank", "of", "and", "securities", "company", "branch", "new", "york", "usa", "us", "in", "such", "capacity", "each", "will",
               "act", "sole", "agent", "administrative", "borrower", "borrowers", "s", "l", "p", "lp", "dac", "designated", "activity",
               "group", "holdings", "international", "global", "north", "finance", "capital", "energy", "health", "lenders"}
_ALIASES = {"jpmcb": "jpmorgan", "jpm": "jpmorgan", "jpmorgan": "jpmorgan", "chase": "jpmorgan", "citi": "citibank", "citigroup": "citibank",
            "citibank": "citibank", "bofa": "bofa", "boa": "bofa", "merrill": "bofa", "wells": "wells", "fargo": "wells", "mufg": "mufg",
            "smbc": "sumitomo", "sumitomo": "sumitomo", "mizuho": "mizuho", "barclays": "barclays", "truist": "truist", "hsbc": "hsbc",
            "pnc": "pnc", "regions": "regions", "deutsche": "deutsche", "goldman": "goldman", "morgan": "morgan", "stanley": "morgan"}


# --------------------------------------------------------------------------- helpers
def _clean_label(label: str) -> str:
    return re.sub(r"^(?:[IVX]+|\d+|[A-Z])\.\s*", "", label.strip()).lower().strip(" :.")


def _squash(s: str) -> str:
    return re.sub(r"[^a-z/]", "", s.lower())


def _squash_rx(pattern: str) -> re.Pattern:
    """Whitespace-free variant of a label regex, so 'BOR ROWERS' / 'ADM INISTRATIVE' (small-caps splits) still match."""
    p = re.sub(r"\\s[?*+]?|\\b| ", "", pattern)
    return re.compile(p, re.IGNORECASE)


def _clauses(text: str) -> list[tuple[int, str]]:
    """Split text into clauses at sentence ends, semicolons and enumerators like '(b)'."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.;])\s+(?=[A-Z(“\"])|;\s+|\s+(?=\((?:[a-z]|[ivx]+)\)\s)", text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return [(s, c) for s, c in out if c.strip()]


def _keyword_windows(spec: Spec, ts: Doc, keywords: list[str], limit: int = 3) -> list[Window]:
    """Clause-bounded windows around a keyword (figures often come BEFORE the noun: '$50 million sublimit for letters of credit')."""
    hits = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), ts.flat, re.IGNORECASE):
            lo = max(0, m.start() - 260)
            seg = ts.flat[lo: m.end() + 260]
            rel = m.start() - lo
            best = next((c for s, c in _clauses(seg) if s <= rel <= s + len(c)), seg)
            hits.append(Window(best.strip(), ts.page_of(m.start()), f'keyword "{kw}"'))
            if len(hits) >= limit:
                return hits
    return hits


def _ts_windows(spec: Spec, entries: list[tuple[str, str, int]], ts: Doc) -> list[Window]:
    inc = re.compile(spec.ts_include, re.IGNORECASE) if spec.ts_include else None
    exc = re.compile(spec.ts_exclude, re.IGNORECASE) if spec.ts_exclude else None
    inc_sq = _squash_rx(spec.ts_include) if spec.ts_include else None
    exc_sq = _squash_rx(spec.ts_exclude) if spec.ts_exclude else None
    hits = []
    if inc:
        for label, value, page in entries:
            for part in re.split(r":\s+", label):  # merged labels "Governing Law: Counsel: Miscellaneous"
                lab = _clean_label(part)
                if not lab:
                    continue
                caps = part.isupper()  # small-caps labels may be split mid-word ("BOR ROWERS")
                ok = inc.search(lab) or (caps and inc_sq.search(_squash(lab)))
                bad = (exc and exc.search(lab)) or (caps and exc_sq and exc_sq.search(_squash(lab)))
                if ok and not bad:
                    tail = label.split(":", 1)[1].strip() if ":" in label else ""
                    hits.append(Window(((tail + " ") if tail else "") + value[:2500], page, f'label "{label}"'))
                    break
    # Sublimits are often stated inside another entry ("Facility Amount: $4bn, with a sublimit of $700m for letters of credit").
    if spec.near and spec.kind == "money":
        near = re.compile(spec.near, re.IGNORECASE)
        for label, value, page in entries:
            for _s, clause in _clauses(value):
                if near.search(clause) and V.parse_money(clause) and re.search(r"sublimit|up to|not (?:to )?exceed|available", clause, re.IGNORECASE):
                    hits.append(Window(clause.strip(), page, f'clause in "{label}"'))
    if spec.grids:
        hits += grid_windows(ts)
    kinds = (spec.kind,) + spec.extra_kinds
    has_vals = any(window_values(w, kinds) for w in hits) if spec.kind in ("money", "pct", "ratio", "date") else bool(hits)
    if spec.kind == "date" and not has_vals:
        has_vals = any(V.parse_tenor(w.text) for w in hits)
    if hits and has_vals:
        return hits
    # Fall back to clause-bounded keyword windows (lender decks, slides, or label entries without figures).
    return hits + _keyword_windows(spec, ts, spec.ts_keywords)


def _ca_windows(spec: Spec, ca: Doc) -> list[Window]:
    wins = definition_windows(ca, spec.ca_defs) if spec.ca_defs else []
    wins += section_windows(ca, spec.ca_sections) if spec.ca_sections else []
    if spec.ca_caps:
        wins += cap_windows(ca, spec.ca_caps)
    if spec.grids:
        wins += grid_windows(ca)
    if spec.ca_cover:
        wins.append(cover_window(ca))  # last: only used for evidence when nothing better confirms
    return wins


def _loc(wins: list[Window]) -> str:
    if not wins:
        return ""
    ps = sorted({w.page for w in wins})
    pages = "p. " + ", ".join(map(str, ps[:6])) + ("…" if len(ps) > 6 else "")
    return f"{pages} ({wins[0].source})"


def _row(spec: Spec, **kw) -> dict:
    row = {"id": spec.rid, "attribute": spec.name, "ts_value": "", "ts_quote": "", "ts_location": "", "ca_value": "",
           "ca_quote": "", "ca_location": "", "status": "review", "materiality": "n/a", "direction": "n/a", "explanation": ""}
    row.update(kw)
    return row


def _fmt(vals: list[V.Value], limit: int = 12) -> str:
    vals = V.unique(vals)
    s = ", ".join(v.display() for v in vals[:limit])
    return s + (f" (+{len(vals) - limit} more)" if len(vals) > limit else "")


def _pages_of(ca: Doc, v: V.Value) -> str:
    ps = ca.index.get(v.key, [])
    return ", ".join(map(str, ps[:4])) + ("…" if len(ps) > 4 else "")


def _quote_around(text: str, needle: str, width: int = 260) -> str:
    """The clause of `text` that contains `needle` (falls back to the start of the text)."""
    i = text.find(needle) if needle else -1
    if i < 0:
        return text[:width]
    for s, c in _clauses(text):
        if s <= i < s + len(c):
            c = c.strip()
            if len(c) <= width:
                return c
            j = c.find(needle)
            return c[max(0, j - width // 2): j + width // 2].strip()
    return text[max(0, i - width // 2): i + width // 2].strip()


def _anchor_dates(ca: Doc) -> list[tuple[str, str]]:
    """Dates a tenor is measured from: 'dated as of <date>' and fixed Closing/Effective Date definitions."""
    out = []
    for m in re.finditer(r"dated\s+as\s+of\s+(.{0,30}?(?:19|20)\d\d)", ca.flat[: ca.starts[min(len(ca.starts) - 1, 8)] + 4000], re.IGNORECASE):
        for v in V.parse_dates(m.group(1)):
            out.append((v.value, "agreement date"))
    for w in definition_windows(ca, [r"Closing Date", r"Effective Date", r"Amendment No\. ?\d+ Effective Date", r"Restatement Effective Date"]):
        for v in V.parse_dates(w.text[:300]):
            out.append((v.value, w.source))
    seen, res = set(), []
    for d, src in out:
        if d not in seen:
            seen.add(d)
            res.append((d, src))
    return res[:6]


def _tenor_compare(spec: Spec, ts_w: list[Window], ca_w: list[Window], ca: Doc, base: dict) -> dict | None:
    """Maturity stated as a tenor in the TS ('five years after the Closing Date', 'fifth anniversary',
    '364 days after') is checked against the CA maturity date measured from the agreement/effective date."""
    from datetime import date as _d
    tenors = [(t, w) for w in ts_w for t in V.parse_tenor(w.text)]
    if not tenors:
        return None
    ca_dates = V.unique([v for w in ca_w for v in V.parse_dates(w.text)])
    anchors = _anchor_dates(ca)
    # Cover/preamble dates of an amendment (its effective date is the anchor for a re-set tenor).
    for v in V.parse_dates(ca.flat[: ca.starts[min(2, len(ca.starts) - 1)] + 3000]):
        if v.value not in [a for a, _ in anchors]:
            anchors.append((v.value, "cover/preamble date"))
    base = dict(base, ts_value=", ".join(sorted({t.display() for t, _ in tenors})))
    tw = tenors[0][1]
    base["ts_quote"] = _quote_around(tw.text, tenors[0][0].text)
    # The CA may itself state the tenor ("the fifth anniversary of the Closing Date").
    ca_tenors = [(t, w) for w in ca_w for t in V.parse_tenor(w.text)]
    for t, _w in tenors:
        for ct, cw in ca_tenors:
            if abs(float(ct.value) - float(t.value)) <= 2:
                return _row(spec, status="match", explanation=f"Both documents state the tenor as {t.display()}.",
                            **dict(base, ca_value=ct.text, ca_quote=_quote_around(cw.text, ct.text), ca_location=f"p. {cw.page} ({cw.source})"))
    if not ca_dates or not anchors:
        return _row(spec, status="review", explanation="TS states a tenor; could not read both the CA maturity date and the agreement/effective date to compute it.", **base)
    tried = []
    for t, _w in tenors:
        tol = max(4.0, float(t.value) * 0.004)
        for v in ca_dates:
            for a, src in anchors:
                days = (_d.fromisoformat(v.value) - _d.fromisoformat(a)).days
                tried.append(f"{v.value} − {a} ({src}) = {days} days")
                if abs(days - float(t.value)) <= tol:
                    return _row(spec, status="match", explanation=f"TS tenor {t.display()} = CA maturity {v.value} measured from {a} ({src}).",
                                **dict(base, ca_value=f"{v.value} ({days} days after {a})"))
    return _row(spec, status="review", explanation=f"TS tenor {', '.join(sorted({t.display() for t, _ in tenors}))} did not equal any CA maturity date measured "
                f"from the agreement/effective dates found ({'; '.join(tried[:4])}). Check whether the CA uses a different anchor date.", **base)


def _numeric_compare(spec: Spec, ts_w: list[Window], ca_w: list[Window], ca: Doc) -> dict:
    kinds = (spec.kind,) + spec.extra_kinds
    if spec.near and spec.kind == "money":  # keep only figures in the same clause as the attribute keyword
        near = re.compile(spec.near, re.IGNORECASE)
        ts_vals = V.unique([v for w in ts_w for _s, c in _clauses(w.text) if near.search(c) or w.source.startswith("label")
                            for v in window_values(Window(c, w.page, w.source), kinds)])
    else:
        ts_vals = V.unique([v for w in ts_w for v in window_values(w, kinds)])
    win_vals = [(w, window_values(w, kinds)) for w in ca_w]
    ca_vals = V.unique([v for _w, vs in win_vals for v in vs])
    ca_keys = {v.key for v in ca_vals}
    key_win = {}
    for w, vs in win_vals:
        for v in vs:
            key_win.setdefault(v.key, (w, v))
    compared = ts_vals
    note = ""
    if spec.mode == "max" and ts_vals:
        top = max(ts_vals, key=lambda v: float(v.value))
        compared = [top]
        others = [v for v in ts_vals if v is not top]
        if others:
            note = f" Other figures in the TS entry (not compared): {_fmt(others, 6)}."
    shown_ca = [w for w in ca_w if w.source != "cover page"] or ca_w
    base = dict(ts_quote=ts_w[0].text[:300] if ts_w else "", ts_location=_loc(ts_w),
                ca_quote=shown_ca[0].text[:300] if shown_ca else "", ca_location=_loc(shown_ca),
                ts_value=_fmt(compared) or ("stated in words (no figures)" if ts_w else "not stated in TS"),
                ca_value=_fmt(ca_vals) or ("provision located, no figures" if ca_w else "not located in CA"))
    if not ts_w and not ca_vals and not [w for w in ca_w if w.source != "cover page"]:
        return _row(spec, status="not_applicable", explanation="Neither document provides for this.", **base)
    if not ts_w:
        return _row(spec, status="not_in_ts", explanation="The credit agreement has this provision; the term sheet does not address it.", **base)
    if not ts_vals and spec.kind == "date":
        res = _tenor_compare(spec, ts_w, ca_w, ca, base)
        if res:
            return res
    if not ts_vals:
        return _row(spec, status="review", explanation="Term sheet addresses this in words only; compare the quoted text manually.", **base)
    if spec.grids:  # drop table noise such as 0% floors and 100% figures
        compared = [v for v in compared if 0 < float(v.value) < 1000]
        if not compared:
            return _row(spec, status="review", explanation="Term sheet pricing figures could not be isolated; compare the quoted grid manually.", **base)
    if spec.rid == "R09":  # covenant percentages are thresholds like 65% debt/capitalisation, not fees in the same entry
        compared = [v for v in compared if v.kind != "pct" or float(v.value) >= 500]
    if not compared:
        return _row(spec, status="review", explanation="No comparable figures in the term sheet text for this attribute; compare the quoted text manually.", **base)
    confirmed = [v for v in compared if v.key in ca_keys]
    elsewhere = [v for v in compared if v.key not in ca_keys and v.key in ca.index]
    missing = [v for v in compared if v.key not in ca_keys and v.key not in ca.index]
    # A figure found elsewhere in the CA next to the attribute's own wording counts as confirmed.
    if elsewhere and spec.ts_keywords:
        kw_rx = re.compile("|".join(re.escape(k) for k in spec.ts_keywords), re.IGNORECASE)
        promoted = []
        for v in elsewhere:
            for pg in ca.index.get(v.key, [])[:12]:
                text = ca.flat_pages[pg - 1]
                if any(u.key == v.key and kw_rx.search(text[max(0, u.start - 300): u.start + 300]) for u in V.parse(text, (v.kind,))):
                    promoted.append(v)
                    key_win.setdefault(v.key, (Window(text, pg, "operative text"), next(u for u in V.parse(text, (v.kind,)) if u.key == v.key)))
                    break
        confirmed += promoted
        elsewhere = [v for v in elsewhere if v not in promoted]
    # Evidence: quote the TS clause holding the first compared figure and the CA window that confirmed it.
    first = (confirmed or compared)[0]
    src_w = next((w for w in ts_w if first.text in w.text), ts_w[0])
    base.update(ts_quote=_quote_around(src_w.text, first.text), ts_location=f"p. {src_w.page} ({src_w.source})")
    if confirmed:
        w, v = key_win[confirmed[0].key]
        base.update(ca_quote=_quote_around(w.text, v.text), ca_location=f"p. {w.page} ({w.source})")
    if not ca_w and not confirmed and not elsewhere:
        return _row(spec, status="not_in_ca", explanation="No matching provision or figure found in the credit agreement." + note, **base)
    parts = []
    if confirmed:
        parts.append(f"Confirmed in CA provision: {_fmt(confirmed)}.")
    if elsewhere:
        parts.append("Found elsewhere in CA (check context): " + "; ".join(f"{v.display()} (p. {_pages_of(ca, v)})" for v in elsewhere[:8]) + ".")
    if missing:
        parts.append(f"NOT found anywhere in CA: {_fmt(missing)}.")
    if spec.mode in ("any", "max"):
        status = "match" if confirmed else ("review" if elsewhere else "differs")
    elif spec.grids:
        # Pricing grids: a TS rate found anywhere in the CA is accepted (grids sit in schedules the windows may miss).
        # If most TS rates are missing, the CA grid is probably not machine-readable (image or garbled table).
        frac_missing = len(missing) / max(1, len(compared))
        if missing and frac_missing > 0.4:
            status = "review"
            parts.append("Most term-sheet rates were not found; the CA pricing grid may not be machine-readable, so check it manually.")
        else:
            status = "differs" if missing else "match"
    else:
        status = "differs" if missing else ("review" if elsewhere else "match")
    return _row(spec, status=status, explanation=" ".join(parts) + note, **base)


def _tokens(name: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z]+", name.lower()):
        if t in _ALIASES:
            out.add(_ALIASES[t])
        elif t not in _PARTY_STOP and len(t) > 1:
            out.add(t)
    return out


def _party_compare(spec: Spec, ts_w: list[Window], ca_pages: list[str], role: str) -> dict:
    ca_names = cover_roles(ca_pages, role)
    ts_text = " ".join(w.text[:600] for w in ts_w[:2])
    base = dict(ts_value=(ts_w[0].text[:220] if ts_w else "not stated in TS"), ts_quote=ts_w[0].text[:300] if ts_w else "",
                ts_location=_loc(ts_w), ca_value="; ".join(ca_names) or "not read from cover page",
                ca_quote="; ".join(ca_names)[:300], ca_location="cover page" if ca_names else "")
    if not ts_w:
        return _row(spec, status="not_in_ts", explanation="Not found in the term sheet.", **base)
    if not ca_names:
        return _row(spec, status="review", explanation="Could not read this role from the CA cover page; check manually.", **base)
    ts_tok = _tokens(ts_text)
    ts_sq = _squash(ts_text)
    hits = [n for n in ca_names if (_tokens(n) and _tokens(n) & ts_tok) or (len(_squash(n)) >= 6 and _squash(n) in ts_sq)]
    unmatched = [n for n in ca_names if n not in hits]
    if not unmatched:
        return _row(spec, status="match", explanation=f"CA cover names {'; '.join(ca_names)}; each appears in the TS entry.", **base)
    if hits:
        return _row(spec, status="review", explanation=f"Matched: {'; '.join(hits)}. Not found in TS entry: {'; '.join(unmatched)}.", **base)
    return _row(spec, status="differs", explanation=f"CA cover names {'; '.join(ca_names)}, which do not appear in the TS entry.", **base)


def _law(text: str) -> set[str]:
    return {j for j in _JURISDICTIONS if re.search(r"\b" + j + r"\b", text, re.IGNORECASE)}


def _ts_law(windows: list[Window], ts: Doc) -> tuple[set[str], str]:
    """Jurisdiction named in the TS governing-law entry (which may be merged with, or misaligned
    against, neighbouring entries). Returns (jurisdictions, quote)."""
    alt = "|".join(_JURISDICTIONS)
    rx = re.compile(r"(?:laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?|State\s+of\s+|^\s*|governing law[:\s]+)(" + alt + r")\b|\b(" + alt + r")\s+law\b", re.IGNORECASE)

    def scan(text: str) -> tuple[set[str], str]:
        found, quote = set(), ""
        for m in rx.finditer(text):
            j = m.group(1) or m.group(2)
            found.add(next(x for x in _JURISDICTIONS if x.lower() == j.lower()))
            quote = quote or text[max(0, m.start() - 60): m.end() + 60]
        return found, quote

    for w in windows:
        found, quote = scan(w.text)
        if found:
            return found, quote
    # Misaligned two-column layouts put the label beside the previous paragraph: search the whole TS
    # for an explicit governing-law statement instead.
    # Only accept a jurisdiction stated in governing-law context ("governed by ... the law of the State of
    # New York", "Governing Law: State of New York"), not incorporation clauses or biographies.
    rx_doc = re.compile(r"(?:governed\s+by|governing\s+law)[^.]{0,120}?(?:laws?\s+of\s+(?:the\s+)?)?(?:State\s+of\s+)?(" + alt + r")\b", re.IGNORECASE)
    found, quote = set(), ""
    for m in rx_doc.finditer(ts.flat):
        found.add(next(x for x in _JURISDICTIONS if x.lower() == m.group(1).lower()))
        quote = quote or ts.snippet(m.start(), 20, 160)
    return found, quote


def _ca_law(ca: Doc) -> tuple[set[str], list[Window]]:
    wins = []
    for m in re.finditer(r"(?:shall\s+be\s+)?governed\s+by,?\s+(?:and\s+)?(?:construed|interpreted)?[^.]{0,160}?laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", ca.flat, re.IGNORECASE):
        wins.append(Window(ca.snippet(m.start(), 0, 260), ca.page_of(m.start()), "governing-law clause"))
    juris = Counter()
    for w in wins:
        for j in _law(w.text[:260]):
            juris[j] += 1
    return ({juris.most_common(1)[0][0]} if juris else set()), wins[:3]


_SECURED = re.compile(r"\b(senior secured|first[- ]lien|first[- ]priority|secured by|security interests?|collateral (?:will|shall) (?:include|consist)|"
                      r"pledge (?:agreement|of)|mortgages? (?:on|over)|guarantee and collateral|perfected)\b", re.IGNORECASE)
_UNSECURED = re.compile(r"\bunsecured\b|^\s*none\b", re.IGNORECASE)


def _security_class(text: str) -> str:
    """Secured vs unsecured from the first decisive phrase (a facility described as 'senior secured' that
    later mentions 'unsecured notes' is secured)."""
    head = text[:500]
    u, sec = _UNSECURED.search(head), _SECURED.search(head)
    plain = re.search(r"(?<!un)\bsecured\b", head, re.IGNORECASE)
    cands = [(m.start(), lab) for m, lab in ((u, "unsecured"), (sec, "secured"), (plain, "secured")) if m]
    return min(cands)[1] if cands else ""


def _set_compare(spec: Spec, ts: Doc, ca: Doc, patterns: dict[str, str]) -> dict:
    def found(doc: Doc):
        res = {}
        for name, pat in patterns.items():
            m = re.search(pat, doc.flat, re.IGNORECASE)
            if m:
                res[name] = m.start()
        return res

    ts_set, ca_set = found(ts), found(ca)
    missing = [k for k in ts_set if k not in ca_set]
    first = min(ts_set.values()) if ts_set else None
    base = dict(ts_value=", ".join(ts_set) or "none stated", ca_value=", ".join(ca_set) or "none found",
                ts_quote=ts.snippet(first, 60, 200) if first is not None else "",
                ts_location=f"p. {ts.page_of(first)}" if first is not None else "", ca_quote="", ca_location="")
    if missing:
        base["ca_location"] = "whole document searched"
    elif ts_set:
        k = next(iter(ts_set))
        base["ca_quote"] = ca.snippet(ca_set[k], 60, 200)
        base["ca_location"] = f"p. {ca.page_of(ca_set[k])}"
    if not ts_set:
        return _row(spec, status="not_in_ts", explanation="Term sheet does not name any.", **base)
    if missing:
        return _row(spec, status="differs", explanation=f"Named in TS but not found in CA: {', '.join(missing)}.", **base)
    extra = [k for k in ca_set if k not in ts_set]
    return _row(spec, status="match", explanation="Every item named in the TS appears in the CA." + (f" CA also has: {', '.join(extra)}." if extra else ""), **base)


# --------------------------------------------------------------------------- main entry points
def check_deal(ts_pages: list[str], ca_pages: list[str], ts_layout: list[dict] | None = None) -> list[dict]:
    """Compare the 15 headline attributes. Pass ts_layout (pdftext.extract_layout) to pair term-sheet labels
    with their values by position; without it a text-line parser is used."""
    ts, ca = Doc(ts_pages), Doc(ca_pages)
    entries = parse_term_sheet_layout(ts_layout) if ts_layout else []
    if len(entries) < 5:
        entries = parse_term_sheet_entries(ts_pages)
    rows = []
    for spec in SPECS:
        if spec.rid == "R14":
            rows.append(_set_compare(spec, ts, ca, _BENCHMARKS))
            continue
        if spec.rid == "R15":
            rows.append(_set_compare(spec, ts, ca, _CURRENCIES))
            continue
        ts_w = _ts_windows(spec, entries, ts)
        if spec.kind in ("money", "pct", "ratio", "date"):
            rows.append(_numeric_compare(spec, ts_w, _ca_windows(spec, ca), ca))
        elif spec.kind == "agent":
            rows.append(_party_compare(spec, ts_w, ca_pages, r"(?:Administrative|Facilit(?:y|ies)|Global) Agent"))
        elif spec.kind == "party":
            rows.append(_party_compare(spec, ts_w, ca_pages, r"(?:Company|Borrowers?|Parent Borrower|Lead Borrower|U\.?S\.? Borrower)"))
        elif spec.kind == "law":
            ca_law, ca_w = _ca_law(ca)
            ts_law, law_quote = _ts_law(ts_w, ts)
            base = dict(ts_value=", ".join(sorted(ts_law)) or ("stated, jurisdiction unclear" if ts_w else "not stated in TS"),
                        ca_value=", ".join(sorted(ca_law)) or "not found", ts_quote=law_quote or (ts_w[0].text[:300] if ts_w else ""),
                        ts_location=_loc(ts_w) or ("whole document searched" if ts_law else ""),
                        ca_quote=ca_w[0].text[:300] if ca_w else "", ca_location=_loc(ca_w))
            if not ts_w and not ts_law:
                rows.append(_row(spec, status="not_in_ts", explanation="Not stated in the term sheet.", **base))
            elif ts_law and ca_law and ca_law <= ts_law:
                rows.append(_row(spec, status="match", explanation="Same governing law.", **base))
            elif ts_law and ca_law:
                rows.append(_row(spec, status="differs", explanation=f"TS: {', '.join(sorted(ts_law))}; CA: {', '.join(sorted(ca_law))}.", **base))
            else:
                rows.append(_row(spec, status="review", explanation="Could not determine the jurisdiction on both sides.", **base))
        elif spec.kind == "security":
            ts_cls, ts_src = "", []
            for w in ts_w + _ts_windows(SPECS[0], entries, ts):  # security/ranking entry first, then the facility description
                ts_cls = _security_class(w.text)
                if ts_cls:
                    ts_src = [w]
                    break
            if not ts_cls:  # whole-document vote (lender decks)
                n_sec, n_uns = len(_SECURED.findall(ts.flat)), len(_UNSECURED.findall(ts.flat))
                ts_cls = "secured" if n_sec > n_uns else ("unsecured" if n_uns else "")
            sec_defs = definition_windows(ca, ["Security Agreement", "Collateral Documents", "Security Documents", "Pledge and Security Agreement",
                                               "Collateral Agent", "Guarantee and Collateral Agreement", "Collateral and Guarantee Agreement", "Mortgages?"])
            ca_cls = "secured" if sec_defs else "unsecured"
            base = dict(ts_value=ts_cls or "not stated",
                        ca_value=ca_cls + (f" ({sec_defs[0].source})" if sec_defs else " (no security documents defined)"),
                        ts_quote=ts_src[0].text[:300] if ts_src else "", ts_location=_loc(ts_src) or ("whole document" if ts_cls else ""),
                        ca_quote=sec_defs[0].text[:300] if sec_defs else "", ca_location=_loc(sec_defs) or "definitions searched")
            if not ts_cls:
                rows.append(_row(spec, status="not_in_ts", explanation="Term sheet does not say whether the facility is secured.", **base))
            else:
                rows.append(_row(spec, status="match" if ts_cls == ca_cls else "differs", explanation=f"TS: {ts_cls}; CA: {ca_cls}.", **base))
        elif spec.kind == "extension":
            ca_w = _ca_windows(spec, ca)
            base = dict(ts_value=(ts_w[0].text[:220] if ts_w else "not stated in TS"), ts_quote=ts_w[0].text[:300] if ts_w else "",
                        ts_location=_loc(ts_w), ca_value=(ca_w[0].text[:220] if ca_w else "no extension / term-out provision found"),
                        ca_quote=ca_w[0].text[:300] if ca_w else "", ca_location=_loc(ca_w))
            if not ts_w:
                rows.append(_row(spec, status="not_in_ts" if ca_w else "not_applicable",
                                 explanation="Not stated in the term sheet." if ca_w else "Neither document has an extension or term-out option.", **base))
            elif not ca_w:
                rows.append(_row(spec, status="not_in_ca", explanation="TS mentions an extension / term-out but no matching CA provision was found.", **base))
            else:
                rows.append(_row(spec, status="review", explanation="Both documents contain a provision; compare the mechanics (number, notice, consent, fee) in the quotes.", **base))
    return rows


TERM_CONTEXT = re.compile(
    r"facilit|commitment|sublimit|margin|fee|spread|ratio|leverage|coverage|maturity|accordion|incremental|swing|letter of credit|"
    r"sofr|sonia|euribor|basket|threshold|default|covenant|tranche|term loan|revolv|tenor|extension|pricing|level|liquidity|"
    r"amortiz|prepay|lien|indebtedness|restricted payment|investment|judgment|grace|borrow",
    re.IGNORECASE,
)


def trace_figures(ts_pages: list[str], ca_pages: list[str]) -> list[dict]:
    """Look up every figure in the term sheet across the whole credit agreement."""
    ts, ca = Doc(ts_pages), Doc(ca_pages)
    ts_vals = V.parse(ts.flat)
    for pno, text in enumerate(ts.flat_pages, 1):
        if is_grid_page(text) and V.BPS_HEADER_RE.search(text):
            ts_vals += [V.Value(v.kind, v.value, v.currency, v.text, ts.starts[pno - 1] + v.start) for v in V.parse_bare_bps(text)]
    rows, seen = [], set()
    for v in sorted(ts_vals, key=lambda x: x.start):
        ctx = ts.snippet(v.start, 90, 110)
        dedupe = (v.key, ctx[:60])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        pages = ca.index.get(v.key, [])
        rows.append({
            "type": {"money": "Amount", "pct": "Rate (bps)", "ratio": "Ratio", "date": "Date"}[v.kind],
            "ts_text": v.text,
            "normalised": v.display(),
            "ts_page": ts.page_of(v.start),
            "context": ctx,
            "credit_term_context": bool(TERM_CONTEXT.search(ctx)),
            "found_in_ca": bool(pages),
            "ca_pages": ", ".join(map(str, pages[:8])) + ("…" if len(pages) > 8 else ""),
        })
    return rows
