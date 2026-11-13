"""Rules for the Security, Guarantors & Ranking rows, and the jurisdiction of the top company.

Fields: guarantors, guarantor_coverage, security, ranking, jurisdiction_topco.

How the rules work
------------------
Every rule starts from the labelled section that normally carries the term ("Guarantors:",
"Collateral:", "Security:", "Ranking:", "Governing Law:") and reads it as a *cell* (``_read``): the
value text with running page headers and footers removed and words broken by the layout rejoined; a
table row cut back to itself where the block reader ran on into its neighbours; a section that
breaks off in mid-sentence at the foot of a page carried on where the next page takes it up in the
value column (``_over_page``); a vertically centred label put back beside its whole cell; and an
amendment table's "Same as existing" replaced by the existing column (the line then says the term
is unchanged). Only the term sheet's own rows count: a lettered
item or bullet of a covenant list that happens to be headed "Guarantees" or "Security" is left alone,
and so is a row worded as an undertaking ("No member of the Group shall create any Security ...").
"per cent." is read as "%". Searches that cross sections (the consent needed to release guarantors,
a pari passu undertaking, where a company's jurisdiction is given) run over ``_flow``, the document
as one cleaned text.

Lines are assembled from pieces matched in that text. Nothing is supplied from what term sheets
usually say; a point that is derived says so and names its basis; a rule that finds no basis
returns "not stated". A label alone decides nothing: what a row says is judged on its wording, and
a row whose wording the rules do not recognise is reported as it stands (or left "not stated"),
never turned into a conclusion. A value left blank ("[ ]") is reported as a blank.

Three habits keep a line true on a document the rules were not written against. A clause that is
conditional, negated or built of several limbs (a coverage level that applies "in the event that
...", a test of which subsidiaries are immaterial, the conditions of a release) is given in the
term sheet's own words and order, over two or three lines if need be, rather than rearranged. A
list is read as a list or not at all: its items are followed by their markers, it ends where its
numbering starts again, and where only some items fit the line says how many there are. And a line
that has to be cut is cut at a clause boundary, never on a lead-in ("which shall include ...") or
in mid-word, and is marked "…".

Whose consent a release needs (``_consent_group``) is read from the structure of the sentence, not
from the nearest mention of a consent: the group written after the release ("... shall require the
consent of all Lenders"), in the same list item, or at the head of the list in which the release is
an item ("the consent of each Lender shall be required with respect to (i) ..., (ii) ... and (iii)
the release of ..."). A group named only as an addition ("in addition to the consent of the Required
Lenders") does not govern; words that qualify the item ("except as provided in the loan
documents") are kept; and where the wording is not of a kind the rules know, or the consent is not
that of a group of Lenders, no line is printed.

guarantors          The lead clause of each guarantor section ("... will be guaranteed by X"), with
                    Parent / Holdings / the Company named where the term sheet defines them, then the
                    points a credit reader looks for: a parent guarantee of subsidiary borrowers,
                    exceptions (as a list of the topics the text mentions, or a lettered list of
                    exclusions item by item), fall-away / release wording, and the lender consent
                    needed to release guarantors. A section about some of the guarantors keeps its
                    label ("Domestic Guarantors: ...", "Foreign Guarantors: None; provided that ...")
                    and a "None" keeps what qualifies it. Coverage levels and materiality tests are
                    left to the next row and pointed to. With no guarantor section, a guarantee of
                    this facility stated in the Borrower or Facility row (not one that belongs to
                    debt being refinanced), or an express "unguaranteed".
guarantor_coverage  A coverage test: a "Guarantor coverage" section, guarantors as a body
                    "constituting > 80% of ..." (a small percentage, or one said of each subsidiary,
                    is a materiality test, not coverage; a level that is conditional or tested is
                    given as its clause), or a cap on what non-guarantor subsidiaries may represent.
                    Otherwise "None stated in term sheet" (not_stated), with the test that decides
                    who must guarantee, if given: the material-subsidiary threshold (the definition
                    itself, not a proviso to it) or an immaterial-subsidiary test in its own words.
                    Where the term sheet says there are no guarantors the row is a derived "None".
security            The Collateral / Security row is classified by its first sentence (_security_kind):
                    it says there is no security ("Unsecured", "None", "No security will be provided",
                    "will not be secured"); it grants or describes security; it only points
                    elsewhere; it is blank; or it is none of these (springing security, one facility
                    secured and another not, wording the rules do not know), in which case the row is
                    given as it stands and nothing is concluded from it. Collateral is described from
                    the bullets of a slide (marked against the existing column of an amendment), an
                    "(a) ...; (b) ..." list, or the "secured by ..." clause, with exclusions (a list
                    of them item by item, with their number), share pledges and their limits, release
                    triggers (in the row or under a "Release of Collateral" heading of their own) and
                    the consent needed to release collateral. With no such row the position is taken
                    from how the facility is
                    described ("senior unsecured revolving credit facility") or, failing that,
                    derived from stated facts (a pari passu undertaking, pricing off senior unsecured
                    ratings) provided nothing in the document points to security.
ranking             One of Senior Unsecured / Senior Secured / Super Senior / Subordinated: from a
                    "Ranking" section (the facility's own ranking words: not ones that are denied,
                    "will not be subordinated", or that describe the debt it is compared with,
                    "behind the Super Senior Revolving Facility"), else from the description of the
                    facility, else derived from the security position; then short qualifiers found in
                    the text (first-priority security, proceeds applied first to the facility, and,
                    in a document about a revolver alone, a "First Lien RCF" label).
jurisdiction_topco  The top company is the entity the term sheet names in a Parent / Holdings / Topco
                    row or defines as such; failing that the Company (row or defined term), the party
                    whose subsidiaries it keeps referring to, a sole named Guarantor or a sole
                    Borrower. Its jurisdiction is read from the words that follow its name ("a
                    Delaware corporation", "incorporated under the laws of Ireland"). If none is
                    given the row is not_stated, says which company was looked for, and carries the
                    governing law of the facility on a second line.

Evidence always comes from ``ctx.quote`` / ``ctx.quote_text``, so every quote is on the page it cites;
a stated or by_reference line that cannot be backed by such a quote is not returned.
"""
from __future__ import annotations

import bisect
import re
import weakref
from dataclasses import dataclass, field

from ..textmodel import clip, fragments, is_footer, tidy
from .blocks import Block, find_blocks
from ..schema import MAX_LINE_CHARS, MAX_QUOTE_CHARS
from .common import LINE_LIMIT, SAME_AS_EXISTING_RE, Ctx, by_reference, not_stated, points_elsewhere, squeeze, stated

MAIN_LIMIT = 340  # the line that carries the substance of a row may run a little longer than LINE_LIMIT
WRAP_AT = 270  # ... but past this length it is broken in two where it has a natural break
LONG_LIMIT = MAX_LINE_CHARS - 5  # a clause that only its own words state truly may run to the length the schema allows before it is cut
NONE_STATED = "None stated in term sheet"
UNCHANGED = " (unchanged from existing terms)"

# ---- labels of the sections the rules read (regex fragments for Ctx.blocks; kept tight on purpose) ----

# "Guarantors:", "Guarantor(s)", "Subsidiary Guarantors:", "Guarantees:", "Guaranty:", "Guarantees and Security:", and the sections of a
# term sheet that sets its guarantors out by kind or by where they are: "Domestic Guarantors:", "Foreign Guarantors:", "U.S. Guarantors:",
# "Canadian Guarantors:", "Additional Guarantors:", "Parent Guarantor:" - one or two capitalised words of any kind before "Guarantor(s)"
# (capitalised as a heading is; not the words that only open a sentence, "Each Guarantor", "Such Guarantors")
_GUARANTOR_SCOPE = r"(?:domestic|foreign|u\.?\s?s\.?|non-?\s?u\.?\s?s\.?|international)"
_GUARANTOR_KIND = (r"(?:(?!(?i:each|any|all|such|no|every|other|certain|its|their|the|these|those|and|or|of|by|as|if|that|which|non-?guarantor)\s)"
                   r"(?-i:[A-Z])[\w.\-’']*\s+){1,2}")
_GUARANTOR_LABELS = (
    r"(?:the\s+)?(?:original\s+|initial\s+|subsidiary\s+|parent\s+|" + _GUARANTOR_SCOPE + r"\s+(?:subsidiary\s+)?|" + _GUARANTOR_KIND
    + r")?guarantors?(?:\s*\(s\))?",
    r"guarant(?:ees?|y|ies)",
    r"guarant(?:ees?|ors?|y)\s+and\s+(?:security|collateral)",
    r"credit\s+support",
)
# LMA style: "Guarantor coverage:", "Guarantor Coverage Test:"
_COVERAGE_LABELS = (r"guarantor\s+coverage(?:\s+test)?", r"guarantee\s+coverage(?:\s+test)?", r"coverage\s+test")
# "Collateral:", "Security:", "Security Package:", "Security Interests:", "Transaction Security:", "Security / Collateral:"
_SECURITY_LABELS = (
    r"(?:the\s+)?(?:collateral|security)(?:\s+(?:package|interests?|arrangements))?",
    r"transaction\s+security",
    r"(?:security|collateral)\s*(?:/|and)\s*(?:collateral|security|guarantees?)",
    r"guarant(?:ees?|ors?|y)\s+and\s+(?:security|collateral)",
)
# "Ranking:", "Ranking and Priority:", "Ranking of the Facilities:"
_RANKING_LABELS = (r"ranking(?:\s+and\s+priority|\s+of\s+the\s+facilit(?:y|ies))?", r"priority\s+and\s+ranking")
# "Governing Law:", "Governing Law and Jurisdiction:", "Governing Law and Forum:"
_LAW_LABELS = (r"governing\s+law(?:\s+and(?:\s+(?:jurisdiction|forum|venue))?)?", r"applicable\s+law", r"law\s+and\s+jurisdiction")
# "Facility:", "Type of Facility:", "Type and Amount of Facility:", "Revolving Credit Facility:", "364-Day Facility:"
_FACILITY_LABELS = (
    r"(?:type\s+(?:and\s+amount\s+)?of\s+|description\s+of\s+)?(?:the\s+)?(?:senior\s+)?(?:secured\s+|unsecured\s+)?"
    r"(?:revolving\s+|term\s+(?:loan\s+)?)?(?:credit\s+)?facilit(?:y|ies)(?:\s+(?:type|description))?",
    r"(?:\d+-?\s?day|\d-?\s?year|five-?\s?year)\s+(?:revolving\s+)?(?:credit\s+)?facility",
)
# "Borrower:", "Borrowers:", "Borrower(s)"
_BORROWER_LABELS = (r"(?:the\s+)?borrowers?(?:\s*\(s\))?",)
# "Parent:", "Ultimate Parent:", "Holdings:", "Parent Guarantor:", "Topco:" (a company above the Company)
_PARENT_LABELS = (r"(?:ultimate\s+)?parent(?:\s+(?:company|guarantor))?", r"holdings", r"topco")
# "Company:", "The Company:"
_COMPANY_LABELS = (r"(?:the\s+)?company",)
# "Affirmative Covenants:", "Covenants:"
_COVENANT_LABELS = (r"affirmative\s+covenants?", r"covenants?")

# ---- wording patterns ----

# layout noise: a hyphen that lost its neighbour ("first -priority", "364- Day")
_HYPHEN_GAP_RE = re.compile(r"(\w+)(?:\s+-|-\s+)(\w)")
# ... except after a rating ("BBB- by S&P")
_RATING_TOKEN_RE = re.compile(r"^(?:A{1,3}|B{1,3}|C{1,3}|D|Aa|Aaa|Ba|Baa|Caa)\d?$")
# a word broken by a layout gap ("obligat ions"): the first piece, looked at together with the piece that follows
_BROKEN_WORD_RE = re.compile(r"\b([A-Za-z]+) (?=([a-z]+)\b)")
# a line that ends with an abbreviation keeps its full stop ("... and GXI, LLC.", "... N.V.")
_ENDS_ABBREVIATED_RE = re.compile(r"(?:\b(?:Inc|Ltd|Corp|Co|etc)|(?:\b[A-Za-z]\.){1,3}[A-Za-z])\.$")
# "(as defined below)", "(defined below)", "(as defined in the Existing Credit Agreement)"
_AS_DEFINED_RE = re.compile(r"\s*\((?:as\s+)?(?:hereinafter\s+)?defined\s+(?:below|above|herein|therein|in\s+[^()]{3,80})\)", re.IGNORECASE)
# a bracket that only introduces defined terms: (the “Guarantor”), (collectively, the “Guarantors”; ...), (“MK”)
_DEFINES_RE = re.compile(
    r"\s*\((?:(?:the|each,?\s+an?|an?|collectively[^()“\"]{0,40}|together[^()“\"]{0,60}|in\s+such\s+capacit\w+[^()“\"]{0,20})\s*)?[“\"][^()]{1,200}\)",
    re.IGNORECASE)
# list markers that must survive when brackets are stripped: (a), (iv), (2), (A), (II)
_ENUM_RE = re.compile(r"\((?:[a-z]|[ivx]{1,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)")
# abbreviations whose full stop does not end a sentence, and initials
_ABBR_RE = re.compile(r"\b(Inc|Ltd|Corp|Co|Bros|No|Nos|LLC|L\.L\.C|L\.P|LLP|N\.A|N\.V|B\.V|S\.A|S\.p\.A|plc|PLC|U\.S|U\.K|e\.g|i\.e|etc|vs|[A-Z])\.(?=\s)")
# ... unless the next word plainly starts a new sentence ("... and GXI, LLC. If on any date ...")
_ABBR_END_RE = re.compile("\x01(?=\\s+(?:If|The|Each|All|Any|In|On|Upon|Subject|Notwithstanding|Additionally|As|For|From|No|Such|This|These|"
                          "Guarantees|Provided|Prior|Following|At)\\s)")
# sentence / list-item boundary: ". Next", "; (b)", '. “Term” means'
_SENTENCE_RE = re.compile(r"(?<=[\w\)\]”\"%’'])[.;]\s+(?=[A-Z(“\"•])")
# a "sentence" that is a later item of a list opened in an earlier one: "(ii) each Material Subsidiary", "and (c) all proceeds"
_LATER_ITEM_RE = re.compile(r"^(?:(?:and|or)\s+)?\((?:[a-z]|[ivx]{2,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)\s")
# the end of the operative clause: provisos and "including without limitation" tails
_PROVISO_RE = re.compile(r"\s*[;,]?\s*(?:provided,?\s+(?:that|however|further)|including,?\s+without\s+limitation|including,?\s+but\s+not\s+limited\s+to)\b",
                         re.IGNORECASE)
# the parties clause of an agreement reference: ", among X, as borrower, ... and the other parties party thereto"
_AMONG_RE = re.compile(r",?\s+(?:by\s+and\s+)?among\s+.{0,400}?\b(?:party|parties)\s+thereto(?:\s+from\s+time\s+to\s+time)?", re.IGNORECASE)
# ", as amended on March 28, 2024"
_AS_AMENDED_RE = re.compile(r",?\s+as\s+amended\s+(?:on|by|through|as\s+of)\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}")
# where a long line may be broken in two, best kind of boundary first: "... and (b) ...", "...; ...", "..., and ...", "..., including ..."
_WRAP_RES = (
    re.compile(r",?\s+and\s+(?=\((?:b|ii|B|2)\)\s)"),
    re.compile(r";\s+"),
    re.compile(r",\s+and\s+(?=[a-z])"),
    re.compile(r",\s+(?=including\s)"),
)
# ... and, for a line that would otherwise have to be cut, where a relative clause, a consequence or a qualification begins
_WRAP_MORE_RES = (
    re.compile(r",\s+(?=which\s)"),
    re.compile(r",\s+(?=then\b)"),
    re.compile(r",\s+(?=(?:subject\s+to|provided\s+that|to\s+the\s+extent)\b)"),
)
# words a cut line must not end on: a lead-in whose object has been cut away ("..., which shall include", "... including", "... of the")
_DANGLING_RE = re.compile(
    r"(?:[,;:]?\s+(?:(?:which|that)\s+(?:shall|will|may|would)\s+(?:also\s+)?(?:include|consist\s+of|comprise)|includ(?:ing|es?)|such\s+as|consisting\s+of|"
    r"compris(?:ing|es?)|without\s+limitation|but\s+not\s+limited\s+to|and|or|of|the|to|by|in|on|with|for|an?|as|that|which|its|their|any|each|all|"
    r"shall|will|is|are|be))+[,;:]?\s*$", re.IGNORECASE)
# a word that opens a new sentence at the head of a page (capitalised, it cannot be the next word of a sentence that runs on)
_PAGE_OPENER_RE = re.compile(r"^(?:The|An|If|In|On|Upon|Each|All|Any|For|To|This|These|Such|At|As|With|Notwithstanding|Subject|There|It|Unless|Until|"
                             r"When|Where|While|Except)\s")
# bullets of a slide cell
_BULLET_RE = re.compile(r"[•·▪●■◼]")
# a covenant-list item under a label such as "Guarantees:" or "Security:": "Limitation on ...", "Restrictions on ...", "Permitted ..."
_COVENANT_WORDING_RE = re.compile(r"^\W*(?:limitations?|restrictions?|restricted|prohibit\w+|permitted|not\s+to|"
                                  r"no\s+(?:other|additional|further)|customary\s+(?:limitations|restrictions))\b",
                                  re.IGNORECASE)
# a row that is an undertaking about what the group may do, whatever its label: "No member of the Group shall create or
# permit to subsist any Security ...", "The Borrower shall not grant ...", "Limitation on liens", "Negative pledge ..."
_COVENANT_CELL_RE = re.compile(
    r"^\W*(?:no\s+(?:member\s+of\s+the\s+group|group\s+company|obligor|borrower|guarantor|loan\s+party|credit\s+party|"
    r"(?:restricted\s+|material\s+)?subsidiary|company|person)\b[^.;]{0,60}?\b(?:shall|will|may|is\s+to)\s+"
    r"(?:create|grant|permit|incur|give|allow|make|enter|issue|suffer|assume|provide|be\s+(?:a\s+)?creditor)\b|"
    r"(?:the\s+|each\s+)?(?:borrowers?|company|parent|obligors?|guarantors?|loan\s+part(?:y|ies)|group)\b[^.;]{0,60}?\b(?:shall|will|may)\s+not\s+"
    r"(?:,[^.;]{0,80}?,\s*)?(?:create|grant|permit|incur|give|allow|make|enter|issue|suffer|assume)\b|"
    r"negative\s+pledge\b|limitations?\s+on\b|restrictions?\s+on\b|not\s+to\s+(?:create|grant|permit|incur|give)\b)", re.IGNORECASE)
# a value left blank: "[ ]", "[●]", "[__]", "[*]"
_BLANK_RE = re.compile(r"^\W*\[[\s●•_*.\-]*\]\W*$")
# a blank level inside a sentence: "[ ]%", "[●] per cent."
_BLANK_PCT_RE = re.compile(r"\[[\s●•_*.\-]*\]\s*(?:%|per\s?cent)", re.IGNORECASE)
# a value given in square brackets (provisional): "[Senior secured]"
_BRACKETED_RE = re.compile(r"^\W*\[\s*([^\[\]]{3,200}?)\s*\]\W*$")
# LMA wording for a percentage: "80 per cent.", "5 percent"
_PER_CENT_RE = re.compile(r"(\d|\])\s*(?i:per\s?cent)\b(?:\.(?=\s+[a-z(\[]|\s*[,;)]))?")  # (the abbreviation's dot goes; a full stop stays)
# a table label that plainly carries on to the next line: "Permitted liens &", "Type and Amount of"
_UNFINISHED_LABEL_RE = re.compile(r"(?:[&/\-]|\b(?:and|of|for|to|the|on|in))\s*$", re.IGNORECASE)
# an "Existing ... Proposed" header: the page is an amendment table
_AMEND_HEADER_RE = re.compile(r"\b(?:Existing|Current)\b.{0,60}\b(?:Proposed|Amended|New)\b")
# a plain-text amendment cell that ends "... Same as existing"
_SAME_TAIL_RE = re.compile(r"(?:^|\s)(?:Same\s+as\s+(?:existing|current)|No\s+change|Unchanged)\W*$", re.IGNORECASE)
# a cell that says nothing applies: "None.", "N/A", "Not applicable"
_NONE_RE = re.compile(r"^\W*(?:none|n/?a|not\s+applicable)\b\W*(?:$|[.;])", re.IGNORECASE)
# a section label that says which guarantors it is about: "Domestic Guarantors", "Foreign Guarantors", "Subsidiary Guarantors",
# "Parent Guarantor", "Additional Guarantors" - any word before "Guarantor(s)" other than the article
_SCOPED_LABEL_RE = re.compile(r"^(?:the\s+)?(?!guarant|the\s)[\w.\-’']+\s+(?:[\w.\-’']+\s+)?guarantors?\b", re.IGNORECASE)
# a cell that only points elsewhere: "Same as the Existing Credit Agreement", "To be agreed", "Customary ..."
_REFERS_RE = re.compile(
    r"^\W*(?:same\s+as|as\s+(?:per|set\s+forth\s+in|provided\s+in|under)|consistent\s+with|substantially\s+(?:the\s+same|similar|consistent|identical)|"
    r"identical\s+to|in\s+accordance\s+with|to\s+be\s+(?:agreed|determined|discussed|confirmed|provided|advised|negotiated|finali[sz]ed|inserted|completed)|"
    r"to\s+(?:come|follow)|usual\s+and\s+customary|customary(?=\W*$|\s+(?:for|in|and)\b)|TBD|TBC|TBA)\b", re.IGNORECASE)

# "shall be guaranteed (the “Guarantee”) by", "jointly and severally guaranteed on a senior basis by"
_GUARANTEED_BY_RE = re.compile(
    r"\bguarante+d\s+(?:(?:on\s+an?\s+[\w\- ]{0,40}?basis|jointly\s+and\s+severally|unconditionally|irrevocably|fully|and|,)\s+){0,6}by\s+", re.IGNORECASE)
# a guarantee mentioned in passing: "fully and unconditionally guaranteed by the Company"
_PASSING_GUARANTEE_RE = re.compile(
    r"(?P<how>(?:fully\s+and\s+unconditionally|unconditionally\s+and\s+irrevocably|irrevocably\s+and\s+unconditionally|unconditionally|irrevocably|"
    r"jointly\s+and\s+severally)\s+)?guarante+d\s+by\s+(?P<who>(?:the\s+)?[A-Z][^.;()]{1,100})")
# shortly before "guaranteed by": the guarantee belongs to other debt ("to refinance the 5.25% Senior Notes guaranteed by X")
_OTHER_DEBT_NEAR_RE = re.compile(r"\b(?:existing|refinanc\w+|repa(?:y|id|yment)\w*|redeem\w*|redemption|notes|bonds|debentures|indebtedness)\b[^.;]{0,60}$",
                                 re.IGNORECASE)
# "the Facility will not be guaranteed", "the Loans are unguaranteed", "an unguaranteed revolving credit facility" (but not the
# "senior unsecured, unguaranteed long-term debt" whose ratings set the pricing: that describes other debt)
_UNGUARANTEED_RE = re.compile(
    r"\b(?:facilit\w+|loans|obligations)\b[^.;]{0,60}\b(?:(?:will|shall)\s+not\s+be\s+guarante+d|(?:is|are|will\s+be|shall\s+be)\s+unguarante+d)\b|"
    r"\bunguarante+d\s+(?:[\w\-]+\s+){0,4}?(?:facilit(?:y|ies)|revolver|RCF)\b", re.IGNORECASE)
# "the Company will guarantee all obligations of the Designated Borrowers"
_GUARANTEES_OBLIGATIONS_RE = re.compile(
    r"\b(?:will|shall)\s+(?:also\s+)?(?:unconditionally\s+)?guarantee\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?obligations\s+of\s+(?:the\s+)?[^.;,()]{3,60}?"
    r"(?=\s+under\b|\s+and\s+under\b|[.;,(]|$)", re.IGNORECASE)
# "guarantees of payment and not of collection"
_PAYMENT_GUARANTEE_RE = re.compile(r"guarant(?:ee|y|ie)s?\s+of\s+payment\s+and\s+not\s+of\s+collection", re.IGNORECASE)
# a sentence that only names things: 'is referred to herein as a “Guarantor”'
_REFERRED_AS_RE = re.compile(r"\breferred\s+to\s+(?:herein\s+|collectively\s+)?as\b", re.IGNORECASE)
# a definition: '“Material Subsidiary” means', 'As used above, the term “X” means'
_DEFINITION_SENTENCE_RE = re.compile(r"^(?:As\s+used\s+(?:above|herein|below)[^“\"]{0,30})?[“\"]")
# '“IP Jurisdictions” means Italy, Switzerland, the United States and the United Kingdom.'
_SHORT_DEFINITION_RE = re.compile(r"[“\"]([^”\"]{3,40})[”\"]\s+means\s+([^.]{3,160})(?:\.|$)")
# release / fall-away wording
_RELEASE_RE = re.compile(
    r"\b(?:shall|will|may|to)\s+be\s+(?:automatically\s+)?(?:released|terminated|"
    r"discharged)\b|\breleased?\s+(?:automatically|upon|on|if|when)\b|\bfall[\s-]?away\b",
    re.IGNORECASE)
# the operative words of a release clause
_RELEASED_RE = re.compile(r"\b(?:shall|will)\s+be\s+(?:automatically\s+)?(?:released|terminated|discharged)", re.IGNORECASE)
# '“Guarantee Fall-Away Event”', '“Collateral Release Date”'
_EVENT_NAME_RE = re.compile(r"[“\"]([^”\"]{3,50}?(?:Fall-?\s?Away|Release|Termination)\s+(?:Event|Date|Condition))[”\"]")
# "If <condition>, then <consequence>" and its relatives
_IF_THEN_RE = re.compile(
    r"^(?:If|In\s+the\s+event\s+that|From\s+and\s+after\s+the\s+date\s+(?:that|on\s+which)|On\s+and\s+after\s+the\s+date\s+(?:that|on\s+which)|"
    r"At\s+such\s+time\s+as)\s+(?P<cond>.+?),\s+then,?\s+(?P<main>.+)$", re.IGNORECASE)
# what follows the operative release clause: "; provided that ...", ", regardless of whether ..."
_RELEASE_TAIL_RE = re.compile(r";\s*provided\b|,\s*provided,?\s+that\b|,\s*regardless\s+of\b", re.IGNORECASE)
# words that make what stands before the operative clause a condition of the release: "then, so long as no Event of Default is continuing, the liens ..."
_CONDITION_WORD_RE = re.compile(r"\b(?:so\s+long\s+as|as\s+long\s+as|subject\s+to|provided|unless|except|if|only|to\s+the\s+extent|upon|following|after|absent|"
                                r"until|when|once|with\s+the\s+(?:consent|approval)|at\s+the\s+(?:option|election|request|direction|discretion)|no\s+default|"
                                r"no\s+event\s+of\s+default)\b", re.IGNORECASE)
# the section provides for the security or guarantee to be given again
_REINSTATE_RE = re.compile(r"\breinstat|\bre-?\s?grant|\bre-?\s?pledg|\bre-?\s?secur|\bspring(?:s|ing)?\s+back", re.IGNORECASE)
# "beginning on such date the guarantees shall be released"
_FROM_SUCH_DATE_RE = re.compile(r"^(?:beginning|commencing|effective)\s+on\s+such\s+date,?\s+", re.IGNORECASE)
# "upon delivery of a written notice from the Borrower"
_NOTICE_RE = re.compile(r"upon\s+(?:delivery\s+of\s+)?(?:a\s+)?(?:written\s+)?(?:notice|request)\s+(?:from|by|of)\s+the\s+\w+", re.IGNORECASE)
# amendments section: "the consent of each Lender directly affected thereby", "the consent of 100% of Lenders"
# (any group of Lenders is taken, so that the nearest consent requirement before a release is the one that governs it:
# "the consent of the Required Lenders", "the consent of Lenders holding more than 50% of ...")
# a group of Lenders: "each Lender", "all Lenders or all affected Lenders", "Lenders holding more than 50% of ..."
_LENDER_GROUP = (r"(?P<who>(?:the\s+)?(?:100\s?%\s+of\s+(?:the\s+)?)?(?:(?!and\b|or\b)[A-Za-z][\w\-]*\s+){0,4}?(?-i:Lenders?)"
                 r"(?:\s+holding\s+[^,;.()]{3,90}?(?=\s+(?:shall|will|is|are)\b|[,;.()])|\s+(?:directly\s+)?(?:and\s+adversely\s+)?affected(?:\s+thereby)?)?"
                 r"(?:\s+or\s+(?:of\s+)?(?:all|each|every)\s+(?:of\s+the\s+)?(?:(?!and\b|or\b)[A-Za-z][\w\-]*\s+){0,3}?(?-i:Lenders?)"
                 r"(?:\s+(?:directly\s+)?(?:and\s+adversely\s+)?affected(?:\s+thereby)?)?)?)")
_CONSENT_OF = r"(?:consent|approval)\s+of\s+" + _LENDER_GROUP
_LENDER_GROUP_RE = re.compile(_LENDER_GROUP, re.IGNORECASE)
# any call for somebody's consent, whoever it is: where the party named is not a group of Lenders the rules can read, they say nothing
_APPROVAL_OF_RE = re.compile(r"\b(?:consents?|approvals?|votes?|agreement)\s+(?:of|from)\s+", re.IGNORECASE)
# a second group named beside the one that governs: "the consent of all Lenders, in addition to the consent of the Required Lenders, shall be ..."
_ALSO_CONSENT_RE = re.compile(r",?\s*\b(?:in\s+addition\s+to|together\s+with|as\s+well\s+as|along\s+with)\s+(?:the\s+)?(?:prior\s+)?(?:written\s+)?"
                              r"(?:consent|approval)\s+of\s+" + _LENDER_GROUP.replace("?P<who>", "?P<also>") + r"\s*,?", re.IGNORECASE)
# what may stand between the group and the list it governs: "... shall be required with respect to (i)", "..., no amendment shall (i)"
_GOVERNS_LIST_RE = re.compile(
    r"^[\s,]*(?:(?:shall|will|would|must|is|are)\s+(?:also\s+)?(?:be\s+)?(?:required|necessary|needed|obtained)\b)?"
    r"[\s,]*(?:no\s+(?:such\s+)?(?:amendment|waiver|modification|consent)\b[\w\s,]{0,60}?\b(?:shall|will|may)\b)?"
    r"[\s,]*(?:(?:with\s+respect\s+to|in\s+respect\s+of|in\s+connection\s+with|in\s+the\s+case\s+of|in\s+order\s+to|for|to)\b)?"
    r"[\s,]*(?:(?:any\s+|all\s+)?(?:matters?|amendments?|waivers?|modifications?|changes?)\b[\w\s,]{0,60}?\b(?:relating\s+to|that\s+would|which\s+would|that|to)\b)?"
    r"[\s,:]*(?:each\s+of\s+)?(?:the\s+following\b)?[\s,:]*$", re.IGNORECASE)
# the verb that makes the group's consent a requirement, where the release is named in the same clause:
# "the consent of each Lender shall be required for <other matters and> the release of ..."
_REQUIRED_RE = re.compile(r"^[\s,]*(?:shall|will|would|must|is|are)\s+(?:also\s+)?(?:be\s+)?(?:required|necessary|needed)\b", re.IGNORECASE)
# ... unless another clause begins in between
_NEW_CLAUSE_RE = re.compile(r"\bprovided,?\s+(?:that|however|further)\b|\bexcept\s+that\b|\bunless\b|\bbut\b|\bhowever\b|\b(?:may|shall|will|can|must)\b",
                            re.IGNORECASE)
# a bracketed aside that gives some items of the list to another group: "(or, in the case of clause (iii), the Required Lenders)"
_REASSIGNS_RE = re.compile(r"\((?=(?:[^()]|\([^()]*\))*\bLenders?\b)(?=(?:[^()]|\([^()]*\))*\b(?:clauses?|in\s+the\s+case\s+of)\b)(?:[^()]|\([^()]*\))*\)",
                           re.IGNORECASE)
# a list marker, "(iii)", and the words that make it a cross-reference instead: "clause (iii)", "Section 6.02(v)"
_MARKER_RE = re.compile(r"\((?P<m>[a-z]|[ivx]{2,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)")
_MARKER_REF_RE = re.compile(r"(?:\bclauses?|\bsections?|\bparagraphs?|\bsub-?clauses?|\bsubsections?|\bitems?)\s*$", re.IGNORECASE)
# words that qualify a list item before it names the release: "(iii) except as provided in the loan documents, the release of ..."
_ITEM_QUALIFIER_RE = re.compile(r"^\s*(?P<q>(?:except|other\s+than|unless|save|subject\s+to)\b[^;]{3,160}?),?\s+(?:(?:the|any|a)\s*)?$", re.IGNORECASE)
_EXCEPTION_WORD_RE = re.compile(r"\b(?:except|other\s+than|unless|save\s+(?:for|as)|subject\s+to)\b", re.IGNORECASE)
# where the list item that names a release ends: the next marker, a semicolon or a full stop
_ITEM_END_RE = re.compile(r";|\.(?!\d)|,?\s+(?:and\s+|or\s+)?\((?:[a-z]|[ivx]{2,5}|[A-Z]|\d{1,2})\)\s")
# the requirement written after the release instead: "... of the Guarantors shall require the consent of all Lenders", "... without the consent of each Lender"
_CONSENT_AFTER_RE = re.compile(r"(?P<gap>(?:[^.;()]|\.(?=\d)){0,80}?)\b(?P<verb>requires?|(?:shall|will)\s+require|without)\s+(?:the\s+)?(?:prior\s+)?"
                               r"(?:written\s+)?" + _CONSENT_OF,
                               re.IGNORECASE)
# ... which is no requirement when it is denied: "the release of X does not require the consent of the Lenders"
_NEGATED_RE = re.compile(r"\b(?:not|no|never|neither|nor|cannot)\b|n[’']t\b", re.IGNORECASE)
# "without the consent of X" is a requirement only where the words before the release forbid it: "no release of ...", "shall not release ..."
# ("the Agent may release the Collateral without the consent of any Lender" says the opposite)
_FORBIDS_RE = re.compile(r"\bno\s+(?:such\s+|other\s+)?$|\b(?:shall|will|may|must|can)\s*not\s+(?:\w+\s+){0,2}$|\bcannot\s+(?:\w+\s+){0,2}$", re.IGNORECASE)
# ... and what may then stand between the release and "without": "no release of X shall be made without the consent of ..."
_PASSIVE_GAP_RE = re.compile(r"^[\s,]*(?:(?:shall|will|may|can|is\s+to|are\s+to)\s+(?:be\s+)?(?:made|effected|given|granted|permitted|allowed|effective|occur|"
                             r"take\s+effect|take\s+place))?[\s,]*$", re.IGNORECASE)
# where the clause that calls for a consent begins: after "except that", a proviso, a semicolon, a list marker
_CLAUSE_START_RE = re.compile(r"\bexcept\s+that\b|\bprovided,?\s+(?:that|however|further)\b|[;:]|\.\s|\b(?:but|unless|however)\b|"
                              r"\((?:[a-z]|[ivx]{2,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)", re.IGNORECASE)
# what joins a second consent to the first in the same clause: "the consent of X, and also the consent of Y, shall be required"
_CO_CONSENT_RE = re.compile(r"\s*,?\s*(?:and|plus|as\s+well\s+as)\s+(?:also\s+)?(?:the\s+)?(?:prior\s+)?(?:written\s+)?", re.IGNORECASE)
# a second group named right after the first: "the consent of the Required Lenders and each affected Lender", "... and the consent of each Lender"
_AND_GROUP_RE = re.compile(r"\s*,?\s*(and|or)\s+(?:also\s+)?(?:(?:the\s+)?(?:prior\s+)?(?:written\s+)?(?:consent|approval)\s+of\s+)?", re.IGNORECASE)
_SECOND_GROUP_RE = re.compile(r"(?:the\s+)?(?:(?:each|all|every|any|other|required|requisite|majority|super-?\s?majority|affected|directly|adversely|and)\s+){0,4}"
                              r"(?-i:Lenders?)\b(?:\s+(?:directly\s+)?(?:and\s+adversely\s+)?affected(?:\s+thereby)?)?", re.IGNORECASE)
# the words just before a later item's marker bring in a verb of their own, so the head of the list no longer governs that item:
# "... shall be required to (i) ... and (ii) ..., but shall not be required to (iii) release ..."
_REGOVERNS_RE = re.compile(r"\b(?:(?:shall|will|may|must|need|can|would|should)(?:\s+not)?|cannot|not)(?:\s+(?:also|only|be|so))*(?:\s+\w+ed)?(?:\s+(?:to|for))?\s*$",
                           re.IGNORECASE)
# "... (iv) the release of the Guarantor from the Guarantee", "releasing all or substantially all of the other Guarantors"
_RELEASE_OF_GUARANTORS_RE = re.compile(
    r"\breleas(?:e|ing)\s+(?:of\s+)?(?P<what>(?:(?!\breleas)[^;.()]){0,90}?\b(?:guarantors?|guarant(?:ees|ies|y|ee))\b"
    r"(?:\s+from\s+(?:the\s+guarant(?:ee|y)|(?:its|their)\s+obligations))?)", re.IGNORECASE)
# "the release of all or substantially all of the Collateral"
_RELEASE_OF_COLLATERAL_RE = re.compile(r"\breleas(?:e|ing)\s+(?:of\s+)?(?P<what>(?:(?!\breleas)[^;.()]){0,60}?\b(?:collateral|transaction\s+security)\b)",
                                       re.IGNORECASE)
# a covenant list item: "...; ERISA; and additional guarantors."
_ADDITIONAL_GUARANTORS_RE = re.compile(
    r"(?:^|[;,]\s*|\band\s+)((?:additional|future|further)\s+(?:subsidiary\s+)?guarantors?(?:\s+and\s+collateral)?)\s*(?=[;.,]|$)", re.IGNORECASE)
# topics of the exceptions to a guarantee requirement, as US term sheets word them
_EXCEPTION_TOPICS = (
    (re.compile(r"prohibited\s+by\s+(?:applicable\s+)?law|"
                r"governmental\s+or\s+regulatory\s+consent", re.IGNORECASE), "legal / regulatory prohibitions or consents"),
    (re.compile(r"financial\s+assistance|corporate\s+benefit", re.IGNORECASE), "corporate benefit / financial assistance"),
    (re.compile(r"non-?\s*wholly[\s-]+owned", re.IGNORECASE), "non-wholly owned subsidiaries"),
    (re.compile(r"controlled\s+foreign\s+corporation|\bCFCs?\b"), "CFCs"),
    (re.compile(r"immaterial\s+subsidiar", re.IGNORECASE), "immaterial subsidiaries"),
    (re.compile(r"unrestricted\s+subsidiar", re.IGNORECASE), "unrestricted subsidiaries"),
    (re.compile(r"\bFSHCOs?\b|foreign\s+subsidiary\s+holding\s+compan", re.IGNORECASE), "foreign subsidiary holding companies"),
    (re.compile(r"joint\s+ventures?", re.IGNORECASE), "joint ventures"),
    (re.compile(r"special\s+purpose", re.IGNORECASE), "special purpose entities"),
    (re.compile(r"captive\s+insurance", re.IGNORECASE), "captive insurance subsidiaries"),
    (re.compile(r"not-?for-?profit", re.IGNORECASE), "not-for-profit subsidiaries"),
    (re.compile(r"securiti[sz]ation|receivables\s+(?:subsidiar|entit)", re.IGNORECASE), "securitisation / receivables subsidiaries"),
    (re.compile(r"Eligible\s+Contract\s+Participant", re.IGNORECASE), "swap obligations of non-Eligible Contract Participants"),
    (re.compile(r"cost[^.;]{0,80}excessive|excessive\s+in\s+relation\s+to", re.IGNORECASE), "cost excessive relative to value (Agent's determination)"),
    (re.compile(r"material\s+adverse\s+tax\s+consequences", re.IGNORECASE), "material adverse tax consequences"),
)
# "subject to certain exclusions consistent with ... and to be mutually agreed, including, but not limited to (a) X; (b) Y; ..."
# (the list must hang on the word "exclusions" / "exceptions" itself: no verb of a new clause may come between it and "including")
# (and the other words by which a list is hung on a noun: "..., which shall include: (a)", "such as (i)", "namely (a)", "as follows: (1)")
_LIST_LEAD_IN = (r"\b(?:including|which\s+(?:shall|will|may)\s+include|such\s+as|namely|consisting\s+of|as\s+follows)\b,?\s*"
                 r"(?:without\s+limitation,?\s*|but\s+not\s+limited\s+to,?\s*)?:?\s*(?=\((?:a|i|1)\)\s)")
_EXCLUSIONS_LIST_RE = re.compile(
    r"\b(?:exclusions|exceptions)\b(?:(?!\b(?:shall|will|must|may|which|is|are)\b)[^.;:()]){0,160}?" + _LIST_LEAD_IN, re.IGNORECASE)
_LIST_LEAD_IN_RE = re.compile(r",?\s+" + _LIST_LEAD_IN, re.IGNORECASE)
# "any immaterial subsidiary (to be defined as any designated subsidiary that does not account for more than ...)", '“Immaterial Subsidiary” means ...'
_IMMATERIAL_RE = re.compile(
    r"\b(?P<term>immaterial\s+subsidiar(?:y|ies))\s*[”\"]?\s*(?:\(\s*(?P<bracket>(?:to\s+be\s+)?defined\s+as|being|meaning|i\.e\.,?)\s+|"
    r"(?P<means>means|shall\s+mean|will\s+mean|is\s+defined\s+as|(?:is\s+|are\s+)?to\s+be\s+defined\s+as)\s+)", re.IGNORECASE)
# the text does carve parties out of the guarantee requirement
_HAS_EXCEPTIONS_RE = re.compile(r"\bexceptions?\b|\bexclud\w+|shall\s+not\s+(?:be\s+required|include)|shall\s+be\s+required\s+to\s+guarantee", re.IGNORECASE)

# what a coverage test or a materiality threshold is measured on
_METRIC = r"(?:EBITDA|assets|revenues?|turnover|sales|earnings)"
# coverage: guarantors "constituting >80% of revenue, EBITDA, and assets", "representing not less than 80% of EBITDA"
# (a level put as a shortfall - "represent less than 85% of ..." - is the same test seen from the other side: it is found, and
# given only in the term sheet's own words)
_COVERAGE_RE = re.compile(
    r"\b(?P<verb>constitut\w+|represent\w*|account\w*\s+for|compris\w+|contribut\w+|generat\w+)\s+(?:in\s+(?:the\s+)?aggregate\s+)?"
    r"(?P<cmp>(?:at\s+least|not\s+less\s+than|no\s+less\s+than|more\s+than|greater\s+than|a\s+minimum\s+of|in\s+excess\s+of|(?P<short>less\s+than|below|"
    r"under))\s+|[>≥]\s*=?\s*)?"
    r"(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?P<base>(?:[^.;]{0,50}?\b" + _METRIC + r"\b)+)", re.IGNORECASE)
# the same test worded round the guarantors' figures instead of a verb of theirs: "the aggregate EBITDA of the Guarantors shall be not less
# than 80% of Consolidated EBITDA", "EBITDA attributable to the Loan Parties must exceed 75% of ..." (given only in the term sheet's own words)
_COVERAGE_OF_RE = re.compile(
    r"(?<!non-)(?<!non )\b(?:guarantors|obligors|loan\s+parties|credit\s+parties)\b[’']?(?:(?!\bnon-?\s?guarant)[^.;]){0,80}?\b(?:is|are|be|being|equals?|equal\s+to|exceeds?|"
    r"exceeding|falls?|fall)\s+(?:or\s+exceeds?\s+)?(?:at\s+least\s+|not\s+less\s+than\s+|no\s+less\s+than\s+|more\s+than\s+|greater\s+than\s+|in\s+excess\s+of\s+|"
    r"a\s+minimum\s+of\s+|equal\s+to\s+or\s+(?:greater|more)\s+than\s+|less\s+than\s+|below\s+)?(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
    r"(?P<base>(?:[^.;]{0,50}?\b" + _METRIC + r"\b)+)", re.IGNORECASE)
# coverage the other way round: "total assets or revenues of non-guarantying subsidiaries may not exceed 20% of ..."
_NON_GUARANTOR_CAP_RE = re.compile(
    r"\b" + _METRIC + r"\b[^.;]{0,80}?\bnon-?\s?guarant\w+[^.;]{0,60}?\b(?:may|shall|will)\s+not\s+exceed\s+\d{1,3}(?:\.\d+)?\s*%[^.;]*", re.IGNORECASE)
# '“Material Subsidiary” means ... ' (the test that decides which subsidiaries must guarantee)
# (the term may carry a word or two of its own between "Material" and "Subsidiary": "Material Domestic Subsidiary", "Material Foreign Subsidiary")
_MATERIAL_DEFINITION_RE = re.compile(
    r"(?<![A-Za-z])(?P<term>Material\s+(?:(?-i:[A-Z])[\w.\-\x01]*\s+){0,2}(?:Subsidiar(?:y|ies)|Compan(?:y|ies)))\s*[”\"]?\s+"
    r"(?P<verb>means|shall\s+mean|will\s+mean|is\s+defined\s+as|to\s+be\s+defined\s+as|is|are)\b(?P<body>(?:[^.]|\.(?=\d)){10,800})", re.IGNORECASE)
# wording in such a definition that the rules cannot turn into "measure >= N% of base" without risk of changing what it says: a
# limb about several subsidiaries together, a test put in the negative, a pairing by "respectively", a figure that measures
# something other than the subsidiary (the price of an acquisition)
_THRESHOLD_UNSAFE_RE = re.compile(r"\b(?:together|aggregat\w+|collectively|combined|respectively|less\s+than|fewer|lower|below|not|other\s+than|except\w*|"
                                  r"unless|acqui\w+|consideration|average)\b", re.IGNORECASE)
# the words that tie a percentage to the subsidiary's own size where no measure is named before the comparison: "accounts for more than 5% of ..."
_SIZE_VERB_RE = re.compile(r"\b(?:account\w*\s+for|represent\w*|contribut\w+|constitut\w+|compris\w+|generat\w+|ha(?:s|ve|ving)|own\w*|hold\w*)\b[^.;]{0,40}$",
                           re.IGNORECASE)
# a figure in a definition: a percentage or an amount of money
_FIGURE_RE = re.compile(r"\d\s*%|[$€£]\s?\d|\b(?:USD|EUR|GBP)\s?\d")
# a sentence that puts a figure on what is "material" (or "immaterial"), whatever its wording
_MATERIAL_FIGURE_RE = re.compile(r"\b(?:im)?material\w*\b(?:[^.;]|\.(?=\d)){0,240}?(?:\d\s*%|[$€£]\s?\d)|"
                                 r"(?:\d\s*%|[$€£]\s?\d)(?:[^.;]|\.(?=\d)){0,240}?\b(?:im)?material\w*\b", re.IGNORECASE)
# LMA wording of the same threshold, with the comparison after the figure: "EBITDA representing 5% or more of Consolidated EBITDA"
_THRESHOLD_OR_MORE_RE = re.compile(
    r"(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s+or\s+more\s+of\s+(?:the\s+)?(?P<base>[^.;,()]{3,90}?)"
    r"(?=\s+(?:for\s+such|for\s+the|as\s+of|(?:or|and)\s+(?:\(|whose\b|which\b|that\b|has\b|have\b)|determined|on\s+a)|[.;,()]|$)", re.IGNORECASE)
# the subject of a percentage is one subsidiary, not the guarantors as a body: "any subsidiary which", "each member of the Group that"
_EACH_SUBSIDIARY_RE = re.compile(
    r"\b(?:each|any|every|an?|such)\s+(?:[\w\-,]+\s+){0,6}?(?:subsidiar(?:y|ies)|member\s+of\s+the\s+group|compan(?:y|ies)|entit(?:y|ies)|person)\b[^.;]{0,50}$",
    re.IGNORECASE)
# the sentence says how a coverage level is tested: "at all times", "tested annually", "on each Test Date", "shall ensure"
_TESTED_RE = re.compile(r"\btest(?:ed|ing|s)?\b|\bat\s+all\s+times\b|\beach\s+(?:financial\s+|fiscal\s+)?(?:year|quarter)\b|\bannual(?:ly)?\b|\bquarterly\b|"
                        r"\bsemi-?\s?annual(?:ly)?\b|\bshall\s+(?:ensure|procure|maintain)\b|\bcompliance\s+certificate\b|\bby\s+reference\s+to\b",
                        re.IGNORECASE)
# the words that open a proviso, dropped when its clause is quoted on its own: "provided that", "provided, however, that"
_PROVISO_LEAD_RE = re.compile(r"^(?:and\s+)?provided,?\s+(?:(?:however|further),?\s+)?(?:that,?\s+)?", re.IGNORECASE)
# "... equal to or greater than 10% of the consolidated total revenues of the Company and its subsidiaries"
_THRESHOLD_RE = re.compile(
    r"(?P<cmp>equal\s+to\s+or\s+greater\s+than|greater\s+than\s+or\s+equal\s+to|at\s+least|not\s+less\s+than|in\s+excess\s+of|more\s+than|greater\s+than|"
    r"exceed(?:s|ing)?|≥|>=|>)\s*(?:(?:either|both)\s+)?(?:\((?:a|i|x|1|A)\)\s*)?(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:the\s+)?(?P<base>[^.;,()]{3,90}?)"
    r"(?=\s+(?:for\s+such|for\s+the|as\s+of|(?:or|and)\s+(?:\(|\d|whose\b|which\b|that\b|has\b|have\b)|determined|on\s+a)|[.;,()]|$)", re.IGNORECASE)
# a further limb of the same comparison: "... greater than or equal to either (a) 5% of X or (b) 5% of Y"
_THRESHOLD_NEXT_RE = re.compile(
    r"\s*,?\s*(?P<join>or|and)\s+(?:\((?:b|c|ii|iii|y|z|2|3|B|C)\)\s*)?(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s+of\s+(?:the\s+)?(?P<base>[^.;,()]{3,90}?)"
    r"(?=\s+(?:for\s+such|for\s+the|as\s+of|(?:or|and)\s+(?:\(|\d|whose\b|which\b|that\b|has\b|have\b)|determined|on\s+a)|[.;,()]|$)", re.IGNORECASE)
# the measure a threshold applies to, as worded before it: "total revenues", "consolidated total assets"
_METRIC_NAME_RE = re.compile(r"(?:consolidated\s+)?(?:total\s+|gross\s+|net\s+)?(?:revenues?|"
                             r"assets|EBITDA|turnover|sales|net\s+income|earnings)", re.IGNORECASE)
# "materiality thresholds to be consistent with those set forth in the Existing Credit Agreement"
_MATERIALITY_REF_RE = re.compile(r"materiality\s+thresholds?\s+(?:to\s+be\s+|will\s+be\s+|shall\s+be\s+)?[^.;()]{5,120}", re.IGNORECASE)
# "material, wholly-owned, domestic subsidiaries", "each material subsidiary" (lower case: not a defined term)
_MATERIAL_UNDEFINED_RE = re.compile(r"\bmaterial\b[\w ,\-]{0,50}?\bsubsidiar(?:y|ies)\b")
# ", respectively," (often broken by layout: "res pectively")
_RESPECTIVELY_RE = re.compile(r",?\s*res\s?pectively\s*,?\s*", re.IGNORECASE)

# the cell says there is no security
_UNSECURED_RE = re.compile(
    r"\b(?:will|shall|is\s+to|to)\s+be\s+unsecured\b|\bis\s+unsecured\b|^\W*unsecured\b|"
    r"^\W*no\s+(?:security|collateral)\b(?!\s+(?:other|interest|shall|will|over|in)\b)",
    re.IGNORECASE)
# a bare statement that there is no security, with nothing else in it: "Unsecured.", "None", "The Facility will be unsecured"
_PLAIN_UNSECURED_RE = re.compile(
    r"^\W*(?:(?:the\s+)?(?:[\w\-]+\s+){0,3}?(?:facilit\w+|loans?|obligations|notes)\s+)?(?:(?:will|shall|is|are|is\s+to|are\s+to|to)\s+)?(?:be\s+)?"
    r"(?:(?:senior\s+)?unsecured|none|nil|n/?a|not\s+applicable)\W*$", re.IGNORECASE)
# the cell says in so many words that there is no security: "Unsecured", "None", "No security will be provided",
# "The Facilities will not be secured", "Not applicable - unsecured facility", "without security"
# ("unsecured" counts only where it is said of the facility: "... and unsecured hedging obligations will be secured by ..." is not it)
_NO_SECURITY_RE = re.compile(
    r"^\W*(?:senior\s+)?unsecured\b|\b(?:be|is|are|remains?)\s+(?:senior\s+)?unsecured\b|\bunsecured\s+(?:basis|facilit(?:y|ies))\b|"
    r"^\W*(?:none|nil|n/?a|not\s+applicable)\b|\bno\s+(?:security|collateral|liens?|guarantees?\s+or\s+security)\b|"
    r"\bnot\s+(?:be\s+|to\s+be\s+)?secured\b|\bwithout\s+(?:any\s+)?(?:security|collateral)\b", re.IGNORECASE)
# ... unless it goes on to make exceptions, which is how a negative pledge reads: "No Security shall be created other than Permitted Security"
_EXCEPT_FOR_RE = re.compile(r"\b(?:other\s+than|except|save\s+(?:for|as)|unless|Permitted\s+(?:Security|Liens?|Encumbrances?))\b", re.IGNORECASE)
# words by which a cell grants or describes security
_GRANT_RE = re.compile(
    r"\bsecured\b|\bsecurity\s+(?:interests?|over|package|documents?|agreements?)\b|\bliens?\b|\bpledge[sd]?\b|\bcharges?\b|\bmortgages?\b|\bdebentures?\b|"
    r"(?<!cash )\bcollateral\b|\b(?:first|second)[\s-]*(?:priority|ranking|lien)\b|\bperfected\b|\bto\s+secure\b|\bhypothec\w*|"
    r"\bassignments?\s+(?:of|by\s+way)\b|"
    r"\ball[\s-]+assets?\b|\bsubstantially\s+all\s+(?:of\s+)?(?:the\s+|its\s+|their\s+)?(?:tangible\s+and\s+intangible\s+)?(?:assets|property)\b", re.IGNORECASE)
# after such words, a statement that (another) facility is not secured: "...; the Bridge Facility will be unsecured"
_ALSO_UNSECURED_RE = re.compile(r"\b(?:will|shall|to|is|are)\s+(?:be\s+)?unsecured\b|\bnot\s+(?:be\s+)?secured\b", re.IGNORECASE)
# security that is only to be given if something happens later: "Springing: ...", "upon a Ratings Downgrade, the Borrower shall grant ..."
_SPRINGING_RE = re.compile(
    r"\bspringing\b|\b(?:upon|if|in\s+the\s+event|following|after|at\s+such\s+time\s+as)\b[^.;]{0,140}?\b(?:ratings?|downgrade\w*|trigger\w*|ceas\w+|fail\w*|"
    r"exceed\w*|falls?|defaults?|breach\w*)\b", re.IGNORECASE)
# "... shall be secured by (a) a perfected first-priority security interest in ..."
_SECURED_BY_RE =re.compile(r"\b(?:(?:shall|will|to)\s+be\s+)?secured\s+by\s+", re.IGNORECASE)
# where the description of the collateral stops: ", with exclusions ...", ", in each case pursuant to ..."
_COLLATERAL_TAIL_RE = re.compile(r",\s+(?:with\s+exclusions?|in\s+each\s+case,?\s+pursuant|pursuant\s+to|as\s+more\s+fully|all\s+as)\b", re.IGNORECASE)
# a lead-in followed by a lettered list: "... in all of the following (the “Collateral”): (a) ...; (b) ..."
_LIST_START_RE = re.compile(r":\s*(?=\((?:a|i|1)\)\s)")
# the lead-in of a list of what is left out: "The Collateral shall exclude the following", "... shall not include", "... other than"
_EXCLUDES_LEAD_RE = re.compile(r"\b(?:exclud\w+|exclusions?|not\s+include|other\s+than|except(?:\s+for)?)\b[^.;:]{0,60}$", re.IGNORECASE)
# one item: its marker and its text
_ITEM_RE = re.compile(r"^\((\w{1,5})\)\s+(.*)$")
# where an item starts on a line of packed items: at the head of the line, or after the "; " that ends the item before
_ITEM_START_RE = re.compile(r"(?:^|; )\(\w{1,5}\)\s")
# where a long clause may be carried on to the next line: before a list marker joined by "and" / "or" or set off by a comma, or at a semicolon
_CHUNK_RES = (
    re.compile(r",?\s+(?:and|or)\s+(?=\((?:[a-z]|[ivx]{2,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)\s)"),
    re.compile(r"[,;]\s+(?=\((?:[a-z]|[ivx]{2,5}|[A-Z]|[IVX]{2,4}|\d{1,2})\)\s)"),
    re.compile(r";\s+"),
)
# detail that follows the head of a list item: ", including, but not limited to, machinery ..."
_ITEM_TAIL_RE = re.compile(r",?\s+(?:including|but\s+excluding|excluding|other\s+than|described\s+in\s+clauses?)\b", re.IGNORECASE)
# "... liens and security interests in all of the following"
_FOLLOWING_RE = re.compile(r"\b(?:in|on|over)\s+(?:all\s+of\s+)?the\s+following\b", re.IGNORECASE)
# exclusions from the collateral
_EXCLUSION_RES = (
    re.compile(r"with\s+an?\s+exclusion\s+of\s+(?P<x>[^();.,]{3,80})", re.IGNORECASE),  # "with an exclusion of all real property"
    re.compile(r"\bexcluding\s+(?P<x>[^();.]{3,140})", re.IGNORECASE),  # 'but excluding the property defined as “Excluded Property” in ...'
    re.compile(r"with\s+(?P<x>exclusions\s+and\s+limitations\s+[^();.,]{3,100})", re.IGNORECASE),  # "with exclusions and limitations consistent with ..."
    re.compile(r"\bcollateral\s+(?:shall|will)\s+(?:not\s+include|"
               r"exclude)\s+(?P<x>[^.]{3,220})", re.IGNORECASE),  # "the Collateral shall exclude (i) real property, ..."
)
# where a captured exclusion stops: ", collectively, the “Collateral”", ", in each case ..."
_EXCLUSION_END_RE = re.compile(r",\s+(?:collectively|together|(?:and\s+)?in\s+each\s+case)\b", re.IGNORECASE)
# "a pledge of 65% of the voting capital stock and 100% of the other capital stock of each such first-tier foreign subsidiary"
# ... and "(limited, in the case of foreign subsidiaries, to 65% of the voting capital stock)"
# ... and "to a pledge of 65% of the capital stock of each such controlled foreign corporation", "a pledge of 100% of the capital stock of the
# Borrower's domestic subsidiaries (...) and 65% of the voting capital stock of any foreign subsidiaries" (what follows is read to the end of its clause)
_PLEDGE_LIMIT_RE = re.compile(r"\b(?P<lead>pledge\s+of|limited\b[^();.]{0,80}?\bto)\s+(?P<x>(?P<pct>\d{1,3})\s*%\s+of\s+(?:the\s+|all\s+)*"
                              r"(?:voting\s+|issued\s+|outstanding\s+)*(?:capital\s+stock|equity\s+interests?|equity|shares|stock)\b)", re.IGNORECASE)
# whose shares a pledge limit is about, as the clause that sets the limit says it: "(limited, in the case of each entity that is a
# “controlled foreign corporation” ..., to a pledge of 65% of ...", "limited in the case of foreign subsidiaries to 65% of ..."
_PLEDGE_SCOPE_RE = re.compile(r"\blimited\b,?\s*in\s+the\s+case\s+of\s+(?P<whose>(?:[^();.]|(?-i:(?<=[A-Z]))\.){3,240}?),?\s*to\s+(?:an?\s+)?(?:pledge\s+of\s+)?$",
                              re.IGNORECASE)
# the list of what is left out of the collateral: "the Collateral shall exclude the following: (i) ...; (ii) ...", "shall not include (a) ..."
# (whatever short lead-in stands between the verb and the first item: "the following:", "any of:", "the following assets (collectively, ...):";
# or under a name of its own: "Excluded Assets shall mean (a) ...", "Excluded Property includes: (i) ...")
_EXCLUDED_LIST_RE = re.compile(
    r"(?:\bcollateral\s+(?:(?:shall|will|does|do)\s+(?:also\s+)?(?:not\s+include|exclude)|excludes)\b|"
    r"\bexcluded\s+(?:assets?|property|collateral)\b[”\"]?\s*(?:means?|includes?|consists?\s+of|(?:shall|will)\s+(?:mean|include|consist\s+of))\b)"
    r"[^.;()]{0,60}?[:,]?\s*(?=\((?:a|i|1)\)\s)", re.IGNORECASE)
# a section about the release of the collateral, under a label of its own: "Release of Collateral:", "Collateral Release:",
# "Release of Collateral and Reinstatement of Collateral:", "Collateral Fall-Away:"
# (and the same headings where they also name the guarantees: "Release of Guarantees and Collateral:", "Guarantee and Collateral Release:")
_RELEASE_LABELS = (
    r"release\s+of\s+(?:the\s+)?(?:guarant(?:ees?|ors?|ies|y)\s+and\s+)?(?:collateral|security|liens)(?:\s+and\s+guarant(?:ees?|ors?|ies|y))?"
    r"(?:\s+and(?:\s+reinstatement(?:\s+of\s+(?:the\s+)?(?:collateral|security|liens))?)?)?",
    r"(?:guarant(?:ees?|ors?|y)\s+and\s+)?(?:collateral|security|liens?)(?:\s+and\s+guarant(?:ees?|ors?|y))?\s+(?:release|fall-?\s?away)(?:\s+(?:events?|date|provisions?|"
    r"conditions?))?",
    r"release\s+and\s+reinstatement\s+of\s+(?:the\s+)?(?:collateral|security|liens)",
    r"fall-?\s?away\s+of\s+(?:the\s+)?(?:collateral|security|liens)",
)
# the operative words of such a section, in the active or the passive: "the Agent shall release the liens", "the liens shall be released"
_RELEASES_RE = re.compile(r"\b(?:shall|will|may)\s+(?:be\s+)?(?:automatically\s+)?releas(?:e|ed)\b|\bfall[\s-]?away\b", re.IGNORECASE)
# "perfected first-priority security interest", "first priority (subject to ...) liens and security interests"
_FIRST_PRIORITY_RE = re.compile(
    r"(?:perfected\s+)?first[\s-]*(?:priority|ranking|lien)(?:\s+perfected)?\s+(?:\([^()]*\)\s+)?(?:liens?(?:\s+and\s+security\s+interests?)?|"
    r"security(?:\s+interests?)?|pledges?|mortgages?|charges?)", re.IGNORECASE)
# "payments and proceeds of collateral shall be applied first to the Facility"
_APPLIED_FIRST_RE = re.compile(r"(?:payments\s+and\s+)?proceeds\s+of\s+(?:the\s+)?collateral\s+(?:shall|"
                               r"will)\s+be\s+applied\s+first\s+to\s+[^.;()]{3,60}", re.IGNORECASE)

# a cash collateral requirement written into the Facility row: "Borrower will be required to post cash collateral in an amount equal to ..."
_CASH_COLLATERAL_RE = re.compile(r"\b(?:[A-Z]\w+\s+)?(?:will|shall)\s+be\s+(?:required|obliged|"
                                 r"obligated)\s+to\s+post\s+cash\s+collateral\b[^.;]{0,420}", re.IGNORECASE)
# "Same, except that ..." (the proposed column of an amendment)
_SAME_EXCEPT_RE = re.compile(r"\bSame,?\s+except\s+(?:that\s+)?$", re.IGNORECASE)
# the line already says the facility is secured
_SAYS_SECURED_RE = re.compile(r"secur|\bliens?\b|pledge|mortgage|\bcharges?\b", re.IGNORECASE)
# the ranking words that open the description of a facility
_RANK_WORDS = (r"\b(?P<rank>super[\s-]?senior(?:\s+secured)?|super[\s-]?priority|senior\s+secured|senior\s+unsecured|senior\s+subordinated|subordinated|senior|"
               r"unsecured|secured|first[\s-]lien|second[\s-]lien|junior)\s+")
# how a facility is described: "senior unsecured revolving credit facility", "Senior Secured Revolving Credit Facility"
_DESCRIBED_RE = re.compile(_RANK_WORDS + r"(?P<rest>(?:[\w\-]+\s+){0,6}?(?:facilit(?:y|ies)|revolver|RCF))\b", re.IGNORECASE)
# the last cell of a table row of figures: "$1,000", "150", "3.5x", "25%"
_FIGURE_CELL_RE = re.compile(r"^[$€£]?\s?\(?\d[\d,.]*\)?\s?(?:x|%|mm|m|bn|k)?$", re.IGNORECASE)
# ... or, failing a "facility", as loans: "senior secured term loans"
_DESCRIBED_LOANS_RE = re.compile(_RANK_WORDS + r"(?P<rest>(?:[\w\-]+\s+){0,4}?(?:term\s+loans?|loans?))\b", re.IGNORECASE)
# ... when it is another facility that is being described: "to refinance the existing senior secured term loans"
_OTHER_DEBT_RE = re.compile(r"\b(?:existing|refinanc\w+|repa(?:y|id|yment)|prepa(?:y|id|yment)|replac\w+)\b[^.;]{0,40}$", re.IGNORECASE)
# '(the “364-Day Facility”)' right after the description
_FACILITY_TERM_RE = re.compile(r"^\s*\((?:the|each,?\s+an?|collectively,?\s+the)\s+[“\"]\s*"
                               r"(?P<term>[^”\"]{0,40}(?:Facilit(?:y|ies)|Revolver|RCF|Loans?))\s*[”\"]")
# a presentation that labels the revolver in passing: "First Lien RCF", "first-lien revolving credit facility"; a chart
# label may wrap ("First Lien" at the end of one line, "RCF" at the start of the next)
_LIEN_LABEL_RE = re.compile(r"\b(?P<lien>first[ \-]+lien)(?P<gap>[ ]{1,3}|[ ]*\n[ ]*)(?P<what>RCF|revolver|revolving(?:[ ]+credit)?[ ]+facilit(?:y|ies))(?=\d?\b)",
                            re.IGNORECASE)
# the document also has term debt of its own kind: "Term Loan B", "Term Facility", "TLB"
_TERM_DEBT_RE = re.compile(r"\bterm\s+loans?\b|\bterm\s+(?:loan\s+)?facilit(?:y|ies)\b|\bTL[AB]\b", re.IGNORECASE)
# signs that the facility is secured, checked before deriving "unsecured" from indirect evidence
_SECURED_SIGN_RE = re.compile(
    r"\bthe\s+Collateral\b|\bCollateral\s+(?:Agent|Documents?|Trustee)\b|\bSecurity\s+(?:Agent|Trustee|Documents?|Agreements?|Principles|Package)\b|"
    r"\bTransaction\s+Security\b|\bSecured\s+(?:Parties|Obligations|Creditors)\b|\bIntercreditor\s+Agreement\b|"
    r"(?i:\b(?:perfected\s+)?first[\s-]+(?:priority|ranking|lien)\s+(?:perfected\s+)?(?:liens?|security|pledges?|mortgages?|charges?)|"
    r"\bperfected\s+(?:liens?|security\s+interests?)|\b(?:will|shall|to)\s+be\s+secured\s+(?:by|on)\b|"
    r"\b(?:senior|super\s+senior)\s+secured\s+(?:revolving|credit|term|facilit)|\b(?:first|second)[\s-]+lien\b|"
    r"\bshare\s+(?:pledges?|charges?)\b|\bdebentures?\b)")
# basis for a derived "unsecured": "... will rank at least pari passu ... with its other unsecured indebtedness"
_PARI_PASSU_RE = re.compile(
    r"rank\s+(?P<least>at\s+least\s+)?pari\s+passu[^.;]{0,100}?\bwith\s+(?P<tail>[^.;]{0,60}?\bunsecured\s+(?:and\s+unsubordinated\s+)?"
    r"(?:indebtedness|debt|obligations|creditors))", re.IGNORECASE)
# basis for a derived "unsecured": "based on the Parent’s long-term senior unsecured non-credit-enhanced debt ratings"
_UNSECURED_RATING_RE = re.compile(
    r"(?:based\s+(?:up)?on|determined\s+by(?:\s+reference\s+to)?|"
    r"by\s+reference\s+to)\s+[^.;]{0,80}?\bsenior\s+unsecured\b[^.;]{0,60}?\bratings?", re.IGNORECASE)
# ranking words in the prose of a "Ranking" section (hyphens already turned into spaces; "unsubordinated" must not count)
_RANK_IN_PROSE_RE = re.compile(r"\bsuper ?senior\b|\bsuper ?priority\b|\bsenior secured\b|\bsenior unsecured\b|\bsenior subordinated\b|"
                               r"\b(?:first|second) (?:lien|ranking)\b|\bsubordinated\b|\bsenior\b")
# ... which are not the facility's own ranking when they are denied ("will not be subordinated", "no senior")
_RANK_NEGATED_RE = re.compile(r"\b(?:not|no|never|nor|neither|without)\s+(?:(?:be|rank|become|are|is|being|otherwise|contractually|expressly|effectively|"
                              r"structurally|in any way)\s+){0,3}$")
# ... or describe other debt the facility is compared with ("pari passu with all other", "senior to the", "behind the", "holders of the")
_RANK_COMPARED_RE = re.compile(
    r"\b(?:with|to|behind|than|over|after|against|below|above|of|ahead of|priority to)\s+"
    r"(?:(?:the|all|any|its|their|other|existing|future|present|such|each|certain|[\w’']+[’']s)\s+){0,4}(?:and\s+(?:the\s+)?)?$")

# an entity defined by a bracket: ... (the “Company”), (“APi” or the “Company”), (together with X, the “Borrowers” or the “Company”)
_DEFINED_AS = r"\(\s*(?P<inner>[^()]{0,90}?)[“\"]\s*%s\s*[”\"](?P<post>[^()]{0,80})\)"
# the role named between a party and its defining bracket: "Aon plc, as parent (the “Parent”)"
_ROLE_TAIL_RE = re.compile(r",?\s+as\s+(?:the\s+)?(?:ultimate\s+)?(?:parent|borrower|guarantor|holdings|company|issuer)(?:\s+\w+){0,3}$", re.IGNORECASE)
# a short name given to a party: Capri Holdings Limited (“Capri”)
_SHORT_NAME_RE = re.compile(r"(?P<pre>[^()“”\"]{2,160})\(\s*[“\"]\s*(?P<short>[A-Z][\w.&\- ]{1,30}?)\s*[”\"]\s*\)")
# "(together with Carnival Corporation, the ..." inside such a bracket
_TOGETHER_WITH_RE = re.compile(r"together\s+with\s+(?P<name>[A-Z][^,()“\"]{2,60}),")
# a company above the borrower that is referred to but may never be named: "the Parent", "Parent and its subsidiaries", “Holdings”
_PARENT_USED_RE = re.compile(r"\bthe\s+Parent\b|\bParent\s+(?:and|shall|will|or)\b|[“\"]\s*Holdings\s*[”\"]")
# words that can make up a company name: capitalised words, "(USA)", "&", "plc"
_NAME_WORD_RE = re.compile(r"^(?:[A-Z0-9][\w&’'.\-]*|\([A-Z][A-Za-z.]{1,14}\)|&|plc|p\.l\.c\.),?$")
# small words allowed between the capitalised words of a name ("Bank of America")
_NAME_GLUE = {"of", "de", "du", "van", "der", "la", "&"}
# corporate suffixes: the only words a comma may precede inside a name ("Delta Air Lines, Inc.")
_NAME_SUFFIX_RE = re.compile(r"^(?:Inc|Incorporated|LLC|L\.L\.C|Ltd|Limited|L\.P|LP|LLP|Corp|Corporation|"
                             r"N\.A|plc|PLC|S\.A|N\.V|B\.V|GmbH|AG|SE|Co|Company|S\.p\.A)\.?,?$")
# capitalised words that start a sentence or name a role, not a company
_NOT_A_NAME = {"The", "Each", "And", "Or", "By", "With", "Between", "Among", "If", "To", "In", "As", "From", "For", "That", "Both", "Either", "When", "Where",
               "While", "Subject", "Notwithstanding", "Additionally", "Initially", "Collectively", "Together", "Borrower", "Borrowers", "Company", "Parent",
               "Guarantor", "Guarantors", "Holdings", "Facility", "Agreement", "Lender", "Lenders", "Agent", "Summary", "Terms", "Conditions"}
# where a company's name ends and the clause saying where it was formed begins, when no "a ... company" comes between:
# "X GmbH, organized under the laws of ...", "X Limited incorporated in ..."
_FORMED_RE = re.compile(r",?\s+(?:(?:duly\s+)?(?:incorporated|organi[sz]ed|formed|registered|established|constituted|domiciled)|existing)\s+"
                        r"(?:and\s+\w+\s+)?(?:under|in|pursuant)\b", re.IGNORECASE)
# where the name that opens a party row ends: ", a ...", " (the “Parent”)", " incorporated in ...", ";", " - "
_NAME_END_RE = re.compile(r",\s+(?:an?|as|which|being|having|the|and|or|together)\b|\s*\(|;|\s+(?:(?:duly\s+)?incorporated|organi[sz]ed|registered|established|"
                          r"formed|existing|and\s+(?:its|each|any|certain)|or\s+(?:its|any))\b|\s+[-–]\s+|$")
# lower-case pieces of a legal form inside a name: "S.à r.l.", "p.l.c.", "s.r.o.", "d.o.o."
_LEGAL_FORM_WORD_RE = re.compile(r"^(?:[a-zà-ÿ]\.){1,4}[a-zà-ÿ]?\.?,?$|^(?:à|plc|oyj)$")
# words that open a party row without naming anyone
_NOT_A_PARTY = {"none", "n/a", "tbd", "tbc", "tba", "same", "see", "not", "no", "yes", "any", "all", "certain", "such", "its", "one", "to", "funds",
                "affiliates", "customary", "usual", "substantially", "initially", "guaranteed", "unsecured", "secured", "senior"}
# "X, a Delaware corporation", "X, a Bermuda exempted company", "X, a Panamanian corporation", "X, a Maryland real estate investment trust"
_PLACE_THEN_TYPE_RE = re.compile(
    r"^an?\s+(?P<place>[A-Z][\w.]*(?:\s+[A-Z][\w.]*){0,3})\s+(?:(?:exempted|public|private|limited|liability|general|statutory|business|stock|"
    r"registered|designated|activity|real|estate|investment|national|banking|holding|joint|non-?profit|professional|master)\s+)*"
    r"(?:corporation|company|partnership|trust|bank|association|société|societe|LLC|L\.L\.C\.|LP|L\.P\.)\b")
# "X, a public limited company incorporated under the laws of Ireland", "organized under the laws of the State of Delaware"
_UNDER_LAWS_RE = re.compile(
    r"(?i:incorporated|organi[sz]ed|formed|registered|established|existing|constituted|"
    r"domiciled)\s+(?i:and\s+(?:registered|existing|organi[sz]ed|incorporated)\s+)?"
    r"(?i:under|in|pursuant\s+to)\s+(?i:and\s+governed\s+by\s+)?(?:the\s+)?(?i:laws?\s+of\s+)?(?:the\s+)?"
    r"(?:(?:Federal\s+|People[’']s\s+)?(?:State|Commonwealth|Republic|Kingdom|Province|Grand\s+Duchy|Bailiwick|Island)\s+of\s+)?(?:the\s+)?"
    r"(?P<place>[A-Z][A-Za-z]*(?:\s+(?:and\s+|of\s+)?[A-Z][A-Za-z]*){0,3})")
# capitalised words that follow a place name without being part of it: "incorporated in Ireland Company number ..."
_NOT_A_PLACE = {"Company", "Corporation", "Number", "No", "With", "Having", "Registered", "Registration", "Whose", "Under", "And", "Reg", "Tax",
                "Its", "Which", "Acting", "Represented", "Being", "Together", "Each", "Such"}
# jurisdictions the rules recognise by name: US states (reported as "United States - <state>"), the parts of the United
# Kingdom, adjectives ("a Panamanian corporation") and the countries term sheets most often name
_US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia",
    "Wisconsin", "Wyoming", "District of Columbia"}
_UK_PARTS = {"England and Wales", "England", "Wales", "Scotland", "Northern Ireland"}
_DEMONYMS = {
    "Panamanian": "Panama", "Bermudian": "Bermuda", "Bermudan": "Bermuda", "Irish": "Ireland", "English": "England and Wales", "Scottish": "Scotland",
    "Dutch": "Netherlands", "Swiss": "Switzerland", "German": "Germany", "French": "France", "Canadian": "Canada", "Luxembourgish": "Luxembourg",
    "Liberian": "Liberia", "Marshallese": "Marshall Islands", "Norwegian": "Norway", "Swedish": "Sweden", "Danish": "Denmark", "Italian": "Italy",
    "Spanish": "Spain", "Japanese": "Japan", "Australian": "Australia", "Singaporean": "Singapore", "Mexican": "Mexico", "Brazilian": "Brazil",
    "Belgian": "Belgium", "Cypriot": "Cyprus", "Maltese": "Malta", "Bahamian": "Bahamas", "Caymanian": "Cayman Islands"}
_PLACES = {
    "Ireland", "Bermuda", "Panama", "Cayman Islands", "British Virgin Islands", "Luxembourg", "Netherlands", "Switzerland", "Germany", "France", "Canada",
    "Liberia", "Marshall Islands", "Norway", "Sweden", "Denmark", "Italy", "Spain", "Japan", "Australia", "Singapore", "Mexico", "Brazil", "Belgium", "Cyprus",
    "Malta", "Bahamas", "Jersey", "Guernsey", "England", "Scotland", "England and Wales", "United Kingdom", "Hong Kong", "Israel", "India", "Curaçao"}
# governing law: "State of New York.", "English law", "governed by ... the laws of the State of New York"
_LAW_FIRST_RE = re.compile(
    r"^\W*(?:The\s+)?(?:[Ll]aws?\s+of\s+)?(?:the\s+)?(?P<law>State\s+of\s+[A-Z]\w+(?:\s+[A-Z]\w+)?|"
    r"[A-Z]\w+(?:\s+(?:and\s+)?[A-Z]\w+)?(?:\s+law)?)(?=\s*(?:[.;,(]|$)|\s+(?:and|will|shall|to|with|governs?|applies)\b)")
_LAW_GOVERNED_RE = re.compile(
    r"governed\s+by[^.;]{0,100}?\blaws?\s+of\s+(?:the\s+)?(?P<law>State\s+of\s+[A-Z]\w+(?:\s+[A-Z]\w+)?|[A-Z]\w+(?:\s+and\s+[A-Z]\w+)?)")


# ---------------------------------------------------------------------------------------------------
# Text tools
# ---------------------------------------------------------------------------------------------------

def _cap(text: str) -> str:
    """First letter in upper case (the rest untouched)."""
    return text[:1].upper() + text[1:] if text else text


def _lower_first(text: str) -> str:
    """Lower the first letter of a clause that is being joined to another ("All present ..." -> "all present ...")."""
    if len(text) > 1 and text[0].isupper() and (text[1].islower() or text.startswith("A ")):
        return text[0].lower() + text[1:]
    return text


def _join_hyphens(text: str) -> str:
    """Close the gap layout extraction leaves beside a hyphen ("first -priority"), except after a rating ("BBB- by")."""
    def join(m: re.Match) -> str:
        return m.group(0) if _RATING_TOKEN_RE.match(m.group(1)) else f"{m.group(1)}-{m.group(2)}"
    return _HYPHEN_GAP_RE.sub(join, text)


def _clean(text: str) -> str:
    """Running text without the gaps layout extraction leaves around hyphens, brackets and punctuation."""
    text = _join_hyphens(tidy(text))
    text = re.sub(r"\s+(’s\b|[,.;:)”])", r"\1", text)
    return re.sub(r"([(“])\s+", r"\1", text)


def _undefine(text: str) -> str:
    """Drop the brackets that only introduce or point to defined terms."""
    return _DEFINES_RE.sub("", _AS_DEFINED_RE.sub("", text))


def _percent(text: str) -> str:
    """ "80 per cent. of" -> "80% of" (LMA wording), so that one set of patterns reads both styles."""
    return _PER_CENT_RE.sub(r"\1%", text)


def _wordy(text: str, need: int = 2) -> bool:
    """The text has at least ``need`` real words (not just punctuation, markers or a stray letter)."""
    return len(re.findall(r"[A-Za-z]{3,}", text or "")) >= need


def _no_brackets(text: str) -> str:
    """Drop bracketed asides (nested ones too) but keep list markers such as (a) and (ii)."""
    kept: list[str] = []

    def hide(m: re.Match) -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    text = _ENUM_RE.sub(hide, text)
    for _ in range(5):
        stripped = re.sub(r"\s*\([^()]*\)", "", text)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    return re.sub(r"\s+([,.;:])", r"\1", tidy(text))


def _sentences(text: str) -> list[str]:
    """Sentences and list items; company suffixes ("Inc.", "N.V.") and initials do not end a sentence."""
    masked = _ABBR_RE.sub(lambda m: m.group(1) + "\x01", text)
    masked = _ABBR_END_RE.sub(".", masked)
    return [s.replace("\x01", ".").strip() for s in _SENTENCE_RE.split(masked) if s.strip()]


def _whole_sentences(text: str) -> list[str]:
    """Sentences, with a list kept in the sentence that opens it: "... if (a) X; (b) Y; and (c) Z, then ..." is one sentence, though
    _sentences ends one at each "; (b)" and ". (ii)". An item is joined on only where its marker follows one already in the sentence."""
    out: list[str] = []
    for s in _sentences(text):
        item = _LATER_ITEM_RE.match(s)
        if out and item:
            label = re.search(r"\((\w+)\)", item.group(0)).group(1)
            earlier = {mark for _, _, mark in _item_markers(out[-1])}
            if any(_marker_before(label, style) in earlier for style in ("roman", "letter", "number")):
                out[-1] = out[-1].rstrip(" .;,") + "; " + s
                continue
        out.append(s)
    return out


def _orphan_item(sentence: str) -> bool:
    """The "sentence" is a later item of a list whose opening is not with it ("(b) no Default exists; and (c) ..."): it cannot stand alone."""
    item = _LATER_ITEM_RE.match(sentence)
    return bool(item) and re.search(r"\((\w+)\)", item.group(0)).group(1) not in ("a", "i", "1", "A", "I")


def _later_items(sents: list[str]) -> list[str]:
    """The later items of a list that the first sentence of a cell opens: "... by (i) X" is followed by "(ii) Y" and "and (iii) Z",
    which sentence splitting has made sentences of their own (it ends one at each "; (ii)" and ". (b)"). [] if it opens no list."""
    if not sents or not re.search(r"\((?:a|i|1|A|I)\)\s", sents[0]):
        return []
    seen = {mark for _, _, mark in _item_markers(sents[0])}
    out: list[str] = []
    for s in sents[1:]:
        item = _LATER_ITEM_RE.match(s)
        label = re.search(r"\((\w+)\)", item.group(0)).group(1) if item else ""
        if not item or not any(_marker_before(label, style) in seen for style in ("roman", "letter", "number")):
            break  # not an item, or not the next item of this list
        out.append(s.strip().rstrip(".;, "))
        seen |= {mark for _, _, mark in _item_markers(s)}
    return out


def _fit(text: str, limit: int = LINE_LIMIT) -> str:
    """Cut at a clause boundary (failing that, a word boundary) so the line is at most ``limit`` characters."""
    text = tidy(text).strip(" ,;:")
    if text.endswith(".") and not _ENDS_ABBREVIATED_RE.search(text):
        text = text[:-1].rstrip(" ,;:")
    if len(text) <= limit:
        return text
    cut = text[: max(1, limit - 2)]
    stop = max(cut.rfind(", "), cut.rfind("; "), cut.rfind(" and "), cut.rfind(" or "))
    if stop < int(limit * 0.6):
        stop = cut.rfind(" ")
    if stop <= 0:
        stop = len(cut)
    kept = cut[:stop].rstrip(" ,;:(")
    whole = _DANGLING_RE.sub("", kept).rstrip(" ,;:(")  # do not stop on a lead-in ("..., which shall include …")
    if len(whole) >= int(limit * 0.4):
        kept = whole
    return kept + " …"


def _line(text: str, limit: int = LINE_LIMIT) -> str:
    """A passage as a house-style line: defined-term brackets dropped, amounts restyled, fitted to ``limit``."""
    return _fit(squeeze(_undefine(_clean(text)), 100_000), limit)


def _pack(pieces: list[str], limit: int = MAIN_LIMIT, joiner: str = "; ") -> list[str]:
    """Join short pieces into as few lines as fit (a piece that follows another on a line loses its capital, unless it is a label)."""
    lines: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if lines and len(lines[-1]) + len(joiner) + len(piece) <= limit:
            lines[-1] += joiner + (piece if ": " in piece[:40] else _lower_first(piece))
        else:
            lines.append(piece)
    return lines


def _norm(text: str) -> str:
    """Letters and digits only, lower case: for comparing two wordings of the same thing."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _only_refers(text: str) -> bool:
    """The cell gives no detail of its own: it points to another document or to later agreement.

    It must open with the pointer ("Same as the Existing Credit Agreement", "To be agreed") or say next to nothing before it. A
    pointer that only qualifies a description ("Each material domestic subsidiary, subject to exceptions to be agreed",
    "..., with exclusions customary for facilities of this type") leaves the substance of the row on the page.
    """
    if len(text) > 220:
        return False
    if _REFERS_RE.match(text):
        return True
    pointer = points_elsewhere(text) if len(text) <= 140 else None
    return pointer is not None and len(re.findall(r"[A-Za-z]{3,}", text[:pointer.start()])) <= 3


# ---------------------------------------------------------------------------------------------------
# The document as the rules read it: cells, running text, quotes
# ---------------------------------------------------------------------------------------------------

_MEMO: "weakref.WeakKeyDictionary[Ctx, dict]" = weakref.WeakKeyDictionary()


def _memo(ctx: Ctx) -> dict:
    """Per-document cache for the readings several rules share (running text, cells, the top company)."""
    try:
        return _MEMO.setdefault(ctx, {})
    except TypeError:  # an object that cannot be weakly referenced: work without the cache
        return {}


def _running(ctx: Ctx) -> set[str]:
    """Short lines repeated at the top or foot of most pages (classification banners, document ids, running titles)."""
    memo = _memo(ctx)
    if "running" not in memo:
        by_page: dict[int, list[str]] = {}
        for ln in ctx.raw.lines:
            if not ln.blank:
                by_page.setdefault(ln.page, []).append(tidy(ln.text))
        seen: dict[str, int] = {}
        for texts in by_page.values():
            for t in set(texts[:3] + texts[-4:]):
                if len(t) <= 60:
                    seen[t] = seen.get(t, 0) + 1
        need = max(3, (len(ctx.raw.pages) + 1) // 2)
        memo["running"] = {t for t, n in seen.items() if n >= need}
        # the same line with a page number in it ("Confidential 2 Arranger Inc."): alike on every page but for its digits
        shapes: dict[str, int] = {}
        for texts in by_page.values():
            for shape in {re.sub(r"\d+", "#", t) for t in texts[:3] + texts[-4:] if len(t) <= 80 and re.search(r"\d", t)}:
                shapes[shape] = shapes.get(shape, 0) + 1
        memo["running_shapes"] = {s for s, n in shapes.items() if n >= need}
    return memo["running"]


def _page_furniture(ctx: Ctx, text: str) -> bool:
    """A running header or footer: a page number, a banner, or a short line that recurs at the head or foot of most pages."""
    t = tidy(text)
    return is_footer(text) or t in _running(ctx) or re.sub(r"\d+", "#", t) in _memo(ctx).get("running_shapes", ())


def _over_page(ctx: Ctx, block: Block) -> Block:
    """Carry a section on over a page break at which the block reader stopped.

    A running header or footer that the block reader does not know as one ("Confidential 2 Arranger Inc.", the company's
    name at the head of each page) sits in the label column, so it ends the block as a new label would. The section
    is carried on only where both signs agree: its text breaks off in the middle of a sentence at the foot of the page,
    and the next page, after its running lines, begins in the value column. It then runs, as on any page, until a line
    returns to the label column.
    """
    if block.mode != "column" or len(block.lines) < 2:
        return block
    lines, parts = list(block.lines), list(block.parts)
    label_indent = _label_line(block).indent
    deeper = [ln.indent for ln in lines if not ln.blank and ln.indent >= label_indent + 10]
    if not deeper:
        return block  # no clear value column to follow
    value_col = min(deeper)
    doc = ctx.doc
    while len(lines) < 400:
        text = tidy(" ".join(p for p in parts if p))
        if not text or re.search(r"[.;:!?][”\"’')\]]*$", text):
            break  # the section ends on a finished sentence: nothing says that it goes on
        n = lines[-1].n + 1
        page = lines[-1].page
        while n < len(doc.lines) and doc.lines[n].page == page and (doc.lines[n].blank or _page_furniture(ctx, doc.lines[n].text)):
            n += 1
        if n >= len(doc.lines) or doc.lines[n].page == page:
            break  # the block ended before the foot of the page
        page = doc.lines[n].page
        while n < len(doc.lines) and doc.lines[n].page == page and (doc.lines[n].blank or _page_furniture(ctx, doc.lines[n].text)):
            n += 1
        if n >= len(doc.lines) or doc.lines[n].page != page or doc.lines[n].indent < value_col - 3:
            break  # the next page opens with a label (or with nothing): the sentence was simply left unfinished
        added = 0
        while n < len(doc.lines) and doc.lines[n].page == page:
            cur = doc.lines[n]
            n += 1
            if cur.blank or _page_furniture(ctx, cur.text):
                continue
            if cur.indent < value_col - 3 and cur.indent <= label_indent + 6:
                break
            lines.append(cur)
            parts.append(cur.text[cur.qstart:].strip() if cur.qstart and cur.indent >= cur.qstart else cur.text.strip())
            added += 1
        if not added:
            break
    if len(lines) == len(block.lines):
        return block
    return Block(label=block.label, line=block.line, lines=lines, parts=parts, inline=block.inline, mode=block.mode)


def _page_title(text: str) -> bool:
    """A short line set wholly in capitals, as the title at the head of a page is: "PRICING GRID", "ANNEX A - CONDITIONS PRECEDENT"."""
    t = tidy(text)
    letters = re.sub(r"[^A-Za-z]", "", t)
    if not 6 <= len(letters) or len(t) > 70 or not letters.isupper() or t.endswith((":", ",", ";")):
        return False
    return len(re.findall(r"[A-Z]{2,}", t)) >= 2 or len(letters) >= 8


def _stop_at_page_start(ctx: Ctx, block: Block) -> Block:
    """Cut a section back to the foot of a page where what follows on the next page is not its continuation.

    A section runs on over a page break when the next page begins in the value column. Two things found there are the
    start of something else: a title in capitals (the heading of an annex or a pricing grid), and, after text that
    stopped without a full stop, a word that opens a sentence ("The", "If", "Each" - the cell above simply carried no
    full stop; a sentence that really runs on does not resume with a capitalised article or conjunction).
    """
    if block.mode != "column":
        return block
    for i in range(1, len(block.lines)):
        if block.lines[i].page == block.lines[i - 1].page:
            continue
        j = i
        while j < len(block.lines) and (block.lines[j].blank or _page_furniture(ctx, block.lines[j].text)):
            j += 1
        if j >= len(block.lines):
            break
        first = block.lines[j].text.strip()
        before = tidy(" ".join(p for p in block.parts[:i] if p and not _page_furniture(ctx, p)))
        unfinished = bool(before) and not re.search(r"[.;:!?][”\"’')\]]*$", before)
        if _page_title(first) or (unfinished and _PAGE_OPENER_RE.match(first)):
            return Block(label=block.label, line=block.line, lines=block.lines[:i], parts=block.parts[:i], inline=block.inline, mode=block.mode)
    return block


def _vocabulary(ctx: Ctx) -> dict[str, int]:
    """How often each word occurs in the document (lower case)."""
    memo = _memo(ctx)
    if "vocabulary" not in memo:
        counts: dict[str, int] = {}
        for ln in ctx.raw.lines:
            for word in re.findall(r"[A-Za-z]+", ln.text):
                counts[word.lower()] = counts.get(word.lower(), 0) + 1
        memo["vocabulary"] = counts
    return memo["vocabulary"]


def _mend(ctx: Ctx, text: str) -> str:
    """Rejoin words that layout extraction broke in two ("obligat ions"), judged by the document's own vocabulary:
    the joined word is used elsewhere in the document and one of the pieces is not a word it uses."""
    vocab = _vocabulary(ctx)

    def join(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        whole = (a + b).lower()
        if len(whole) >= 5 and vocab.get(whole, 0) >= 2 and (vocab.get(a.lower(), 0) <= 1 or vocab.get(b.lower(), 0) <= 1):
            return a
        return m.group(0)

    return _BROKEN_WORD_RE.sub(join, text)


def _flow(ctx: Ctx) -> tuple[str, list[int]]:
    """The whole document as cleaned running text (the proposed view), and the offset at which each page starts."""
    memo = _memo(ctx)
    if "flow" not in memo:
        running = _running(ctx)
        per_page: dict[int, list[str]] = {}
        marks: dict[int, list[tuple[int, int]]] = {}  # per page: (offset in the page's uncleaned text, line number) of each line
        for ln in ctx.doc.lines:
            if ln.blank or is_footer(ln.text):
                continue
            t = tidy(ln.text)
            if t not in running and not _page_furniture(ctx, ln.text):
                marks.setdefault(ln.page, []).append((sum(len(x) + 1 for x in per_page.get(ln.page, [])), ln.n))
                per_page.setdefault(ln.page, []).append(t)
        chunks, starts, pos = [], [], 0
        scale: dict[int, float] = {}  # per page: length of the uncleaned text over the length of the cleaned text
        for page in range(1, len(ctx.raw.pages) + 1):
            raw = " ".join(per_page.get(page, []))
            chunk = _percent(_mend(ctx, _clean(raw)))
            scale[page] = len(raw) / max(1, len(chunk))
            starts.append(pos)
            chunks.append(chunk)
            pos += len(chunk) + 1
        memo["flow"] = (" ".join(chunks), starts)
        memo["flow_lines"] = (marks, scale)
    return memo["flow"]


def _line_near(ctx: Ctx, offset: int) -> int | None:
    """The number of the source line that holds (to within a line or two) character ``offset`` of the running text."""
    starts = _flow(ctx)[1]
    marks, scale = _memo(ctx).get("flow_lines", ({}, {}))
    page = _page_of(ctx, offset)
    target = (offset - starts[page - 1]) * scale.get(page, 1.0)
    found = None
    for at, n in marks.get(page, []):
        if at > target:
            break
        found = n
    return found


def _page_of(ctx: Ctx, offset: int) -> int:
    """The page (1-based) that holds character ``offset`` of the running text."""
    return max(1, bisect.bisect_right(_flow(ctx)[1], offset))


def _quote_text_near(ctx: Ctx, pattern: str, page: int, target: int, reach: int = 2) -> dict | None:
    """As Ctx.quote_text, but only a source line within ``reach`` lines of line ``target`` is quoted (the nearest one)."""
    rx = re.compile(pattern, re.IGNORECASE)
    best: tuple[int, dict] | None = None
    for ln in ctx.doc.lines:
        if ln.blank or ln.page != page or abs(ln.n - target) > reach or not rx.search(ln.text):
            continue
        quote = tidy(ln.text[ln.qstart:] if ln.qstart else ln.text)
        if len(quote) > MAX_QUOTE_CHARS:
            m = rx.search(quote)
            quote = clip(quote[max(0, m.start() - 60):], MAX_QUOTE_CHARS) if m else ""
        if len(quote) >= 8 and ctx.raw.has_quote(quote, ln.page) and (best is None or abs(ln.n - target) < abs(best[0] - target)):
            best = (ln.n, {"quote": quote, "page": ln.page})
    return best[1] if best else None


def _quote_words(ctx: Ctx, phrase: str, page: int | None = None, tail_first: bool = False, near: int | None = None) -> dict | None:
    """Evidence for a phrase found in the running text: the source line that holds the start of it (or, ``tail_first``, the end).

    ``near`` is the offset of the phrase in the running text. Where the same words stand in more than one place on the
    page (the amendments section and the participations paragraph both speak of releasing the collateral), the line
    quoted is the one at that place, not the first on the page.
    """
    words = re.findall(r"[A-Za-z0-9]+", phrase or "")
    words = words[-16:] if tail_first else words[:16]
    pages = [page] if page else None
    target = _line_near(ctx, near) if near is not None and page else None
    if target is not None:
        for size in (7, 5, 4, 3):
            starts = range(max(0, len(words) - size + 1))
            for i in (reversed(starts) if tail_first else starts):
                try:
                    found = _quote_text_near(ctx, r"\W+".join(re.escape(w) for w in words[i:i + size]), page, target) if len(words) >= size else None
                except re.error:
                    found = None
                if found:
                    return found
    for size in (7, 5, 4, 3, 2):
        if len(words) < size or (size == 2 and len(words) > 2):  # two words identify a line only when they are the whole phrase
            continue
        starts = range(len(words) - size + 1)
        for i in (reversed(starts) if tail_first else starts):
            try:
                found = ctx.quote_text(r"\W+".join(re.escape(w) for w in words[i:i + size]), pages)
            except re.error:
                found = None
            if found:
                return found
    return None


def _quote_line(ctx: Ctx, line) -> dict | None:
    """Evidence that is one whole source line (label and value), for values too short to quote on their own ("None.")."""
    words = tidy(line.text).split() if line is not None else []
    if not words:
        return None
    try:
        return ctx.quote_text(r"\s+".join(re.escape(w) for w in words), [line.page])
    except re.error:
        return None


def _quote(ctx: Ctx, block: Block | None, phrase: str | None = None) -> dict | None:
    """Evidence cut from ``block`` around ``phrase`` (matched word by word, so layout noise does not matter)."""
    if block is None:
        return None
    try:
        words = re.findall(r"[A-Za-z0-9]+", phrase or "")[:7]
        for size in (len(words), 4, 2):
            if 0 < size <= len(words):
                found = ctx.quote(block, r"\W*".join(re.escape(w) for w in words[:size]))
                if found:
                    return found
        return ctx.quote(block) or _quote_line(ctx, _label_line(block))
    except (re.error, IndexError, AttributeError):
        return None


@dataclass
class _Cell:
    """The value of a labelled section, ready to read."""
    text: str  # cleaned value text ("" when an amendment cell only says "Same as existing" and the existing text is not available)
    block: Block  # where quotes are cut from
    unchanged: bool = False  # an amendment table marks the term as the same as the existing one
    mixed: bool = False  # existing and proposed terms run together in the text (their columns could not be separated)


def _label_line(block: Block):
    """The line of ``block`` that carries its label (a centred label is not on the first line)."""
    word = (block.label.split() or [""])[0].lower()
    hits = [ln for ln in block.lines[:16] if word and ln.text.strip().lower().startswith(word)]
    return min(hits, key=lambda ln: ln.indent) if hits else block.line


def _mid_clause(text: str) -> bool:
    """The text beside a label reads as the middle of a sentence: the cell started on a line above."""
    if not text:
        return False
    close, open_ = text.find(")"), text.find("(")
    return text[0].islower() or text[0] in ",;)" or (close >= 0 and (open_ < 0 or close < open_))


def _own_row(block: Block, pattern: str) -> Block:
    """Cut a block back to its own row when it has swallowed the rows around it.

    In a table whose labels carry no colon, blocks.py takes the label of the row below (or above) for a
    wrapped piece of this label, so the value runs across several rows. A neighbouring line that opens
    with a capitalised label of its own and has its own value beside it is another row, unless the
    label before it is plainly unfinished ("Permitted liens &"). (A narrow table read without columns runs on to the
    foot of the page in the same way.)
    """
    if block.mode not in ("column", "plain"):
        return block
    try:
        rx = re.compile(r"^(?:" + pattern + r")$", re.IGNORECASE)
    except re.error:
        return block
    margin = min((ln.indent for ln in block.lines if not ln.blank), default=0)  # the label column
    at = next((i for i, ln in enumerate(block.lines[:8])
               if ln.indent <= margin + 1 and (c := fragments(ln.text, 3)) and rx.match(c[0][2].strip())), None)
    if at is None:
        return block  # a label with a colon, or one that shares its line differently: blocks.py reads those as they are
    row = block.lines[at]
    cells = fragments(row.text, 3)
    if len(cells) < 2:
        return block  # the label stands on a line of its own

    def another_row(line, label_before: str) -> bool:
        c = fragments(line.text, 3)
        return (len(c) >= 2 and abs(line.indent - row.indent) <= 1 and c[0][2][:1].isupper() and not c[0][2].rstrip().endswith(":")
                and not _UNFINISHED_LABEL_RE.search(label_before))

    start = at
    while start > 0:
        above = block.lines[start - 1]
        above_cells = fragments(above.text, 3)
        if another_row(above, above_cells[0][2] if above_cells else ""):
            break
        start -= 1
    end = at + 1
    label_so_far = cells[0][2]
    while end < len(block.lines):
        if another_row(block.lines[end], label_so_far):
            break
        below_cells = fragments(block.lines[end].text, 3)
        if below_cells and abs(block.lines[end].indent - row.indent) <= 1:
            label_so_far = below_cells[0][2]
        end += 1
    if start == 0 and end == len(block.lines):
        return block
    lines, parts = block.lines[start:end], block.parts[start:end]
    return Block(label=tidy(cells[0][2]), line=lines[0], lines=lines, parts=parts, inline=False, mode="column")


def _recentre(doc, block: Block) -> Block:
    """Rebuild a table cell whose label is centred vertically beside it.

    blocks.py reads such a cell only when the text beside the label starts in lower case, stops at a
    bulleted first line (the bullet sits left of the wrapped text) and then runs on into the cell
    below. Here the cell is the lines above the label up to the previous row, and about as many below.
    """
    if block.mode != "column":
        return block
    ln = _label_line(block)
    cells = fragments(ln.text, 3)
    if len(cells) < 2:
        return block
    col = cells[1][0]
    if not _mid_clause(ln.text[col:].strip()):
        return block
    above = []
    k = ln.n - 1
    while k >= 0 and len(above) < 12:
        prev = doc.lines[k]
        if prev.blank or prev.page != ln.page or prev.indent < col - 6 or is_footer(prev.text) or _AMEND_HEADER_RE.search(prev.text):
            break
        above.insert(0, prev)
        k -= 1
    if not above:
        return block
    below = []
    k = ln.n + 1
    while k < len(doc.lines) and len(below) <= len(above):
        nxt = doc.lines[k]
        if nxt.blank or nxt.page != ln.page or nxt.indent < col - 6 or is_footer(nxt.text):
            break
        below.append(nxt)
        k += 1
    lines = above + [ln] + below
    parts = [x.text.strip() for x in above] + [ln.text[col:].strip()] + [x.text.strip() for x in below]
    return Block(label=block.label, line=lines[0], lines=lines, parts=parts, inline=False, mode="column")


def _cell_text(ctx: Ctx, block: Block) -> str:
    """The value text of a block, cleaned: running footers dropped, layout gaps closed, broken words rejoined."""
    running = _running(ctx)
    parts = [tidy(p) for p in block.parts]
    return _percent(_mend(ctx, _clean(" ".join(p for p in parts if p and p not in running and not _page_furniture(ctx, p)))))


def _amendment_page(ctx: Ctx, page: int) -> bool:
    """The page prints existing and proposed terms (whether or not the two columns could be separated)."""
    memo = _memo(ctx).setdefault("amendment_pages", {})
    if page not in memo:
        head = [ln.text for ln in ctx.raw.page_lines(page) if not ln.blank][:8]
        memo[page] = page in ctx.split_pages or any(_AMEND_HEADER_RE.search(t) for t in head)
    return memo[page]


def _twin(ctx: Ctx, block: Block) -> Block | None:
    """The same row in the existing column of an amendment table."""
    pattern = re.escape(block.label)
    try:
        found = find_blocks(ctx.existing, pattern)
    except re.error:
        return None
    target = _label_line(block).n
    for b in found:
        b = _own_row(b, pattern)
        if _label_line(b).n == target or b.line.n == block.line.n:
            return b
    return None


def _read(ctx: Ctx, block: Block, pattern: str = "") -> _Cell:
    """A block as a cell: its own row, re-centred, with "Same as existing" resolved against the existing column."""
    if pattern:
        block = _own_row(block, pattern)
    block = _stop_at_page_start(ctx, _over_page(ctx, block))
    cell_block = _recentre(ctx.doc, block)
    text = _cell_text(ctx, cell_block)
    if block.page in ctx.split_pages and SAME_AS_EXISTING_RE.match(text):
        twin = _twin(ctx, block)
        if twin is None:
            return _Cell("", cell_block, True)
        cell_block = _recentre(ctx.existing, twin)
        text = _cell_text(ctx, cell_block)
        return _Cell("" if SAME_AS_EXISTING_RE.match(text) else text, cell_block, True)
    if _amendment_page(ctx, block.page):
        m = _SAME_TAIL_RE.search(text)
        if m:
            return _Cell(text[:m.start()].rstrip(), cell_block, True)
        return _Cell(text, cell_block, mixed=block.page not in ctx.split_pages)
    return _Cell(text, cell_block)


def _mixed_note(cells: list[_Cell]) -> str:
    """Reviewer note for a row read from a page whose existing and proposed columns came out as one run of text."""
    if any(c.mixed for c in cells):
        return "This page prints existing and proposed terms side by side and the two columns could not be separated: check the line against the page."
    return ""


def _existing_text(ctx: Ctx, cell: _Cell) -> str:
    """Text of the existing column for a cell read from the proposed column ("" if there is none)."""
    if cell.unchanged or cell.block.page not in ctx.split_pages:
        return ""
    twin = _twin(ctx, cell.block)
    return _cell_text(ctx, _recentre(ctx.existing, twin)) if twin is not None else ""


def _cells(ctx: Ctx, patterns: tuple[str, ...], limit: int = 3, sections: bool = False) -> list[_Cell]:
    """The sections whose label matches any of ``patterns``, in document order (each section once).

    ``sections`` keeps to the term sheet's own rows: a lettered item of a longer section ("(c) Guarantees - ...") or a
    bullet of a covenant list ("• Guarantees: restrictions on ...") has the right label but is about what the group may
    do, not about the support the facility has.
    """
    found: dict[int, tuple[Block, str]] = {}
    for pattern in patterns:
        try:
            blocks = ctx.blocks(pattern)
        except re.error:
            continue
        for block in blocks:
            if block is not None and block.text:
                found.setdefault(block.line.n, (block, pattern))
    picked = [found[n] for n in sorted(found)]
    if sections:
        picked = [(b, p) for b, p in picked if b.mode != "enum" and not (b.inline and _COVENANT_WORDING_RE.match(b.text))]
        if any(not b.inline for b, _ in picked):
            picked = [(b, p) for b, p in picked if not b.inline]
    out = []
    for block, pattern in picked:
        cell = _read(ctx, block, pattern)
        if len(cell.block.label.split()) > 7:
            continue
        if sections and _COVENANT_CELL_RE.match(cell.text):
            continue  # an undertaking that happens to be headed "Security" or "Guarantees" (LMA covenant rows)
        out.append(cell)
        if len(out) >= limit:
            break
    return out


def _with_evidence(lines: list[str], evidence: list, note: str = "") -> dict:
    """A not_stated entry that still shows what the term sheet does say (the schema allows this for a few rows)."""
    entry = not_stated(note=note)
    clean = [tidy(x) for x in lines if x and tidy(x)]
    if clean:
        entry["lines"] = clean[:8]
    seen: set[str] = set()
    for e in evidence:
        if e and e.get("quote") and e["quote"] not in seen and len(entry["evidence"]) < 3:
            seen.add(e["quote"])
            entry["evidence"].append({"quote": e["quote"], "page": e["page"]})
    return entry


def _guard(rule):
    """A rule never raises: a failure is reported in the note, in the form the engine itself uses."""
    def guarded(ctx: Ctx) -> dict:
        try:
            return rule(ctx)
        except Exception as exc:  # noqa: BLE001 - one awkward document must not stop the run
            return not_stated(note=f"The rule for this row failed ({type(exc).__name__}: {exc}).")
    guarded.__name__ = rule.__name__
    guarded.__doc__ = rule.__doc__
    return guarded


# ---------------------------------------------------------------------------------------------------
# Parties: the top company and where it is incorporated
# ---------------------------------------------------------------------------------------------------

def _tail_name(text: str) -> str:
    """The company name that ends ``text`` ("... by Accenture plc" -> "Accenture plc"), or ""."""
    tokens = text.split()
    out: list[str] = []
    for tok in reversed(tokens):
        if _ENUM_RE.fullmatch(tok.rstrip(",")):
            break  # a list marker, "(ii)", not part of a name like "(USA)"
        if tok in _NAME_GLUE:
            if not out:
                break
            out.insert(0, tok)
            continue
        if not _NAME_WORD_RE.match(tok):
            break
        if tok.endswith(",") and not (out and _NAME_SUFFIX_RE.match(out[0])):
            break  # a comma belongs to a name only before Inc. / LLC / Ltd.
        out.insert(0, tok)
    while out and (out[0] in _NAME_GLUE or out[0] in _NOT_A_NAME):
        out.pop(0)
    name = re.sub(r"(?:’s|'s)$", "", " ".join(out).strip(" ,"))
    words = name.split()
    if len(words) < 2 or len(name) > 90 or all(_NAME_SUFFIX_RE.match(w) or w in _NOT_A_NAME for w in words):
        return ""
    return name


def _split_descriptor(pre: str) -> tuple[str, str]:
    """("Granite Construction Incorporated", "a Delaware corporation") from the text before a defining bracket."""
    pre = _ROLE_TAIL_RE.sub("", pre.strip(" ,;:")).strip(" ,;:")
    cut = max(pre.rfind(", a "), pre.rfind(", an "))
    if cut > 0:
        name = _tail_name(pre[:cut])
        if name:
            return name, pre[cut + 2:].strip()
    formed = list(_FORMED_RE.finditer(pre))  # "X GmbH, organized under the laws of Germany": the name ends where that clause starts
    if formed:
        name = _tail_name(pre[:formed[-1].start()])
        return (name, pre[formed[-1].start():].strip(" ,")) if name else ("", "")
    return _tail_name(pre), ""


def _leading_name(text: str) -> tuple[str, str]:
    """(name, the words after it) for a party row that opens with a company name the stricter parser does not accept:
    a legal form it does not know ("Nordic Topco S.à r.l., a private limited liability company ...") or a single word."""
    text = text.strip()
    end = _NAME_END_RE.search(text)
    name = (text[:end.start()] if end else text).rstrip(" ,;:")
    if name.endswith(".") and not _ENDS_ABBREVIATED_RE.search(name):
        name = name[:-1]
    words = name.split()
    if not 1 <= len(words) <= 8 or len(name) > 90 or not (name[0].isupper() or name[0].isdigit()):
        return "", ""
    if words[0].strip(",.") in _NOT_A_NAME or words[0].strip(",.").lower() in _NOT_A_PARTY or all(w.strip(",.") in _NOT_A_NAME for w in words):
        return "", ""
    if not all(w[0].isupper() or w[0].isdigit() or w in _NAME_GLUE or _LEGAL_FORM_WORD_RE.match(w) for w in words):
        return "", ""
    return name, (text[end.start():].lstrip(" ,;:") if end else "")


def _row_party(cell: _Cell) -> tuple[str, str]:
    """(name, descriptor) of the company a party row names ("Parent: Aon plc, a public limited company ..."), or ("", "")."""
    first = (_sentences(_undefine(cell.text[:400])) or [""])[0].strip(" .")
    name, desc = _split_descriptor(first) if ", a" in first else (_tail_name(first), "")
    if name and _norm(first).startswith(_norm(name)):
        return name, desc
    return _leading_name((_sentences(cell.text[:400]) or [""])[0])


def _related_company(pre: str) -> str:
    """A second company named just before a defining bracket, as the owner of the one the passage is about:
    "X, a Delaware corporation and a wholly-owned subsidiary of Acme Holdings plc (the “Parent”)" -> "Acme Holdings plc"."""
    pre = _ROLE_TAIL_RE.sub("", pre.strip(" ,;:")).strip(" ,;:")
    tail = _tail_name(pre)
    at = pre.rfind(tail) if tail else -1
    if at <= 0:
        return ""
    owner = re.search(r"\b(?:subsidiar(?:y|ies)|affiliate|division|branch)\s+of\s+$|\b(?:owned|controlled|held)\s+(?:(?:directly|indirectly|or|and)\s+)*by\s+$",
                      pre[:at], re.IGNORECASE)
    return tail if owner else ""


def _defined_in(text: str, term: str, row_label: str = "") -> list[tuple[str, str]]:
    """(name, descriptor) of the entities a passage defines as ``term``; a "together with X" inside the bracket adds X.

    ``row_label`` is the label of the row the passage is in. Where two companies stand before the bracket ("X, a ...
    subsidiary of Y (the “Parent”)"), a parent-type term in a row that is about another role (the Borrower row) names
    the owner, Y, which the bracket follows: X is not offered as the top company with its place of incorporation.
    """
    rx = re.compile(r"(?P<pre>[^()“”\"]{2,240})" + _DEFINED_AS % re.escape(term).replace(r"\ ", r"\s+"))
    out: list[tuple[str, str]] = []
    for m in rx.finditer(text):
        inner = m.group("inner") + " " + m.group("post")
        if re.search(r"\bTarget\b|\beach\b", inner):
            continue  # an acquisition target, or a class of entities ("each, a “Borrower”")
        name, desc = _split_descriptor(m.group("pre"))
        owner = _related_company(m.group("pre"))
        own_row = bool(row_label) and _norm(term) in _norm(row_label)  # "(the “Borrower”)" in the Borrower row names the row's own party
        if owner and owner != name and not own_row and re.search(r"parent|holdings|topco", term, re.IGNORECASE):
            name, desc = owner, ""
        together = _TOGETHER_WITH_RE.search(m.group("inner"))
        if together:
            other = _tail_name(together.group("name"))
            if other and other != name:
                out.append((other, ""))
        if name:
            out.append((name, desc))
    return out


def _defined_on_pages(ctx: Ctx, term: str) -> list[tuple[str, str]]:
    """As _defined_in, read line by line from the page text (for definitions outside any labelled section)."""
    rx = re.compile(_DEFINED_AS % re.escape(term).replace(r"\ ", r"\s+"))
    for text in ctx.raw.pages:
        for m in rx.finditer(text):
            if re.search(r"\bTarget\b|\beach\b", m.group("inner") + " " + m.group("post")):
                continue
            lines = text[max(0, m.start() - 400):m.start()].split("\n")
            cell = re.split(r"\s{3,}", lines[-1].rstrip())[-1] if lines[-1].strip() else ""
            name, desc = _split_descriptor(cell)
            if (not name or _norm(name) == _norm(cell)) and len(lines) > 1:
                prev = lines[-2].rstrip()
                if len(prev.strip()) >= 60 and not prev.endswith((".", ":", ";")):  # the name may have wrapped from the line above
                    wrapped = _split_descriptor(re.split(r"\s{3,}", prev)[-1] + " " + cell)
                    name, desc = wrapped if wrapped[0] else (name, desc)
            owner = _related_company(cell)  # "... a subsidiary of Y (the “Parent”)": the bracket names the owner
            if owner and owner != name and re.search(r"parent|holdings|topco", term, re.IGNORECASE):
                name, desc = owner, ""
            if name:
                return [(name, desc)]
    return []


def _party_cells(ctx: Ctx) -> list[_Cell]:
    """The rows that introduce the parties: Parent / Holdings / Company, Borrower(s), Guarantor(s)."""
    memo = _memo(ctx)
    if "party_cells" not in memo:
        memo["party_cells"] = (_cells(ctx, _PARENT_LABELS + _COMPANY_LABELS, 3) + _cells(ctx, _BORROWER_LABELS, 3)
                               + _cells(ctx, _GUARANTOR_LABELS, 3, sections=True))
    return memo["party_cells"]


def _defined(ctx: Ctx, term: str) -> list[tuple[str, str]]:
    """(name, descriptor) of the entities defined as ``term``: in the party rows first, else anywhere on the pages."""
    for cell in _party_cells(ctx):
        found = _defined_in(cell.text, term, cell.block.label)
        if found:
            return found
    return _defined_on_pages(ctx, term)


def _group_parent(ctx: Ctx) -> list[tuple[str, str]]:
    """The party whose subsidiaries the term sheet keeps referring to ("subsidiaries of Capri", "Capri and its Subsidiaries"),
    resolved to the full name it was introduced with: Capri Holdings Limited (“Capri”)."""
    flow = _flow(ctx)[0]
    best: tuple[str, str, int] = ("", "", 0)
    for cell in _party_cells(ctx):
        for m in _SHORT_NAME_RE.finditer(cell.text):
            name, desc = _split_descriptor(m.group("pre"))
            if not name:
                continue
            short = re.escape(tidy(m.group("short")))
            try:
                uses = len(re.findall(r"(?i:subsidiar(?:y|ies))\s+of\s+(?:the\s+)?" + short + r"\b|\b" + short
                                      + r"\s+and\s+its\s+(?i:(?:restricted\s+|consolidated\s+)?subsidiaries)", flow))
            except re.error:
                continue
            if uses > best[2]:
                best = (name, desc, uses)
    return [(best[0], best[1])] if best[2] >= 2 else []


def _topco(ctx: Ctx) -> tuple[list[tuple[str, str]], str]:
    """([(name, descriptor)], basis) for the top company named in the term sheet; ([], "") if it cannot be told.

    basis says how the company was identified: "Parent", "Holdings", "Topco" or "Company" (a row or a defined term),
    "Group" (the party whose subsidiaries the term sheet refers to), "Guarantor" or "Borrower" (the only one named),
    or "Unnamed Parent" / "Unnamed Holdings" with no name when such a company is referred to but could not be named
    (the borrower is then not the top company, so nothing below it is offered in its place).
    """
    memo = _memo(ctx)
    if "topco" in memo:
        return memo["topco"]
    result: tuple[list[tuple[str, str]], str] = ([], "")
    unread = ""  # a Parent / Holdings row is there, but no company name could be read from it
    for cell in _cells(ctx, _PARENT_LABELS, 3):  # a "Parent:" / "Holdings:" / "Topco:" row: a company above the Company
        label = cell.block.label.lower()
        basis = "Holdings" if "holdings" in label else "Topco" if "topco" in label else "Parent"
        name, desc = _row_party(cell)
        if name:
            result = ([(name, desc)], basis)
            break
        if not re.match(r"^\W*(?:(?:the\s+)?(?:company|borrower)|none|n/?a|not\s+applicable)\b", cell.text, re.IGNORECASE):
            unread = unread or f"Unread {basis}"  # ("Parent: the Company" and "Parent: None" name nobody above the Company)
    if not result[0]:
        for term in ("Ultimate Parent", "Parent", "Parent Guarantor", "Parent Borrower", "Holdings", "Topco"):
            found = _defined(ctx, term)
            if found:
                result = (found, "Parent" if "Parent" in term else term)
                break
    if not result[0]:
        above = _PARENT_USED_RE.search(_flow(ctx)[0])  # a company above the borrower that the rules could not put a name to
        if unread:
            result = ([], unread)
        elif above:
            result = ([], "Unnamed Holdings" if "Holdings" in above.group(0) else "Unnamed Parent")
    if not result[0] and not result[1]:
        for cell in _cells(ctx, _COMPANY_LABELS, 2):  # a "Company:" row
            name, desc = _row_party(cell)
            if name:
                result = ([(name, desc)], "Company")
                break
    if not result[0] and not result[1]:
        found = _defined(ctx, "Company") or _group_parent(ctx)
        if found:
            result = (found, "Company" if _defined(ctx, "Company") else "Group")
        else:
            for term in ("Guarantor", "Borrower"):  # a sole named guarantor, else a sole borrower
                found = _defined(ctx, term)
                if term == "Guarantor" and any(re.search(r"\bsubsidiar(?:y|ies)\b", c.text, re.IGNORECASE)
                                               for c in _cells(ctx, _GUARANTOR_LABELS, 3, sections=True)):
                    continue  # the guarantor section speaks of subsidiaries: a guarantor named there need not be the top company
                if len({n for n, _ in found}) == 1:
                    result = (found[:1], term)
                    break
    memo["topco"] = result
    return result


def _name_pattern(name: str) -> str:
    """Regex for a company name as it appears in running text (any whitespace between its words)."""
    return r"\s+".join(re.escape(t) for t in name.split())


def _normalise_place(place: str) -> str:
    """House form of a jurisdiction: "United States - Delaware", "United Kingdom - England and Wales", "Panama"."""
    place = tidy(place).strip(" .,")
    place = _DEMONYMS.get(place, place)
    if place in _US_STATES:
        return f"United States - {place}"
    return f"United Kingdom - {place}" if place in _UK_PARTS else place


def _trim_place(place: str) -> str:
    """The place name at the start of a run of capitalised words ("Ireland Company" -> "Ireland"): the longest opening
    the rules know as a place; failing that, the words up to the first that cannot be part of one."""
    words = tidy(place).strip(" .,").split()
    for n in range(len(words), 0, -1):
        known = " ".join(words[:n])
        if known in _US_STATES or known in _UK_PARTS or known in _PLACES:
            return known
    kept: list[str] = []
    for word in words:
        if word in _NOT_A_PLACE or word in _NOT_A_NAME or _NAME_SUFFIX_RE.match(word):
            break
        kept.append(word)
    while kept and kept[-1] in ("and", "of"):
        kept.pop()
    return " ".join(kept)


def _parse_place(descriptor: str) -> str:
    """Jurisdiction from the words that follow a company name ("a Delaware corporation" -> "United States - Delaware")."""
    descriptor = descriptor.strip()
    m = _PLACE_THEN_TYPE_RE.match(descriptor)
    if m:
        place = m.group("place")
        if place in _US_STATES or place in _DEMONYMS or place in _PLACES:
            return _normalise_place(place)
    m = _UNDER_LAWS_RE.search(descriptor.split(",")[0])
    place = _trim_place(m.group("place")) if m else ""
    return _normalise_place(place) if place else ""


def _place_of(ctx: Ctx, name: str, descriptor: str = "") -> tuple[str, str]:
    """(jurisdiction, the words it was read from) for a named company, from its descriptor or wherever the name is followed by one."""
    if descriptor:
        place = _parse_place(descriptor)
        if place:
            return place, f"{name}, {descriptor}"
    flow = _flow(ctx)[0]
    try:  # "X, a Delaware corporation", "X (the “Company”), a Maryland real estate investment trust", "X, organized under the laws of ..."
        rx = re.compile(_name_pattern(name) + r"(?:\s*\([^()]{0,80}\))?\s*,\s+(?P<desc>(?:an?\s+|(?:duly\s+)?(?:incorporated|organi[sz]ed|formed|registered|"
                        r"established)\s+)[^()“”\"]{3,200})")
    except re.error:
        return "", ""
    for m in rx.finditer(flow):
        place = _parse_place(m.group("desc"))
        if place:
            return place, m.group(0)
    return "", ""


def _governing_law(ctx: Ctx) -> tuple[str, dict | None]:
    """("State of New York", evidence) from the governing law section, or ("", None)."""
    for cell in _cells(ctx, _LAW_LABELS, 2):
        m = _LAW_GOVERNED_RE.search(cell.text) or _LAW_FIRST_RE.match(cell.text)
        law = tidy(m.group("law")) if m else ""
        place = re.sub(r"\s+law$", "", law)
        if law.startswith("State of") or place in _US_STATES or place in _PLACES or place in _DEMONYMS or place in _UK_PARTS:
            return law, _quote(ctx, cell.block, law)  # anything else beside the label is not the name of a law ("Customary.")
    return "", None


@_guard
def jurisdiction_topco(ctx: Ctx) -> dict:
    """Jurisdiction of the top company, e.g. "Ireland (Accenture plc)"; else not stated, with the governing law."""
    parties, basis = _topco(ctx)
    placed, unplaced, evidence = [], [], []
    for name, desc in parties[:2]:
        place, words = _place_of(ctx, name, desc)
        if place:
            placed.append(f"{place} ({name})")
            evidence.append(_quote_words(ctx, words) or _quote_words(ctx, name))
        else:
            unplaced.append(f"{name}: jurisdiction of incorporation not given")
    if placed:
        note = ""
        if basis in ("Guarantor", "Borrower"):
            note = f"{parties[0][0]} is taken as the top company because it is the only {basis} named; the term sheet names no parent."
        elif basis == "Group":
            note = f"{parties[0][0]} is taken as the top company because the term sheet refers to it and its subsidiaries; it names no parent."
        return stated(["; ".join(placed + unplaced)], evidence, note)
    law, law_quote = _governing_law(ctx)
    first = "Not stated in term sheet"
    if parties:
        names = " and ".join(n for n, _ in parties[:2])
        if basis == "Group":
            first += f" (the term sheet refers to {names} and its subsidiaries; its jurisdiction of incorporation is not given)"
        else:
            role = {"Parent": "the Parent is", "Holdings": "Holdings is", "Company": "the Company is", "Topco": "Topco is"}.get(basis, f"the {basis} is")
            first += f" ({role} {names}; its jurisdiction of incorporation is not given)"
        name = parties[0][0]
        evidence = [_quote_words(ctx, f"{name} the {basis}") or _quote_words(ctx, f"{name} {basis}") or _quote_words(ctx, name)]
    elif basis.startswith("Unnamed"):
        first += " (Holdings is referred to but not named)" if "Holdings" in basis else " (a Parent is referred to but not named)"
        evidence = [_quote_words(ctx, "Holdings" if "Holdings" in basis else "the Parent")]
    note = ""
    if basis.startswith("Unread"):
        note = f"The term sheet has a {basis.split()[-1]} row, but the rules could not read a company name from it: check the row."
    lines = [first] + ([f"Governing law of the facility: {law}"] if law else [])
    return _with_evidence(lines, evidence + [law_quote], note)


# ---------------------------------------------------------------------------------------------------
# Guarantors
# ---------------------------------------------------------------------------------------------------

def _name_the_party(ctx: Ctx, line: str) -> str:
    """ "Parent and any subsidiary ..." -> "Parent (Aon plc) and any subsidiary ..." when the term sheet names the party."""
    parties, basis = _topco(ctx)
    if len(parties) != 1 or basis not in ("Parent", "Holdings", "Company", "Topco"):
        return line
    m = re.match(r"^((?:[Tt]he\s+)?" + basis + r")\b(?!\s*\()", line)
    if not m or parties[0][0] in line:
        return line
    return f"{m.group(1)} ({parties[0][0]}){line[m.end():]}"


def _chunked(text: str, most: int = 2, limit: int = LONG_LIMIT) -> list[str]:
    """A long clause over up to ``most`` lines, in its own order, broken before the markers of the list it holds
    ("... and (B) ...", "..., (b) ..."); only what does not fit in the last line is cut (and marked)."""
    out: list[str] = []
    rest = text.strip()
    while rest:
        if len(rest) <= limit or len(out) == most - 1:
            out.append(rest if len(rest) <= limit else _fit(rest, limit))
            break
        cut = None
        for rx in _CHUNK_RES:
            for m in rx.finditer(rest[:limit + 1]):
                left = rest[:m.start()]
                if len(left) >= limit * 0.35 and left.count("(") == left.count(")") and (cut is None or m.start() > cut.start()):
                    cut = m
        if cut is None:
            out.append(_fit(rest, limit))
            break
        out.append(rest[:cut.start()].rstrip(" ,;"))
        rest = "… " + rest[cut.start():].lstrip(" ,;")  # marked as carrying the line above on
    return out


def _release_lines(sentence: str, reinstated: bool | None = None) -> list[str]:
    """Lines for a release / fall-away sentence: what is released, then the conditions (over more than one line when
    they are long). ``reinstated`` says the section provides for the security or guarantee to be given again."""
    sentence = sentence.strip()
    if sentence.endswith(".") and not _ENDS_ABBREVIATED_RE.search(sentence):
        sentence = sentence[:-1]
    named = _EVENT_NAME_RE.search(sentence)
    label = "Release" + (f" ({tidy(named.group(1))})" if named else "")
    if reinstated is None:
        reinstated = bool(_REINSTATE_RE.search(sentence))
    plain = _no_brackets(sentence)
    tail = _RELEASE_TAIL_RE.search(plain)
    core = plain[:tail.start()] if tail else plain
    # a proviso to the release is a further condition of it (unless it is the reinstatement, which the line already marks): it is
    # given with the line, or pointed to where it is too long to give
    proviso = plain[tail.start():].strip(" ;,") if tail and "provided" in tail.group(0).lower() else ""
    further = ""
    if proviso and not _REINSTATE_RE.search(proviso):
        further = f"; {proviso}" if len(proviso) <= 160 else " (subject to a proviso set out in the term sheet)"
    m = _IF_THEN_RE.match(core)
    if not m:
        return [_line(f"{label}: {_lower_first(core)}" + (" (subject to reinstatement)" if reinstated else "") + further, MAIN_LIMIT)]
    cond, main = tidy(m.group("cond")), _FROM_SUCH_DATE_RE.sub("", tidy(m.group("main")))
    notice = _NOTICE_RE.search(main)
    operative = _RELEASED_RE.search(main) or _RELEASES_RE.search(main)
    if operative:
        cut = main.rfind(", ", 0, operative.start())
        # what stands before the operative clause is left out only where it adds no condition of its own ("at the Company's sole
        # cost and expense, ..."; a notice is added back below): "so long as no Event of Default is continuing, ..." stays
        if cut >= 0 and not _CONDITION_WORD_RE.search(_NOTICE_RE.sub(" ", main[:cut])):
            main = main[cut + 2:]
    main = re.sub(r"\s+at\s+such\s+time$", "", main)
    if notice and notice.group(0) not in main:
        main += ", " + notice.group(0)
    if reinstated:
        main += " (subject to reinstatement)"
    whole = _line(f"{label}: {main} if {cond}{further}", 100_000)
    if len(whole) <= MAIN_LIMIT:
        return [whole]
    conditions = _line(f"Release conditions: {cond}{further}", 100_000)
    if len(conditions) <= MAIN_LIMIT:
        return [_line(f"{label}: {main}", MAIN_LIMIT), conditions]
    return _chunked(whole, 3)  # conditions too long for a line: what is released and each group of conditions, in order


def _item_markers(text: str) -> list[tuple[int, int, str]]:
    """(start, end, label) of the list markers in ``text``: "(a)", "(iii)", "(2)". Cross-references are left out
    ("clause (i)", "clauses (a), (b) and (c)", "Section 6.02(v)")."""
    out: list[tuple[int, int, str]] = []
    ref_end = -1  # where the last cross-reference ended
    for m in _MARKER_RE.finditer(text):
        before = text[max(0, m.start() - 16):m.start()]
        glued = m.start() > 0 and not text[m.start() - 1].isspace()
        joins_ref = ref_end >= 0 and re.fullmatch(r"\s*(?:,|,?\s*(?:and|or|through|to))\s*", text[ref_end:m.start()]) is not None
        if glued or _MARKER_REF_RE.search(before) or joins_ref:
            ref_end = m.end()
            continue
        ref_end = -1
        out.append((m.start(), m.end(), m.group("m")))
    return out


def _marker_before(label: str, style: str) -> str | None:
    """The marker that precedes ``label`` in a list numbered in ``style``; "" if ``label`` opens such a list; None if it is not of that style."""
    if style == "roman":
        numerals = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"]
        low = label.lower()
        if low not in numerals or (label != low and label != label.upper()):
            return None
        prev = numerals[numerals.index(low) - 1] if numerals.index(low) else ""
        return prev.upper() if label.isupper() else prev
    if style == "letter":
        if len(label) != 1 or not label.isalpha():
            return None
        return "" if label in "aAxX" else chr(ord(label) - 1)  # "(x) ... (y) ... (z)" is a list of its own
    if not label.isdigit():
        return None
    return "" if label == "1" else str(int(label) - 1)


def _list_start(markers: list[tuple[int, int, str]]) -> int | None:
    """Index of the marker that opens the list to which the last marker belongs: "(iii)" is followed back to "(ii)" and
    "(i)". None when the sequence cannot be followed, so that nothing is concluded about what governs the list."""
    for style in ("roman", "letter", "number"):
        at, label = len(markers) - 1, markers[-1][2]
        while True:
            prev = _marker_before(label, style)
            if prev is None:
                break  # not a marker of this style
            if prev == "":
                return at
            found = next((k for k in range(at - 1, -1, -1) if markers[k][2] == prev), None)
            if found is None:
                break
            at, label = found, prev
    return None


def _named_group(text: str, mention: re.Match, group: re.Match) -> str:
    """The group of Lenders as the line names it: "the unanimous consent of the Lenders" is "the Lenders (unanimous)"."""
    who = tidy(group.group("who"))
    unanimous = re.search(r"\bunanimous\s+(?:written\s+)?$", text[:mention.start()], re.IGNORECASE)
    return f"{who} (unanimous)" if unanimous else who


def _joint_group(segment: str, mentions: list, who: str) -> str | None:
    """``who`` together with any other group of Lenders whose consent the same clause calls for: "the consent of each
    affected Lender, and also the consent of the Required Lenders, shall be required to ..." needs both, and naming the
    nearer one alone would misstate it. None where a second group is named in a way the rules cannot read."""
    last = mentions[-1]
    start = max((b.end() for b in _CLAUSE_START_RE.finditer(segment[:last.start()])), default=0)
    earlier = [(x, g) for x in mentions[:-1] if x.start() >= start and (g := _LENDER_GROUP_RE.match(segment, x.end()))]
    if not earlier:
        return who
    if len(earlier) > 1 or not _CO_CONSENT_RE.fullmatch(segment[earlier[0][1].end():last.start()]):
        return None
    return f"{_named_group(segment, *earlier[0])} and {who}"


def _consent_group(before: str, rest_of_item: str) -> tuple[str, str, str, str] | None:
    """Whose consent a release needs, read from the sentence it stands in: (the group, a second group named beside it,
    words that qualify the release, where the group was found: "after" the release, in its "item" or at the "head" of
    its list). ``before`` is the sentence up to the release, ``rest_of_item`` what follows it.

    The group is the one that governs the release, not the one named nearest to it:
      - "... the release of X shall require the consent of all Lenders" - written after the release;
      - "(ii) the consent of all Lenders shall be required for the release of X" - written in the same list item;
      - "the consent of each Lender shall be required with respect to (i) ..., (ii) ... and (iii) the release of X" - at the
        head of the list in which the release is an item, however many items (and whatever asides) lie between.
    A group mentioned only as an addition ("in addition to the consent of the Required Lenders") does not govern. A
    consent that is dispensed with is not a requirement: "the release of X does not require the consent of the
    Lenders", "the Agent may release X without the consent of any Lender" ("without" counts only after words that
    forbid the release: "no release of X ... without the consent of each Lender"). Where the wording between the group
    and the list, or between the item's marker and the release, is not of a kind the rules know, or the party whose
    consent is called for is not a group of Lenders, the answer is None.
    """
    after = _CONSENT_AFTER_RE.match(rest_of_item)
    if after:
        gap = after.group("gap")
        who = tidy(after.group("who"))
        more = _AND_GROUP_RE.match(rest_of_item, after.end())  # "... the consent of the Required Lenders and each affected Lender"
        second = _SECOND_GROUP_RE.match(rest_of_item, more.end()) if more else None
        unread = bool(more) and not second and re.match(r"(?:[\w\-]+\s+){0,4}?(?-i:Lenders?)\b", rest_of_item[more.end():], re.IGNORECASE)
        if second:
            who = f"{who} {more.group(1).lower()} {tidy(second.group(0))}"
        if unread:
            pass  # a second group of Lenders is named in words the rules do not read: the first alone would misstate the requirement
        elif after.group("verb").lower() == "without":
            if _FORBIDS_RE.search(before) and _PASSIVE_GAP_RE.match(gap):
                return who, "", "", "after"
        elif not (_EXCEPTION_WORD_RE.search(gap) or _NEW_CLAUSE_RE.search(gap) or _NEGATED_RE.search(gap)):
            return who, "", "", "after"
    item_rest = _ITEM_END_RE.split(rest_of_item, 1)[0]
    if re.search(r"\b(?:consents?|approvals?|votes?)\b", _no_brackets(item_rest), re.IGNORECASE):
        return None  # the item goes on to say whose consent it needs, in words the rules do not read
    also = ""

    def drop(m: re.Match) -> str:
        nonlocal also
        also = also or tidy(m.group("also"))
        return " "

    if _REASSIGNS_RE.search(before):
        return None  # "(or, in the case of clause (iii), the Required Lenders)": the head of the list does not govern every item
    plain = _ALSO_CONSENT_RE.sub(drop, _no_brackets(before))
    markers = _item_markers(plain)
    lead = plain[markers[-1][1]:] if markers else plain  # the words between the item's marker and the release
    mentions = list(_APPROVAL_OF_RE.finditer(lead))
    if mentions:  # the group is named in the item itself (or the sentence has no list)
        group = _LENDER_GROUP_RE.match(lead, mentions[-1].end())
        if not group:
            return None
        gap = lead[group.end():]
        negative = re.search(r"\bwithout\s+(?:the\s+)?(?:prior\s+)?(?:written\s+)?$", lead[:mentions[-1].start()], re.IGNORECASE)
        who = _joint_group(lead, mentions, _named_group(lead, mentions[-1], group))
        if who is None:
            return None
        if negative and not gap.strip(" ,"):  # "no amendment shall, without the consent of each Lender, release ..."
            return who, also, "", "item"
        verb = _REQUIRED_RE.match(gap)
        if not verb or ";" in gap or _NEW_CLAUSE_RE.search(gap[verb.end():]):
            return None
        return who, also, "", "item"
    if not markers:
        return None
    qualifier = ""
    q = _ITEM_QUALIFIER_RE.match(lead)
    if q:
        qualifier = tidy(q.group("q")).rstrip(",")
    elif _EXCEPTION_WORD_RE.search(lead):
        qualifier = "subject to an exception set out in the term sheet"
    if _NEW_CLAUSE_RE.search(lead if not q else ""):
        return None  # another clause begins between the marker and the release: the head of the list need not govern it
    start = _list_start(markers)
    if start is None:
        return None
    if start != len(markers) - 1 and _REGOVERNS_RE.search(re.sub(r"[\s,;]*(?:\b(?:and|or)\b)?[\s,;]*$", "", plain[:markers[-1][0]])):
        return None  # "..., but shall not be required to (iii) release ...": this item has a verb of its own
    head = plain[:markers[start][0]]
    mentions = list(_APPROVAL_OF_RE.finditer(head))
    if not mentions:
        return None
    group = _LENDER_GROUP_RE.match(head, mentions[-1].end())
    if not group or not _GOVERNS_LIST_RE.match(head[group.end():]):
        return None
    who = _joint_group(head, mentions, _named_group(head, mentions[-1], group))
    return (who, also, qualifier, "head") if who else None


def _sentence_start(flow: str, at: int, reach: int = 2500) -> int:
    """Offset at which the sentence holding ``at`` begins (looking back at most ``reach`` characters)."""
    low = max(0, at - reach)
    ends = [m.end() for m in re.finditer(r"(?<=[a-z0-9)\]”\"%])\.\s+(?=[A-Z“\"(])", flow[low:at])]
    return low + ends[-1] if ends else low


def _consent_to_release(ctx: Ctx, release_re: re.Pattern) -> tuple[str, dict | None]:
    """ "Release of all or substantially all of the Guarantors requires the consent of each Lender ..." from the amendments section."""
    flow = _flow(ctx)[0]
    who, also, whats, evidence, who_tail = "", "", [], None, ""

    def exception_in(tail: str) -> str:
        """The exception a tail of the item makes, in its own words (or a pointer to it when the words cannot be cut cleanly)."""
        trailing = _EXCEPTION_WORD_RE.search(tail)
        if not trailing:
            return ""
        words = tidy(tail[trailing.start():]).rstrip(" ,)")
        return words if len(words) <= 140 and words.count("(") == words.count(")") else "subject to an exception set out in the term sheet"

    for m in release_re.finditer(flow):
        before = flow[_sentence_start(flow, m.start()):m.start()]
        rest = flow[m.end():m.end() + 300]
        found = _consent_group(before, rest)
        if found is None:
            continue
        this_who, this_also, qualifier, where = found
        if who and this_who.lower() != who.lower():
            continue
        what = tidy(m.group("what")).strip(" ,")
        if not what or what.lower() in (w.lower().split(" (")[0] for w in whats):
            continue
        if where == "after":
            # the consent is written after the release, so an exception that follows it is written after the group and
            # is given there, in the term sheet's order: "... requires the consent of all Lenders (other than Defaulting Lenders)"
            named = _CONSENT_AFTER_RE.match(rest)
            this_tail = exception_in(_ITEM_END_RE.split(rest[named.end():], 1)[0]) if named else ""
            if whats and this_tail != who_tail:
                continue  # two releases whose requirements are qualified differently do not share a line
            who_tail = this_tail
        elif who_tail:
            continue
        elif not qualifier:
            # an exception written after the release: "... of the Collateral (other than in connection with a permitted disposition)"
            qualifier = exception_in(_ITEM_END_RE.split(rest, 1)[0])
        who, also = this_who, also or this_also
        whats.append(f"{what} ({qualifier})" if qualifier else what)
        span = before[-200:] + m.group(0)  # the words leading up to and naming the release
        evidence = evidence or _quote_words(ctx, span, _page_of(ctx, m.start()), tail_first=True, near=m.start())
        if len(whats) >= 2:
            break
    if not whats or evidence is None:
        return "", None
    line = (f"Release of {' and of '.join(whats)} requires the consent of {who}" + (f" ({who_tail})" if who_tail else "")
            + (f" (in addition to {also})" if also else ""))
    return _line(line, MAIN_LIMIT), evidence


def _additional_guarantors(ctx: Ctx) -> tuple[str, dict | None]:
    """ "additional guarantors" as an item in the covenant list (a joinder undertaking the term sheet does not detail)."""
    for cell in _cells(ctx, _COVENANT_LABELS, 4):
        m = _ADDITIONAL_GUARANTORS_RE.search(cell.text)
        if m:
            return tidy(m.group(1)), _quote(ctx, cell.block, m.group(1))
    return "", None


def _guarantor_exceptions(text: str) -> str:
    """The topics of the carve-outs in a long guarantor section, as one line."""
    if len(text) < 300 or not _HAS_EXCEPTIONS_RE.search(text):
        return ""
    topics = [label for rx, label in _EXCEPTION_TOPICS if rx.search(text)]
    return "Exceptions referred to: " + "; ".join(topics) if len(topics) >= 2 else ""


def _closed(text: str) -> str:
    """``text`` up to a bracket that is opened and never closed (marked as cut there); unchanged if its brackets pair up."""
    opened: list[int] = []
    for i, ch in enumerate(text):
        if ch == "(":
            opened.append(i)
        elif ch == ")" and opened:
            opened.pop()
    if not opened:
        return text
    return text[:opened[0]].rstrip(" ,;:") + " …"


def _listed_exclusions(text: str) -> list[str]:
    """The lettered list that follows "subject to certain exclusions ..., including (a) ...; (b) ...", item by item in the
    term sheet's words (the head of each item; what qualifies it further is marked as left out), on up to two lines."""
    m = _EXCLUSIONS_LIST_RE.search(text)
    if not m:
        return []
    items = _list_items(text[m.end():])
    items[-1] = (_sentences(items[-1]) or [items[-1]])[0]
    heads = []
    for item in (_ITEM_RE.match(x.strip()) for x in items):
        if item:
            heads.append(f"({item.group(1)}) " + _item_cut(_closed(_line(_no_brackets(item.group(2)), 100_000))))
    if len(heads) < 2:
        return []
    word = "Exclusions" if "exclu" in m.group(0).lower() else "Exceptions"
    lines = _pack(heads, MAIN_LIMIT - 40)
    shown = sum(len(_ITEM_START_RE.findall(line)) for line in lines[:3])
    label = f"{word} include" if shown == len(heads) else f"{word} include (first {shown} of the {len(heads)} listed)"
    return [f"{label}: {lines[0]}"] + ["… " + more for more in lines[1:3]]  # (the later lines are marked as carrying the list on)


def _item_cut(text: str, short: int = 130, longer: int = 240) -> str:
    """A list item cut to its head. An item that goes on to a list of its own ("any subsidiary that ... intends to sell ... to (i) ...,
    (ii) ...") is cut where that list begins, so that the words which narrow it are kept; any other long item at a clause boundary."""
    if len(text) <= short:
        return text
    inner = [at for at, _, _ in _item_markers(text) if at > 20]
    if inner and inner[0] <= longer:
        head = text[:inner[0]].rstrip(" ,;:(")
        return (_DANGLING_RE.sub("", head).rstrip(" ,;:(") or head) + " …"
    return _fit(text, short)


def _wrap(text: str, most: int = WRAP_AT, boundaries: tuple = _WRAP_RES) -> list[str]:
    """Two lines for a long one, broken at the most even of the best kind of boundary it has; [] if there is no good place."""
    for rx in boundaries:
        best: tuple[int, str, str] | None = None
        for m in rx.finditer(text):
            left, right = text[:m.start()].rstrip(" ,;"), text[m.end():]
            if left.count("(") != left.count(")") or min(len(left), len(right)) < 80 or max(len(left), len(right)) > most:
                continue
            if best is None or abs(len(left) - len(right)) < best[0]:
                best = (abs(len(left) - len(right)), left, right)
        if best:  # (after the weaker kind of boundary the second line cannot stand alone: it is marked as carrying the first on)
            return [best[1], "… " + best[2] if rx in _WRAP_MORE_RES else _cap(best[2])]
    return []


def _split_long(text: str, limit: int = MAIN_LIMIT) -> list[str]:
    """A long line as two lines if it has a natural break; else whole, without its bracketed asides, or cut to ``limit``."""
    if len(text) <= WRAP_AT:
        return [text]
    wrapped = _wrap(text)
    if wrapped:
        return wrapped
    if len(text) <= limit:
        return [text]
    plain = _no_brackets(text)  # bracketed asides go before any of the sentence does
    if len(plain) <= limit:
        return [plain]
    # too long for one line: two full-length lines at a clause boundary keep what a cut would lose
    boundaries = _WRAP_RES + _WRAP_MORE_RES
    return _wrap(text, limit, boundaries) or _wrap(plain, limit, boundaries) or _wrap(plain, LONG_LIMIT, boundaries) or [_fit(text, limit)]


def _describe_guarantors(ctx: Ctx, cell: _Cell) -> dict:
    """What one guarantor section says: main lines, extra points, release lines, evidence."""
    out = {"main": [], "extra": [], "listed": [], "release": [], "evidence": [], "refers": False}
    text = _undefine(cell.text)
    sents = _sentences(text)
    # a section about some of the guarantors only keeps its label: "Foreign Guarantors: None" must not read as "no guarantors"
    label = cell.block.label.capitalize() if cell.block.label.isupper() else cell.block.label
    scope = f"{label}: " if _SCOPED_LABEL_RE.match(label) else ""
    if _BLANK_RE.match(cell.text):
        out["main"].append("[ ] - left blank in term sheet")
        out["evidence"].append(_quote_line(ctx, _label_line(cell.block)) or _quote(ctx, cell.block))
        return out
    if not sents or not _wordy(sents[0], 1):
        return out  # nothing readable beside the label
    none = _NONE_RE.match(text)
    if none:
        if re.match(r"^\W*(?:n/?a|not\s+applicable)\W*$", text, re.IGNORECASE) and _amendment_page(ctx, cell.block.page):
            return out  # in an amendment table "N/A" says nothing is being changed, not that there are no guarantors
        # "None" may be qualified in the same breath ("None; provided that the Company may designate ...") or by the
        # sentences that follow (a guarantee that springs on a later event): what the section goes on to say about
        # guarantees is given in its own words, so that a qualified "None" is not printed as a bare one
        rest = sents[0][none.end():].strip(" ,;") if len(sents[0]) > none.end() else ""
        if _wordy(rest, 3):
            out["main"] = _split_long(_line(f"{scope}None; {_lower_first(rest)}", 100_000))
        else:
            out["main"].append(f"{scope}None")
        out["evidence"].append(_quote(ctx, cell.block) or _quote_line(ctx, _label_line(cell.block)))
        for s in sents[1:4]:
            if _PAYMENT_GUARANTEE_RE.search(s):
                out["extra"].append("guarantee of payment and not of collection")
            elif re.search(r"guarant", s, re.IGNORECASE) and not _DEFINITION_SENTENCE_RE.match(s) and len(out["extra"]) < 2:
                out["extra"] += _split_long(_line(s, 100_000))[:2]
                out["evidence"].append(_quote(ctx, cell.block, s))
        return out
    if re.match(r"^\W{0,3}" + _BULLET_RE.pattern, text):  # a slide cell: one guarantor, or class of guarantors, per bullet
        bullets = [b.strip(" ;") for b in _BULLET_RE.split(text) if _wordy(b, 1)]
        out["main"] = _pack([_line(b) for b in bullets[:6]], LINE_LIMIT)[:3]
        if scope and out["main"]:
            out["main"][0] = scope + out["main"][0]
        out["refers"] = _only_refers(text)
        out["evidence"].append(_quote(ctx, cell.block, bullets[0]) if bullets else None)
        if cell.unchanged and out["main"]:
            out["main"][-1] += UNCHANGED
        return out
    first = sents[0]
    m = _GUARANTEED_BY_RE.search(first)
    if m and re.search(r"\b(?:not|no\s+longer)\s+(?:be\s+)?$", first[:m.start()], re.IGNORECASE):
        m = None  # "will not be guaranteed by ...": the sentence is the statement
    head = first[m.end():] if m and len(first) - m.end() > 8 else first
    head = _AS_AMENDED_RE.sub("", _AMONG_RE.sub("", _PROVISO_RE.split(head, 1)[0]))
    listed = [] if _guarantor_exceptions(text) else _listed_exclusions(text)
    items = _later_items(sents)  # the later items of a list this sentence opens ("... by (i) X" / "(ii) Y" / "and (iii) Z")
    lead_in = _LIST_LEAD_IN_RE.search(head)
    if lead_in and (listed or (items and _guarantor_exceptions(text))):
        head = head[:lead_in.start()]  # "..., subject to exceptions, including (a) ...": the list is given below, item by item or by topic
    elif items and re.search(r"\((?:a|i|1|A|I)\)\s", head):
        # the list is the description itself: all of its items belong to the line, not the first alone
        head = head.rstrip(" ,;") + "; " + "; ".join(items)
    out["main"] = _split_long(scope + _name_the_party(ctx, _cap(_line(head, 100_000))))
    out["refers"] = _only_refers(text)
    out["evidence"].append(_quote(ctx, cell.block, head))
    short = len(text) <= 420
    for s in _whole_sentences(text)[1:]:  # (each sentence whole: the conditions of a release may be set out as a list)
        if _DEFINITION_SENTENCE_RE.match(s) or re.match(r"^(?:(?:and|or)\s+)?\((?:[a-z]|[ivx]{2,5}|\d{1,2})\)\s", s):
            continue  # a definition, or a later item of a list that began in an earlier sentence
        if _RELEASE_RE.search(s):
            if not out["release"]:
                out["release"] = _release_lines(s)
                out["evidence"].append(_quote(ctx, cell.block, (_RELEASED_RE.search(s) or _RELEASE_RE.search(s)).group(0)))
            continue
        m = _GUARANTEES_OBLIGATIONS_RE.search(s)
        if m:
            clause = re.sub(r"^(?:Additionally|In\s+addition|Further(?:more)?|Also),?\s+", "", s[:m.end()], flags=re.IGNORECASE)
            out["extra"].append(_line(_cap(clause)))
            continue
        m = _GUARANTEED_BY_RE.search(s)
        if m and len(out["main"]) < 3 and not re.search(r"\b(?:not|no\s+longer)\s+(?:be\s+)?$", s[:m.start()], re.IGNORECASE):
            out["main"] += _split_long(_line(_cap(_PROVISO_RE.split(s, 1)[0]), 100_000))[:2]  # a second set of obligations and its guarantors
            continue
        if _PAYMENT_GUARANTEE_RE.search(s):
            continue  # added once below
        if _REFERRED_AS_RE.search(s):
            proviso = re.search(r"provided,?\s+that\s+(.{5,140})$", s, re.IGNORECASE)
            if proviso:
                out["extra"].append(_line(_cap(proviso.group(1))))
            continue
        if _coverage_in(s) or _NON_GUARANTOR_CAP_RE.search(s):
            continue  # belongs to the Guarantee Net Maintenance row (pointed to below)
        if short and len(s) > 12 and re.search(r"guarant", s, re.IGNORECASE):  # another point about the guarantee in a short section
            out["extra"].append(_line(s))
    m = _PAYMENT_GUARANTEE_RE.search(text)
    if m:
        out["extra"].append("guarantee of payment and not of collection")
    if not re.search(r"\d\s*%", " ".join(out["main"])):  # no repetition across rows: these figures are in the next row
        elsewhere = [what for found, what in ((_material_threshold(cell.text)[0], "material-subsidiary test"),
                                              (_NON_GUARANTOR_CAP_RE.search(text), "non-guarantor cap"),
                                              (_coverage_in(text), "guarantor coverage level")) if found]
        if elsewhere:
            out["extra"].append(f"{_cap(' and '.join(elsewhere))}: see Guarantee Net Maintenance")
    exceptions = _guarantor_exceptions(text)
    if exceptions:
        out["extra"].append(exceptions)
    out["listed"] = listed
    for term, body in _SHORT_DEFINITION_RE.findall(cell.text)[:4]:  # a short definition of a term the main line relies on
        if _norm(term)[: max(4, len(_norm(term)) - 3)] in _norm(" ".join(out["main"])) and "Subsidiar" not in term:
            out["extra"].append(_line(f"{term}: {body}"))
    if cell.unchanged and out["main"]:
        out["main"][-1] += UNCHANGED
    return out


def _guarantee_in_passing(ctx: Ctx) -> dict:
    """No guarantor section: a guarantee stated in the Borrower or Facility row, or an express statement that there is none."""
    party_cells = _cells(ctx, _BORROWER_LABELS + _FACILITY_LABELS, 5)
    for cell in party_cells:
        for sentence in _sentences(cell.text):
            m = _PASSING_GUARANTEE_RE.search(sentence)
            before = sentence[:m.start()] if m else ""
            if not m or re.search(r"\b(?:not|no\s+longer|un)\s*$", before, re.IGNORECASE):
                continue
            if not re.search(r"(?:^|[,;:)]|\b(?:and|be|are|is|being))\s*$", before) or _OTHER_DEBT_NEAR_RE.search(before):
                continue  # "... to refinance the Senior Notes guaranteed by X": other debt is guaranteed, not this facility
            who = _fit(tidy(re.split(r";|\s\(", sentence[m.start("who"):])[0]).rstrip(" .,"), 200)
            how = tidy(m.group("how") or "")
            label = cell.block.label.capitalize() if cell.block.label.isupper() else cell.block.label
            named = _name_the_party(ctx, _cap(who))
            if named != _cap(who) and len(who) <= 40:
                line = f"{named}: {label} {how} guaranteed by {who}"
            else:
                line = f"{named} ({how + '; ' if how else ''}guarantee stated in the {label} row)"
            return stated([_line(line, MAIN_LIMIT)], _quote(ctx, cell.block, m.group(0)))
    for cell in party_cells:  # an express statement that there is no guarantee, in the same rows
        m = _UNGUARANTEED_RE.search(cell.text)
        if m:
            rest = re.match(r"[^.;]{0,160}", cell.text[m.end():])
            return stated([_line(f"None ({m.group(0)}{_capped(cell.text[m.end():], rest) if rest else ''})", MAIN_LIMIT)],
                          _quote(ctx, cell.block, m.group(0)))
    flow = _flow(ctx)[0]
    m = _UNGUARANTEED_RE.search(flow)
    if m:
        rest = re.match(r"[^.;]{0,160}", flow[m.end():])  # the rest of the clause may qualify it ("... unless ...")
        clause = m.group(0) + (_capped(flow[m.end():], rest) if rest else "")
        quote = _quote_words(ctx, m.group(0), _page_of(ctx, m.start()))
        return stated([_line(f"None ({clause})", MAIN_LIMIT)], quote)
    return not_stated()


@_guard
def guarantors(ctx: Ctx) -> dict:
    """Named guarantors or the description the term sheet gives, then exceptions and release provisions."""
    cells = _cells(ctx, _GUARANTOR_LABELS, sections=True)
    if not cells:
        return _guarantee_in_passing(ctx)
    main, listed, extra, release, evidence, refers = [], [], [], [], [], []
    for cell in cells:
        if not cell.text:
            if cell.unchanged:  # "Same as existing" and the existing column could not be read
                main.append("Same as existing (existing terms not restated in the term sheet)")
                evidence.append(_quote(ctx, cell.block))
                refers.append(True)
            continue
        got = _describe_guarantors(ctx, cell)
        for item in got["main"]:
            if _norm(item) not in {_norm(x) for x in main}:
                main.append(item)
        listed += got["listed"] if not listed else []
        extra += [x for x in got["extra"] if _norm(x) not in {_norm(y) for y in extra}]
        release += got["release"] if not release else []
        evidence += got["evidence"]
        refers.append(got["refers"])
    if not main:
        return not_stated()
    consent, consent_quote = _consent_to_release(ctx, _RELEASE_OF_GUARANTORS_RE)
    joinder, joinder_quote = _additional_guarantors(ctx)
    lines = list(main[:4])
    extras = [x for x in extra if x]
    if len(lines) == 1 and extras and not extras[0].startswith("Exceptions") and len(lines[0]) + len(extras[0]) + 2 <= LINE_LIMIT:
        lines[0] += "; " + _lower_first(extras.pop(0))  # a short second point reads better on the first line
    lines += listed + _pack([_cap(x) for x in extras[:4]], LINE_LIMIT)
    if joinder:
        lines.append(f"{_cap(joinder)}: listed among the covenants, without detail")
    lines += release[:2]
    if consent:
        lines = lines[:7] + [consent]  # (a row holds eight lines: the consent needed for a release is not the one to lose)
    quotes = [e for e in evidence if e]
    picked = quotes[:1] + [e for e in quotes[1:] if e not in quotes[:1]][:1] + [consent_quote or joinder_quote]
    picked += quotes[2:]
    if refers and all(refers):
        return by_reference(lines[:8], picked, _mixed_note(cells))
    return stated(lines[:8], picked, _mixed_note(cells))


# ---------------------------------------------------------------------------------------------------
# Guarantor coverage
# ---------------------------------------------------------------------------------------------------

def _compare_symbol(words: str) -> str:
    """">=" or ">" for the words a threshold is expressed in ("equal to or greater than", "in excess of")."""
    words = tidy(words or "").lower()
    if not words:
        return ""
    if words in (">", "in excess of", "more than", "greater than") or words.startswith("exceed"):
        return ">"
    return ">="


def _coordinated_metric(window: str) -> str:
    """The measure named last in ``window``, with those joined to it: "total assets or revenues" (not just "revenues")."""
    found = list(_METRIC_NAME_RE.finditer(window))
    if not found:
        return ""
    first = len(found) - 1
    while first > 0 and re.fullmatch(r"\s*(?:,|,?\s*(?:and/or|and|or))\s*", window[found[first - 1].end():found[first].start()]):
        first -= 1
    phrase = window[found[first].start():found[-1].end()]
    return " ".join(w if w.isupper() or w == "EBITDA" else w.lower() for w in phrase.split())


def _material_threshold(text: str) -> tuple[list[str], str]:
    """(["Material Subsidiary: total revenues >= 10% of ... or total assets >= 10% of ..."], matched words) or ([], "").

    The definition is recast as "measure >= N% of base" only where that can be done without changing what it says: every
    figure in it is accounted for, each is tied to the subsidiary's own size, the limbs are joined as the term sheet
    joins them, and nothing in it speaks of subsidiaries taken together, of a negative, or of "respectively". Any other
    definition that has a figure is given in the term sheet's own words (over two lines if need be).
    """
    masked = _ABBR_RE.sub(lambda a: a.group(0).replace(".", "\x01"), text)  # ("U.S." does not end the definition)
    m = _MATERIAL_DEFINITION_RE.search(masked)
    if not m:
        return [], ""
    term, words = tidy(m.group("term").replace("\x01", ".")), m.group(0).replace("\x01", ".")[:60]
    raw_body = m.group("body").replace("\x01", ".")
    # the definition itself: a proviso to it is another rule (often the coverage level the guarantors must reach), and a
    # bracketed aside is not part of the test
    body = _PROVISO_RE.split(_no_brackets(raw_body), 1)[0]
    line = _threshold_line(term, body)
    if line:
        return [line], words
    own = _PROVISO_RE.split(_AS_DEFINED_RE.sub("", raw_body), 1)[0].strip(" ,;:")
    defines = not re.fullmatch(r"is|are", m.group("verb"), re.IGNORECASE) or re.match(r"\s*(?:any|each|every|an?|all|those)\b", own, re.IGNORECASE)
    if defines and _FIGURE_RE.search(own) and _wordy(own, 4):  # not safely recast: the definition as the term sheet words it
        return _own_words(f"{term}: {own}"), words
    return [], ""


def _threshold_line(term: str, body: str) -> str:
    """The recast definition ("<term>: total assets >= 10% of consolidated total assets or ..."), or "" where it cannot be recast safely."""
    if _THRESHOLD_UNSAFE_RE.search(body):
        return ""
    found = []
    for t in _THRESHOLD_RE.finditer(body):
        symbol = _compare_symbol(t.group("cmp"))
        found.append((t.start(), t.end(), symbol, t.group("pct"), t.group("base"), ""))
        at = t.end()
        while True:  # "... greater than or equal to either (a) 5% of X or (b) 5% of Y": the comparison carries over
            more = _THRESHOLD_NEXT_RE.match(body, at)
            if not more:
                break
            found.append((more.start("pct"), more.end(), symbol, more.group("pct"), more.group("base"), more.group("join").lower()))
            at = more.end()
    found += [(t.start(), t.end(), ">=", t.group("pct"), t.group("base"), "") for t in _THRESHOLD_OR_MORE_RE.finditer(body)]
    pieces, last_end = [], 0  # (how the piece is joined to the one before, the piece)
    for start, end, symbol, pct, base, join in sorted(found):
        if start < last_end:
            continue
        base = re.sub(r"^(?:the\s+)", "", tidy(base))
        if join:  # a further limb of the same comparison
            if not _METRIC_NAME_RE.search(base) or not pieces:
                return ""
            pieces.append((join, f"{symbol} {pct}% of {base}"))
            last_end = end
            continue
        between = body[last_end:start]
        metric = _coordinated_metric(body[max(last_end, start - 200):start])  # the measure(s), named shortly before the comparison
        if metric:  # "total revenues ... equal to or greater than 10% of the consolidated total revenues"
            piece = f"{metric} {symbol} {pct}% of {base}"
        elif _METRIC_NAME_RE.search(base) and (_SIZE_VERB_RE.search(body[max(last_end, start - 80):start])
                                               or (pieces and re.fullmatch(r"[\s,]*(?:and|or)\s+(?:\(\w{1,3}\)\s*)?", between))):
            piece = f"{symbol} {pct}% of {base}"  # "accounts for more than 5% of consolidated EBITDA or total assets"
        else:
            return ""  # a percentage of something that is not said to measure the subsidiary
        join = ""
        if pieces:  # joined as the term sheet joins them: "... or (ii) ...", "... and whose ..."
            marked = re.search(r"\b(and|or)\s+\(\w{1,3}\)", between, re.IGNORECASE)
            words = {w.lower() for w in re.findall(r"\b(and|or)\b", between, re.IGNORECASE)}
            join = marked.group(1).lower() if marked else next(iter(words)) if len(words) == 1 else ""
            if not join:
                return ""
        pieces.append((join, piece))
        last_end = end
    # every figure of the definition must be in the line: one left out (a dollar test, a fourth limb) would make it read as the whole test
    if not pieces or len(pieces) > 3 or len(_FIGURE_RE.findall(body)) != len(pieces):
        return ""
    line = _line(f"{term}: " + "".join((f" {join} " if join else "") + piece for join, piece in pieces), 100_000)
    return line if len(line) <= MAIN_LIMIT else ""


def _immaterial_test(text: str) -> tuple[list[str], str]:
    """(lines, matched words) for a test of which subsidiaries are immaterial - "immaterial subsidiary (to be defined as any
    subsidiary that does not account for more than ...)" - given in the term sheet's own words, since the limbs of such a
    test (each subsidiary, all of them together, assets, EBITDA) cannot be rearranged safely. Only a test with a figure counts."""
    for m in _IMMATERIAL_RE.finditer(text):
        if m.group("bracket"):
            depth, end = 1, None
            for i in range(m.end(), min(len(text), m.end() + 900)):
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                if depth == 0 or (depth == 1 and text[i] == ";"):  # (a bracket left unclosed ends with the list item it stands in)
                    end = i
                    break
            if end is None:
                continue
            body, intro = text[m.end():end], tidy(m.group("bracket"))
        else:
            body, intro = (_sentences(text[m.end():]) or [""])[0], ""
        body = _AS_DEFINED_RE.sub("", body).strip(" .;")
        if not re.search(r"\d\s*%|[$€£]\s?\d", body):
            continue
        return _chunked(_line(f"Immaterial subsidiary: {intro} {body}".replace(":  ", ": "), 100_000), 2), m.group(0)
    return [], ""


def _coverage_in(text: str) -> re.Match | None:
    """A statement of what the guarantors as a body cover ("constituting >80% of revenue, EBITDA and assets").

    The same words with a small percentage, or said of each subsidiary, are a test of which subsidiaries are
    material ("any subsidiary which accounts for more than 5% of consolidated EBITDA"): not a coverage level.
    """
    for m in _COVERAGE_RE.finditer(text):
        try:
            small = float(m.group("pct")) < 50
        except ValueError:
            continue
        if not small and not _EACH_SUBSIDIARY_RE.search(text[max(0, m.start() - 120):m.start()]):
            return m
    for m in _COVERAGE_OF_RE.finditer(text):  # "the EBITDA of the Guarantors shall be not less than 80% of ..."
        try:
            if float(m.group("pct")) >= 50:
                return m
        except ValueError:
            continue
    return None


def _own_words(text: str) -> list[str]:
    """A clause of the term sheet as one line, or as two broken at a clause boundary; cut (and marked) only when neither will hold it."""
    text = _line(text, 100_000)
    if len(text) <= MAIN_LIMIT:
        return [text]
    boundaries = _WRAP_RES + _WRAP_MORE_RES
    return (_wrap(text, MAIN_LIMIT, boundaries) or _wrap(text, LONG_LIMIT, boundaries)
            or [text if len(text) <= LONG_LIMIT else _fit(text, MAIN_LIMIT)])


def _coverage_lines(text: str, m: re.Match, label: str) -> list[str]:
    """The line(s) for a coverage level found in a Guarantors row: the clause itself when it says how the level is
    tested or makes it a condition ("in the event that the Guarantors do not represent at least 85% of ..., then ..."),
    otherwise the level with a remark that the term sheet does not say how it is tested."""
    where = f"stated in the {label.capitalize() if label.isupper() else label} row"
    start = max(text.rfind(". ", 0, m.start()), text.rfind("; ", 0, m.start()))
    stops = [p for p in (text.find(". ", m.end()), text.find("; ", m.end())) if p >= 0]
    begin = start + 2 if start >= 0 else 0
    sentence = text[begin:min(stops) if stops else len(text)]
    # a level that is denied or conditional, or that somebody undertakes (or is merely to try) to reach, is not a bare statement of
    # what the guarantors cover: only the clause says what it means
    conditional = re.search(r"\b(?:no|not|never|neither|nor|without|if|unless|until|whether|in\s+the\s+event|to\s+the\s+extent|so\s+long\s+as|provided|"
                            r"except|other\s+than|fail\w*|ceas\w+|need|requirement|may|might|could|should|will|shall|must|would|efforts?|endeavou?rs?|"
                            r"cause|procure|ensure|intend\w*|expect\w*|target\w*|anticipat\w*|aim\w*|seek\w*|required?|agree\w*)\b",
                            text[begin:m.start()], re.IGNORECASE)
    own_only = m.re is not _COVERAGE_RE or m.group("short")  # worded in a way the bare form below would not render truly
    if _TESTED_RE.search(sentence) or conditional or own_only:
        return _own_words(f"{_cap(_PROVISO_LEAD_RE.sub('', sentence.strip(' .;')))} ({where})")
    cmp_words = tidy(m.group("cmp") or "")
    cmp_text = cmp_words if cmp_words in (">", "≥") else (cmp_words + " " if cmp_words else "")
    line = f"Guarantors {tidy(m.group('verb'))} {cmp_text}{m.group('pct')}% of {tidy(m.group('base'))} ({where}; how it is tested is not stated)"
    return [_line(line, MAIN_LIMIT)]


@_guard
def guarantor_coverage(ctx: Ctx) -> dict:
    """A guarantor coverage test if the term sheet has one; else "None stated", with any material-subsidiary threshold."""
    lines, evidence = [], []
    refers: _Cell | None = None  # a coverage section that only points elsewhere
    for cell in _cells(ctx, _COVERAGE_LABELS, 2, sections=True):  # LMA style: its own section
        if not cell.text or lines:
            continue
        if not re.search(r"guarant|obligor", cell.block.label + " " + cell.text, re.IGNORECASE):
            continue  # a "Coverage Test" of something else (interest cover, asset cover)
        sents = _sentences(_undefine(cell.text))
        if _BLANK_RE.match(cell.text):
            lines.append("[ ] - left blank in term sheet")
            evidence.append(_quote_line(ctx, _label_line(cell.block)) or _quote(ctx, cell.block))
        elif _BLANK_PCT_RE.search(cell.text) and sents:  # "[ ]% of consolidated EBITDA"
            lines.append(_line(sents[0], MAIN_LIMIT - 40) + " (level left blank in term sheet)")
            evidence.append(_quote(ctx, cell.block))
        elif re.search(r"\d\s*%", cell.text):
            lines += [_line(s, MAIN_LIMIT) for s in sents[:2] if re.search(r"\d\s*%", s) or s is sents[0]]
            evidence.append(_quote(ctx, cell.block, re.search(r"\d{1,3}(?:\.\d+)?\s*%[^.;]{0,40}", cell.text).group(0)))
        elif _only_refers(cell.text):
            refers = cell
        if cell.unchanged and lines:
            lines[-1] += UNCHANGED
    guarantor_cells = [c for c in _cells(ctx, _GUARANTOR_LABELS, sections=True) if c.text]
    if not lines:
        for cell in guarantor_cells:
            text = _undefine(cell.text)
            m = _coverage_in(text)
            if m:
                lines += _coverage_lines(text, m, cell.block.label)
                if cell.unchanged:
                    lines[-1] += UNCHANGED
                evidence.append(_quote(ctx, cell.block, m.group(0)))
                break
            m = _NON_GUARANTOR_CAP_RE.search(text)
            if m:
                start = max(text.rfind("that ", 0, m.start()), text.rfind("; ", 0, m.start()), text.rfind(". ", 0, m.start()))
                clause = text[start + (5 if text.startswith("that ", start) else 2) if start >= 0 else m.start():m.end()]
                clause = _RESPECTIVELY_RE.sub(" ", re.sub(r"^the\s+", "", clause.strip()))
                lines.append(_line(_cap(clause), MAIN_LIMIT) + (UNCHANGED if cell.unchanged else ""))
                evidence.append(_quote(ctx, cell.block, "may not exceed") or _quote(ctx, cell.block, m.group(0)))
                break
    # the threshold that decides who must guarantee
    threshold, threshold_quote = "", None
    more: list[str] = []  # further lines of a test given in the term sheet's own words
    for cell in guarantor_cells:
        found, words = _material_threshold(cell.text)
        if found:
            threshold, more = found[0], found[1:]
            threshold_quote = _quote(ctx, cell.block, words)
            break
        m = _MATERIALITY_REF_RE.search(cell.text)
        if m:
            threshold = _line(f"Material subsidiaries: {_capped(cell.text, m)} (not given in the term sheet)", MAIN_LIMIT)
            threshold_quote = _quote(ctx, cell.block, m.group(0))
            break
    if not threshold and any(re.search(r"\bMaterial\s+(?:\w+\s+)?(?:Subsidiar|Compan)", c.text) for c in guarantor_cells):
        flow = _flow(ctx)[0]  # the guarantors are the Material Subsidiaries, and the term is defined elsewhere in the term sheet
        found, words = _material_threshold(flow)
        if found:
            m = _MATERIAL_DEFINITION_RE.search(_ABBR_RE.sub(lambda a: a.group(0).replace(".", "\x01"), flow))
            threshold_quote = (_quote_words(ctx, words, _page_of(ctx, m.start())) if m else None) or _quote_words(ctx, words)
            if threshold_quote:
                threshold, more = found[0], found[1:]
    if not threshold:  # the test of which subsidiaries are too small to have to guarantee, in the term sheet's own words
        for cell in guarantor_cells:
            more, words = _immaterial_test(cell.text)
            if more:
                threshold, threshold_quote = more[0], _quote(ctx, cell.block, words)
                more = more[1:]
                break
    # guarantors are the "material" subsidiaries, with no test of what material means (not said where a sentence of the
    # section puts a figure on "material" in words the rules have not read)
    if not threshold and not any(_MATERIAL_FIGURE_RE.search(c.text) for c in guarantor_cells):
        for cell in guarantor_cells:
            m = _MATERIAL_UNDEFINED_RE.search(cell.text)
            if m:
                threshold = "Guarantors include 'material' subsidiaries; no materiality threshold is given"
                threshold_quote = _quote(ctx, cell.block, m.group(0))
                break
    if lines:
        return stated(lines + ([threshold] if threshold else []) + more, evidence + [threshold_quote])
    if refers is not None:  # "Guarantor coverage: to be agreed"
        return by_reference([_line(refers.text, MAIN_LIMIT)] + ([threshold] if threshold else []) + more, [_quote(ctx, refers.block), threshold_quote])
    if threshold:
        return _with_evidence([NONE_STATED, threshold] + more, [threshold_quote])
    # (a section about some of the guarantors, "Subsidiary Guarantors: None", does not say that there are no guarantors at all)
    bare = [c for c in guarantor_cells if _NONE_RE.match(c.text) and not _wordy(_NONE_RE.sub("", c.text, 1), 2)
            and not _SCOPED_LABEL_RE.match(c.block.label)
            and not (re.match(r"^\W*(?:n/?a|not\s+applicable)\W*$", c.text, re.IGNORECASE) and _amendment_page(ctx, c.block.page))]
    if guarantor_cells and len(bare) == len(guarantor_cells):  # "Guarantors: None." - with no guarantors there is nothing for a coverage test to measure
        quote = _quote_line(ctx, _label_line(bare[0].block)) or _quote(ctx, bare[0].block)
        return stated(["None (not stated expressly; the term sheet says there are no guarantors, so there is no guarantor coverage test)"], quote)
    joinder, joinder_quote = _additional_guarantors(ctx)
    if joinder and guarantor_cells:
        return _with_evidence([NONE_STATED, f"No material-subsidiary threshold given; '{joinder}' is listed among the covenants without detail"],
                              [joinder_quote])
    return not_stated(NONE_STATED)


# ---------------------------------------------------------------------------------------------------
# Security and ranking
# ---------------------------------------------------------------------------------------------------

@dataclass
class _Described:
    """How the term sheet describes the facility: "senior unsecured revolving credit facility"."""
    rank: str  # the ranking words, lower case: "senior unsecured"
    phrase: str  # the description as written
    evidence: dict | None


@dataclass
class _Position:
    """Whether the facility is secured, and on what basis the rules say so."""
    secured: bool | None  # None: the term sheet gives no basis
    express: bool = False  # stated in so many words (a collateral section, or the description of the facility)
    why: str = ""  # the basis, worded for the brackets of a line
    evidence: list = field(default_factory=list)
    cell: _Cell | None = None  # the collateral section, if there is one
    kind: str = ""  # what that section does (see _security_kind): "secured", "unsecured", "refers", "blank", "unclear"


def _described_as(phrase: str) -> str:
    """ "described as a senior secured revolving credit facility" / "described as senior secured credit facilities"."""
    if phrase.lower().endswith("s"):  # a plural takes no article
        return f"described as {phrase}"
    return f"described as {'an' if phrase[:1].lower() in 'aeiou' else 'a'} {phrase}"


def _as_described(match: re.Match) -> tuple[str, str]:
    """(ranking words in lower case, the description as written) from a _DESCRIBED_RE match."""
    phrase = _clean(match.group("rank") + " " + match.group("rest"))
    if phrase.isupper():
        phrase = phrase.lower()
    return re.sub(r"[\s-]+", " ", match.group("rank").lower()), phrase


def _described(ctx: Ctx) -> _Described | None:
    """The ranking words used to describe this facility: in a Facility row, in the title, or where the facility is defined.

    The first description that says whether the facility is secured wins over one that only says "senior".
    """
    memo = _memo(ctx)
    if "described" in memo:
        return memo["described"]
    found: list[_Described] = []

    def informative() -> bool:
        return bool(found) and bool(_rank_class(found[-1].rank) or "secured" in found[-1].rank or "unsecured" in found[-1].rank)

    for cell in _cells(ctx, _FACILITY_LABELS, 6):
        if re.search(r"incremental|existing|documentation|fee|increase|swing|letter", cell.block.label, re.IGNORECASE):
            continue
        head = cell.text[:200]
        m = _DESCRIBED_RE.search(head) or _DESCRIBED_LOANS_RE.search(head)
        if m and not _OTHER_DEBT_RE.search(head[:m.start()]):
            rank, phrase = _as_described(m)
            found.append(_Described(rank, phrase, _quote(ctx, cell.block, m.group(0))))
            if informative():
                break
    if not informative():  # the title of the term sheet: the lines before the first label or the first line of running prose
        title = []
        for ln in ctx.raw.page_lines(1):
            if ln.blank:
                continue
            cells = fragments(ln.text, 3)
            if len(title) >= 12 or (cells and cells[0][2].rstrip().endswith(":")) or len(re.findall(r"(?<![\w’'])[a-z]{2,}", ln.text)) >= 6:
                break
            if len(cells) >= 2 and _FIGURE_CELL_RE.match(cells[-1][2]):
                break  # a row of figures (sources and uses, capitalisation): a table has begun, and what it lists is not the title
            title.append(tidy(ln.text))
        m = _DESCRIBED_RE.search(_clean(" ".join(title)))
        quote = _quote_words(ctx, m.group(0), 1) if m else None
        if m and quote:
            rank, phrase = _as_described(m)
            found.append(_Described(rank, phrase, quote))
    if not informative():  # "... a senior unsecured revolving credit facility (the “Facility”)"
        flow = _flow(ctx)[0]
        for m in _DESCRIBED_RE.finditer(flow):
            term = _FACILITY_TERM_RE.match(flow[m.end():m.end() + 80])
            name = tidy(term.group("term")) if term else ""
            other = _OTHER_DEBT_RE.search(flow[max(0, m.start() - 60):m.start()]) and name not in ("Facility", "Facilities")
            if (name and not re.search(r"Existing|Prior|Bridge|Notes", name) and not other
                    and (name in ("Facility", "Facilities") or flow.count(name) >= 5)):
                # "the Facility" is the one the term sheet is about; under any other name, that facility is named throughout,
                # while one it refinances is named once or twice
                rank, phrase = _as_described(m)
                quote = _quote_words(ctx, m.group(0), _page_of(ctx, m.start()))
                if quote:
                    found.append(_Described(rank, phrase, quote))
                    break
    best = next((d for d in found if _rank_class(d.rank) or "secured" in d.rank or "unsecured" in d.rank), found[0] if found else None)
    memo["described"] = best
    return best


def _derived_unsecured(ctx: Ctx) -> tuple[str, dict | None]:
    """Stated facts from which "unsecured" follows when the term sheet has no security provision at all."""
    flow = _flow(ctx)[0]
    if _SECURED_SIGN_RE.search(flow):
        return "", None
    m = _PARI_PASSU_RE.search(flow)
    if m:
        basis = f"the obligations are to rank {tidy(m.group('least') or '')} pari passu with {tidy(m.group('tail'))}"
        quote = _quote_words(ctx, "pari passu " + m.group(0).split("pari passu", 1)[-1], _page_of(ctx, m.start())) or _quote_words(ctx, m.group(0))
        return tidy(basis), quote
    m = _UNSECURED_RATING_RE.search(flow)
    if m:
        tail = m.group(0)[m.group(0).lower().find("senior unsecured"):]
        quote = _quote_words(ctx, tail, _page_of(ctx, m.start())) or _quote_words(ctx, m.group(0), _page_of(ctx, m.start()))
        return f"pricing is {tidy(m.group(0))}", quote
    return "", None


def _says_secured(described: _Described | None) -> bool | None:
    """What the description of the facility says about security: True ("senior secured", "first lien"), False ("unsecured"), None."""
    words = described.rank.split() if described else []
    if "unsecured" in words:
        return False
    return True if "secured" in words or "lien" in words else None


def _contradiction(pos: _Position, described: _Described | None) -> str:
    """Reviewer note where the Collateral / Security row and the description of the facility disagree, else ""."""
    says = _says_secured(described)
    if pos.cell is None or says is None or pos.kind not in ("secured", "unsecured") or says == (pos.kind == "secured"):
        return ""
    row = "says there is no security" if pos.kind == "unsecured" else "describes security"
    return f"The Collateral / Security row {row}, but the facility is {_described_as(described.phrase)}: the term sheet contradicts itself; check both."


def _security_kind(ctx: Ctx, cell: _Cell) -> tuple[str, str]:
    """What a Collateral / Security row does, judged on its first sentence, and the words that decide it.

    "unsecured"  it says there is no security ("Unsecured", "None", "No security will be provided", "will not be secured")
    "secured"    it grants or describes security ("secured by ...", liens, pledges, charges, "the Collateral")
    "refers"     it only points to another document or to later agreement
    "blank"      the value is left blank ("[ ]")
    "unclear"    anything else: security that springs on a later event, one facility secured and another not, a
                 statement with exceptions, or text with none of the words above. The row is reported as it stands
                 and nothing is concluded from it.
    ""           nothing readable beside the label
    """
    text = _undefine(cell.text)
    if _BLANK_RE.match(cell.text):
        return "blank", ""
    first = (_sentences(text) or [text])[0]
    none, grant = _NO_SECURITY_RE.search(first), _GRANT_RE.search(first)
    if none and (grant is None or none.start() <= grant.start()):
        if re.match(r"^\W*(?:n/?a|not\s+applicable)\W*$", first, re.IGNORECASE) and _amendment_page(ctx, cell.block.page):
            return "", ""  # in an amendment table "N/A" says nothing is being changed, not that there is no security
        if none.group(0).lower().startswith("no ") and _EXCEPT_FOR_RE.search(first[none.end():]):
            return "unclear", ""
        return "unsecured", none.group(0)
    if grant:
        if _ALSO_UNSECURED_RE.search(first[grant.end():]) or _SPRINGING_RE.search(first[:grant.start()]):
            return "unclear", ""
        return "secured", grant.group(0)
    if _only_refers(text):
        return "refers", ""
    return ("unclear", "") if _wordy(text, 3) else ("", "")


def _position(ctx: Ctx) -> _Position:
    """Whether the facility is secured: from the collateral section, else the description of the facility, else derived."""
    memo = _memo(ctx)
    if "position" in memo:
        return memo["position"]
    pos = _Position(None)
    rows = [c for c in _cells(ctx, _SECURITY_LABELS, 3, sections=True) if c.text]
    described = _described(ctx)
    read = [(c, *_security_kind(ctx, c)) for c in rows]
    # the first row that says whether there is security; failing that, the first row that says anything
    pick = next((r for r in read if r[1] in ("secured", "unsecured")), None) or next((r for r in read if r[1]), None)
    if pick:
        cell, kind, words = pick
        if (kind == "unsecured" and described and _says_secured(described) is True
                and re.match(r"^\W*(?:n/?a|not\s+applicable)\W*$", cell.text, re.IGNORECASE)):
            kind = ""  # "N/A" beside a facility described as secured: the row is not about whether there is security
        if kind == "unsecured":
            pos = _Position(False, True, "", [_quote(ctx, cell.block, words) or _quote(ctx, cell.block)], cell, kind)
        elif kind == "secured":
            pos = _Position(True, True, "collateral is provided for", [_quote(ctx, cell.block)], cell, kind)
        elif kind:  # the row is there, but does not itself say whether the facility is secured
            pos = _Position(None, False, "", [], cell, kind)
    if pos.secured is None and described:
        words = described.rank.split()
        if "unsecured" in words:
            pos = _Position(False, True, _described_as(described.phrase), [described.evidence], pos.cell, pos.kind)
        elif "secured" in words or "lien" in words:
            pos = _Position(True, True, _described_as(described.phrase), [described.evidence], pos.cell, pos.kind)
    if pos.secured is None and not rows:  # no Collateral / Security row of any kind: the position may be derived from stated facts
        basis, quote = _derived_unsecured(ctx)
        if basis and quote:
            pos = _Position(False, False, basis, [quote])
    memo["position"] = pos
    return pos


def _clause_from(text: str, start: int, limit: int = 300) -> str:
    """The clause that begins at ``start``, to its end: a semicolon, a full stop, the bracket that closes around it, or
    a comma that is not followed by a further percentage ("65% of ..., and 100% of ..."). Bracketed asides inside it
    are left out."""
    out, depth = [], 0
    for i in range(start, min(len(text), start + 900)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0:
            if ch == ";" or (ch == "." and (i + 1 >= len(text) or text[i + 1].isspace())):
                break
            if ch == "," and not re.match(r",\s*(?:and\s+|or\s+)?\d{1,3}\s*%", text[i:i + 16]):
                break
            out.append(ch)
    return _fit(re.sub(r"\s+([,.;:])", r"\1", tidy("".join(out))), limit)


def _capped(text: str, m: re.Match, group: str | int = 0) -> str:
    """A regex capture as it may be printed: one that ran into the length cap of its pattern, and so stops in the middle
    of a phrase, is taken back to a word boundary and marked as cut."""
    got, end = tidy(m.group(group)), m.end(group)
    if end >= len(text) or text[end] in "();.,":
        return got  # the capture ends where its clause ends
    if text[end].isspace() and re.match(r"\s*(?:(?:and|or)\s+)?\(", text[end:end + 8]):
        return got  # ... or where the next list item begins
    if " " not in got:
        return got
    return (got if text[end].isspace() else got.rsplit(" ", 1)[0]).rstrip(" ,;:") + " …"


def _item_head(item: str) -> str:
    """ "(a) All present and future shares of capital stock of (...) each of its ... subsidiaries (limited ...)" -> its head clause."""
    m = _ITEM_RE.match(item.strip())
    if not m:
        return ""
    plain = _no_brackets(m.group(2))
    tail = _ITEM_TAIL_RE.search(plain)
    body = plain[:tail.start()] if tail else plain
    head = _fit(_line(body, 100_000), 200)
    # detail left off the head goes unmarked ("..., including machinery, ..."), but not words that take something out of the item
    # ("..., other than Excluded Accounts", "(excluding ...)")
    raw_tail = _ITEM_TAIL_RE.search(m.group(2))
    aside = re.search(r"\(\s*(?:other\s+than|excluding|except|but\s+not|not\s+including)\b", m.group(2)[:raw_tail.start()] if raw_tail else m.group(2), re.IGNORECASE)
    if ((tail and re.search(r"exclud|other\s+than", tail.group(0), re.IGNORECASE)) or aside) and not head.endswith("…"):
        head += " …"
    return f"({m.group(1)}) {_lower_first(head)}"


def _collateral_extras(ctx: Ctx, cell: _Cell, main_text: str) -> tuple[list[str], list]:
    """Exclusions, share-pledge limits, definitions the description relies on, and release wording."""
    text, lines, evidence = cell.text, [], []
    m = _PLEDGE_LIMIT_RE.search(text)
    if m:
        pledged = _clause_from(text, m.start("x"))
        if int(m.group("pct")) < 100 or m.group("lead").lower().startswith("limited"):  # a pledge of less than all the shares
            # whose shares the limit is about, where the clause itself says so: "limited, in the case of <whom>, to (a pledge of) N% ..."
            # (not from the word "foreign" somewhere nearby: that may be said of something else)
            scope = _PLEDGE_SCOPE_RE.search(text[max(0, m.start("x") - 320):m.start("x")])
            about = scope.group("whose").lower() if scope else ""
            whose = " (controlled foreign corporations)" if "controlled foreign corporation" in about else " (foreign subsidiaries)" if "foreign" in about else ""
            lines.append(_line(f"Share pledge limit{whose}: {pledged}", MAIN_LIMIT))
        else:
            lines.append(_line(f"Share pledge: {pledged}", MAIN_LIMIT))
        evidence.append(_quote(ctx, cell.block, m.group("x")))
    excluded = []
    listed = _EXCLUDED_LIST_RE.search(text)
    if listed:  # "the Collateral shall exclude the following: (i) ...; (ii) ..." - the items in their own words, and how many there are
        items = _list_items(text[listed.end():])
        items[-1] = (_sentences(items[-1]) or [items[-1]])[0]
        heads = []
        for i in (_ITEM_RE.match(x.strip()) for x in items):
            if i:  # the head of the item; whatever qualifies it further is marked as left out
                whole = _line(_no_brackets(i.group(2)), 100_000)
                head = _EXCLUSION_END_RE.split(whole, 1)[0]
                heads.append(f"({i.group(1)}) " + (_fit(head, 110) if len(head) > 110 or head == whole else head.rstrip(" ,;") + " …"))
        shown: list[str] = []
        for head in heads:
            if len("; ".join(shown + [head])) > MAIN_LIMIT - 45:
                break
            shown.append(head)
    # inside a statement of what the collateral leaves out, "excluding" carves back in: such words count only before it
    left_out = _EXCLUSION_RES[-1].search(text)
    upto = listed.start() if listed else left_out.start() if left_out else len(text)
    for rx in _EXCLUSION_RES if not listed else _EXCLUSION_RES[:1]:
        for x in rx.finditer(text if rx is _EXCLUSION_RES[-1] else text[:upto]):
            item = _EXCLUSION_END_RE.split(_capped(text, x, "x"), 1)[0].strip(" ,")
            if _item_markers(item):
                continue  # a list the rules could not follow from its first item: a piece of it must not stand for the whole
            if _wordy(item, 1) and _norm(item) not in {_norm(e) for e in excluded}:
                excluded.append(item)
    if listed:
        if excluded:  # an exclusion named before the list ("with an exclusion of all real property")
            lines.append(_line("Exclusions: " + "; ".join(excluded[:2]), MAIN_LIMIT))
        if shown:
            label = "Exclusions" if len(shown) == len(heads) else f"Exclusions (first {len(shown)} of the {len(heads)} listed)"
            lines.append(f"{label}: " + "; ".join(shown))
            evidence.append(_quote(ctx, cell.block, listed.group(0)))
    elif excluded:
        if len(excluded) == 1 and excluded[0].lower().startswith("exclusion"):
            lines.append(_line(_cap(excluded[0])))
        else:
            named = [e for e in excluded[:3] if not e.lower().startswith("exclusion")] or excluded[:1]
            lines.append(_line("Exclusions: " + "; ".join(named), MAIN_LIMIT))
    definitions = []
    for term, body in _SHORT_DEFINITION_RE.findall(text)[:6]:
        if _norm(term)[: max(4, len(_norm(term)) - 3)] in _norm(main_text):
            definitions.append(_line(f"{term}: {body}"))
    lines += _pack(definitions[:2], MAIN_LIMIT)
    for s in _whole_sentences(_undefine(text))[1:]:  # (a sentence whole: the conditions of a release may be set out as a list)
        if _orphan_item(s):
            continue  # an item of a list whose opening the rules could not find: not a sentence that can stand alone
        if _RELEASE_RE.search(s) and re.search(r"security|liens?\b|collateral", s, re.IGNORECASE) and not _DEFINITION_SENTENCE_RE.match(s):
            lines += _release_lines(s)
            evidence.append(_quote(ctx, cell.block, (_RELEASED_RE.search(s) or _RELEASE_RE.search(s)).group(0)))
            break
    return lines, evidence


def _clause_lines(text: str, most: int = 4) -> list[str]:
    """A short cell as lines: its sentences and semicolon clauses as they stand. A very short clause ("debentures") joins
    the line before it, a long one is broken in two, and a release clause is restructured."""
    lines: list[str] = []
    clauses: list[str] = []
    for sentence in _whole_sentences(text):
        about_release = _RELEASE_RE.search(sentence) and re.search(r"security|liens?\b|collateral", sentence, re.IGNORECASE)
        if clauses and about_release and _item_markers(sentence):
            clauses.append(sentence)  # a release whose conditions are a list ("... if (a) X; (b) Y; and (c) Z"): kept whole
        else:
            clauses += re.split(r";\s+", sentence)
    for clause in clauses:
        clause = clause.strip()
        if not _wordy(clause, 1) or _DEFINITION_SENTENCE_RE.match(clause):
            continue
        if lines and _RELEASE_RE.search(clause) and re.search(r"security|liens?\b|collateral", clause, re.IGNORECASE):
            new = _release_lines(clause)
        else:
            new = _split_long(_line(_cap(clause), 100_000))
        if lines and len(new) == 1 and len(new[0]) <= 40 and len(lines[-1]) + len(new[0]) + 2 <= LINE_LIMIT:
            lines[-1] += "; " + _lower_first(new[0])
        elif len(lines) < most:
            lines += new
    return lines


def _list_items(text: str) -> list[str]:
    """The items of "(a) ...; (b) ...; and (c) ..." (or "(a) ... and (b) ..."), each with its marker.

    Only markers that continue the sequence the list opens with count, and only outside brackets, so that a
    "(i) ... and (ii) ..." inside item (a), or "clauses (a) and (b) above", does not split an item.
    """
    opening = re.match(r"\s*\((a|i|1)\)\s", text)
    if not opening:
        return [text]
    first = opening.group(1)
    sequence = {"a": "bcdefghijklmnop", "i": ["ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii",
                                              "xviii", "xix", "xx"],
                "1": [str(n) for n in range(2, 21)]}[first]
    items, start = [], 0
    for marker in sequence:
        found = None
        # strongest separator first: the items of a list end in semicolons or, each a sentence of its own, in full stops
        for rx, slack in ((r"[;.]\s+(?:and\s+|or\s+)?(?=\(%s\)\s)", 0), (r",?\s+(?:and|or)\s+(?=\(%s\)\s)", 0), (r",\s+(?=\(%s\)\s)", 0),
                          (r";\s+(?:and\s+|or\s+)?(?=\(%s\)\s)", 1)):  # (last: a bracket the term sheet opens and never closes)
            for m in re.finditer(rx % marker, text[start:]):
                item = text[start:start + m.start()]
                if 0 <= item.count("(") - item.count(")") <= slack:
                    found = m
                    break
            if found:
                break
        if not found:
            break
        item = text[start:start + found.start()]
        # the list has ended if its numbering starts again, or a long run of other text lies, before the next marker: that marker
        # belongs to a later enumeration ("In addition, (a) ..., (b) ...")
        if any(label == first for at, _, label in _item_markers(item) if at > 0) or len(item) > 1500:
            break
        items.append(item.strip())
        start += found.end()
    items.append(text[start:].strip())
    return items


def _describe_security(ctx: Ctx, cell: _Cell) -> tuple[list[str], list]:
    """The collateral as lines: a slide's bullets, a lettered list, or the "secured by ..." clause; then the extras."""
    text = cell.text
    lines, evidence = [], []
    if _BULLET_RE.search(text):  # a slide cell: one line per bullet, marked against the existing column of an amendment
        bullets = [b.strip(" ;") for b in _BULLET_RE.split(text) if b.strip(" ;")]
        old = {_norm(b) for b in _BULLET_RE.split(_existing_text(ctx, cell)) if b.strip(" ;")}
        mark = bool(old) and any(_norm(b) not in old for b in bullets)
        for b in bullets[:6]:
            line = _line(b, MAIN_LIMIT)
            if mark:
                line += UNCHANGED if _norm(b) in old else " (proposed change)"
            lines.append(line)
            if len(evidence) < 3 and (not evidence or _norm(b) not in old):
                evidence.append(_quote(ctx, cell.block, b))
        if cell.unchanged and lines:
            lines[-1] += UNCHANGED
        return lines, evidence
    listed = _LIST_START_RE.search(text)
    if listed and _EXCLUDES_LEAD_RE.search(text[:listed.start()]):
        listed = None  # "The Collateral will exclude: (i) ..." - a list of what is left out, read with the exclusions
    if listed:  # "... in all of the following: (a) ...; (b) ...; and (c) ..."
        lead = _undefine(text[:listed.start()])
        following = _FOLLOWING_RE.search(lead)
        lead = lead[:following.end()] if following else lead
        by = _SECURED_BY_RE.search(lead + " ")
        if by and not lead[by.end():].strip(" :"):  # "... will be secured by:" - the list itself is the collateral
            lead = "Secured by"
        lines.append(_line(lead, MAIN_LIMIT) + ":")
        evidence.append(_quote(ctx, cell.block, by.group(0)) if by else _quote(ctx, cell.block))
        items = _list_items(text[listed.end():])
        if items:
            items[-1] = (_sentences(items[-1]) or [items[-1]])[0]
        heads = [h for h in (_item_head(i) for i in items[:8]) if h]
        lines += _pack(heads, MAIN_LIMIT)[:3]
        main_text = " ".join(lines)
    elif len(text) <= 520:  # a short cell: its clauses as they stand
        lines = _clause_lines(_undefine(text))
        evidence.append(_quote(ctx, cell.block))
        if cell.unchanged and lines:
            lines[-1] += UNCHANGED
        return lines, evidence
    else:  # running text: the "secured by ..." clause
        sents = _sentences(_undefine(text)) or [text]
        first = sents[0]
        m = _SECURED_BY_RE.search(first)
        head = "Secured by " + first[m.end():] if m and len(first) - m.end() > 20 else first
        head = _COLLATERAL_TAIL_RE.split(_PROVISO_RE.split(head, 1)[0], 1)[0]
        items = _later_items(sents)
        if items and re.search(r"\((?:a|i|1|A|I)\)\s", head):  # "secured by (i) X; (ii) Y; and (iii) Z": every item, not the first alone
            head = head.rstrip(" ,;") + "; " + "; ".join(items)
        lines += _split_long(_line(_cap(head), 100_000))
        evidence.append(_quote(ctx, cell.block, first[m.start():] if m else first))
        main_text = head
    extras, extra_quotes = _collateral_extras(ctx, cell, main_text)
    if cell.unchanged and lines:
        lines[-1] += UNCHANGED
    return lines + extras, evidence + extra_quotes


def _unsecured_head(clause: str) -> tuple[str, str]:
    """The first line for a row that says there is no security, and what is left of its opening clause for a line of its own:
    "Unsecured" for a bare statement, "Unsecured (no security will be provided)" where the term sheet puts it another way."""
    if _PLAIN_UNSECURED_RE.match(clause):
        return "Unsecured", ""
    m = re.match(r"^\W*(?:senior\s+)?unsecured\b\W*(?P<rest>.*)$", clause, re.IGNORECASE)  # "Unsecured, provided that ..."
    if m:
        return "Unsecured", _cap(m.group("rest"))
    m = re.match(r"^\W*(?:none|nil|n/?a|not\s+applicable)\s*[(\-–—,:]\s*(?P<rest>.+?)\)?\W*$", clause, re.IGNORECASE)  # "None (investment grade)"
    if m and _wordy(m.group("rest"), 1):
        bare = re.match(r"^\W*(?:senior\s+)?unsecured(?:\s+facilit\w+)?\W*$", m.group("rest"), re.IGNORECASE)
        return ("Unsecured" if bare else f"Unsecured ({_lower_first(_line(m.group('rest'), 160))})"), ""
    if len(clause) <= 160 and _wordy(clause):
        return f"Unsecured ({_lower_first(_line(clause, 160))})", ""  # how the term sheet puts it
    return "Unsecured", clause


def _release_section(ctx: Ctx) -> tuple[list[str], dict | None]:
    """The trigger for releasing the collateral, where the term sheet gives it a section of its own ("Release of Collateral:")."""
    for cell in _cells(ctx, _RELEASE_LABELS, 2, sections=True):
        if not cell.text:
            continue
        about = cell.block.label + " " + cell.text
        reinstated = bool(_REINSTATE_RE.search(about)) and not re.search(
            r"\b(?:no|not|never|without)\b[^.;]{0,40}(?:" + _REINSTATE_RE.pattern + r")", about, re.IGNORECASE)
        for s in _whole_sentences(cell.text)[:2]:  # (a sentence whole: its conditions may be set out as a list)
            if _DEFINITION_SENTENCE_RE.match(s) or _orphan_item(s) or not _RELEASES_RE.search(_no_brackets(s)):
                continue
            words = re.search(r"releas\w*\s+(?:the\s+|all\s+|any\s+)?(?:liens?|security|collateral)[^.;()]{0,40}", s, re.IGNORECASE)
            return _release_lines(s, reinstated), (_quote(ctx, cell.block, words.group(0)) if words else None) or _quote(ctx, cell.block)
    return [], None


def _cash_collateral(ctx: Ctx) -> tuple[str, dict | None]:
    """A requirement to post cash collateral written into the Facility row (an amendment that adds credit support)."""
    for cell in _cells(ctx, _FACILITY_LABELS, 6):
        m = _CASH_COLLATERAL_RE.search(cell.text)
        if m:
            label = "Cash collateral" + (" (proposed change)" if _SAME_EXCEPT_RE.search(cell.text[:m.start()]) else "")
            return _line(f"{label}: {_no_brackets(m.group(0))}", MAIN_LIMIT), _quote(ctx, cell.block, "post cash collateral")
    return "", None


@_guard
def security(ctx: Ctx) -> dict:
    """ "Unsecured", or what the collateral is, with exclusions and release triggers."""
    pos = _position(ctx)
    cell = pos.cell
    if cell is None:
        unreadable = [c for c in _cells(ctx, _SECURITY_LABELS, 2, sections=True) if not c.text and c.unchanged]
        if unreadable:  # "Same as existing" and the existing column could not be read
            return by_reference(["Same as existing (existing terms not restated in the term sheet)"], _quote(ctx, unreadable[0].block))
        if pos.secured is False and pos.express:
            return stated([f"Unsecured ({pos.why})"], pos.evidence)
        if pos.secured is False:
            return stated([f"Unsecured (not stated expressly; no security or collateral provision, and {pos.why})"], pos.evidence,
                          "Derived: the term sheet has no security or collateral section.")
        if pos.secured and _cells(ctx, _SECURITY_LABELS, 2, sections=True):
            return stated([f"Secured ({pos.why})"], pos.evidence, "The term sheet has a Collateral / Security row that the rules could not read as a "
                          "description of collateral: check the row. The position is taken from the description of the facility.")
        if pos.secured:  # (said of the headings the rules read, not of the whole document: the collateral may be described elsewhere)
            return stated([f"Secured ({pos.why}); collateral not described under a Collateral / Security heading"], pos.evidence,
                          "No Collateral / Security row was found; the position is taken from the description of the facility.")
        return not_stated()
    if pos.secured is False:
        clauses = [c for c in re.split(r";\s+", " ; ".join(_sentences(_undefine(cell.text)))) if c.strip()]
        head = "Unsecured"
        if pos.kind != "unsecured":  # the row itself does not say so: the description of the facility does
            head += f" ({pos.why})" if pos.why else ""
        elif clauses:
            head, rest = _unsecured_head(clauses[0])
            clauses = ([rest] if rest else []) + clauses[1:]
        lines = [head + (UNCHANGED if cell.unchanged else "")]
        for clause in clauses:  # what else the section says about security
            plain = len(clause) < 90 and (_UNSECURED_RE.search(clause) or _NONE_RE.match(clause))
            if not plain and len(lines) < 3 and re.search(r"secur|collateral|\bliens?\b|pledge", clause, re.IGNORECASE):
                lines.append(_line(_cap(clause), MAIN_LIMIT))  # e.g. security to be granted if a rating is lost
        return stated(lines, pos.evidence, _contradiction(pos, _described(ctx)))
    if pos.secured is None:
        if pos.kind == "blank":
            return stated(["[ ] - left blank in term sheet"], _quote_line(ctx, _label_line(cell.block)) or _quote(ctx, cell.block))
        if pos.kind == "refers":  # the section only points elsewhere
            return by_reference([_line(cell.text, MAIN_LIMIT) + (UNCHANGED if cell.unchanged else "")], _quote(ctx, cell.block))
        # the row does not say in so many words whether the facility is secured: it is given as it stands, nothing is concluded
        lines = _clause_lines(_undefine(cell.text))[:3]
        if cell.unchanged and lines:
            lines[-1] += UNCHANGED
        note = "The Security / Collateral row does not say in so many words whether the facility is secured; its text is given as it stands."
        return stated(lines, _quote(ctx, cell.block), (note + " " + _mixed_note([cell])).strip())
    described = _described(ctx)
    if pos.kind == "blank":  # secured by description; the row that should say what the collateral is has been left blank
        return stated([f"Secured ({pos.why}); collateral: [ ] - left blank in term sheet"],
                      pos.evidence + [_quote_line(ctx, _label_line(cell.block))])
    lines, evidence = _describe_security(ctx, cell)
    if not lines:
        return stated([f"Secured ({pos.why})"], pos.evidence) if pos.kind != "secured" and pos.why else not_stated()
    if described and "secured" in described.rank.split() and not _SAYS_SECURED_RE.search(lines[0]):
        lines[0] = f"Secured ({_described_as(described.phrase)}): {_lower_first(lines[0])}"
    release, release_quote = [], None
    if not any(x.startswith("Release") for x in lines):  # a release trigger set out under a heading of its own
        release, release_quote = _release_section(ctx)
    cash, cash_quote = _cash_collateral(ctx)
    consent, consent_quote = _consent_to_release(ctx, _RELEASE_OF_COLLATERAL_RE)
    tail = release + [x for x in (cash, consent) if x]
    # a row holds eight lines: a release trigger is given whole or not at all, so it is the detail of the description that gives way
    lines = lines[:max(2, 8 - len(tail))] + tail
    quotes = [e for e in evidence if e]
    if release_quote:
        picked = quotes[:1] + [cash_quote, release_quote, consent_quote] + quotes[1:]
    else:
        picked = quotes[:1] + [cash_quote] + quotes[1:2] + [consent_quote] + quotes[2:]
    if _only_refers(cell.text):
        return by_reference(lines[:8], picked, _mixed_note([cell]))
    unclear = ("The facility is described as secured, but the Security / Collateral row does not say in so many words what secures it; "
               "its text is given as it stands.") if pos.kind == "unclear" else ""
    return stated(lines[:8], picked, " ".join(n for n in (unclear, _mixed_note([cell]), _contradiction(pos, described)) if n))


def _rank_class(words: str) -> str:
    """The template's ranking category for the ranking words of a description, or ""."""
    if re.search(r"\bsuper ?(?:senior|priority)\b", words):
        return "Super Senior"
    if re.search(r"\bsubordinated\b", words):
        return "Subordinated"
    if re.search(r"\bsenior secured\b|\b(?:first|second) (?:lien|ranking)\b", words):  # a second lien facility is secured debt, not subordinated debt
        return "Senior Secured"
    if re.search(r"\bsenior unsecured\b", words):
        return "Senior Unsecured"
    return ""


def _security_basis(pos: _Position) -> str:
    """The security position in the words used inside a ranking line's brackets."""
    if pos.secured:
        if pos.cell is not None and pos.kind == "secured":
            return "facility is secured by the collateral described in the term sheet"
        return f"facility is secured: {pos.why}" if pos.why else "facility is secured"
    if pos.express:
        return f"facility is unsecured: {pos.why}" if pos.why else "facility is stated to be unsecured"
    return f"unsecured position not stated expressly: no security or collateral provision, and {pos.why}"


def _lien_label(ctx: Ctx) -> tuple[str, dict | None]:
    """A presentation that labels the revolver "First Lien RCF" outside the terms table (possibly wrapped, as a chart label is).

    Only when the document is about a revolver alone: where it also has term loans, a first lien revolver named in
    passing need not be the facility the row is about.
    """
    if _TERM_DEBT_RE.search(ctx.text or ""):
        return "", None
    for page, text in enumerate(ctx.raw.pages, 1):
        for m in _LIEN_LABEL_RE.finditer(text):
            if "\n" in m.group("gap"):  # wrapped: the second line must sit under the first, as the lines of one label do
                lien_col = m.start("lien") - (text.rfind("\n", 0, m.start("lien")) + 1)
                what_col = m.start("what") - (text.rfind("\n", 0, m.start("what")) + 1)
                if not lien_col - 12 <= what_col <= lien_col + len(m.group("lien")):
                    continue
            label = tidy(f"{m.group('lien')} {m.group('what')}")
            quote = _quote_words(ctx, m.group("lien") if "\n" in m.group("gap") else label, page)
            if quote:
                return label, quote
    return "", None


def _own_rank(words: str) -> tuple[str, str]:
    """(the ranking words a "Ranking" row gives the facility itself, the ranking words of debt it ranks equally with).

    ``words`` is the row in lower case with hyphens turned into spaces. Ranking words that are denied ("will not be
    subordinated") or that describe the debt the facility is compared with ("behind the Super Senior Revolving
    Facility", "pari passu with the Senior Secured Notes") are not the facility's own.
    """
    equal = ""
    for m in _RANK_IN_PROSE_RE.finditer(words):
        before = words[max(0, m.start() - 90):m.start()]
        if _RANK_NEGATED_RE.search(before):
            continue
        if _RANK_COMPARED_RE.search(before):
            if not equal and re.search(r"pari passu[^.;]{0,70}$", before):
                equal = m.group(0)
            continue
        return m.group(0), equal
    return "", equal


def _rank_said(cell: _Cell, category: str) -> str:
    """What a "Ranking" row adds to the category, for the brackets of the line."""
    text = _undefine(cell.text)
    bracketed = _BRACKETED_RE.match(text)
    if bracketed:
        text = bracketed.group(1)
    sents = [s.strip(" .") for s in _sentences(text)] or [text.strip(" .")]
    # the category itself, where the row opens with it ("Senior secured, first lien" -> "first lien")
    said = re.sub(r"^\W*" + r"[\s-]+".join(re.escape(w) for w in category.split()) + r"\b\s*(?:[,;:.\-–]+\s*|$)", "", sents[0], flags=re.IGNORECASE)
    if not _wordy(said, 1) and len(sents) > 1:  # the first sentence is the category alone: the next one qualifies it
        said = sents[1]
    if _wordy(said, 1):
        said = _lower_first(_fit(_line(said, 100_000), 200))
    else:
        said = f"stated in the {cell.block.label.capitalize() if cell.block.label.isupper() else cell.block.label} row"
    return said + ("; in square brackets in the term sheet" if bracketed else "")


@_guard
def ranking(ctx: Ctx) -> dict:
    """Senior Unsecured / Senior Secured / Super Senior / Subordinated, with a short qualifier and the basis."""
    pos = _position(ctx)
    described = _described(ctx)
    qualifiers, evidence = [], []
    category, express = "", False
    open_row: _Cell | None = None  # a Ranking row that is blank or only points elsewhere
    unplaced: _Cell | None = None  # a Ranking row whose wording fits none of the template's categories
    for cell in _cells(ctx, _RANKING_LABELS, 1, sections=True):  # a "Ranking" section
        if not cell.text:
            continue
        if _BLANK_RE.match(cell.text):
            open_row = cell
            continue
        words = re.sub(r"[\s-]+", " ", cell.text.lower())
        own, equal = _own_rank(words)
        category = _rank_class(own)
        if not category and (own or equal or re.search(r"pari passu|unsubordinated|not (?:be )?subordinated", words)):
            if pos.secured:
                category = "Senior Secured"
            elif pos.secured is False:
                category = "Senior Unsecured"
            elif _rank_class(equal):  # "pari passu with all other senior unsecured obligations"
                category = _rank_class(equal)
            elif re.search(r"(?<!not )(?<!not be )\bunsecured\b", words):
                category = "Senior Unsecured"
            elif re.search(r"(?<!not )(?<!not be )\bsecured\b", words):
                category = "Senior Secured"
        if category:
            express = True
            qualifiers.append(_rank_said(cell, category) + (", unchanged from existing terms" if cell.unchanged else ""))
            evidence.append(_quote(ctx, cell.block))
        elif _only_refers(cell.text):
            open_row = cell
        elif _wordy(cell.text, 3):
            unplaced = cell  # the row says something about ranking, but not which of the template's categories it is
    if not category and described:
        # the ranking words that open the description, or any others in it ("unsecured subordinated term loan facility")
        category = _rank_class(described.rank) or _rank_class(re.sub(r"[\s-]+", " ", described.phrase.lower()))
        if not category and "senior" in described.rank.split() and pos.secured is not None:
            category = "Senior Secured" if pos.secured else "Senior Unsecured"
        if category:
            express = True
            qualifiers.append(_described_as(described.phrase))
            evidence.append(described.evidence)
            if "secured" not in described.rank:  # "senior revolving credit facility": say where secured / unsecured comes from
                qualifiers.append(_security_basis(pos))
                evidence += pos.evidence
    if not category:  # derived from the security position
        if pos.secured is None:
            if open_row is not None and _BLANK_RE.match(open_row.text):
                return stated(["[ ] - left blank in term sheet"], _quote_line(ctx, _label_line(open_row.block)) or _quote(ctx, open_row.block))
            if open_row is not None:  # "To be agreed", "Consistent with the Existing Credit Agreement"
                return by_reference([_line(open_row.text, MAIN_LIMIT) + (UNCHANGED if open_row.unchanged else "")], _quote(ctx, open_row.block))
            if unplaced is not None:  # the term sheet does deal with ranking: its words are given, not "not stated"
                said = (_sentences(_undefine(unplaced.text)) or [unplaced.text])[0]
                return stated([_line(f"Ranking as stated in the term sheet: {_lower_first(said)}", MAIN_LIMIT) + (UNCHANGED if unplaced.unchanged else "")],
                              _quote(ctx, unplaced.block),
                              "The Ranking row does not say whether the facility is secured or unsecured, and nothing else in the term sheet does, so "
                              "the row could not be put into one of the template's categories; its wording is given as it stands.")
            return not_stated()
        category = "Senior Secured" if pos.secured else "Senior Unsecured"
        if pos.secured or pos.express:
            qualifiers.append("not stated expressly; " + _security_basis(pos))
        else:
            qualifiers.append(f"not stated expressly; no security or collateral provision, and {pos.why}")
        evidence += pos.evidence
        if not pos.secured and "rating" not in qualifiers[-1]:  # pricing off senior unsecured ratings supports the reading
            m = _UNSECURED_RATING_RE.search(_flow(ctx)[0])
            quote = _quote_words(ctx, m.group(0)[m.group(0).lower().find("senior unsecured"):], _page_of(ctx, m.start())) if m else None
            if m and quote:
                qualifiers.append(f"pricing is {tidy(m.group(0))}")
                evidence.append(quote)
    # the ranking found and the Collateral / Security row must not be read as agreeing when they do not
    disagrees = (category == "Senior Unsecured" and pos.kind == "secured") or (category == "Senior Secured" and pos.kind == "unsecured")
    if disagrees:
        qualifiers.append("but the Collateral / Security row " + ("describes security" if pos.kind == "secured" else "says there is no security"))
        evidence = evidence[:2] + pos.evidence
    elif pos.cell is not None and pos.secured and pos.kind == "secured":  # qualifiers from a collateral section that grants security
        m = _FIRST_PRIORITY_RE.search(pos.cell.text)
        if m:
            qualifiers.append(_lower_first(_no_brackets(_clean(m.group(0)))))
            evidence.append(_quote(ctx, pos.cell.block, "first"))
        m = _APPLIED_FIRST_RE.search(pos.cell.text)
        if m:
            qualifiers.append(_capped(pos.cell.text, m))
            evidence.append(_quote(ctx, pos.cell.block, "applied first"))
    if (category == "Senior Secured" and not any(re.search(r"\b(?:first|second)\b", q.lower()) for q in qualifiers)
            and not (described and "second" in described.rank)):
        label, quote = _lien_label(ctx)
        if label:
            qualifiers.append(f"referred to as '{label}' elsewhere in the document")
            evidence.append(quote)
    seen: list[str] = []
    for q in qualifiers:
        if q and _norm(q) not in {_norm(s) for s in seen}:
            seen.append(q)
    line = category + (f" ({'; '.join(seen)})" if seen else "")
    note = "" if express else "Ranking is derived from the security position; the term sheet does not state it expressly."
    if disagrees:
        note = "The ranking wording and the Collateral / Security row disagree: the term sheet contradicts itself; check both."
    return stated([_fit(line, MAIN_LIMIT + 60)], evidence, note)


RULES: dict = {
    "guarantors": guarantors,
    "guarantor_coverage": guarantor_coverage,
    "security": security,
    "ranking": ranking,
    "jurisdiction_topco": jurisdiction_topco,
}
