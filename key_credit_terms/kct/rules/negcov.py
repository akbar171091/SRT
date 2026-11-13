"""Rules for the Non-Financial Covenants rows.

Fields: negative_pledge, permitted_acquisitions, permitted_disposals, permitted_distributions,
permitted_indebtedness, permitted_loans, permitted_guarantees, permitted_payments, other_covenants.

How the rules work
------------------
Term sheets deal with the negative covenants in one of three ways, and the module reads each of them.

1. A covenant list (US style): a "Negative Covenants:" section, a general "Covenants:" section, a sentence
   of one ("Negative covenants will include limitations on ...") or a lettered sub-section of one ("(a)
   Affirmative Covenants - ... (b) Negative Covenants - Restrictions on: (i) ...", ``_sub_sections``), that
   names the covenants - separated by semicolons, commas, bullets or (i) / (a) / (1) numbering - usually after
   words that point to an existing agreement ("Substantially similar to the Existing Credit Agreement and
   limited to:").
   ``_build_package`` reads the section into a ``_Package``:
     * the introduction: which document it points to (``_reference``), and whether the list is closed.
       Only the words that hand over to the list close it (``_closing_words``): "limited to:", "consist
       exclusively of limitations on (...):", "only the following", "the following covenants" - not "limited
       to the Borrower and its subsidiaries and to include: ...", not when "including" follows, and the last
       of them not in a document that says it does not set out all its terms. An aside between the opening
       words and the colon ("(in each case subject to exceptions ... consistent with ...)") is what the term
       sheet says of every item; where it only leaves the exceptions to the definitive documents the
       covenants themselves are not by reference (``ref_deferred``);
     * the items, each tagged with the covenant topics its head names (liens, debt, restricted payments ...).
       A numbered list is told apart by its numbers: by bracket depth, and - where the items stand one under
       the other - by the column the numbers stand in (``_tab_marks``), so that a bracket an item never
       closes does not swallow the rest of the list. A proviso inside an item stays with it ("(i) investments;
       provided that (A) ...; (ii) indebtedness ..."); the one after the last item does too unless it speaks
       of other covenants or of the package (``_general_proviso``). The last item ends with its paragraph;
     * the clauses after the list - or a list of "modifications" to another agreement - that add or change a
       basket or an amount ("provided that (i) a general basket ... will be added to the asset sale
       covenant"), each tagged with the covenant it names first (``_clause_topic``); the components of a sum
       ("an amount equal to (a) ..., plus (b) ...") stay one clause;
     * a fall-away sentence, if there is one, and the listed covenants it switches off.
   ``_from_package`` then answers a row:
     * its covenant is listed: the row says so in the term sheet's own words - with the baskets if the item
       gives them (flowed over as many lines as the row may hold, broken only where a clause ends), otherwise
       "baskets not detailed in term sheet" - and is by reference when the section points to another document
       and the item sets out no terms of its own;
     * its covenant is dealt with inside another listed one (acquisitions in investments, disposals in
       fundamental changes ...): the row says where, and gives the exception of that covenant that opens on
       its subject (``_home_limbs``);
     * its covenant is not on a closed list: an express "None" - but only if nothing in the section speaks
       of the subject even loosely (``_LOOSE_TOPIC_RES``) and the section was read to its end; otherwise the
       row is "not stated";
     * its covenant is not on an open list: by reference if the section points elsewhere, else not stated;
     * the section says "None": every row says so.

2. Rows of their own (lender presentations, LMA style, long-form US style): "Restricted payments",
   "Permitted liens & indebtedness (Secured)", "Limitation on asset sales", "Negative pledge:", "General Debt
   Basket" ... with the baskets in the value. ``_assign_rows`` collects them from
     * tables of terms extracted with layout - Existing / Proposed amendment tables and dense one-page
       summaries with a single value column (``_read_table``). Nothing on the page says whether a label sits
       against the middle of its cells or against their first line, nor whether a line that starts in lower
       case carries on the line above, so each run of lines is read every way the lines allow (``_segment``,
       ``_top_rows``, ``_continues``) and a row is used only when all readings give it the same lines;
     * amendment slides extracted in plain reading order (``_read_slide``: label, existing text, proposed
       text, one after the other);
     * labelled sections of a term sheet whose label is a covenant ("Permitted Disposals:") and whose text
       reads as one (``_reads_as_covenant``; an "Asset Sales: 100% of net cash proceeds" sweep does not);
     * sub-headings inside the covenant section itself ("Indebtedness: ...", "Liens: ...").
   A row is given to the template row its label names (``_row_fields``); rows that give liens and
   indebtedness baskets together sit under Negative Pledge and are pointed to from Permitted Financial
   Indebtedness, and one passage for two covenants ("Loans and guarantees") is given once and pointed to. On
   amendment tables the proposed terms are recorded, an existing figure is shown straight after the figure
   that replaces it ("< 1.75x (existing: 1.00x)") and "same as existing" is said where the proposed cell says
   so (``_render_use``). A row whose boundaries or columns cannot be established with confidence is left
   out rather than guessed, and so is a page whose table cannot be rebuilt.

3. Not at all: the row is "not stated".

What is read is checked before it is used: a section must be a labelled section of a page of terms
(``_State.is_section``), a list with no words introducing it must look like one (``_plausible_list``), and
``_State.clean`` puts right the shapes the shared section finder gets wrong - among them a section that the
finder ends at the foot of a page because the next page opens with a running header or, set further left,
with a list number (``_State._carry_over``). A section that could still not be read to its end - it breaks
off in mid-phrase, stops at the foot of a page without a full stop, leaves a bracket open in the last thing
read, or shows the next number of its list inside what was read as the last item - is not relied on for
what it does not list, nor for the item it breaks off in (``_Package.cut_off``).

Every line is assembled from text matched in the document and every stated / by-reference entry carries
quotes cut by ``ctx.quote`` from the passages the lines were built from (``_checked`` drops an entry that
is left without one). A rule never raises: anything unexpected ends as "not stated" (set ``DEBUG = True``
to let errors surface while developing). Nothing here is specific to a client or a document.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import wraps

from ..textmodel import Line, fragments, is_footer, tidy
from .blocks import Block
from .common import BY_REFERENCE_RE, SAME_AS_EXISTING_RE, Ctx, by_reference, not_stated, points_elsewhere, squeeze, stated

LINE = 250  # house style: a line stays under about this many characters
MAX_FIELD_LINES = 6
_ROW_LINES = 8  # the most a row may hold (house style); used up only by a covenant the term sheet gives with all its baskets
_STATE_ATTR = "_negcov_state"
DEBUG = False  # set True (tests, development) to let an error surface instead of turning into "not stated"


def _rx(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern:
    """Compile a pattern, case-insensitive unless told otherwise."""
    return re.compile(pattern, flags)


# ---- covenant topics -----------------------------------------------------------------------------------
# What a list item, a basket clause or a row label is about. Lower-case "loans" / "advances" / "acquisition"
# only: capitalised they are the facility's own Loans / Advances or a defined deal ("the Acquisition").
_TOPIC_RES: dict[str, re.Pattern] = {
    # "limitation on liens", "negative pledge", "collateral to secure ...", "liens securing ..."
    "liens": _rx(r"\bliens?\b|negative\s+pledge|security\s+interests?|\bencumbrances?\b|\bto\s+secure\b|\bsecuring\b"),
    # "indebtedness", "debt", "issuance of preferred stock"
    "debt": _rx(r"\bindebtedness\b|\bdebt\b|\bborrowings\b|preferred\s+stock"),
    # "restricted payments", "dividends", "share repurchases", "RP capacity"
    "rp": _rx(r"restricted\s+payments?\b|\bdividends?\b|\bdistributions?\b|share\s+(?:buy[\s-]?backs?|repurchases?)|"
              r"stock\s+repurchases?|(?-i:\bRPs?\b)"),
    # "asset sales", "sale of assets", "sales of all or substantially all of its assets", "dispositions"
    # ... and "sales of the Aircraft Collateral", "sale or other transfer of property", "may sell assets", "dispose of"
    "disposals": _rx(r"asset\s+sales?|sales?\s+of\s+(?:all\s+or\s+substantially\s+all\s+(?:of\s+)?)?(?:its\s+|their\s+|the\s+)?assets|"
                     r"\bdispositions?\b|\bdisposals?\b|"
                     r"\bsales?\s+(?:or\s+other\s+(?:dispositions?|transfers?)\s+)?of\s+(?:[\w\-]+\s+){0,3}?(?:assets|propert(?:y|ies)|collateral)\b|"
                     r"\bsell(?:s|ing)?\s+(?:[\w\-]+\s+){0,3}?(?:assets|propert(?:y|ies)|collateral)\b|\bdispos(?:e|es|ing)\s+of\b"),
    # "mergers", "consolidations", "fundamental changes"
    "mergers": _rx(r"\bmergers?\b|\bconsolidations?\b|fundamental\s+changes?|\bamalgamations?\b"),
    # "investments, loans and advances"; capitalised only as the name of the covenant ("Limitation on Loans and Advances")
    "investments": _rx(r"\binvestments?\b|(?-i:\bloans\b)|(?-i:\badvances\b)|"
                       r"(?-i:\bLoans(?:,|\s+and|\s+or|\s+&)\s+(?:Advances|Investments|Guarantees|Guaranties|Credit)\b)|"
                       r"(?-i:\b(?:Advances|Investments|Guarantees),?\s+(?:and\s+|or\s+|&\s+)?Loans\b)|"
                       r"(?<=limitation on )(?-i:Loans|Advances)\b|(?<=limitations on )(?-i:Loans|Advances)\b|"
                       r"(?<=restrictions on )(?-i:Loans|Advances)\b"),
    # "acquisitions", "permitted acquisition"
    "acquisitions": _rx(r"\bacquisitions\b|(?-i:\bacquisition\b)"),
    # "guarantees", "guaranties" (not "Guarantor")
    "guarantees": _rx(r"\bguarant(?:ees?|y|ies)\b"),
    # "restricted debt payments", "RDP", "prepayments of junior debt", "subordinated indebtedness"
    # ... and "payments and modifications of subordinated and other material debt instruments", "prepayments, redemptions
    # and repurchases of junior debt"
    # ... and "redemptions of subordinated notes", "repurchases of junior lien obligations"
    "payments": _rx(r"restricted\s+debt\s+payments?|(?-i:\bRDPs?\b)|\bjunior\s+debt\b|restricted\s+junior\s+payments?|"
                    r"(?:pre)?payments?\s+(?:of|on)\s+(?:junior|subordinated|other|certain|restricted)\s+(?:debt|indebtedness)|"
                    r"(?:(?:pre)?payments?|redemptions?|repurchases?),?(?:\s+(?:and|or)\s+[\w\-]+|,\s+[\w\-]+){0,3}\s+(?:of|on|in\s+respect\s+of)\s+"
                    r"(?:[\w\-]+\s+){0,3}?(?:junior|subordinated)\b[^;.()]{0,40}?(?:debt|indebtedness|financing|notes|obligations)|"
                    r"subordinated\s+(?:debt|indebtedness)|junior\s+(?:financing|indebtedness|lien\s+debt)"),
    # "transactions with affiliates"
    "affiliates": _rx(r"\baffiliates?\b"),
    # "change in business", "nature of business", "business of the loan parties"
    "business": _rx(r"(?:changes?|nature|lines?)\s+(?:in|of)\s+(?:the\s+)?business|business\s+of\s+the\b|business\s+activities"),
    # "sale and leaseback", "sale-leaseback"
    "leaseback": _rx(r"sale[\s-]+(?:and[\s-]+)?lease[\s-]?backs?"),
    # "restrictive agreements", "negative pledge clauses", "dividend and other payment restrictions affecting subsidiaries"
    "restrictive": _rx(r"restrictive\s+agreements?|burdensome\s+agreements?|negative\s+pledge\s+clauses?|"
                       r"(?:(?:dividends?|distributions?)\s+(?:and|or)\s+(?:other\s+)?)?payment\s+restrictions\s+affecting|"
                       r"restrictions\s+on\s+(?:subsidiary\s+)?(?:dividends|distributions)"),
    # "swap agreements", "hedging arrangements"
    "hedging": _rx(r"swap\s+(?:agreements?|contracts?)|hedg(?:ing|e)\s+(?:agreements?|arrangements?|transactions?|obligations?)|\bspeculative\b"),
    # "change in fiscal year", "accounting changes"
    "fiscal": _rx(r"chang\w+\s+(?:in|of|to)\s+(?:its\s+|the\s+)?fiscal\s+year|fiscal\s+year\s+(?:changes?|end)|accounting\s+(?:changes|policies)"),
    # "sanctions", "anti-corruption laws", "OFAC"
    "sanctions": _rx(r"\bsanctions?\b|anti[\s-]*corruption|\bOFAC\b|\bFCPA\b|anti[\s-]*money[\s-]*laundering|anti[\s-]*terrorism|anti[\s-]*bribery"),
    # "use of proceeds"
    "proceeds": _rx(r"use\s+of\s+proceeds"),
    # "rank at least pari passu"
    "pari": _rx(r"pari\s+passu"),
    # "anti cash hoarding"
    "hoarding": _rx(r"cash\s+hoarding"),
    # "most favoured nation"
    "mfn": _rx(r"most[\s-]+favou?red[\s-]+nation"),
}
# Topics that are negative covenants (the first eight have a template row of their own, see _SPECS) ...
_NEG_TOPICS = ("liens", "debt", "rp", "disposals", "mergers", "investments", "acquisitions", "guarantees", "payments",
               "affiliates", "business", "leaseback", "restrictive", "hedging", "fiscal")
# ... and other undertakings worth a mention in the [Other] row.
_NOTABLE_TOPICS = ("sanctions", "proceeds", "pari", "hoarding", "mfn")
# A wider net for the subject of each row, cast only before an express "None" is printed: where the covenant section
# says any of this, the rules do not claim that the covenant is absent (they answer "not stated" instead).
_LOOSE_TOPIC_RES: dict[str, re.Pattern] = {
    "liens": _rx(r"\bliens?\b|pledge|encumbranc|security\s+interests?|mortgag|\bcharges?\b|\bsecur(?:e|ed|ing)\b"),
    "debt": _rx(r"indebtedness|\bdebt\b|\bborrowings?\b|borrowed\s+money|preferred\s+stock"),
    "rp": _rx(r"dividend|distribution|restricted\s+payments?|buy[\s-]?backs?|repurchase|redemption|redeem|capital\s+stock|share\s+capital"),
    "disposals": _rx(r"dispos|asset\s+sales?|sales?\s+of|\btransfers?\b|divest"),
    "investments": _rx(r"\binvest|\bloans?\b|\badvances?\b|joint\s+ventures?"),
    "acquisitions": _rx(r"acqui"),
    "guarantees": _rx(r"\bguarant(?:ees?|y|ies)\b|contingent\s+(?:obligations|liabilities)"),
    "payments": _rx(r"prepay|redemption|redeem|\bjunior\b|subordinated|repurchase|restricted\s+debt"),
}
# Wording that contains a topic word without being about the topic; blanked before topics are looked for.
_NOT_A_TOPIC_RE = _rx(
    r"Outbound\s+Investment\s+Rules?|Investment\s+Company(?:\s+Act)?|investment[\s-]+grade|debt\s+ratings?|"
    r"(?:first|second|third|1st|2nd|3rd|junior|senior)[\s-]+lien\s+(?:notes?|debt|facilit\w+|(?:net\s+)?leverage|term\s+loans?)|"
    r"(?<=guarantee)\s+of\s+(?:the\s+)?(?:indebtedness|debt)|(?<=guarantees)\s+of\s+(?:the\s+)?(?:indebtedness|debt)|"
    r"(?<=securing)\s+(?:[\w\-]+\s+){0,3}?(?:indebtedness|debt)|(?<=to secure)\s+(?:[\w\-]+\s+){0,3}?(?:indebtedness|debt)|"
    r"secured\s+(?:debt|indebtedness)|(?:Term\s+)?Loan\s+(?:Credit\s+)?(?:Agreements?|Documents?|Documentation|Parties)|"
    r"(?:Existing|Prior|Current)\s+[\w\- ]{0,30}?(?:Agreements?|Facilit(?:y|ies))|Merger\s+Agreement|Acquisition\s+(?:Agreement|Closing\s+Date)")
# A list item that opens like an affirmative covenant: whatever covenant word it goes on to use, it is not a restriction
# ("additional guarantees and collateral", "further assurances as to security interests", "delivery of notices of default
# under other indebtedness"; "payment of restricted payments" is not one of these).
_AFFIRMATIVE_LEAD_RE = _rx(r"^(?:certain\s+)?(?:maintenance\s+of|delivery\s+of|payment\s+of\s+(?:taxes|obligations|claims|liabilities)|"
                           r"compliance\s+with|further\s+assurances|additional\s+(?:guarant|collateral|security|subsidiar)|notices?\s+of|"
                           r"preservation\s+of|inspection|keeping\s+of|conduct\s+of|designation\s+of|reporting|books\s+and\s+records|"
                           r"information|financial\s+statements)")
# Where the head of a list item ends and its qualification begins: ", to be consistent with ...", "(consisting of ...".
_QUALIFIER_RE = _rx(
    r",\s+with\b|,?\s+(?:to\s+be\b|which\b|with\s+(?:respect|certain|exceptions?|customary)\b|subject\s+to\b|except\b|provided\b|"
    r"consistent\s+with\b|substantially\s+(?:similar|the\s+same|consistent|identical)\b|not\s+(?:to\s+)?exceed|not\s+in\s+excess|"
    r"in\s+each\s+case\b|permitting\b|including\b|other\s+than\b|in\s+an?\s+(?:aggregate\s+)?amount|in\s+excess\s+of\b)|"
    r"\s*\(|:\s|\s[-–]\s|(?-i:\.\s+(?=[A-Z(]))")  # ... or "Limitation on Liens. No liens on ..."
_HEAD_CHARS = 90  # an item's head is at most this long: topics named further on are detail, not the covenant

# ---- wording of the covenant sections ------------------------------------------------------------------
# Section labels. Kept tight: the label runs from the start of the line to a colon, a dash or a gap.
# "Negative Covenants", "Restrictive Covenants", "Negative Undertakings":
_NEG_LABEL = r"(?:negative|restrictive)\s+(?:covenants?|undertakings?)"
# "Covenants", "Certain Covenants", "General Undertakings", "Affirmative and Negative Covenants":
_GEN_LABEL = (r"(?:(?:certain|other|general|non[\s-]*financial|operating)\s+)?(?:covenants?|undertakings?)(?:\s+and\s+undertakings?)?"
              r"|affirmative\s+and\s+negative\s+covenants?")
# "Affirmative Covenants", "Positive Undertakings":
_AFF_LABEL = r"(?:affirmative|positive)\s+(?:covenants?|undertakings?)"
# "Documentation", "Documentation Principles" (where the precedent agreement is named):
_DOC_LABEL = r"documentation(?:\s+principles)?"
# Inside a general "Covenants" paragraph, the start of the sentence that lists the negative covenants: "Negative covenants
# will include limitations on ...", "The negative covenants shall be limited to: ...".
_NEG_SENTENCE_RE = _rx(r"(?:(?<=[.;:]\s)|^)(?:the\s+)?(?:negative|restrictive)\s+(?:covenants?|undertakings?)\s+"
                       r"(?=(?:shall|will|to|are|would)\s+(?:be\s+)?(?:includ|consist|limited|contain)|includ|consist|limited)")
# Words that open a list, up to its colon: "limited to:", "including, but not limited to:", "only the following ... :".
_OPENER_WORDS = (r"(?<!not )limited\s+to|only\s+the\s+following|consist(?:s|ing)?\s+(?:solely\s+|only\s+|exclusively\s+)?of|"
                 r"includ(?:e|es|ing)|such\s+as|the\s+following")
# ... from the opening word to the colon, within one sentence ("3.00:1.00" is not such a colon). A bracketed aside may
# stand straight before the colon: "consist exclusively of limitations on (in each case subject to ...):".
_OPENER_RE = _rx(r"(?:" + _OPENER_WORDS + r")(?:(?:(?!\.\s)[^:;]){0,150}?|(?:(?!\.\s)[^:;(]){0,80}?\([^()]{0,300}\)\s*):(?!\d)")
# ... and the same words without a colon, straight before the list ("including limitations on liens, debt ...").
_OPENER_BARE_RE = _rx(r"(?:(?<!not )limited\s+to|consist(?:s|ing)?\s+(?:solely\s+|only\s+|exclusively\s+)?of|includ(?:e|es|ing))"
                      r"(?:,?\s+(?:without\s+limitation|but\s+not\s+limited\s+to))?,?\s+")
# The list is exhaustive: "limited to", "only the following", "consisting of", "consist exclusively of", "will include only".
_CLOSED_RE = _rx(r"(?<!not )(?:limited|restricted)\s+(?:solely\s+|only\s+|exclusively\s+)?to|(?:only|solely|exclusively)\s+the\s+following|"
                 r"consist(?:s|ing)?\s+(?:solely\s+|only\s+|exclusively\s+)?of|(?:shall|will)\s+(?:contain|include|be)\s+only|"
                 r"the\s+following\s+(?:[\w,\-]+\s+){0,5}?(?:covenants|undertakings)")
# ... of these, a bare "the following covenants" closes a list only by implication: it is not relied on where the document
# says of itself that it does not set out all the terms ("is not intended to summarize all of the conditions, covenants ...").
_WEAK_CLOSE_RE = _rx(r"^the\s+following\b")
_NOT_ALL_TERMS_RE = _rx(r"(?:\bnot|n't)\s+(?:intended\s+to\s+|purport\s+to\s+|meant\s+to\s+)?(?:summari[sz]e|describe|include|contain|set\s+forth|"
                        r"set\s+out)\s+(?:descriptions?\s+of\s+)?all\s+(?:of\s+)?(?:the\s+)?(?:[\w,]+\s+){0,8}?(?:terms|covenants|provisions|conditions)|"
                        r"(?:\bnot|n't)\s+purport\s+to\s+be\s+(?:complete|exhaustive|all[\s-]inclusive)")
# ... the last of these ("will contain the following negative covenants: ...") closes the list as the house style
# reads it, but not after a word that opens one ("will include the following covenants").
_FOLLOWING_RE = _rx(r"the\s+following\b")
# ... and what may stand between those words and the list for the words to be about the list: nothing, "the following
# (...)", "limitations on", a list mark. "Limited to the Borrower and its subsidiaries" is not about the list.
_CLOSED_TAIL_RE = _rx(r"^\s*(?:the\s+following\b[^.;:]{0,200})?\s*:?\s*(?:(?:customary\s+)?(?:limitations?|restrictions?|prohibitions?)\s+"
                      r"(?:on|upon|with\s+respect\s+to)\s*(?:\([^()]{0,300}\)\s*)?:?\s*)?(?:\(?\w{1,5}[.)]\s*|[•·▪●◼■‣]\s*)?$")
# After "only the following" / "will include only" any words may run up to the list, within the sentence.
_CLOSED_ONLY_TAIL_RE = _rx(r"^(?:(?!\.\s)[^;]){0,220}$")
# A comma that separates two items of a list: ", " / ", and " / ", or ".
_COMMA_RE = _rx(r",\s+(?:(?:and|or)\s+)?")
# A closing remark about every item of a comma list: ", in each case with exceptions to be agreed".
_EACH_CASE_RE = _rx(r"^(?:in\s+each\s+case|each\s+(?:with|subject)|all\s+(?:with|subject)|subject\s+to|"
                    r"with\s+(?:(?:certain|customary|agreed)\s+)?(?:exceptions|baskets|carve))")
# ... the same remark at the end of the last item of any list: "...; and affiliate transactions, in each case, subject to ...".
_EACH_TAIL_RE = _rx(r",\s+(?:in\s+each\s+case|(?:each|all)\s+of\s+the\s+foregoing)\b")
# A list item written as a heading and its text: "Limitation on Liens. No liens on any property other than ...".
_HEADING_ITEM_RE = re.compile(r"[A-Z][^.;:]{2,60}\.\s+\S")
# The list sets out changes to a package of covenants, not the covenants: "with the following modifications: (i) ...".
_MODIFICATION_RE = _rx(r"\b(?:following|certain|such)\s+(?:[\w\-]+\s+){0,3}?(?:modifications?|changes|amendments|exceptions|differences|"
                       r"additions|adjustments)\b")
# A part after a comma that qualifies the item before it rather than naming a new one: ", with a general basket of ...".
_QUALIFIER_START_RE = _rx(r"^(?:with\b|subject\s+to\b|except\b|provided\b|in\s+each\s+case\b|other\s+than\b|including\b|which\b|to\s+be\b|"
                          r"not\s+(?:to\s+)?exceed|so\s+long\s+as\b|if\b|unless\b|as\s+(?:well|applicable|long)\b|in\s+an?\b|"
                          r"consistent\b|substantially\b|but\b|plus\b|to\s+the\s+extent\b|[$€£\d(])")
# A section that opens with the stem of its list: "Limitations on: liens; indebtedness; ...".
# ... also with an aside before the colon: "Restrictions on (in each case, with customary exceptions ... to be set forth in ...): (i) ...".
_STEM_RE = _rx(r"^(?:customary\s+)?(?:limitations?|restrictions?|prohibitions?)\s+(?:on|upon|with\s+respect\s+to)(?:\s+the\s+following)?\s*"
               r"(?:\([^()]{0,300}\)\s*)?:\s*")
# The aside that stands between the words that open a list and its colon: what the term sheet says of every item.
_LIST_ASIDE_RE = re.compile(r"\(([^()]{12,300})\)\s*:\s*(?:\(?\w{1,5}[.)]\s*|[•·▪●◼■‣]\s*)?$")
# ... how such an aside begins: "in each case subject to ...", "with customary exceptions ...", "to be applicable to ...".
_ASIDE_START_RE = _rx(r"^(?:in\s+each\s+case|subject\b|with\b|to\s+be\b|which\b|each\s+of\b|all\s+of\b|except\b|other\s+than\b)")
# The list is illustrative: "including", "to include", "such as".
_OPEN_RE = _rx(r"includ(?:e|es|ing)(?:,?\s+(?:but\s+not\s+limited\s+to|without\s+limitation))?|such\s+as")
# A proviso after the list: "; provided, that (i) ...".
_PROVISO_RE = _rx(r"[;,]?\s+provided\b,?\s*(?:however\b,?\s*)?(?:further\b,?\s*)?(?:that\b,?\s*)?")
# ... at the start of a semicolon-separated part or of a sentence: "; provided that ...", "; and provided further that ...".
_PROVISO_LEAD_RE = _rx(r"\s*(?:and\s+|or\s+)?provided\b")
# End of a sentence inside running text (decimals and "U.S." stay whole; an acronym may end a sentence: "... of
# Consolidated EBITDA. The ...").
_SENT_END_RE = re.compile(r"(?:(?<=[a-z0-9\)\]”\"%])|(?<=[A-Z]{2}))\.\s+(?=[A-Z(“\"•])")
# List markers: bullets, "(i)", "(a)", "(A)", "(1)", "1.".
_BULLETS = "•·▪●◼■‣"
# ... at the start of the text or after a blank; a dotted number counts only when a blank follows ("3.00" does not).
_MARK_RE = re.compile(r"(?:(?<=\s)|^)(?:(?P<bullet>[" + _BULLETS + r"])(?!\s*\])|\((?P<tag>[ivxl]{1,5}|[a-z]|[A-Z]|\d{1,2})\)|"
                      r"(?P<dot>\d{1,2})\.(?=\s))\s*")
# A mark that is a cross-reference, not the start of a list item: "clauses (A) and (B)", "clause (b) above".
_XREF_BEFORE_RE = _rx(r"(?:clauses?|paragraphs?|sections?|items?)\s+(?:\(\w{1,5}\)\s*(?:,|and|or|through|to)\s+)*$")
# A list number at the start of a line, and the gap that sets it off from its text: "(iv)      Restricted payments", "3.   Limitation on".
_LINE_MARK_RE = re.compile(r"^\s*(?P<mark>\((?P<tag>[ivxl]{1,6}|[a-zA-Z]|\d{1,2})\)|(?P<dot>\d{1,2})\.)(?P<gap>\s+)(?=\S)")
# A lettered or numbered sub-heading inside a general "Covenants" section: "(c) Negative Covenants - Restrictions on: ...".
# ... also "A. Negative Covenants.", "2) Negative Covenants:", "II. Negative Covenants -".
_SUB_HEAD_RE = re.compile(r"(?:(?<=\s)|^)(?:\((?:[a-zA-Z]|\d{1,2}|[ivx]{1,5})\)|\d{1,2}[.)]|[A-Za-z][.)]|[IVX]{1,4}[.)])\s+"
                          r"(?P<label>(?:[A-Z][A-Za-z]+\s+){0,3}(?:Covenants?|Undertakings?))\s*(?:[-–—:]|\.(?=\s))\s*")
# ... and such a sub-heading without a number, at the start of a line of the section: on a line of its own ("Negative
# Covenants" / "NEGATIVE COVENANTS:") or opening a paragraph ("Negative Covenants - Limitations on ...").
_SUB_LINE_RE = re.compile(r"(?P<label>(?=[A-Z])(?i:(?:[a-z]+\s+){0,3}(?:covenants?|undertakings?)))\s*(?P<end>:?\s*$|[-–—:]\s+|\.\s+(?=[A-Z(]))")
# The words "Negative Covenants" written as a heading or a name (capitalised) inside a general covenant section.
_NEG_HEADING_RE = re.compile(r"(?:(?<=\s)|^)[NR](?i:egative|estrictive)\s+(?i:covenants?|undertakings?)\b")
# A left-hand cell that reads as a label though no colon ends it: one to five words, each capitalised ("Events of Default").
_TITLE_CELL_RE = re.compile(r"^[A-Z][\w’'\-]*(?:\s+(?:[A-Z][\w’'\-/&]*|of|and|the|to|for|on|in|&|/)){0,4}$")
# The text read so far ends on a full stop (or a full stop inside closing quotes / brackets).
_FULL_STOP_END_RE = re.compile(r"[.!?][”\"')\]]*\s*$")
# The section points to another document: "substantially similar to the Existing Credit Agreement", "Similar to (and no
# less favorable to the Company than) the Existing 364-Day Agreement", "similar to existing Revolving Credit Facility",
# "substantially the same as the Closing Date Term Loan Credit Agreements", "consistent with the X Indenture Precedent".
_REF_RE = re.compile(
    r"(?i:(?:substantially\s+|generally\s+|broadly\s+)?(?:similar|consistent|(?:the\s+)?same|identical))\s+(?i:to|with|as)\s+"
    r"(?:\([^)]{0,100}\)\s+)?"
    r"(?i:those\s+(?:set\s+forth\s+|contained\s+|provided\s+)?(?:in|under)\s+|under\s+|in\s+)?"
    r"(?:(?i:the|its|their)\s+)?(?:(?i:existing|prior|current)\b|[A-Z])[\w’'\-]*(?:\s+[\w’'\-]+){0,8}?\s+"
    r"(?:Agreements?|Facilit(?:y|ies)|Indentures?|Precedents?|Documentation|Notes)\b")
# Other ways of pointing elsewhere that the shared pattern does not cover: "customary for investment grade facilities of
# this type", "as set forth in Annex B", "in line with the Existing Facilities Agreement".
_ELSEWHERE_RE = re.compile(
    r"(?i:(?:usual|customary|standard)\s+for\s+[\w\- ]{0,40}?(?:facilities|transactions|financings|loans)"
    r"(?:\s+and\s+(?:facilities|transactions))?(?:\s+of\s+this\s+(?:type|nature|kind|size))?)|"
    r"(?i:(?:as\s+)?(?:set\s+(?:forth|out)|described|specified|detailed|provided)\s+(?:in|on|under)\s+(?:the\s+)?(?:attached\s+)?)"
    r"(?:Annex|Exhibit|Schedule|Appendix|Attachment)\s+[\w\-]{1,6}|(?i:see\s+)(?:Annex|Exhibit|Schedule|Appendix)\s+[\w\-]{1,6}|"
    r"(?i:(?:as\s+per|in\s+line\s+with|in\s+accordance\s+with|based\s+on)\s+(?:the\s+)?(?:existing|prior|current)\s+)"
    r"[\w\- ]{0,40}?(?:Agreements?|Facilit(?:y|ies)|Indentures?|Documentation)\b")
# The detail is left to the definitive documents: "with customary exceptions, qualifications, materiality standards and
# baskets to be set forth in the Facilities Documentation", "exceptions and baskets to be agreed in the Loan Documents".
_DEFERRED_RE = re.compile(
    r"(?i:(?:customary\s+|certain\s+|other\s+|usual\s+)?(?:exceptions|qualifications|baskets|carve[\s-]?outs|thresholds)\b"
    r"(?:(?!\.\s)[^;:()]){0,90}?\bto\s+be\s+(?:(?:mutually\s+)?agreed(?:\s+upon)?|determined|set\s+forth|set\s+out|specified|included|provided|"
    r"contained|negotiated))(?:(?i:\s+in\s+(?:the\s+)?(?:definitive\s+)?)(?:[A-Za-z]+\s+){0,3}?(?:Documentation|Documents|Agreement)\b)?")
# ... "to be agreed" on its own says so of whatever stands before it.
_TO_BE_AGREED_RE = _rx(r"^to\s+be\s+(?:agreed|determined)$")
# A sentence after the list that adds or changes a basket or a covenant: "a general basket ... will be added".
_BASKET_RE = _rx(r"\bbaskets?\b|\bcovenants?\b|\bcarve[\s-]?outs?\b|\bexceptions?\b")
# ... or that changes an amount of the package: "... except that the starter component shall be increased to $1,000,000,000".
_AMOUNT_CHANGE_RE = _rx(r"\b(?:increased|reduced|decreased|raised|lowered)\s+(?:from\b|to\b|by\b)")
# The limbs of a sum, not of a list: "an amount equal to (a) ..., plus (b) ..., minus (c) ...".
_SUM_LIMB_RE = _rx(r"\b(?:plus|minus|less)\s*$")
# ... and words before the first limb that tie the limbs into one amount or one condition: "the greater of (a) ... and
# (b) ...", "the sum of (i) ...", "so long as (i) ... and (ii) ...", "not to exceed (x) ...".
_ONE_WHOLE_RE = _rx(r"\b(?:(?:greater|lesser|higher|lower|larger|smaller|sum|total|aggregate|ratio|excess|product|difference|amount)\s+of|"
                    r"so\s+long\s+as|to\s+the\s+extent(?:\s+that)?|if|unless|until|when|either|both|between|equal\s+to|"
                    r"not\s+(?:to\s+)?exceed(?:ing)?|in\s+excess\s+of|up\s+to)\s*:?\s*$")
# Opening words that introduce the financial covenants, not the covenant list: "including, with respect to the
# financial covenants:".
_FINCOV_RE = _rx(r"\bratio\b|financial\s+covenants?")
# Wording by which a list item sets out terms of its own instead of only naming a covenant: a proviso, an express
# permission, a condition ("provided that ...", "shall be permitted to ...", "so long as ...", "subject to no Event of Default").
_OWN_TERMS_RE = _rx(r"\bprovided\b,?\s+(?:however,?\s+)?that\b|(?:shall|will|to)\s+be\s+permitted\b|\bso\s+long\s+as\b|"
                    r"pro\s+forma\s+compliance|subject\s+to\s+no\s+(?:\w+\s+){0,4}?default|\bexcept\s+that\b")
# Wording by which a list item qualifies the covenant it names - an exception, a permission, a condition - whether or not
# it gives a figure: "except that ...", "other than ...", "unless ...", "may ...", "... is permitted if ...".
_EXCEPTION_RE = _rx(r"\bprovided\b|\bexcept\s+(?:that|for|to\s+the\s+extent|where|as\s+(?:follows|set))\b|\bother\s+than\b|\bunless\b|"
                    r"\bso\s+long\s+as\b|\b(?:is|are|be|being)\s+permitted\b|(?<!as )\bmay\b(?!\s+be\s+(?:mutually\s+|otherwise\s+)?(?:agreed|determined))|\bif\b|"
                    r"\bexcluding\b|pro\s+forma\s+compliance|subject\s+to\s+no\b")
# Words an introduction is left dangling on once the list opener is cut off: "... Credit Agreement and to".
_DANGLING_END_RE = _rx(r"(?:,?\s+(?:and|to|shall|will|which|are|is|be|with|as|the|contain|include|includes|including))+$")
# The section's text breaks off in mid-phrase: what was read is not all of it (a list may go on, an item may be missing).
_CUT_OFF_RE = _rx(r"(?:\b(?:and|or|includ(?:e|es|ing)|to|of|the|with|an?|in|by|at|as|for|on|from|than|any|its|their|that|which|such|be|is|are|"
                  r"shall|will|not|no|each|all|per|under|upon)|[,;:(])\s*$")
# Covenants that stop applying: "shall be of no further force and effect", "shall cease to apply".
_FALL_AWAY_RE = _rx(r"(?:shall|will)\s+(?:be\s+of\s+no\s+further\s+force(?:\s+(?:and|or)\s+effect)?|cease\s+to\s+(?:apply|be\s+in\s+effect)|"
                    r"no\s+longer\s+apply|be\s+suspended|terminate)")
# "... then, beginning on such date the [covenants] shall be of no further force and effect".
_THEN_RE = _rx(r"\bthen\b,?\s*(?:beginning\s+on\s+such\s+date\s+|from\s+(?:and\s+after\s+)?such\s+date\s+|thereafter\s+)?")
# The defined event that triggers it: (... referred to as a “Covenant Fall-Away Event”).
_DEFINED_EVENT_RE = re.compile(r"[“\"]([A-Z][\w\- ]{2,50}?(?:Event|Date|Trigger|Period))[”\"]")
# An ellipsis: a quote that carries one is not accepted as contiguous, even when the page itself has it.
_ELLIPSIS_RE = re.compile(r"\.\.\.|…")
# A value the term sheet leaves open: "$[ ] million", "[●]", "[___]", "[TBD]", "[to be agreed]".
_BLANK_RE = _rx(r"\[\s*[●•_.\s]*\]|\[\s*(?:TBD|TBC|to\s+be\s+(?:agreed|determined|confirmed))\s*\]")
# ... a section or cell that is nothing but such a blank.
_ONLY_BLANK_RE = _rx(r"^\W*(?:" + _BLANK_RE.pattern + r")\W*$")
# "limitations on liens" -> "liens": the words in front of the covenant's name.
_LIMITATION_PREFIX_RE = _rx(r"^(?:limitations?|restrictions?|prohibitions?)\s+(?:on|of|upon)\s+(?:the\s+)?")

# A financial covenant that allows a higher level after an acquisition ("Following a qualified acquisition, steps up to
# 4.50x", "after any permitted acquisition ... shall not exceed 4.25 to 1.00").
_FINCOV_LABEL = r"financial\s+covenants?"
# A covenant level: "4.50x", "4.25 to 1.00", "3.50:1.00".
_LEVEL = r"\d\.\d{1,2}\s*(?:x\b|:\s?1|to\s+1)"
_RATIO_LEVEL_RE = re.compile(_LEVEL)
# ... the acquisition and the higher level in one sentence. The level must be tied to the acquisition by words of
# stepping up ("following a qualified acquisition, steps up to 4.50x", "step-up to 4.50x for four quarters after a Material
# Acquisition", "shall be increased from 3.50 to 1.00 to 4.00 to 1.00") or of time ("for the four quarters ending after any
# permitted acquisition ... shall not exceed 4.25 to 1.00"): a ratio merely tested pro forma for acquisitions is not one.
_STEP_WORDS = r"(?:step(?:s|ped|ping)?[\s-]*ups?|\bincreas(?:e|ed|es|ing)\b)"
_ACQUISITION_STEP_RE = _rx(
    r"\bacquisitions?\b(?:(?!\.\s).){0,320}?" + _STEP_WORDS + r"(?:(?!\.\s).){0,80}?" + _LEVEL + r"|"
    + _STEP_WORDS + r"(?:(?!\.\s).){0,80}?" + _LEVEL + r"(?:(?!\.\s).){0,200}?\bacquisitions?\b|"
    r"(?:following|after(?!\s+giving)|upon|in\s+the\s+event|complet\w+|consummat\w+)\b(?:(?!\.\s).){0,80}?\bacquisitions?\b"
    r"(?:(?!\.\s).){0,320}?(?:shall\s+not\s+(?:exceed|be\s+more\s+than)|not\s+to\s+exceed|may\s+not\s+exceed)(?:(?!\.\s).){0,60}?" + _LEVEL + r"|"
    # "shall be 4.00:1.00 for the four fiscal quarters ending after a Qualified Acquisition"
    + _LEVEL + r"(?:(?!\.\s).){0,20}?\bfor\s+(?:the|each|a|any)\b(?:(?!\.\s).){0,60}?\b(?:quarters?|periods?|months|year)\b"
    r"(?:(?!\.\s).){0,60}?(?:following|after(?!\s+giving)|upon)\b(?:(?!\.\s).){0,60}?\bacquisitions?\b")
# ... the higher level is the borrower's to choose: "may be increased at the Company's option", "the Borrower may elect to".
# ... "the Borrower may, by notice to the Agent, increase the maximum ratio", "may be increased", "may request an increase".
_AT_OPTION_RE = _rx(r"\b(?:at|upon)\s+(?:the\s+)?(?:[\w’']+\s+){0,3}?(?:option|election|request)\b|\bmay\b(?:\s+\w+){0,3}?\s+elect\b|"
                    r"\belection\b|\belects\b|\bmay\b(?:,[^,.;]{0,80},)?\s+(?:be\s+)?(?:increased?|stepped|step|raised?|request)\b|"
                    r"\b(?:has|have|shall\s+have|will\s+have)\s+the\s+(?:right|option)\s+to\b|\b(?:is|are|shall\s+be|will\s+be)\s+entitled\s+to\b")
# Covenants that US term sheets fold into another one: acquisitions into investments (or mergers), guarantees into
# indebtedness or investments, payments of junior debt into restricted payments, sales of all or substantially all
# assets into mergers / fundamental changes.
_HOME_TOPICS = {"acquisitions": ("investments", "mergers"), "guarantees": ("debt", "investments"), "payments": ("rp",),
                "disposals": ("mergers",)}
# What the undertakings without a row of their own are called in the [Other] row.
_OTHER_NAMES = {"mergers": "Mergers / fundamental changes", "affiliates": "Transactions with affiliates", "business": "Change of business",
                "leaseback": "Sale and leaseback", "restrictive": "Restrictive agreements", "hedging": "Hedging", "fiscal": "Fiscal year"}

# ---- wording of amendment tables -----------------------------------------------------------------------
# Header cells of the two term columns: "Existing" / "Existing Terms" / "Current", "Proposed" / "Amended" / "New".
_EXISTING_HEAD_RE = _rx(r"^(?:existing|current)\b")
# ... and the cell beside it.
_PROPOSED_HEAD_RE = _rx(r"^(?:proposed|amended|new)\b")
# The header of a slide extracted without layout: "Existing Terms Proposed Terms".
_SLIDE_HEAD_RE = _rx(r"^\W*(?:existing|current)(?:\s+\w+){0,2}?\s+(?:proposed|amended|new)(?:\s+\w+){0,2}\W*$")
# A label line on such a slide: "General Debt Basket: Greater of ...", "Capacity:".
_SLIDE_LABEL_RE = re.compile(r"^(?P<label>[A-Z][A-Za-z0-9 /&\-()’'.]{1,48}?):(?:\s+(?P<rest>\S.*))?$")
# A wrapped piece of a label above its last line: "Restricted Payment /", "Designated Non-Cash".
_SLIDE_LABEL_PIECE_RE = re.compile(r"^(?:[A-Z(][\w\-’']*|[/&\-])(?:\s+(?:[A-Z(][\w\-’')]*|[/&\-]|of|and|on|for|to))*\s*$")
# A footnote under the table: "1. Liquidity defined as ...", "(2) Pro forma for ...".
_FOOTNOTE_RE = re.compile(r"^\s*\(?\d{1,2}[.)]\s+[A-Z]")
# A proposed cell written as an instruction: "Eliminate access to ...", "Reduce basket ...", "Same, except that ...".
_AMEND_WORDS = (r"Eliminat(?:e|ion)|Reduc(?:e|tion)|Retain|Add(?:ition)?|Remov(?:e|al)|Increase|Decrease|Amend(?:ment)?|Extend|Extension|"
                r"Replace|Delete|Implement|Modify|Revise|Tighten|Loosen|Introduce|Lower|Raise|Reset|Waive|Same|No\s+change|Unchanged")
# ... at the start of a line or bullet,
_AMEND_START_RE = re.compile(r"^(?:[" + _BULLETS + r"]\s*)?(?:" + _AMEND_WORDS + r")\b(?=[\s,]|$)")
# ... or in the middle of a line, straight after the existing text: "... in incremental debt Reduce incremental capacity".
_AMEND_INLINE_RE = re.compile(r"(?<=[\w\)%.])\s+(?=(?:" + _AMEND_WORDS + r")\s+[a-z$\d])")
# A proposed cell written as a requirement: "Debt under general debt basket to be unsecured ...".
_WILL_BE_RE = _rx(r"\b(?:to|will|shall)\s+be\b")
# The row ends with the proposed cell "Same as existing" / "No change" / "Unchanged".
_SAME_TAIL_RE = _rx(r"(?:^|\s)(?:same(?:\s+as\s+(?:existing|current))?|no\s+change|unchanged)\W*$")
# A cell that says there is nothing: "N/A", "None".
_NONE_CELL_RE = _rx(r"^\W*(?:n\s?/\s?a|none|not\s+applicable)\W*$")
# The line above ends in the middle of a phrase: a comparison sign, a comma, a conjunction, a numbering mark.
_HANGING_END_RE = _rx(r"(?:[,≤≥<>=&/(\-–]|\b(?:and|or|of|the|to|for|in|on|with|by|an?|all|any|than|from|at|as|per|net|total|gross|"
                      r"consolidated|senior|secured|first|second)|\((?:[ivx]+|[a-z]|\d)\))\s*$")
# The cell line starts a new bulleted item.
_BULLET_START_RE = re.compile(r"^\s*[" + _BULLETS + r"]")
# A bullet that opens an item inside a cell's text (the "●" of a blank left for a value - "EUR [●] million" - is not one).
_ITEM_BULLET_RE = re.compile(r"(?:^|(?<=\s))[" + _BULLETS + r"](?!\s*\])")
# A label line that carries on to the next: "Permitted liens &", "(2nd Lien Notes /".
_LABEL_CARRIES_RE = _rx(r"(?:[&/,\-–]|\b(?:of|and|on|for|to|the|in))\s*$")
# A label line that cannot stand alone, so the next label line belongs to it: "Permitted" / "Indebtedness".
_LABEL_OPENS_RE = _rx(r"^(?:permitted|restricted|limitations?|restrictions?|negative|affirmative|financial|mandatory|additional|"
                      r"specified|anti)$")
# Row labels that collect assorted changes; their cells are sorted by what each item says.
_BUCKET_LABEL_RE = _rx(r"(?:additional|other|certain|further)\s+(?:amendments?|changes|modifications|terms)|"
                       r"covenant\s+(?:amendments?|changes|modifications|flexibility)|\bbaskets?\b|\bcapacity\b|non[\s-]*cash\s+consideration")
# A "Guarantees" row is the credit support, not a covenant, unless the label says it restricts.
_RESTRICTS_RE = _rx(r"permitted|limitations?|restrictions?|baskets?|capacity")
# "Permitted liens & indebtedness (Unsecured)": baskets for debt that carries no lien.
_UNSECURED_RE = _rx(r"\bunsecured\b")
# "Loans and guarantees", "Permitted Loans", "Loans and advances": the label of a covenant on loans made by the group.
_LOANS_LABEL_RE = _rx(r"loans\s+(?:and|or|&)\s+(?:guarantees|advances|credit|investments)|(?:investments|guarantees),?\s+(?:and\s+)?loans|"
                      r"(?:permitted|limitations?\s+on|restrictions?\s+on)\s+loans")
# Labelled sections of a term sheet that are covenant rows in their own right (LMA style and long-form US style).
_ROW_LABELS = (
    r"negative\s+pledge",
    r"permitted\s+(?:liens|security|encumbrances|(?:financial\s+)?indebtedness|debt|acquisitions?|disposals?|dispositions?|"
    r"distributions?|dividends?|investments?|loans?|guarantees?|payments?)(?:\s+(?:and|&)\s+\w+)?",
    r"(?:limitations?|restrictions?)\s+on\s+(?:liens|(?:financial\s+)?indebtedness|debt|acquisitions|disposals|dispositions|"
    r"asset\s+sales|sales?\s+of\s+assets|dividends|distributions|restricted\s+payments|investments|loans|guarantees)"
    r"(?:\s+(?:and|&)\s+[\w ]{3,30})?",
    r"restricted\s+payments?", r"asset\s+sales?", r"(?:asset\s+)?dispositions|disposals", r"financial\s+indebtedness",
    r"loans\s+(?:and|or|&)\s+(?:guarantees|advances|credit)", r"dividends(?:\s+and\s+(?:distributions|share\s+redemptions?))?|distributions",
    r"acquisitions(?:\s+and\s+(?:joint\s+ventures|mergers))?", r"mergers?(?:\s+and\s+(?:acquisitions|consolidations))?",
    r"anti[\s-]*cash\s+hoarding",
    # rows of summary tables that name the baskets: "Debt incurrence", "Debt baskets", "Lien basket", "RP capacity"
    r"(?:debt|lien|liens|investments?|restricted\s+payments?|RP|dividend)\s+(?:incurrence|baskets?|capacity)|"
    r"incurrence\s+of\s+(?:debt|indebtedness|liens)",
    # other undertakings with a row of their own: "Change of business", "Transactions with affiliates", "Sale and leaseback"
    r"fundamental\s+changes", r"change\s+of\s+business|nature\s+of\s+(?:the\s+)?business",
    r"transactions\s+with\s+affiliates|affiliate\s+transactions", r"sale[\s-]+and[\s-]+lease[\s-]?backs?(?:\s+transactions)?",
    r"(?:restrictive|burdensome)\s+agreements",
)
# The last line of such a label where it wraps in a narrow left column: "Permitted Financial" / "Indebtedness:".
_ROW_LABEL_TAIL = (r"(?:indebtedness|debt|liens|security|pledge|disposals|dispositions|sales|acquisitions|distributions|dividends|payments|"
                   r"investments|loans|guarantees|advances|baskets?|capacity|changes|affiliates|business|agreements|transactions|hoarding)")
# A section that sweeps proceeds into prepayment ("100% of the net cash proceeds of asset sales ... reinvestment").
_PREPAYMENT_LABEL = r"(?:mandatory\s+)?prepayments?(?:\s+and\s+commitment\s+reductions?)?"
# ... and the wording of such a sweep.
_SWEEP_RE = _rx(r"\bprepa(?:y|id|yment)s?\b|net\s+(?:cash\s+)?proceeds|\breinvest")
# Row labels that name a covenant topic without being a covenant row ("Incremental Debt", "Net Debt", "Debt Ratings").
_NOT_A_ROW_RE = _rx(r"incremental|accordion|ratings?\b|leverage|(?:net|total|existing|funded|gross)\s+debt|pro\s+forma|capitali[sz]ation|maturit|"
                    r"pricing|\bfees?\b|purpose|use\s+of\s+proceeds|prepayment|amorti[sz]|financial\s+covenants?|events?\s+of\s+default|"
                    r"\bEBITDA\b|outstanding|sources|\buses\b|coverage|representations")
# A sub-heading at the start of a sentence inside the covenant section: "... to be agreed: Indebtedness: Limitation on".
# ... also where its text opens in lower case or on a figure: "Liens: general basket of ...", "Restricted Payments: $20 million per year".
_INNER_LABEL_RE = re.compile(r"(?:(?<=[.;:]\s)|^)(?P<label>(?:(?:Limitations?|Restrictions?)\s+on\s+)?[A-Z][A-Za-z,/&\- ]{2,58}?):\s+(?=\S)")
# Wording that makes a labelled paragraph read as a covenant rather than as narrative about the company.
_COVENANT_WORDS_RE = _rx(
    r"permit|basket|limit|restrict|prohibit|subject\s+to|(?:not|n't)\s+(?:to\s+)?exceed|unlimited|shall\s+not|may\s+not|will\s+not|"
    r"no\s+(?:event\s+of\s+)?default|pro\s+forma|greater\s+of|lesser\s+of|customary|consistent\s+with|same\s+as|similar\s+to|exception|"
    r"carve|\bcap(?:ped)?\b|in\s+(?:the\s+)?aggregate|(?:per|in\s+any)\s+(?:fiscal|financial)\s+year|ordinary\s+course|leverage|"
    r"negative\s+pledge|[≤≥<>]|"
    # LMA wording: "No Obligor shall ...", "No member of the Group may ...", "... other than a Permitted Disposal", "unless"
    r"\bno\s+(?:obligor|borrower|guarantor|member\s+of\s+the\s+group|group\s+(?:company|member)|(?:loan|credit)\s+party|"
    r"(?:restricted\s+|material\s+)?subsidiary)\b|\bno\s+(?:substantial|material|significant)\s+change|other\s+than|\bunless\b|"
    r"\bexcept\b|\bnone\b")
# A label that says of itself that it restricts ("Permitted Disposals", "Limitation on Liens", "Restricted Payments") ...
_RESTRICTS_LABEL_RE = _rx(r"permitted|limitations?|restrictions?|restricted|negative|baskets?|capacity|incurrence|\banti\b|covenants?|"
                          r"undertakings?")
# ... and, under a label that is also an ordinary noun ("Merger", "Acquisitions", "Dividends"), the wording that makes the
# paragraph a restriction rather than a description of the deal or of the company.
_RESTRICTIVE_WORDS_RE = _rx(r"\b(?:no|not|shall\s+not|may\s+not|will\s+not|prohibit\w*|restrict\w*|limit\w*|permitted|other\s+than|unless|"
                            r"except|baskets?|cap(?:ped)?|customary|unlimited|none)\b|to\s+be\s+agreed|n't\b|[≤≥<>]")
# Labels that mark a page as a page of terms (used to keep slide prose out).
_CORE_LABEL_RE = _rx(r"^\s{0,14}(?:borrowers?|guarantors?|facilit(?:y|ies)|maturity|tenor|purpose|security|collateral|pricing|"
                     r"financial\s+covenants?|fees|amorti[sz]ation|accordion|incremental|administrative\s+agent|governing\s+law|"
                     r"events\s+of\s+default|lenders|interest\s+rates?)\b[^.]{0,30}(?::|\s{2,}|$)")

# A line that starts a labelled paragraph inside the value column: "Financial Covenant – Maximum ...", "• Pricing: ...".
_INLINE_LABEL_RE = re.compile(r"^\s*(?:[" + _BULLETS + r"\-–]\s*)?[A-Z][\w /&()’'\-]{2,44}?\s*(?::|\s[-–]\s)")
# What may stand in front of a label on its line: a bullet, a dash, "(c)", "3.".
_LABEL_LEAD_RE = re.compile(r"^(?:[" + _BULLETS + r"\-–]\s*|\(?[a-zA-Z0-9]{1,3}[.)]\s+)")
# The next "Label:" line on a page read in plain order, also where the page's text is set in from the edge.
_PLAIN_NEXT_RE = re.compile(r"^\s{0,8}[A-Z][A-Za-z /&\-()’']{2,44}:(?:\s|$)")
# Any "Label:" line at the left of a page, followed by its value or standing alone above it.
_LABEL_LINE_RE = re.compile(r"^\s{0,20}[A-Z][\w /&\-()’'.,]{1,45}:(?:\s{2,}\S|\s*$)")

# ---- the rows of the template --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    """One "Permitted ..." row of the template: the covenant it is about and how lines speak of it."""
    fid: str
    topic: str  # the covenant topic the row is about
    name: str  # what the covenant is called in a line
    none: str  # ... and in "no ... covenant"
    detail: str  # what the term sheet leaves out when it only lists the covenant
    see: str  # how other rows point here


_SPECS = {s.fid: s for s in (
    _Spec("negative_pledge", "liens", "Limitation on liens", "limitation on liens", "baskets", "Negative Pledge"),
    _Spec("permitted_acquisitions", "acquisitions", "Restriction on acquisitions", "acquisitions covenant", "conditions and baskets",
          "Permitted Acquisitions"),
    _Spec("permitted_disposals", "disposals", "Asset sale / disposal covenant", "asset sale / disposal covenant", "baskets and conditions",
          "Permitted Disposals"),
    _Spec("permitted_distributions", "rp", "Restricted payments covenant", "restricted payments covenant (dividends, share buybacks)",
          "baskets", "Permitted Distributions"),
    _Spec("permitted_indebtedness", "debt", "Limitation on indebtedness", "limitation on indebtedness", "baskets",
          "Permitted Financial Indebtedness"),
    _Spec("permitted_loans", "investments", "Restriction on loans, advances and investments", "covenant on loans, advances or investments",
          "baskets", "Permitted Loans"),
    _Spec("permitted_guarantees", "guarantees", "Restriction on guarantees", "separate covenant on guarantees", "baskets",
          "Permitted Guarantees"),
    _Spec("permitted_payments", "payments", "Restriction on payments of junior / subordinated debt",
          "covenant on payments or prepayments of junior or subordinated debt", "baskets and conditions", "Permitted Payments"),
)}
_FIELD_OF_TOPIC = {s.topic: s.fid for s in _SPECS.values()}
_OTHER = "other_covenants"


# ---- small text helpers --------------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Tidy, and close the stray gaps extraction leaves inside words ("anti -corruption", "364- Day", "(  i)")."""
    text = tidy(text or "")
    text = re.sub(r"(?<=[a-z0-9])\s+-(?=[a-z])", "-", text)
    text = re.sub(r"(?<=[a-z])\((?=[a-z]{2,}\s)", " (", text)  # "Pool Assets(as defined in ...)"
    text = re.sub(r"(?<=\w)-\s+(?=[A-Z0-9])", "-", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+([,;:)])", r"\1", text)
    return re.sub(r"\s+\.(?=\s|$)", ".", text)


def _cap(text: str) -> str:
    """Upper-case the first letter."""
    return text[:1].upper() + text[1:] if text else text


def _low(text: str) -> str:
    """Lower-case the first letter, unless the passage opens with an acronym or a capitalised name ("ERISA",
    "Outbound Investment Rule ...", "Sale and Leaseback Transactions")."""
    words = text.split()
    if len(text) > 1 and text[0].isupper() and text[1].islower() and not any(w[:1].isupper() for w in words[1:3]):
        return text[0].lower() + text[1:]
    return text


def _line(text: str, limit: int = LINE) -> str:
    """A passage as a house-style line: amounts restyled, comparison signs spelt out, cut at a word boundary."""
    text = squeeze(_norm(text), limit)
    text = re.sub(r"(?<=\d)(m|bn|k)\(", r"\1 (", text)  # restyle_money drops the blank between an amount and a bracket
    return text.replace("≤", "<=").replace("≥", ">=").strip(" ;,")


def _strip_item(text: str) -> str:
    """A list item or clause without the separators and the "and" / "or" that tie it to its neighbours."""
    text = _norm(text).strip(" ;,.")
    text = re.sub(r"^(?:and|or)\s+", "", text, flags=re.IGNORECASE)
    return re.sub(r"[;,]?\s+(?:and|or)$", "", text, flags=re.IGNORECASE).strip(" ;,.")


def _has_amount(text: str) -> bool:
    """The passage gives an amount, a percentage or a ratio."""
    return bool(re.search(r"[$€£]\s?\d|\d\s?%|\d\.\d+\s?(?:x\b|:\s?1\b|to\s+1\b)|\d\s?(?:million|billion|mm|bn)\b", text))


def _has_figure(text: str) -> bool:
    """The passage gives an amount, a percentage or a ratio - or leaves a blank for one: it states a basket rather than
    naming a covenant."""
    return _has_amount(text) or bool(_BLANK_RE.search(text))


def _has_terms(text: str) -> bool:
    """The passage sets out terms - a figure, a proviso, a permission or a condition - rather than naming a covenant and
    pointing elsewhere for the rest."""
    return _has_figure(text) or bool(_OWN_TERMS_RE.search(text))


def _qualified(text: str) -> bool:
    """A list item goes on, after the name of its covenant, to say what is excepted, permitted or conditional ("asset
    sales, except that the Borrower may ...", "liens other than ...", "dividends, which shall be permitted if ...") -
    more than a pointer to another document or to later agreement ("liens, to be consistent with the ... Precedent",
    "... with certain exceptions consistent with the Existing Agreement")."""
    rest = text[len(_head(text)):]
    for pointer in (_REF_RE, BY_REFERENCE_RE, _ELSEWHERE_RE, _DEFERRED_RE):
        rest = pointer.sub(" ", rest)
    return bool(_EXCEPTION_RE.search(rest))


def _keep_names(text: str) -> str:
    """A clause that defines a basket or an amount keeps the name it gives it - (the “Available Amount Basket”) - when it
    is made into a line: other rows speak of the thing by that name. (House-style lines otherwise drop such brackets.)"""
    return re.sub(r"\((the\s+)?[“\"]([^”\"]{1,60})[”\"]\)", r"(\1'\2')", text)


def _note_blanks(lines: list[str]) -> list[str]:
    """Say of each line that carries a blank left for a value that the term sheet leaves it blank."""
    return [ln + " (value left blank in term sheet)" if _BLANK_RE.search(ln) and "left blank" not in ln else ln for ln in lines]


def _closing_bracket(text: str, start: int) -> int:
    """Index of the bracket that closes the one opened at ``start``, -1 if it is never closed."""
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == "(") - (text[i] == ")")
        if depth == 0:
            return i
    return -1


def _run_key(text: str) -> str:
    """A line with its digits masked, so that "Page 3" and "Page 4" count as the same running line."""
    return re.sub(r"\d+", "#", tidy(text or "")).lower()


class _Span:
    """A stretch of a block's text, usable as the needle of ``ctx.quote`` (it only needs start() and end())."""

    def __init__(self, start: int, end: int):
        self._start, self._end = start, max(start, end)

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end


def _topics_in(text: str, names=tuple(_TOPIC_RES)) -> list[tuple[int, str]]:
    """(position, topic) for each topic named in ``text``, in order of first mention."""
    text = _NOT_A_TOPIC_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    found = []
    for name in names:
        m = _TOPIC_RES[name].search(text)
        if m:
            found.append((m.start(), name))
    names_found = {n for _, n in found}
    if "restrictive" in names_found:
        # a covenant about restrictions in other agreements is not about dividends or liens: those two count only where
        # the text names them outside the words of that covenant ("liens, ... and burdensome agreements")
        rest = _TOPIC_RES["restrictive"].sub(lambda k: " " * len(k.group(0)), text)
        kept = []
        for p, n in found:
            if n in ("rp", "liens"):
                m = _TOPIC_RES[n].search(rest)
                if m is None:
                    continue
                p = m.start()
            kept.append((p, n))
        found = kept
    if "payments" in names_found:  # "junior debt repayments" is about the payment, not the debt
        m = _TOPIC_RES["debt"].search(_TOPIC_RES["payments"].sub(lambda k: " " * len(k.group(0)), text))
        if not m:
            found = [(p, n) for p, n in found if n != "debt"]
    return sorted(found)


def _head(text: str) -> str:
    """The part of a list item that names the covenant, before any qualification."""
    m = _QUALIFIER_RE.search(text, 3)
    head = text[:m.start()] if m else text
    if len(head) > _HEAD_CHARS and (_has_figure(head) or len(head) > 200):
        return head[:_HEAD_CHARS].rsplit(" ", 1)[0]  # running text, not a list of covenant names
    return head


def _item_topics(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(negative-covenant topics named in the head of the item, other notable topics anywhere in it)."""
    notable = tuple(n for _, n in _topics_in(text, _NOTABLE_TOPICS))
    if "pari" in notable and not _AFFIRMATIVE_LEAD_RE.match(text):
        head = _head(text)
        if _topics_in(head, _NEG_TOPICS) and not _topics_in(head, ("pari",)):
            # the item names a covenant and "pari passu" stands only in its detail (the name of a basket, "the 'pari passu
            # debt' exception"): that does not make it a ranking undertaking
            notable = tuple(n for n in notable if n != "pari")
    if "pari" in notable:  # a ranking undertaking: the indebtedness it mentions is not a debt covenant
        return (), notable
    if _AFFIRMATIVE_LEAD_RE.match(text):  # "additional guarantees and collateral", "notices of default under other indebtedness"
        return (), notable
    return tuple(n for _, n in _topics_in(_head(text), _NEG_TOPICS)), notable


def _reference(text: str, lo: int = 0, hi: int | None = None) -> tuple[str, object] | None:
    """(phrase, match) if ``text`` (or its stretch lo..hi) points to another document or to later agreement instead of
    stating terms. The phrase reads on from "covenants are ...": "substantially similar to the Existing Credit Agreement",
    "customary for facilities of this type", "to be agreed", "subject to exceptions and baskets to be set forth in the ..."."""
    text = text or ""
    hi = len(text) if hi is None else hi
    m = _REF_RE.search(text, lo, hi)
    if m:
        phrase = _low(_norm(re.sub(r"\s*\([^)]*\)", "", m.group(0))))
        return ("the " + phrase if phrase.startswith("same ") else phrase), m
    m = BY_REFERENCE_RE.search(text, lo, hi)
    if m and _TO_BE_AGREED_RE.match(m.group(0)):
        # "... with exceptions and baskets to be agreed": it is the exceptions that are left open, not the covenants
        left = next((d for d in _DEFERRED_RE.finditer(text, lo, hi) if d.start() < m.start() < d.end()), None)
        if left is not None:
            return "subject to " + _low(_norm(left.group(0))), left
    if m:
        tail = re.match(r"(?:\s+for\s+(?:facilities|transactions|financings)(?:\s+and\s+(?:facilities|transactions))?)?"
                        r"(?:\s+of\s+this\s+(?:type|nature|kind|size))?", text[m.end():hi])
        phrase = _norm(m.group(0) + (tail.group(0) if tail else ""))
        if re.fullmatch(r"documentation\s+principles", phrase, re.IGNORECASE):
            phrase = "subject to the Documentation Principles"
        return _low(phrase), m
    m = _ELSEWHERE_RE.search(text, lo, hi)
    if m:
        return _low(_norm(m.group(0))), m
    m = _DEFERRED_RE.search(text, lo, hi)
    if m:  # the exceptions and baskets are left to the definitive documents
        return "subject to " + _low(_norm(m.group(0))), m
    return None


# ---- the covenant list ---------------------------------------------------------------------------------

@dataclass
class _Item:
    """One item of the covenant list."""
    text: str  # the item as listed
    block: Block
    start: int  # its place in block.text
    end: int
    neg: tuple[str, ...] = ()  # negative-covenant topics its head names
    notable: tuple[str, ...] = ()
    terminated: bool = False  # switched off by the fall-away sentence

    @property
    def span(self) -> _Span:
        return _Span(self.start, self.end)


@dataclass
class _Extra:
    """A clause after the covenant list that adds or changes a basket."""
    text: str  # the clause, with the words that introduce it
    block: Block
    start: int
    end: int
    topic: str = ""  # the first covenant topic it names ("" = applies generally)
    about: str = ""  # of an amount given as a sum, the words that say what it is for (its components name covenants in passing)

    @property
    def span(self) -> _Span:
        return _Span(self.start, self.end)


@dataclass
class _Package:
    """The covenant section of a term sheet, read as a list."""
    block: Block | None = None  # the section holding the list (or, with no list, the section's words)
    label: str = "Covenants"
    negative_only: bool = False  # the section is headed "Negative Covenants"
    none: bool = False  # the section says there are none ("Negative Covenants: None")
    blank: bool = False  # the section is left blank ("Negative Covenants: [ ]")
    cut_off: bool = False  # the text read breaks off in mid-phrase ("... change in fiscal year; and"): the list may be longer
    unread_part: bool = False  # a general section has a part headed "Negative Covenants" that could not be told apart
    intro: str = ""  # its words before the list
    items: list[_Item] = field(default_factory=list)
    opener: str = ""  # the words that open the list ("including, but not limited to")
    opener_block: Block | None = None  # where those words are, if not in ``block`` (the paragraph the section is part of)
    closed_block: Block | None = None  # where the words that close the list are
    closed_match: object = None
    ref_phrase: str = ""  # "substantially similar to the Existing Credit Agreement"
    ref_block: Block | None = None
    ref_match: object = None
    ref_in_intro: bool = True  # the pointer stands in the introduction (not in the words that open the list, nor in a parent section)
    ref_deferred: bool = False  # the pointer is to the definitive documents of this facility, for the exceptions and baskets only
    sub_headed: bool = False  # the section sets its covenants out under sub-headings of their own ("Indebtedness: ...")
    aside: str = ""  # what the opening words say of every item: "(in each case subject to exceptions ... consistent with ...)"
    aside_span: _Span | None = None
    extras: list[_Extra] = field(default_factory=list)
    unplaced: list[tuple[int, int]] = field(default_factory=list)  # sentences after the list (spans in block.text) that no row gives
    fall_event: str = ""  # "Covenant Fall-Away Event"
    fall_block: Block | None = None
    fall_span: _Span | None = None  # the covenants the sentence switches off
    fall_def: _Span | None = None  # what the event is
    affirmative: list[_Item] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        """The term sheet says the list is exhaustive."""
        return self.closed_match is not None and bool(self.items) and not self.cut_off

    def with_topic(self, topic: str) -> list[_Item]:
        """The items whose head names the topic."""
        return [it for it in self.items if topic in it.neg]

    def negatives(self) -> list[_Item]:
        """The negative covenants on the list: all of a "Negative Covenants" list, those of a mixed list that name one."""
        if self.negative_only:
            return [it for it in self.items if it.notable != ("pari",)]
        return [it for it in self.items if it.neg]


def _roman(tag: str) -> int | None:
    """Value of a lower-case roman numeral, None if ``tag`` is not one."""
    total, top = 0, 0
    for ch in reversed(tag):
        v = {"i": 1, "v": 5, "x": 10, "l": 50}.get(ch)
        if v is None:
            return None
        total += v if v >= top else -v
        top = max(top, v)
    return total or None


def _mark_value(tag: str, kind: str) -> int | None:
    """Position in its sequence of a list mark of the given kind: (3) / (C) / (iii) / (c) -> 3."""
    if kind == "digit":
        return int(tag) if tag.isdigit() else None
    if kind == "roman":
        return _roman(tag)
    if len(tag) != 1 or not tag.isalpha() or (kind == "upper") != tag.isupper():
        return None
    return ord(tag.lower()) - 96


def _mark_family(marks: list, first, text: str, from_one: bool = False) -> list:
    """The marks that carry on the sequence ``first`` starts: every bullet, or (a), (b), (c) ... / 1., 2., 3. ... in order.
    With ``from_one`` the sequence must start at its first number and may not skip one."""
    if first.group("bullet"):
        return [m for m in marks if m.group("bullet")]
    group = "dot" if first.group("dot") else "tag"
    tag = first.group(group)
    if tag.isdigit():
        kind = "digit"
    elif tag.isupper():
        kind = "upper"
    elif _roman(tag) is not None and (len(tag) > 1 or (tag == "i" and re.search(r"\(ii\)", text))):
        kind = "roman"
    else:
        kind = "alpha"
    family, expect = [], _mark_value(tag, kind)
    if (group == "dot" or from_one) and expect != 1:
        return []  # "... December 31. The" is a sentence end, not item 31 of a list
    for m in marks:
        value = _mark_value(m.group(group), kind) if m.start() >= first.start() and m.group(group) and expect is not None else None
        if value is not None and (value == expect or (family and value == expect + 1 and not from_one)):
            # (one mark may be missing from the text - lost in extraction - without the list ending there)
            family.append(m)
            expect = value + 1
    return family


def _marked_items(text: str, lo: int, hi: int, tabs: dict[int, tuple[int, int]] | None = None) -> list[tuple[int, int, int]] | None:
    """(start of the mark, start of the item, end of the item) for the items of a bulleted or numbered list in
    text[lo:hi]; None if the list is not marked that way.

    The list is the run of consecutive marks of one kind - (a), (b), (c) ... or 1., 2., 3. ... - that starts earliest,
    so the (i), (ii) of an item's own exceptions and cross-references such as "clause (a) above" do not split it.
    Marks inside brackets belong to the bracket - unless the layout shows them to be the numbers of the list (``tabs``,
    see ``_tab_marks``): where the items stand one under the other, each behind its number, the list is the run of
    numbers in that column, whatever bracket an item leaves open."""
    cand = [m for m in _MARK_RE.finditer(text, lo, hi) if not _XREF_BEFORE_RE.search(text[max(lo, m.start() - 24):m.start()])]
    flat = [m for m in cand if _depth0(text, lo, m.start())]
    laid = [m for m in cand if tabs and m.start() in tabs]
    firsts = sorted({m.start(): m for m in flat[:6] + laid[:6]}.items())
    for _, first in firsts[:8]:
        family = _mark_family(flat, first, text[lo:hi]) if _depth0(text, lo, first.start()) else []
        if tabs and first.start() in tabs:
            # the numbers the layout shows are the surer reading, unless part of the list is run on in the text
            shown = _mark_family(_same_column(laid, first, tabs), first, text[lo:hi], from_one=True)
            if len(shown) >= len(family):
                family = shown
        if len(family) >= 2:
            return [(m.start(), m.end(), family[i + 1].start() if i + 1 < len(family) else hi) for i, m in enumerate(family)]
    return None


def _same_column(laid: list, first, tabs: dict[int, tuple[int, int]]) -> list:
    """The laid-out list numbers that stand in the column of ``first``: on its own page that column, on another page the
    leftmost column that holds a list number (the left margin differs from page to page)."""
    page0, col0 = tabs[first.start()]
    left: dict[int, int] = {}
    for m in laid:
        page, col = tabs[m.start()]
        left[page] = min(left.get(page, col), col)
    left[page0] = col0
    return [m for m in laid if abs(tabs[m.start()][1] - left[tabs[m.start()][0]]) <= 1]


def _tab_marks(block: Block) -> dict[int, tuple[int, int]]:
    """Places in block.text where a source line begins with a list number that a gap sets off from its text - "(iv)
    Restricted payments", "3.   Limitation on ..." - the way a word processor sets out the items of a list:
    {offset in block.text: (page, column of the number)}. A number that merely happens to start a wrapped line
    ("(x) purchase money debt ...") has a single blank after it and is not one of these - unless it stands in the very
    column of the list's numbers on its page and no wrapped line of text starts in that column (a long number such as
    "(xviii)" may fill the whole gap)."""
    out: dict[int, tuple[int, int]] = {}
    rows: list[tuple[int, int, int, bool | None]] = []  # (offset, page, column, gap of two or more / one; None = a line of text)
    for ln, part, (a, b) in zip(block.lines, block.parts, _part_offsets(block)):
        if b <= a:
            continue
        pm = _LINE_MARK_RE.match(part)
        at = ln.text.find(pm.group("mark")) if pm else -1
        rest = ln.text[at + len(pm.group("mark")):] if at >= 0 else ""
        if not rest.strip():
            rows.append((a, ln.page, ln.indent, None))
            continue
        wide = len(rest) - len(rest.lstrip()) >= 2
        rows.append((a, ln.page, at, wide))
        if wide:
            out[a] = (ln.page, at)
    for page in {r[1] for r in rows if r[3]}:
        on_page = [r for r in rows if r[1] == page]
        first = next(i for i, r in enumerate(on_page) if r[3])
        last = max(i for i, r in enumerate(on_page) if r[3] is not None)
        cols = {r[2] for r in on_page if r[3]}
        inside = {r[2] for r in on_page[first:last + 1] if r[3] is None}  # where the items' wrapped lines start
        for a, _, col, wide in on_page[first:last + 1]:
            if wide is False and any(abs(col - c) <= 1 for c in cols) and not any(abs(col - c) <= 1 for c in inside):
                out[a] = (page, col)
    return out


def _para_starts(block: Block) -> list[int]:
    """Offsets in block.text at which a new paragraph starts: the line above it in the source is blank."""
    out = []
    offsets = _part_offsets(block)
    for i in range(1, len(block.lines)):
        prev, cur = block.lines[i - 1], block.lines[i]
        if cur.page == prev.page and cur.n - prev.n > 1 and offsets[i][1] > offsets[i][0]:
            out.append(offsets[i][0])
    return out


def _unclosed(text: str) -> list[int]:
    """Positions of the brackets that ``text`` opens and never closes."""
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            stack.pop()
    return stack


def _list_runs_on(text: str, spans: list[tuple[int, int]]) -> bool:
    """After the last item read there stands the number that would come next in the list - "(iii)" after items (i) and
    (ii): the list goes on inside what was read as its last item."""
    if len(spans) < 2:
        return False
    number = r"(?:\((?P<tag>[ivxl]{1,6}|[a-zA-Z]|\d{1,2})\)|(?P<dot>\d{1,2})\.)\s*$"
    prev, last = re.search(number, text[:spans[-2][0]]), re.search(number, text[:spans[-1][0]])
    if not prev or not last or bool(prev.group("dot")) != bool(last.group("dot")):
        return False
    group = "dot" if last.group("dot") else "tag"
    for kind in ("digit", "roman", "upper", "alpha"):
        a, b = _mark_value(prev.group(group), kind), _mark_value(last.group(group), kind)
        if a is None or b is None or b != a + 1:
            continue
        for m in _MARK_RE.finditer(text, spans[-1][0]):
            tag = m.group(group)
            if tag and _mark_value(tag, kind) == b + 1 and not _XREF_BEFORE_RE.search(text[max(0, m.start() - 24):m.start()]):
                return True
        return False
    return False


def _list_marks(text: str, start: int, hi: int, tabs: dict[int, tuple[int, int]] | None = None) -> list[tuple[int, int, int]] | None:
    """The numbered or bulleted items of the list that starts at ``start`` (see ``_marked_items``), or None. Numbers are
    those of the list only if the first of them follows the opening words directly: numbers that stand in a later
    sentence, or after items already given without one ("... liens; indebtedness; and dividends. The basket shall be the
    greater of (a) $50 million and (b) ..."), belong to a clause further on, not to the list."""
    marked = _marked_items(text, start, hi, tabs)
    if not marked:
        return None
    lead = text[start:marked[0][0]]
    if _SENT_END_RE.search(lead) or any(_depth0(lead, 0, m.start()) for m in re.finditer(";", lead)):
        return None
    return marked


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span past surrounding blanks, separators and a leading / trailing "and"."""
    start, end = max(0, start), min(len(text), end)
    while start < end and text[start] in " ;,.":
        start += 1
    while end > start and text[end - 1] in " ;,.":
        end -= 1
    m = re.match(r"(?:and|or)\s+", text[start:end], re.IGNORECASE)
    if m:
        start += m.end()
    m = re.search(r"[;,]?\s+(?:and|or)$", text[start:end], re.IGNORECASE)
    if m:
        end = start + m.start()
    while end > start and text[end - 1] in " ;,.":
        end -= 1
    return start, end


def _depth0(text: str, lo: int, pos: int) -> bool:
    """True if text[pos] is outside every bracket opened since ``lo``."""
    return text.count("(", lo, pos) <= text.count(")", lo, pos)


def _split_semicolons(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """Spans of the semicolon-separated items of text[lo:hi]; semicolons inside brackets do not separate."""
    spans, pos = [], lo
    for m in re.finditer(r";", text[lo:hi]):
        at = lo + m.start()
        if _depth0(text, lo, at):
            spans.append((pos, at))
            pos = at + 1
    spans.append((pos, hi))
    return spans


def _read_list(block: Block) -> tuple[int, int, list[tuple[int, int]], str, bool]:
    """(end of the introduction, end of the list, item spans, opening words, about the financial covenants) for the
    list in a covenant section. With no list the introduction is the whole text; when the opening words introduce
    the financial covenants what follows them is not the covenant list."""
    text = block.text
    opener, start, intro_end = "", None, 0
    m = _OPENER_RE.search(text)
    if m and _FINCOV_RE.search(m.group(0)) and not re.search(r"negative|affirmative", m.group(0), re.IGNORECASE):
        return m.start(), m.end(), [], "", True
    stem = None if m else _STEM_RE.match(text)
    if m:
        opener, start, intro_end = _norm(m.group(0)).rstrip(":").strip(), m.end(), m.start()
        if text[:m.start()].rstrip().lower().endswith(" to") and opener.lower().startswith("include"):
            opener = "to " + opener
        opener = _last_opener(opener)
    elif stem:
        start, intro_end = stem.end(), 0  # "Limitations on: liens (...); indebtedness (...); ..."
    else:
        sentence_end = _SENT_END_RE.search(text)
        first_stop = sentence_end.start() if sentence_end else len(text)
        # the last opening word of the first sentence that has covenants after it: in "limited to those customary for
        # ..., including limitations on liens and mergers" the list follows "including"
        bare = [k for k in _OPENER_BARE_RE.finditer(text, 0, first_stop) if _depth0(text, 0, k.start())]
        m = next((k for k in reversed(bare) if len({n for _, n in _topics_in(text[k.end():first_stop], _NEG_TOPICS)}) >= 2), None)
        if m:
            opener, start, intro_end = _norm(m.group(0)).strip(" ,"), m.end(), m.start()
        else:
            lead = _REF_RE.match(text) or (points_elsewhere(text[:70]) if text[:1].isupper() else None)
            comma = text.find(", ", lead.end() - 1) if lead else -1
            if lead and 0 <= comma < first_stop and len(_split_semicolons(text, comma + 2, first_stop)) >= 3:
                start, intro_end = comma + 2, comma  # "Consistent with ..., delivery of ...; approvals ...; ..."
            elif not lead and (len(_split_semicolons(text, 0, first_stop)) >= 3 or _list_marks(text, 0, len(text))):
                start = 0  # the section is the list itself
            elif not lead and len(text) <= 400 and len({n for _, n in _topics_in(text[:first_stop], _NEG_TOPICS)}) >= 2:
                stop = min(len(text), first_stop + 1)
                parts = _split_commas(text, 0, stop)  # "Limitations on liens, debt and ..."
                if parts:
                    return 0, parts[-1][1], parts, "", False
                return 0, stop, [_trim_span(text, 0, stop)], "", False
    if start is None:
        return len(text), len(text), [], "", False
    hi = len(text)
    marked = _list_marks(text, start, hi, _tab_marks(block))
    if marked:
        # a numbered or bulleted list: a proviso inside an item is part of that item ("(i) investments; provided that (A) ...;
        # (ii) indebtedness ..."), and so is the one after the last item unless it speaks of the package (``_general_proviso``)
        last_start = marked[-1][1]
        tail = next((k for k in _PROVISO_RE.finditer(text, last_start) if _depth0(text, last_start, k.start())), None)
        if tail is not None and _general_proviso(text, last_start, tail):
            hi = tail.start()
        spans = [(a, min(b, hi)) for _, a, b in marked]
        last_start = spans[-1][0]
        stop = _SENT_END_RE.search(text, last_start, hi)
        if stop and stop.start() - last_start <= 70 and any(_HEADING_ITEM_RE.match(text[a:b]) for a, b in spans[:-1]):
            # the items are written "Heading. What it says.": the last one too takes the sentence after its heading
            stop = _SENT_END_RE.search(text, stop.end(), hi) or re.search(r"\.\s*$", text[:hi])
        if stop:
            hi = stop.start() + 1
            spans[-1] = (last_start, hi)
        # ... and the last item ends with its paragraph: what starts a new paragraph with a capital letter after it
        # ("(xvii) the sale ... of assets (...);" / blank line / "The Facilities Documentation will include ...") is said of
        # the package, not of that item
        new_para = next((p for p in _para_starts(block) if last_start + 3 < p < hi and (text[p].isupper() or text[p] in "“\"")
                         and not _MARK_RE.match(text, p)), None)
        if new_para is not None:
            hi = new_para
            spans[-1] = (last_start, hi)
    else:
        # a list without numbers is one sentence, its items separated by semicolons or by commas
        stop = _SENT_END_RE.search(text, start, hi)
        if stop:
            hi = stop.start() + 1
        proviso = next((k for k in _PROVISO_RE.finditer(text, start, hi) if _depth0(text, start, k.start())), None)
        semicolons = proviso is None or any(_depth0(text, start, k.start()) for k in re.finditer(";", text[:proviso.start()]) if k.start() >= start)
        if semicolons:
            spans, hi = _plain_items(text, start, hi)
        else:
            hi = proviso.start()  # a list separated by commas ends at its proviso
            spans = [(start, hi)]
        if len(spans) == 1 and (proviso is None or not semicolons):  # no semicolons: a comma list, if it names several covenants
            parts = _split_commas(text, start, hi)
            if parts:
                spans, hi = parts, parts[-1][1]
    if len(spans) > 1:
        # "...; and transactions with affiliates, in each case subject to exceptions to be agreed": the closing remark is
        # about the whole list, not part of its last item
        a, b = spans[-1]
        m = next((k for k in _EACH_TAIL_RE.finditer(text, a + 3, b) if _depth0(text, a, k.start())), None)
        if m:
            spans[-1], hi = (a, m.start()), m.start()
    spans = [_trim_span(text, a, b) for a, b in spans]
    return intro_end, hi, [(a, b) for a, b in spans if b - a >= 3], opener, False


def _general_proviso(text: str, item_start: int, proviso) -> bool:
    """The proviso that follows the last item of a list is about the package, not about that item: it speaks of a
    covenant the item does not name ("...; and (f) asset sales; provided that (i) the lien basket shall ...") or of the
    covenants or baskets in general ("... will be added to each dollar basket")."""
    stop = _SENT_END_RE.search(text, proviso.end())
    said = text[proviso.end():stop.start() if stop else len(text)]
    own = {n for _, n in _topics_in(_head(text[item_start:proviso.start()]), _NEG_TOPICS)}
    named = {n for _, n in _topics_in(said, _NEG_TOPICS)}
    return bool(named - own) or bool(re.search(r"\bcovenants\b|\b(?:each|all|every|any)\s+(?:[\w\-]+\s+){0,3}baskets?\b|\bthe\s+foregoing\b|"
                                               r"\bin\s+each\s+case\b|\b(?:each|all)\s+of\s+the\b", said, re.IGNORECASE))


def _item_like(text: str) -> bool:
    """A semicolon-separated part reads as one more item of a covenant list - a short name ("investments", "and asset
    sales"), possibly with a proviso of its own - rather than as a clause of running text or a numbered limb."""
    inner = next((k for k in _PROVISO_RE.finditer(text) if k.start() > 0 and _depth0(text, 0, k.start())), None)
    part = _strip_item(text[:inner.start()] if inner else text)
    if not part or _PROVISO_LEAD_RE.match(part) or _MARK_RE.match(part):
        return False
    words = len(part.split())
    return words <= 5 or (words <= 12 and bool(_topics_in(_head(part), _NEG_TOPICS + _NOTABLE_TOPICS)))


def _plain_items(text: str, start: int, hi: int) -> tuple[list[tuple[int, int]], int]:
    """(item spans, end of the list) for a list without numbers in text[start:hi]: one sentence, its items separated by
    semicolons. A proviso does not end such a list where items follow it - it is said of the item it stands with
    ("liens; indebtedness, provided that ...; investments; and dividends"). The proviso after the last item stays with
    that item unless it speaks of other covenants or of the package (``_general_proviso``): then the list ends before it."""
    parts = _split_semicolons(text, start, hi)
    items: list[tuple[int, int]] = []
    for i, (a, b) in enumerate(parts):
        opens = _PROVISO_LEAD_RE.match(text, a, b)
        inner = None if opens else next((k for k in _PROVISO_RE.finditer(text, a, b) if _depth0(text, a, k.start())), None)
        if not opens and inner is None:
            items.append((a, b))
            continue
        more = [text[x:y] for x, y in parts[i + 1:]]
        if any(_item_like(p) for p in more) and all(_item_like(p) or _PROVISO_LEAD_RE.match(p) for p in more):
            # items follow: the proviso is said of this item (where the part opens with it, of the item before)
            if opens and items:
                items[-1] = (items[-1][0], b)
            else:
                items.append((a, b))
            continue
        # the last proviso of the sentence: about the package, or about the item it stands with
        proviso = inner or next(iter(_PROVISO_RE.finditer(text, max(start, a - 1), b)), None)
        owner = items[-1][0] if opens and items else a
        if proviso is not None and _general_proviso(text, owner, proviso):
            if not opens and proviso.start() - a >= 3:
                items.append((a, proviso.start()))
            return items, proviso.start()
        if opens and items:
            items[-1] = (items[-1][0], hi)
        else:
            items.append((a, hi))
        return items, hi
    return items, hi


def _last_opener(opener: str) -> str:
    """The words that actually open the list, when the opening runs through more than one of them: "limited to the
    Borrower and its subsidiaries and to include" -> "to include"."""
    last = None
    for last in _OPEN_RE.finditer(opener):
        pass
    if last is None or not _CLOSED_RE.search(opener[:last.start()]):
        return opener
    lead = "to " if opener[:last.start()].rstrip().lower().endswith(" to") else ""
    return (lead + opener[last.start():]).strip()


def _split_commas(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """Spans of the items of a list separated by commas only ("liens, indebtedness, restricted payments and asset
    sales"), [] if text[lo:hi] is not one. A part that qualifies the one before it (", with a general basket of ...",
    ", subject to ...") stays with it; a closing ", in each case ..." is about the whole list and is left out. The
    text is only read as such a list when its parts name at least three different covenants: one covenant described
    with commas stays one item."""
    cuts = [m for m in _COMMA_RE.finditer(text, lo, hi) if _depth0(text, lo, m.start())]
    if len(cuts) < 2:
        return []
    raw, pos = [], lo
    for m in cuts:
        raw.append((pos, m.start()))
        pos = m.end()
    raw.append((pos, hi))
    if _EACH_CASE_RE.match(text[raw[-1][0]:raw[-1][1]]):
        raw.pop()  # ", in each case with exceptions to be agreed": about every item
    parts: list[tuple[int, int]] = []
    for a, b in raw:
        if parts and _QUALIFIER_START_RE.match(text[a:b]):
            parts[-1] = (parts[-1][0], b)
        else:
            parts.append((a, b))
    parts = [_trim_span(text, a, b) for a, b in parts]
    parts = [(a, b) for a, b in parts if b - a >= 3]
    named = {n for a, b in parts for _, n in _topics_in(_head(text[a:b]), _NEG_TOPICS)}
    return parts if len(parts) >= 3 and len(named) >= 3 else []


def _closing_words(lead: str, about_covenants: bool = False):
    """The match of the words that make the list after ``lead`` exhaustive ("... and limited to:", "will include only the
    following covenants ...:"), or None. They must be the last thing said before the list and be about the list: an
    "including" after them, or "limited to" something else ("limited to the Borrower and its subsidiaries and to
    include: ..."), leaves the list open. ``about_covenants`` also requires the words to speak of covenants (used for
    the general paragraph above a "Negative Covenants" sub-section)."""
    found = list(_CLOSED_RE.finditer(lead or ""))
    if not found:
        return None
    last = found[-1]
    if _FOLLOWING_RE.match(last.group(0)):
        if len(found) > 1 and not lead[found[-2].end():last.start()].strip():
            last = found[-2]  # "will include only" + "the following covenants": one phrase
        elif _OPEN_RE.search(lead[max(0, last.start() - 40):last.start()]):
            return None  # "will include the following covenants": not said to be all of them
    tail = lead[last.end():]
    if _OPEN_RE.search(tail):
        return None
    only = re.search(r"^(?:only|solely|exclusively|the\s+following)\b|\bonly$", last.group(0), re.IGNORECASE) is not None
    if not (_CLOSED_ONLY_TAIL_RE if only else _CLOSED_TAIL_RE).match(tail):
        return None
    if about_covenants and not re.search(r"covenants?|undertakings?", lead[max(0, last.start() - 80):], re.IGNORECASE):
        return None
    return last


def _make_items(block: Block, spans: list[tuple[int, int]]) -> list[_Item]:
    """The list items at ``spans`` of block.text, each tagged with the topics it names."""
    items = []
    for a, b in spans:
        text = _strip_item(_LINE_MARK_RE.sub("", _strip_item(block.text[a:b]), count=1))  # (without a number left in front of it)
        if not text or text.lower() in ("and", "or", "and/or"):
            continue  # (what is left of an item where the section breaks off)
        neg, notable = _item_topics(text)
        items.append(_Item(text=text, block=block, start=a, end=b, neg=neg, notable=notable))
    return items


def _sentences(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """Spans of the sentences of text[lo:hi]."""
    out, pos = [], lo
    for end in [m.start() + 1 for m in _SENT_END_RE.finditer(text, lo, hi)] + [hi]:
        a, b = _trim_span(text, pos, end)
        if b - a >= 12:
            out.append((a, b))
        pos = end
    return out


def _limbs(text: str, lo: int, hi: int) -> list[tuple[str, int, int]]:
    """A sentence as (stem, start, end) clauses: its lettered or numbered limbs, each with the words that introduce
    them ("baskets for (A) liens ..., (B) investments ..."), or the sentence itself."""
    limbs = _marked_items(text, lo, hi)
    if not limbs:
        return [("", lo, hi)]
    if any(_SUM_LIMB_RE.search(text[lo:mark]) for mark, _, _ in limbs[1:]) or _ONE_WHOLE_RE.search(text[lo:limbs[0][0]]):
        # "an amount equal to (a) ..., plus (b) ..., minus (c) ...", "the greater of (a) ... and (b) ...", "so long as (i)
        # ... and (ii) ...": one amount or one condition, not a list of baskets. (The third value says where the words
        # that tell what it is for end: before its components.)
        return [("", lo, hi, limbs[0][0])]
    if len({_clause_topic(text[a:b]) for _, a, b in limbs}) < 2:
        # the limbs are split to send each to the row of the covenant it names; limbs that all speak of one covenant (or
        # of none) are parts of one clause, which stays whole and in the term sheet's words
        return [("", lo, hi)]
    stem = _strip_item(_PROVISO_RE.sub(" ", " " + text[lo:limbs[0][0]]))
    out = []
    for _, a, b in limbs:
        a, b = _trim_span(text, a, b)
        if b - a >= 8:
            out.append((stem, a, b))
    return out


def _singular(text: str) -> str:
    """Lower-case words without a final "s", to compare "sale of assets" with "sales of assets"."""
    return " ".join(re.sub(r"s$", "", w) for w in re.findall(r"[a-z]+", text.lower()))


def _clause_topic(clause: str) -> str:
    """The covenant a clause about baskets belongs to: the first one it names ("baskets for liens permitting indebtedness
    in connection with ..." is about liens). A clause that opens on two covenants at once ("the debt and lien baskets
    will each be increased ...") belongs to no single row ("")."""
    found = _topics_in(clause, _NEG_TOPICS)
    if not found:
        return ""
    if len(found) > 1:
        blanked = _NOT_A_TOPIC_RE.sub(lambda m: " " * len(m.group(0)), clause)
        first = _TOPIC_RES[found[0][1]].search(blanked)
        if first and re.fullmatch(r"\s*(?:,|and|or|&|/|,\s*and)\s*", blanked[first.end():found[1][0]] or "x"):
            return ""
    return found[0][1]


def _plausible_list(block: Block, parsed: tuple) -> bool:
    """A section read as a list although no words introduce one ("Use of proceeds; merger; liens; ...") must look like
    one: most of its items open with a short name, and it names covenants or is short throughout. Running text with a
    few semicolons or bracketed numbers in it does not."""
    intro_end, _, spans, opener, _ = parsed
    if opener or intro_end > 0 or len(spans) < 2:
        return True
    heads = [_head(block.text[a:b]) for a, b in spans]
    short = sum(1 for h in heads if len(h.split()) <= 12 and not re.search(r"[$€£%]|\d{3}", h))
    named = sum(1 for h in heads if _topics_in(h, _NEG_TOPICS + _NOTABLE_TOPICS))
    return short * 2 >= len(heads) and (named * 3 >= len(heads) or all(len(h.split()) <= 6 for h in heads))


def _sub_sections(block: Block) -> tuple[Block | None, list[tuple[str, int, Block]]]:
    """A general covenant section written as a lead-in and lettered or numbered sub-sections - "... including the
    following: (a) Affirmative Covenants - ... (b) Negative Covenants - Restrictions on: ..." - as (the lead-in as a block
    of its own, [(heading, source line of the heading, the sub-section as a block of its own)]). A section is read this
    way only when it has at least two such headings; otherwise the list is empty."""
    text = block.text
    heads = {m.start(): (m.end(), _norm(m.group("label"))) for m in _SUB_HEAD_RE.finditer(text)}  # start -> (end, heading)
    # ... and headings without a number: a line of the section that is nothing but the heading, or the heading at the
    # start of a paragraph (the line above it is blank)
    offsets = _part_offsets(block)
    for i in range(1, len(block.lines)):
        a, b = offsets[i]
        m = _SUB_LINE_RE.match(text, a, b) if b > a else None
        if m is None or any(s <= a < e for s, (e, _) in heads.items()):
            continue
        alone = m.end() >= b
        new_para = block.lines[i].page == block.lines[i - 1].page and block.lines[i].n - block.lines[i - 1].n > 1
        if alone or (new_para and m.group("end").strip()):
            heads[a] = (min(len(text), m.end() + (1 if alone else 0)), _norm(m.group("label")))
    if len(heads) < 2:
        return None, []
    out = []
    starts = sorted(heads)
    for i, at in enumerate(starts):
        head_end, label = heads[at]
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        sub = _sub_block(block, _Span(head_end, end)) if end - head_end >= 2 else None
        if sub is not None:
            sub.label = label
            out.append((sub.label, block.lines[block.line_at(at)].n, sub))
    lead = _sub_block(block, _Span(0, starts[0])) if starts[0] >= 12 else None
    return lead, out


def _build_package(ctx: Ctx, state: "_State") -> _Package | None:
    """Read the covenant section(s) of the document into a _Package, or None if there is none."""
    amend_pages, terms = state.amend_pages, state.terms_pages
    # a covenant section is a labelled section of a page of terms; in the prose of a presentation only a bullet of its
    # own counts ("• Negative covenants: ..."), since a "Covenants:" line there takes the rest of the slide with it
    usable = lambda b: (bool(b.text) and len(b.label) <= 60 and b.page not in amend_pages  # noqa: E731
                        and (state.is_section(b) or bool(_BULLET_START_RE.match(b.line.text))))
    neg_blocks = [state.clean(b) for b in ctx.all(_NEG_LABEL) if usable(b)]
    gen_blocks = []
    for b in ctx.all(_GEN_LABEL):
        if not usable(b):
            continue
        # a label that wraps ("Negative" / "Covenants:") is found by its last line: sort it by its whole label, and
        # leave out what is not a covenant section at all ("Financial" / "Covenants:")
        label = _norm(b.label).rstrip(":").strip()
        if re.fullmatch(_NEG_LABEL, label, re.IGNORECASE):
            if all(b.line.n != x.line.n for x in neg_blocks):
                neg_blocks.append(state.clean(b))
        elif re.fullmatch(_GEN_LABEL, label, re.IGNORECASE):
            gen_blocks.append(state.clean(b))
    labelled = len(neg_blocks)
    lead_of: dict[int, Block | None] = {}  # a sub-section taken from a general paragraph -> that paragraph's lead-in
    for k, b in enumerate(list(gen_blocks)):
        # "Covenants: ... including the following: (a) Affirmative Covenants - ... (b) Negative Covenants - Restrictions on:
        # (i) ...": the paragraph is a lead-in and sub-sections, not a list of covenants. The negative covenants are the
        # sub-section under that heading (it replaces a section found for the same heading that the section finder cut
        # short); the paragraph itself is read as its lead-in only.
        lead, subs = _sub_sections(b)
        if not subs:
            continue
        gen_blocks[k] = lead
        found = next(((n, sub) for label, n, sub in subs if re.fullmatch(_NEG_LABEL, label, re.IGNORECASE)), None)
        if found is not None:
            twin = next((i for i, x in enumerate(neg_blocks) if found[0] <= x.line.n <= found[1].line.n), None)
            if twin is not None and len(found[1].text) > len(neg_blocks[twin].text):
                neg_blocks[twin] = found[1]
                lead_of[id(found[1])] = lead
            elif twin is None and not labelled:
                neg_blocks.append(found[1])
                lead_of[id(found[1])] = lead
    gen_blocks = [b for b in gen_blocks if b is not None]
    for b in gen_blocks:
        # "Covenants: ... Negative covenants will include limitations on liens, ..."
        m = _NEG_SENTENCE_RE.search(b.text)
        stop = _SENT_END_RE.search(b.text, m.end()) if m else None
        sub = _sub_block(b, _Span(m.end(), stop.start() + 1 if stop else len(b.text))) if m else None
        if sub is not None and len(sub.text) >= 12 and not labelled:
            sub.label = "Negative covenants"
            neg_blocks.append(sub)
    for row in state.rows:  # ... and so is a "Negative covenants" row of an amendment table (its proposed cell)
        cell = row.existing if row.same else row.proposed
        if row.unsure or cell is None or not cell.text:
            continue
        if re.fullmatch(_NEG_LABEL, row.label, re.IGNORECASE):
            neg_blocks.append(cell)
        elif re.fullmatch(_GEN_LABEL, row.label, re.IGNORECASE):
            gen_blocks.append(cell)
    for blocks in (neg_blocks, gen_blocks):  # a covenant section on a page of terms beats one in slide prose
        blocks.sort(key=lambda b: (b.page not in terms, b.line.n))
    if not neg_blocks and not gen_blocks:
        return None
    b = (neg_blocks or gen_blocks)[0]
    if _NONE_CELL_RE.match(b.text) or _ONLY_BLANK_RE.match(b.text):  # "Negative Covenants: None", "Negative Covenants: [ ]"
        blank = not _NONE_CELL_RE.match(b.text)
        return _Package(block=b, negative_only=bool(neg_blocks), none=not blank, blank=blank,
                        label=_norm(b.label).title() if b.label.isupper() else _norm(b.label))
    pkg = _Package()
    parsed = None
    for negative_only, blocks in ((True, neg_blocks), (False, gen_blocks)):
        for b in blocks:
            got = _read_list(b)
            if got[2] and _plausible_list(b, got):
                pkg.block, pkg.negative_only, parsed = b, negative_only, got
                break
        if parsed:
            break
    if parsed is None:  # no list anywhere: keep the section's words, unless they are about the financial covenants
        general = [b for b in gen_blocks if _read_list(b)[4] or not _RATIO_LEVEL_RE.search(b.text[:400])]
        if not neg_blocks and not general:
            return None
        pkg.block = (neg_blocks or general)[0]
        pkg.negative_only = bool(neg_blocks)
        parsed = _read_list(pkg.block)
        if parsed[2]:  # what looked like a list is running text
            parsed = (len(pkg.block.text), len(pkg.block.text), [], "", False)
    block, text = pkg.block, pkg.block.text
    intro_end, list_end, spans, pkg.opener, about_fincov = parsed
    if not spans and not about_fincov:  # a section without a list: its first sentence is the introduction
        first = _SENT_END_RE.search(text)
        intro_end = first.start() + 1 if first else len(text)
    pkg.label = _norm(block.label).title() if block.label.isupper() else _norm(block.label)
    pkg.intro = _DANGLING_END_RE.sub("", " " + _norm(text[:intro_end]).strip(" ,;:.")).strip()
    # the text breaks off if it ends in mid-phrase or inside a bracket. A bracket left open in an item that further items
    # follow is a slip of the drafting, not a break (the list was then told apart by its layout)
    open_at = _unclosed(text)
    # ... nor is a list relied on that has an open bracket somewhere and, inside its last item, the number that would
    # come next: the list was not told apart to its end
    runs_on = bool(open_at) and _list_runs_on(text, spans)
    pkg.cut_off = bool(_CUT_OFF_RE.search(text)) or any(p >= (spans[-1][0] if spans else 0) for p in open_at) or runs_on
    # ... or if it stops at the foot of a page without a full stop: it goes on overleaf in a way that was not followed
    # (said of the running text of a term sheet only: the cells of a table and the bullets of a slide end without one)
    pkg.cut_off = pkg.cut_off or (block.mode == "column" and len(text) > 150 and state.at_page_foot(block)
                                  and not _FULL_STOP_END_RE.search(text))
    kept = spans
    if pkg.cut_off:
        # of such a section an item is only used where its extent is known: not one that holds an open bracket, nor the
        # last one where the list runs on in it or the text breaks off in it ("... asset sales, with a general basket of")
        kept = [(a, b) for a, b in spans if not any(a <= p < b for p in open_at)]
        ends_text = bool(kept) and kept[-1] == spans[-1] and not text[kept[-1][1]:].strip(" ;,.")
        if kept and kept[-1] == spans[-1] and (runs_on or _CUT_OFF_RE.search(text[kept[-1][0]:kept[-1][1]])
                                               or (ends_text and len(text[kept[-1][0]:kept[-1][1]]) > 60 and not _FULL_STOP_END_RE.search(text))):
            kept = kept[:-1]  # (also a long last item that the text simply stops in)
    pkg.items = _make_items(block, kept)
    said = re.sub(r"\([^)]*\)", " ", pkg.opener)  # the opening words without their asides
    if pkg.items and _MODIFICATION_RE.search(said) and not re.search(r"covenants?|undertakings?", said, re.IGNORECASE):
        # "... with the following modifications: (i) the general debt basket shall be ...": what is listed are changes to
        # the package, each of which goes to the row of the covenant it names; the covenants themselves are not listed
        pkg.extras += [_Extra(text=it.text, block=block, start=it.start, end=it.end, topic=_clause_topic(it.text)) for it in pkg.items]
        pkg.items, pkg.opener = [], ""
    if not pkg.negative_only and pkg.items and not any(it.neg for it in pkg.items):
        # a general "Covenants" list with no negative covenant in it is an affirmative list
        pkg.affirmative, pkg.items = pkg.items, []
    if not pkg.negative_only and not pkg.items and _NEG_HEADING_RE.search(text, intro_end):
        # ... but where the section goes on to a part headed "Negative Covenants" that was not told apart from the rest,
        # nothing is said of what it lists or does not list: the section counts as not read to its end
        pkg.unread_part = pkg.cut_off = True
        pkg.affirmative = []

    # words that close the list, and the document the section points to: in the section itself, else in the
    # general "Covenants" paragraph above a "Negative Covenants" sub-section
    parents = [b for b in gen_blocks if b is not block]
    opener_at = text.rfind(":", 0, spans[0][0]) if spans else -1
    head_text = text[:spans[0][0]] if spans else text
    # (a bare "the following covenants" is not taken to close the list of a document that says it does not set out all terms)
    relied_on = lambda k: k is not None and not (state.not_all_terms and _WEAK_CLOSE_RE.match(k.group(0)))  # noqa: E731
    m = _closing_words(head_text) if pkg.items else None
    if relied_on(m):
        pkg.closed_block, pkg.closed_match = block, m
    elif pkg.items and not _OPEN_RE.search(head_text[max(0, opener_at - 160):]):
        for parent in parents:
            # the paragraph's lead-in, up to the colon that hands over to its sub-sections (or its first sentence)
            colon, stop = parent.text.find(":"), _SENT_END_RE.search(parent.text)
            lead = parent.text[:colon] if 0 <= colon <= 400 else parent.text[:stop.start() if stop else len(parent.text)]
            m = _closing_words(lead, about_covenants=True) if parent.line.n < block.line.n else None
            if relied_on(m):
                pkg.closed_block, pkg.closed_match = parent, m
                break
            # ... or the words that open the paragraph's list of sub-sections: "..., including, without limitation, the following:"
            opens = _OPENER_RE.search(parent.text) if lead_of.get(id(block)) is parent and not pkg.opener else None
            if opens and opens.end() == colon + 1 and _OPEN_RE.search(opens.group(0)) and not _FINCOV_RE.search(opens.group(0)):
                pkg.opener, pkg.opener_block = _last_opener(_norm(opens.group(0)).rstrip(":").strip()), parent
    if pkg.items:  # what the opening words say of every item: "... limitations on (in each case subject to ...):"
        aside = _LIST_ASIDE_RE.search(head_text)
        if aside and _ASIDE_START_RE.match(_norm(aside.group(1))):
            # (only an aside that qualifies the items: "(including, without limitation)" opens the list, "(as defined in
            # Annex A)" belongs to a word before it)
            pkg.aside, pkg.aside_span = _norm(aside.group(1)), _Span(aside.start(1), aside.end(1))
    ref = _reference(text, 0, intro_end) if spans else _reference(text)
    if not ref and spans:  # ... the pointer may stand in the words that open the list
        ref = _reference(text, intro_end, spans[0][0])
        pkg.ref_in_intro = False
    closing_remark = None
    if not ref and spans and _EACH_TAIL_RE.match(text, list_end):
        # ... or in the remark that closes it: "...; and affiliate transactions, in each case with exceptions to be agreed"
        stop = _SENT_END_RE.search(text, list_end)
        ref = _reference(text, list_end, stop.start() if stop else len(text))
        if ref:
            closing_remark = (list_end, stop.start() + 1 if stop else len(text))
    if ref:
        pkg.ref_phrase, pkg.ref_block, pkg.ref_match = ref[0], block, ref[1]
    else:
        for parent in parents:
            ref = _reference(parent.text)
            if ref:
                pkg.ref_phrase, pkg.ref_block, pkg.ref_match, pkg.ref_in_intro = ref[0], parent, ref[1], False
                break
    pkg.ref_deferred = bool(ref) and ref[1].re is _DEFERRED_RE
    if pkg.ref_phrase and "documentation principles" in pkg.ref_phrase.lower():
        # the principles themselves usually name the precedent agreement
        for b in ctx.all(_DOC_LABEL):
            b = state.clean(b)
            m = _REF_RE.search(b.text) if usable(b) else None
            if m:
                pkg.ref_phrase = _low(_norm(re.sub(r"\s*\([^)]*\)", "", m.group(0)))) + " (Documentation Principles)"
                pkg.ref_block, pkg.ref_match = b, m
                break

    # after the list: the fall-away sentence and the clauses that add or change baskets
    if spans:
        rest_lo = list_end
    else:
        rest_lo = intro_end if about_fincov else len(text)
        if not about_fincov:  # a section without a list: its first sentence is the introduction
            first = _SENT_END_RE.search(text)
            rest_lo = first.start() + 1 if first else len(text)
    for a, b in _sentences(text, rest_lo, len(text)):
        if a - rest_lo > 3000:
            break  # (what stands pages after the list is no longer taken to be said of it)
        sentence = text[a:b]
        fall = _FALL_AWAY_RE.search(sentence)
        if fall and re.search(r"\bcovenants?\b", sentence, re.IGNORECASE):
            if pkg.fall_block is None:
                _read_fall_away(pkg, block, a, b, fall)
            continue
        changes_amount = _has_amount(sentence) and bool(_AMOUNT_CHANGE_RE.search(sentence))
        # the proviso that closes the list is said of the covenants listed, whatever words it uses
        closes_list = bool(spans) and a - rest_lo <= 8 and bool(_PROVISO_LEAD_RE.match(sentence))
        if not closes_list:
            about_baskets = bool(_BASKET_RE.search(sentence) or changes_amount) and not re.search(r"financial\s+covenants?", sentence, re.IGNORECASE)
            if about_baskets and re.search(r"\bratio\b", sentence, re.IGNORECASE) and not re.search(r"\bbaskets?\b", sentence, re.IGNORECASE):
                about_baskets = False  # a financial covenant, not a basket
            if not about_baskets:
                pkg.unplaced.append((a, b))  # (not given in any row: a row whose covenant it names does not say "not detailed")
                continue
        for stem, la, lb, *named_by in _limbs(text, a, b):
            clause = text[la:lb]
            if _REF_RE.match(clause):
                continue
            body = _strip_item(_PROVISO_RE.sub(" ", " " + clause, count=1) if _PROVISO_LEAD_RE.match(clause) else clause)
            topic = _clause_topic(text[la:named_by[0]] if named_by else clause)
            if pkg.cut_off and (lb >= len(text.rstrip(" ;,.")) or any(la <= p < lb for p in open_at)):
                continue  # the clause the text breaks off in
            if closing_remark and closing_remark[0] <= la and lb <= closing_remark[1] and not topic and not _has_figure(clause):
                continue  # the list's closing remark, already given as what the section points to
            pkg.extras.append(_Extra(text=f"{stem} {body}" if stem else body, block=block, start=la, end=lb, topic=topic,
                                     about=text[la:named_by[0]] if named_by else ""))
    if pkg.fall_block is not None and pkg.fall_span is not None:
        switched = _singular(text[pkg.fall_span.start():pkg.fall_span.end()])
        for it in pkg.items:
            head = _singular(_head(it.text))
            it.terminated = bool(head) and head in switched

    if pkg.unread_part:
        pkg.extras, pkg.unplaced = [], []
    if not (pkg.items or pkg.affirmative or pkg.ref_phrase or pkg.extras or pkg.fall_block is not None):
        if not (pkg.cut_off and (pkg.negative_only or pkg.unread_part)):  # (a negative covenant section that could not be read is kept, to say so)
            return None  # a paragraph that neither lists covenants nor points to another document
    # the affirmative list, for the [Other] row
    if pkg.items and not pkg.negative_only:
        pkg.affirmative = [it for it in pkg.items if not it.neg and not it.notable]
    elif not pkg.affirmative:
        for b in ctx.all(_AFF_LABEL):
            if not usable(b):
                continue
            b = state.clean(b)
            got = _read_list(b)
            pkg.affirmative = _make_items(b, got[2]) if _plausible_list(b, got) else []
            if pkg.affirmative:
                break
    return pkg


def _read_fall_away(pkg: _Package, block: Block, a: int, b: int, fall) -> None:
    """Record the fall-away sentence block.text[a:b]: the event, what it is, and the covenants it switches off."""
    sentence = block.text[a:b]
    events = [m for m in _DEFINED_EVENT_RE.finditer(sentence, 0, fall.start())]
    then = None
    for then in _THEN_RE.finditer(sentence, 0, fall.start()):
        pass
    pkg.fall_block = block
    pkg.fall_event = events[-1].group(1) if events else ""
    pkg.fall_span = _Span(a + (then.end() if then else 0), a + fall.end())
    if events and then:
        # the event is what the sentence describes before the bracket that names it: "(A) ... or (B) ... (... referred to as a X)"
        name_at = events[-1].start()
        opened = max((k for k in range(name_at) if sentence[k] == "(" and not _depth0(sentence, k, name_at)), default=-1)
        first = _MARK_RE.search(sentence)
        start = first.start() if first and first.start() < name_at else 0
        end = opened if opened > start else name_at
        if end - start >= 20:
            pkg.fall_def = _Span(a + start, a + end)


# ---- amendment tables: label, existing and proposed columns ---------------------------------------------

@dataclass
class _Row:
    """A row of terms with a label: a row of an amendment table, a labelled section, or a sub-heading of the covenant
    section. The cells are Blocks, so quotes can be cut from them like from any section."""
    label: str
    page: int
    existing: Block | None  # the existing cell (None where the document has a single value column)
    proposed: Block | None  # the proposed cell, or the only one
    same: bool = False  # the proposed cell says "Same as existing"
    unsure: bool = False  # boundaries or columns could not be established with confidence
    inner: bool = False  # a sub-heading inside the covenant section, not a row of a table
    plain: bool = False  # a row of a summary table with a single value column (no existing / proposed)


def _cell_block(label: str, lines: list[Line], parts: list[str], mode: str) -> Block | None:
    """A table cell as a Block: the lines of its row on which it has text, and that text."""
    keep = [(ln, p) for ln, p in zip(lines, parts) if p.strip()]
    if not keep:
        return None
    return Block(label=label, line=keep[0][0], lines=[k[0] for k in keep], parts=[k[1] for k in keep], inline=False, mode=mode)


def _header_spans(text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Spans of the "Existing" and "Proposed" header cells if this line is the header of an amendment table."""
    cells = fragments(text, 3)
    if not 2 <= len(cells) <= 3:
        return None
    ex = [c for c in cells if _EXISTING_HEAD_RE.match(c[2]) and len(c[2].split()) <= 3]
    pr = [c for c in cells if _PROPOSED_HEAD_RE.match(c[2]) and len(c[2].split()) <= 3]
    if len(ex) == 1 and len(pr) == 1 and ex[0][0] < pr[0][0] and pr[0] is cells[-1]:
        # (a further column to the right of "Proposed" - comments, rationale - would run into the proposed cells)
        return (ex[0][0], ex[0][1]), (pr[0][0], pr[0][1])
    return None


def _column_edge(starts: Counter) -> int | None:
    """Left edge of a column from the positions its cells start at: the leftmost recurring start near the commonest
    one (bullets and "Same as existing" may start a little left of the wrapped text)."""
    if not starts:
        return None
    modal = starts.most_common(1)[0][0]
    near = [s for s, c in starts.items() if modal - 8 <= s <= modal and c >= 2]
    return min(near) if near else modal


def _continues(prev: str, cur: str, lax: bool = False) -> bool:
    """The cell text ``cur`` carries on the phrase that ``prev`` (the line above, same column) left unfinished.

    A line that ends in the middle of a phrase or inside a bracket is unfinished whatever follows. A next line that
    starts in lower case is a wrapped line if the line above is a full line of running text; after a short line, or
    one that ends on a figure, it may just as well be an item of its own ("Unlimited" / "up to $25mm"). That case is
    read as a continuation, or under ``lax`` as a new item; a table is read both ways and a row is kept only if the
    two readings agree on it (``_read_table``)."""
    if not prev or not cur or _BULLET_START_RE.match(cur):
        return False
    if _HANGING_END_RE.search(prev) or prev.count("(") > prev.count(")"):
        return True
    if not cur[0].islower():
        return False
    return not lax or (len(prev) >= 45 and prev[-1].isalpha())


def _label_groups(cells: list[tuple[str, str, str]]) -> list[tuple[int, int]]:
    """Line ranges of the labels in a run of table lines. A label may wrap over several lines."""
    groups: list[list[int]] = []
    for i, (label, _, _) in enumerate(cells):
        if not label:
            continue
        prev = cells[i - 1][0] if i and groups and groups[-1][-1] == i - 1 else ""
        if prev and (_LABEL_CARRIES_RE.search(prev) or _LABEL_OPENS_RE.match(prev) or prev.count("(") > prev.count(")")
                     or label[0].islower() or label[0] in "(/&"):
            groups[-1].append(i)
        else:
            groups.append([i])
    merged: list[list[int]] = []
    for g in groups:
        empty = not any(cells[i][1] or cells[i][2] for i in g)
        if empty and merged and merged[-1][-1] == g[0] - 1:
            merged[-1].extend(g)  # a label line with no value beside it is the tail of the label above
        else:
            merged.append(g)
    return [(g[0], g[-1]) for g in merged]


def _row_cost(cells, a: int, b: int, s: int, e: int) -> float:
    """How badly the row s..e fits a label on lines a..b that is centred vertically against its cells."""
    # where the free lines cannot be shared equally, the label (or the cell) sits on the upper of the two middle
    # positions: that is as natural as dead centre and costs nothing, so a choice between two splits that are both
    # natural ends as a tie (unsure) instead of being settled by a hair
    off = (e - b) - (a - s)
    cost = 0.0 if off in (0, 1) else abs(off) + (0.3 if off < 0 else 0.0)
    for col in (1, 2):
        used = [i for i in range(s, e + 1) if cells[i][col]]
        if used:
            off = (e - used[-1]) - (used[0] - s)
            cost += 0.0 if off in (0, 1) else 0.2 * min(3, abs(off))
    return cost


def _segment(cells: list[tuple[str, str, str]], lax: bool = False) -> tuple[list[tuple[int, int, int, int, bool]], set[int]]:
    """Split a run of table lines into rows: ([(first line, last line, first label line, last label line, unsure)],
    lines left out because their row is a near tie).

    Labels are centred vertically against the tallest cell of their row, so the lines between two labels belong
    partly to the row above and partly to the row below. The split is the one that centres every label best and
    never cuts a phrase in two; lines whose side is a near tie are dropped from both rows (unsure)."""
    groups = _label_groups(cells)
    n = len(cells)
    if not groups:
        return [], set()
    gaps = [groups[j + 1][0] - groups[j][1] - 1 for j in range(len(groups) - 1)]

    def cut_penalty(e: int) -> float:
        if e + 1 >= n:
            return 0.0
        return 10.0 if any(_continues(cells[e][c], cells[e + 1][c], lax) for c in (1, 2)) else 0.0

    def solve(forced: dict[int, int]) -> tuple[float, list[int]]:
        """Cheapest split, optionally with the number of gap lines given to some rows fixed: (cost, lines given per gap)."""
        states: dict[int, tuple[float, list[int]]] = {0: (0.0, [])}  # first line of the next row -> (cost so far, choices)
        for j, (a, b) in enumerate(groups):
            last = j == len(groups) - 1
            options = [0] if last else ([forced[j]] if j in forced else list(range(gaps[j] + 1)))
            new: dict[int, tuple[float, list[int]]] = {}
            for x in options:
                e = n - 1 if last else b + x
                for s, (cost, choices) in states.items():
                    c = cost + _row_cost(cells, a, b, s, e) + (0.0 if last else cut_penalty(e))
                    if e + 1 not in new or c < new[e + 1][0]:
                        new[e + 1] = (c, choices + [x])
            states = new
        return min(states.values(), key=lambda t: t[0])

    best_cost, choice = solve({})
    disputed: set[int] = set()
    for j, gap in enumerate(gaps):
        if not gap:
            continue
        lo = hi = choice[j]
        for x in range(gap + 1):
            if x != choice[j] and solve({j: x})[0] <= best_cost + 0.25:
                lo, hi = min(lo, x), max(hi, x)
        if lo != hi:
            disputed.update(range(groups[j][1] + 1 + lo, groups[j][1] + 1 + hi))
    rows, s = [], 0
    for j, (a, b) in enumerate(groups):
        e = n - 1 if j == len(groups) - 1 else b + choice[j]
        # a row that could only be had by cutting a phrase in two (above or below it) is not to be relied on
        cut = (s > 0 and cut_penalty(s - 1) > 0) or cut_penalty(e) > 0
        rows.append((s, e, a, b, cut or any(i in disputed for i in range(s, e + 1))))
        s = e + 1
    return rows, disputed


def _top_rows(cells: list[tuple[str, str, str]], groups: list[tuple[int, int]], lax: bool = False) -> list[tuple[int, int]] | None:
    """(first line, last line) of each row of a run under the other reading of the table - cells aligned to the top, so
    that every label starts on the first line of its row - or None where the lines contradict that reading: cell text
    above the first label, a label whose first line has nothing beside it, a phrase that runs on from the line above a
    label into the label's line."""
    if not groups or groups[0][0] != 0:
        return None
    rows = []
    for j, (a, _) in enumerate(groups):
        if not (cells[a][1] or cells[a][2]):
            return None
        if a and any(_continues(cells[a - 1][c], cells[a][c], lax) for c in (1, 2)):
            return None
        rows.append((a, groups[j + 1][0] - 1 if j + 1 < len(groups) else len(cells) - 1))
    return rows


def _read_run(cells: list[tuple[str, str, str]], lax: bool) -> list[tuple[int, int, int, int, bool, list[int]]]:
    """Rows of a run of table lines: [(first line, last line, first label line, last label line, unsure, lines kept)].

    The centred reading (``_segment``) gives the rows. A row is unsure when its boundary is a tie between two splits
    (both of the rows the tie lies between), when the lines also fit the top-aligned reading (``_top_rows``) and that
    reading gives the row other lines, or - with only the centred reading left - when its label still ends up well
    off the middle of the row, which says that the split was forced, not found (that row and its neighbours)."""
    segments, disputed = _segment(cells, lax)
    if not segments:
        return []
    top = _top_rows(cells, _label_groups(cells), lax)
    strained = [top is None and _row_cost(cells, a, b, s, e) >= 0.5 for s, e, a, b, _ in segments]
    out = []
    for j, (s, e, a, b, unsure) in enumerate(segments):
        unsure = unsure or s - 1 in disputed or e + 1 in disputed or (top is not None and (s, e) != top[j])
        unsure = unsure or any(strained[max(0, j - 1):j + 2])
        out.append((s, e, a, b, unsure, [i for i in range(s, e + 1) if i not in disputed]))
    return out


def _amendment_columns(lines: list[Line]) -> tuple[int, int, int] | None:
    """(first body line, left edge of the existing column, left edge of the proposed column) of a table with "Existing"
    and "Proposed" header cells."""
    head = next(((i, h) for i, ln in enumerate(lines) if (h := _header_spans(ln.text))), None)
    if head is None:
        return None
    i0, (ex, pr) = head
    left, right = Counter(), Counter()
    for ln in lines[i0 + 1:]:
        if ln.blank or is_footer(ln.text):
            continue
        for i, (s, _, _) in enumerate(fragments(ln.text, 3)):
            if 8 <= s <= ex[0] and i <= 1:
                left[s] += 1
            if ex[1] < s <= pr[0] + 2:
                right[s] += 1
    edge_l, edge_r = _column_edge(left), _column_edge(right)
    if edge_l is None or edge_r is None or not edge_l < edge_r:
        return None
    if not (edge_l <= ex[1] and ex[0] < edge_r <= pr[1]):
        return None  # the header cells do not stand over the columns found: the positions on this page cannot be relied on
    return i0 + 1, edge_l, edge_r


def _summary_columns(lines: list[Line], running: set[str]) -> tuple[int, int] | None:
    """(first body line, left edge of the value column) of a one-page summary of terms set as a dense table without
    colons - "Facility      $750mm revolving credit facility" on line after line - which the labelled-section reader
    cannot take apart. Pages whose labels end in colons, or whose rows stand apart, are left to that reader."""
    if sum(1 for ln in lines if _CORE_LABEL_RE.match(ln.text)) < 3:
        return None  # not a page of terms
    found = []  # (line index, label cell, value cell) of the lines that read "label   value"
    for i, ln in enumerate(lines):
        if ln.blank or is_footer(ln.text) or _run_key(ln.text) in running:
            continue
        cells = fragments(ln.text, 3)
        if len(cells) == 2 and cells[0][0] <= 20 and len(cells[0][2].split()) <= 6 and len(cells[0][2]) <= 45:
            found.append((i, cells[0], cells[1]))
    if len(found) < 4 or sum(1 for _, label, _ in found if label[2].rstrip().endswith(":")) * 2 >= len(found):
        return None
    edge = Counter(value[0] for _, _, value in found).most_common(1)[0][0]
    rows = {i for i, label, value in found if abs(value[0] - edge) <= 1 and label[1] < edge - 1}
    if len(rows) < 4 or len(rows) * 5 < len(found) * 3:
        return None
    if sum(1 for i in rows if i - 1 in rows or i + 1 in rows) * 2 < len(rows):
        return None  # rows set apart by blank lines: labelled sections
    first = min(rows)
    while first > 0 and not lines[first - 1].blank and lines[first - 1].indent >= edge - 1:
        first -= 1  # the cell of the first row may start above its label
    return first, edge


def _read_table(page: int, lines: list[Line], running: set[str]) -> list[_Row]:
    """Rows of a table of terms on a page extracted with layout: an Existing / Proposed table, or a dense one-page
    summary with a single value column.

    The label of a row may sit against the middle of its cells or against their first line, and nothing on the page
    says which; nor whether a short line followed by one in lower case is an item of its own. Each run of lines is
    therefore read every way (``_read_run`` with both answers to the second question, ``_segment`` and ``_top_rows``
    for the first); a row is kept when the readings that the lines allow agree on it, and left out (unsure) when
    they do not. A line whose text runs across a column edge makes its row unsure too."""
    columns = _amendment_columns(lines)
    single = None if columns else _summary_columns(lines, running)
    if columns:
        i0, edge_l, edge_r = columns
    elif single:
        (i0, edge_l), edge_r = single, None
    else:
        return []
    runs: list[list[tuple[Line, tuple[str, str, str]]]] = [[]]
    crossing: set[int] = set()  # lines whose text runs across a column edge: their cells cannot be told apart
    for ln in lines[i0:]:
        text = ln.text
        cells = fragments(text, 3)
        noise = ln.blank or is_footer(text) or _run_key(text) in running
        if not noise and cells and cells[0][0] < edge_l - 3 and cells[0][1] > edge_l + 2:
            noise = True  # a line that runs across the columns: a title or a footnote
        if noise:
            if runs[-1]:
                runs.append([])
            continue
        if any(len(text) > edge and not text[edge - 1].isspace() and not text[edge].isspace() for edge in (edge_l, edge_r) if edge):
            crossing.add(ln.n)
        runs[-1].append((ln, (text[:edge_l].strip(), text[edge_l:edge_r].strip(), text[edge_r:].strip() if edge_r else "")))
    rows: list[_Row] = []
    for run in runs:
        if not run:
            continue
        cells = [c for _, c in run]
        strict, loose = _read_run(cells, False), _read_run(cells, True)
        if not strict:
            if rows:
                rows[-1].unsure = True  # lines with no label of their own: the row above may run on
            continue
        for (s, e, a, b, unsure, keep), other in zip(strict, loose):
            unsure = unsure or other[4] or (s, e) != other[:2]  # the row must come out the same under both readings
            label = _norm(" ".join(cells[i][0] for i in range(a, b + 1)))
            row_lines = [run[i][0] for i in keep]
            unsure = unsure or len(label) > 60 or any(ln.n in crossing for ln in row_lines)
            if single:
                value = _cell_block(label, row_lines, [cells[i][1] for i in keep], "table")
                rows.append(_Row(label=label, page=page, existing=None, proposed=value, unsure=unsure or value is None, plain=True))
                continue
            existing = _cell_block(label, row_lines, [cells[i][1] for i in keep], "table")
            proposed = _cell_block(label, row_lines, [cells[i][2] for i in keep], "table")
            same = bool(proposed and SAME_AS_EXISTING_RE.match(proposed.text))
            rows.append(_Row(label=label, page=page, existing=existing, proposed=proposed, same=same,
                             unsure=unsure or proposed is None or (same and existing is None)))
    return rows


def _split_slide_cell(units: list[tuple[Line, str]]) -> tuple[list, list, bool, bool]:
    """Split the text of a slide row into (existing units, proposed units, same as existing, unsure).

    In reading order the existing cell comes first and the proposed cell follows without a mark; the proposed cell
    is recognised by how it is written ("Same as existing", "Eliminate ...", "Reduce ...", "... to be unsecured")."""
    if not units:
        return [], [], False, True
    joined = " ".join(t for _, t in units)
    tail = _SAME_TAIL_RE.search(joined)
    if tail:
        cut = len(joined) - len(joined[tail.start():].lstrip())
        existing, pos = [], 0
        for ln, t in units:
            if pos >= cut:
                break
            existing.append((ln, t[:max(0, cut - pos)].rstrip()))
            pos += len(t) + 1
        return [(ln, t) for ln, t in existing if t], [], True, not any(t for _, t in existing)
    if _NONE_CELL_RE.match(units[0][1]) and len(units) > 1:
        return [units[0]], units[1:], False, False
    for i, (ln, t) in enumerate(units):
        if i and _AMEND_START_RE.match(t):
            return units[:i], units[i:], False, False
        m = _AMEND_INLINE_RE.search(t)
        if m:
            return units[:i] + [(ln, t[:m.start()].rstrip())], [(ln, t[m.end():])] + units[i + 1:], False, False
    # "... (Section 6.01(e)) Debt under general debt basket to be unsecured ...": the existing cell closes on a bracket and
    # the proposed one says what is "to be". Only where the row has a single such place; with two the split is a guess.
    places = []
    for i, (ln, t) in enumerate(units):
        for m in re.finditer(r"(?<=\))\s+(?=[A-Z])", t):
            left, right = t[:m.start()], t[m.end():]
            before = " ".join(u for _, u in units[:i]) + " " + left
            if _WILL_BE_RE.search(right) and not _WILL_BE_RE.search(before) and (i or left):
                places.append((i, ln, left, right))
    if len(places) == 1:
        i, ln, left, right = places[0]
        return units[:i] + [(ln, left)], [(ln, right)] + units[i + 1:], False, False
    return units, [], False, True


def _read_slide(page: int, lines: list[Line], running: set[str]) -> list[_Row]:
    """Rows of an Existing / Proposed slide extracted in plain reading order (no columns)."""
    i0 = next((i for i, ln in enumerate(lines) if _SLIDE_HEAD_RE.match(ln.text)), None)
    if i0 is None:
        return []
    body = []
    for ln in lines[i0 + 1:]:
        if ln.blank or is_footer(ln.text) or _run_key(ln.text) in running:
            continue
        if _FOOTNOTE_RE.match(ln.text):
            break
        body.append(ln)
    # label lines, each with the wrapped pieces of the label above it
    starts: list[tuple[int, int, str, str]] = []  # (first line, label line, label, rest of the label line)
    for i, ln in enumerate(body):
        text = ln.text.strip()
        m = _SLIDE_LABEL_RE.match(text)
        if not m or len(m.group("label").split()) > 6 or _BULLET_START_RE.match(text):
            continue
        label, first = m.group("label"), i
        taken = starts[-1][1] if starts else -1
        while first - 1 > taken and i - first < 2:
            piece = body[first - 1].text.strip()
            if not (len(piece) <= 32 and _SLIDE_LABEL_PIECE_RE.match(piece) and not _SLIDE_LABEL_RE.match(piece)):
                break
            label = piece + " " + label
            first -= 1
        starts.append((first, i, _norm(label), m.group("rest") or ""))
    rows: list[_Row] = []
    for k, (first, at, label, rest) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(body)
        units = ([(body[at], rest.strip())] if rest.strip() else []) + [(ln, ln.text.strip()) for ln in body[at + 1:end]]
        ex_units, pr_units, same, unsure = _split_slide_cell(units)
        existing = _cell_block(label, [u[0] for u in ex_units], [u[1] for u in ex_units], "slide")
        proposed = _cell_block(label, [u[0] for u in pr_units], [u[1] for u in pr_units], "slide")
        rows.append(_Row(label=label, page=page, existing=existing, proposed=proposed, same=same,
                         unsure=unsure or (proposed is None and not same)))
    return rows


def _several_value_columns(lines: list[Line]) -> bool:
    """The page holds a table with two or more value columns beside its labels: at least three lines start with a short
    label at the left and carry a further cell that begins at one and the same column. (A stray gap inside a line of
    running text begins anywhere; a pricing grid inside the value column has no label at the left.)"""
    thirds: Counter = Counter()
    for ln in lines:
        cells = fragments(ln.text, 3)
        if len(cells) >= 3 and cells[0][0] <= 20 and len(cells[0][2].split()) <= 6:
            thirds[cells[2][0]] += 1
    return any(sum(thirds[c + d] for d in (-1, 0, 1)) >= 3 for c in thirds)


# ---- per-document state --------------------------------------------------------------------------------

class _State:
    """What the rules of this module share for one document: page lines, running headers, tables, the covenant list."""

    def __init__(self, ctx: Ctx):
        self.pages: dict[int, list[Line]] = {}
        for ln in ctx.raw.lines:
            self.pages.setdefault(ln.page, []).append(ln)
        self.doc_lines: list[Line] = ctx.doc.lines  # the lines the labelled sections are cut from
        self.running = self._running_lines()
        self.terms_pages = self._terms_pages()
        # the document says of itself that it does not set out all the terms ("does not purport to summarize all terms")
        opening = tidy(" ".join(ln.text for page in sorted(self.pages)[:2] for ln in self.pages[page]))
        self.not_all_terms = bool(_NOT_ALL_TERMS_RE.search(opening))
        self.rows: list[_Row] = []
        self.amend_pages: set[int] = set()
        for page, lines in self.pages.items():
            try:
                # layout extraction leaves runs of blanks between the cells of a line; plain reading order does not
                gaps = sum(1 for ln in lines if len(fragments(ln.text, 3)) > 1)
                rows = _read_table(page, lines, self.running) if gaps >= 3 else []
                rows = rows or _read_slide(page, lines, self.running)
            except Exception:  # an unreadable table is left to the analyst
                if DEBUG:
                    raise
                rows = []
            if rows:
                self.amend_pages.add(page)
                self.rows.extend(rows)
            elif _several_value_columns(lines):
                # a table with more than one value column that could not be rebuilt: read as labelled sections its rows
                # would run the cells of a line together ("Restricted payments: $50mm general basket $100mm general
                # basket"), so the page is left alone
                self.amend_pages.add(page)
        self.amend_pages |= set(getattr(ctx, "split_pages", ()) or ())
        try:
            self.package = _build_package(ctx, self)
        except Exception:
            if DEBUG:
                raise
            self.package = None
        try:
            self.uses = _assign_rows(ctx, self)
        except Exception:
            if DEBUG:
                raise
            self.uses = {}

    def _terms_pages(self) -> set[int]:
        """Pages that set out terms under labels (as opposed to slide prose): every page of a term sheet, the summary
        pages of a presentation."""
        pages = set()
        for page, lines in self.pages.items():
            core = sum(1 for ln in lines if _CORE_LABEL_RE.match(ln.text))
            labelled = sum(1 for ln in lines if _LABEL_LINE_RE.match(ln.text))
            if max(core, labelled) >= 3:
                pages.add(page)
        return set(self.pages) if len(pages) * 5 >= len(self.pages) * 2 else pages

    def _running_lines(self) -> set[str]:
        """Text repeated at the top or bottom of the pages: running headers, footers, classification stamps."""
        counts: Counter = Counter()
        for lines in self.pages.values():
            body = [ln for ln in lines if not ln.blank]
            for key in {_run_key(ln.text) for ln in body[:2] + body[-3:]}:
                if len(key) >= 4:
                    counts[key] += 1
        need = max(2, (len(self.pages) + 2) // 3)  # on every third page at least, and on two pages in a short document
        return {k for k, c in counts.items() if c >= need}

    def is_section(self, block: Block) -> bool:
        """The block is a labelled section of a term sheet, not a "Label: ..." that happens to open a line of prose: it
        stands on a page of terms, or its label has the left column to itself (the value starts after a gap or on a
        later line)."""
        label = tidy(block.label).lower()
        if not label or not block.label[:1].isupper() and not block.label[:1].isdigit():
            return False  # "acquisitions  not  exceeding ..." at the start of a justified line is not a label
        if label not in tidy(block.line.text).lower():
            # a label put together from several lines is only trusted when a colon ends it: in a dense table without
            # colons the section finder strings the labels of consecutive rows together
            ends = [fragments(ln.text, 3) for ln in block.lines[:4]]
            if not any(cells and cells[0][2].rstrip().endswith(":") for cells in ends):
                return False
        # the label has the left column to itself ("Covenants:        Similar to ..."), or is marked off from the text
        # that follows it on the line ("Negative Covenants: Usual ...", "Negative Covenants - Usual ...")
        cells = fragments(block.line.text, 3)
        first = _LABEL_LEAD_RE.sub("", tidy(cells[0][2])).lower() if cells else ""
        alone = bool(first) and label.startswith(first.rstrip(": "))
        marked = bool(re.match(re.escape(label) + r"\s*(?::|[-–]\s)", first))
        if block.mode == "plain":
            return marked and block.page in self.terms_pages  # in plain reading order only "Label:" marks a section
        return (alone or marked) and (block.page in self.terms_pages or block.mode == "column")

    def clean(self, block: Block) -> Block:
        """The block as the rules read it: without the running header / footer lines a page break dropped into it, and
        with three shapes put right that the section finder gets wrong - a bulleted "Label: ..." runs on over the
        bullets that follow it; on a page read in plain order whose text is set in from the edge a section runs on
        over the "Label:" lines that follow it; and a "Label - ..." paragraph written inside a value column that
        starts left of column 40 is cut off after its first line."""
        lines, parts = list(block.lines), list(block.parts)
        if not lines:
            return block
        first = lines[0]
        if _BULLET_START_RE.match(first.text):
            # a bullet ends where the next bullet of its own level starts
            stop = next((i for i, ln in enumerate(lines) if i and _BULLET_START_RE.match(ln.text) and ln.indent <= first.indent + 1), None)
            if stop is not None:
                lines, parts = lines[:stop], parts[:stop]
        elif block.mode == "plain":
            # in plain reading order a section ends at the next "Label:" line, also one set in from the edge
            stop = next((i for i, ln in enumerate(lines) if i and _PLAIN_NEXT_RE.match(ln.text)), None)
            if stop is not None:
                lines, parts = lines[:stop], parts[:stop]
        elif len(lines) == 1 and first.indent > 20 and block.mode == "column" and tidy(parts[0]):
            # the rest of the paragraph: the lines that follow at the label's own indent, up to a blank line or a new label
            for ln in self.doc_lines[first.n + 1:first.n + 1 + 40]:
                if ln.blank or ln.page != first.page or abs(ln.indent - first.indent) > 1 or _INLINE_LABEL_RE.match(ln.text) or is_footer(ln.text):
                    break
                lines.append(ln)
                parts.append(ln.text.strip())
        elif block.mode == "column":
            self._carry_over(lines, parts, block.label)
        keep = [(ln, part) for ln, part in zip(lines, parts) if not (part.strip() and _run_key(part) in self.running)]
        if not keep or keep[0][0] is not first or (len(keep) == len(block.lines) and len(lines) == len(block.lines)):
            return block
        return Block(label=block.label, line=block.line, lines=[k[0] for k in keep], parts=[k[1] for k in keep],
                     inline=block.inline, mode=block.mode)


    def at_page_foot(self, block: Block) -> bool:
        """The block's last line is the last line of text on its page (only page numbers, footers and blanks follow it)."""
        if not block.lines:
            return False
        last = block.lines[-1]
        for ln in self.doc_lines[last.n + 1:last.n + 40]:
            if ln.page != last.page:
                return True
            if not self._noise(ln):
                return False
        return last.n + 1 < len(self.doc_lines)  # (the very end of the document is not the foot of a page it goes on from)

    def _noise(self, ln: Line) -> bool:
        """A line that is no part of any section: blank, a page number or footer, a running header."""
        return ln.blank or is_footer(ln.text) or _run_key(ln.text) in self.running

    def _carry_over(self, lines: list[Line], parts: list[str], label: str = "") -> None:
        """Extend a column section (``lines`` / ``parts``, in place) that the section finder ended at the foot of a page
        although it carries on overleaf. The finder takes two things at the top of a page for a new label: a running page
        header at the left margin, and - on a page whose text is set further left than the page before - a line that opens
        with a list number ("(i)      Indebtedness (including ..."). Here the header is skipped, and the list number is read
        as the next item of the section when the text so far is unfinished or the number follows the section's last one.
        From there the section runs as the finder would have run it: in its value column until a line returns to the
        label column, or - on a page set further left - until the next "Label:" line."""
        doc, first_page = self.doc_lines, lines[0].page
        label_indent = min(ln.indent for ln in lines if ln.page == first_page)
        deeper = [ln.indent for ln in lines if ln.indent > label_indent + 6]
        if not deeper and tidy(parts[0]):  # a section of one line: its value column is where the value stands beside the label
            deeper = [at for at in (lines[0].text.find(parts[0].strip()[:12]),) if at > label_indent + 6]
        if not deeper:
            return  # no value column to go by
        value_col = min(deeper)
        n = lines[-1].n + 1
        while n < len(doc) and doc[n].page == lines[-1].page:
            if not self._noise(doc[n]):
                return  # the section ended inside its page
            n += 1
        prev_page, how = lines[-1].page, ""
        # a section headed for one kind of covenant ("Negative Covenants:") ends where a sub-heading for another kind starts
        # ("(c) Financial Covenants - ..."); a general "Covenants" section runs through its sub-headings
        one_kind = bool(re.fullmatch(_NEG_LABEL + "|" + _AFF_LABEL, _norm(label).rstrip(": "), re.IGNORECASE))
        while n < len(doc) and len(lines) < 400:
            cur = doc[n]
            n += 1
            if self._noise(cur):
                continue
            if one_kind and (_SUB_HEAD_RE.match(cur.text.strip()) or _SUB_LINE_RE.match(cur.text.strip())):
                return
            if cur.page != prev_page:
                prev_page = cur.page
                how = self._page_start(cur, lines, parts, value_col, label_indent)
                if not how:
                    return
            if how == "shifted":
                cells = fragments(cur.text, 3)
                if (len(cells) > 1 and cells[0][2].rstrip().endswith(":") and _label_like(cur.text)) or _LABEL_LINE_RE.match(cur.text):
                    return
                if len(cells) > 1 and cur.indent <= label_indent + 6 and cells[1][0] - cells[0][0] >= 16 and _TITLE_CELL_RE.match(cells[0][2]):
                    return  # a label written without a colon: "Events of Default        Usual and customary ..."
            elif cur.indent < value_col - 3 and cur.indent <= label_indent + 6:
                return
            lines.append(cur)
            parts.append(cur.text[cur.qstart:].strip() if cur.qstart and cur.indent >= cur.qstart else cur.text.strip())

    @staticmethod
    def _page_start(cur: Line, lines: list[Line], parts: list[str], value_col: int, label_indent: int) -> str:
        """What the first line of a new page is to the section read so far: "value" (the section carries on in its value
        column), "shifted" (it carries on, on a page whose text is set further left) or "" (something else starts)."""
        if re.fullmatch(r"[A-Z][A-Z,&/\-’']*(?:\s+[A-Z,&/\-’']+){1,7}", cur.text.strip()):
            return ""  # a heading in capitals opens a new part of the document ("PRICING, FEES AND EXPENSES")
        if cur.indent >= value_col - 3:
            return "value"
        mark = _LINE_MARK_RE.match(cur.text)
        if mark and cur.indent <= label_indent + 6:
            unfinished = not _FULL_STOP_END_RE.search(tidy(" ".join(parts[-2:])))
            return "shifted" if unfinished or _follows(mark, lines) else ""
        if _label_like(cur.text):
            return "" if cur.indent <= label_indent + 6 else "value"
        return "shifted"


def _label_like(text: str) -> bool:
    """The line could be a label of the left column (as the section finder judges it): a short first cell that starts
    with a capital, a digit or a bracket, and ends in a colon, has a second cell beside it, or stands alone."""
    cells = fragments(text, 3)
    if not cells:
        return False
    first = cells[0][2]
    if not (first[0].isupper() or first[0].isdigit() or first[0] in "(“\""):
        return False
    return len(first.split()) <= 7 and (first.rstrip().endswith(":") or len(cells) > 1 or len(text.strip()) < 50)


def _follows(mark, lines: list[Line]) -> bool:
    """The list number ``mark`` is the next after the last list number of its style that starts a line of ``lines``."""
    new = mark.group("dot") or mark.group("tag")
    for ln in reversed(lines):
        m = _LINE_MARK_RE.match(ln.text)
        if not m or bool(m.group("dot")) != bool(mark.group("dot")):
            continue
        old = m.group("dot") or m.group("tag")
        for kind in ("digit", "roman", "upper", "alpha"):
            a, b = _mark_value(old, kind), _mark_value(new, kind)
            if a is not None and b is not None and b == a + 1:
                return True
        return False
    return False


def _state(ctx: Ctx) -> _State:
    """The module's reading of this document, built once and kept on the context."""
    state = getattr(ctx, _STATE_ATTR, None)
    if state is None:
        state = _State(ctx)
        try:
            setattr(ctx, _STATE_ATTR, state)
        except Exception:
            pass
    return state


# ---- rows of their own: which template row each belongs to -----------------------------------------------

@dataclass
class _Use:
    """A table row or labelled section used for one template row, with the items of its cells that belong there."""
    row: _Row
    existing: list[tuple[str, _Span]]
    proposed: list[tuple[str, _Span]]
    combined: bool = False  # the row gives liens and indebtedness baskets together
    see: str = ""  # the passage is given in another template row (its name): this row only points there


def _part_offsets(block: Block) -> list[tuple[int, int]]:
    """(start, end) in block.text of the value part of each line of the block."""
    out, pos = [], 0
    for part in block.parts:
        part = tidy(part)
        out.append((pos, pos + len(part)))
        if part:
            pos += len(part) + 1
    return out


def _sub_block(block: Block, span: _Span) -> Block | None:
    """A stretch of a block as a block of its own (same source lines), so that a quote can be cut to exactly it."""
    lines, parts = [], []
    for ln, part, (a, b) in zip(block.lines, block.parts, _part_offsets(block)):
        lo, hi = max(a, span.start()), min(b, span.end())
        if hi > lo:
            lines.append(ln)
            parts.append(tidy(part)[lo - a:hi - a])
    if not lines:
        return None
    parts[0] = parts[0].lstrip(_BULLETS + " ")
    return Block(label=block.label, line=lines[0], lines=lines, parts=parts, inline=block.inline, mode=block.mode)


def _item_quote(ctx: Ctx, block: Block | None, span: _Span) -> dict | None:
    """A quote that is exactly one item of a cell or list (or, where the cell wraps beside another column, its first line)."""
    sub = _sub_block(block, span) if block is not None else None
    if sub is None:
        return ctx.quote(block, span) if block is not None else None
    if len(sub.text) < 12:  # "$100mm": too short to stand alone, so the whole line of the table it sits on
        ln = sub.lines[0]
        return ctx.quote(Block(label=block.label, line=ln, lines=[ln], parts=[ln.text], inline=False, mode=block.mode))
    return ctx.quote(sub, _Span(0, len(sub.text))) or ctx.quote(sub, _Span(0, len(tidy(sub.parts[0]))))


def _cell_items(block: Block | None) -> list[tuple[str, _Span]]:
    """The bulleted items of a cell, the sentences of a long unbulleted one, or the whole cell; each with its span."""
    if block is None or not block.text:
        return []
    text = block.text
    cuts = [m.start() for m in _ITEM_BULLET_RE.finditer(text)]
    spans = []
    if cuts:
        if text[:cuts[0]].strip():
            spans.append((0, cuts[0]))
        for i, c in enumerate(cuts):
            spans.append((c + 1, cuts[i + 1] if i + 1 < len(cuts) else len(text)))
    elif len(text) > LINE:
        spans = _sentences(text, 0, len(text)) or [(0, len(text))]
    else:
        spans.append((0, len(text)))
    out = []
    for a, b in spans:
        a, b = _trim_span(text, a, b)
        if b - a >= 2:
            out.append((_norm(text[a:b]), _Span(a, b)))
    return out


def _inner_sections(block: Block) -> tuple[list[_Row], int]:
    """(paragraphs of a covenant section that stand under their own sub-heading - "Indebtedness: Limitation on ..." -,
    where the first of them starts)."""
    text = block.text
    heads = [m for m in _INNER_LABEL_RE.finditer(text)
             if len(m.group("label").split()) <= 7 and _topics_in(m.group("label").lower(), _NEG_TOPICS)]
    rows = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        a, b = _trim_span(text, m.end(), end)
        sub = _sub_block(block, _Span(a, b)) if b - a >= 12 else None
        if sub is not None:
            rows.append(_Row(label=_norm(m.group("label")), page=sub.line.page, existing=None, proposed=sub, inner=True))
    return rows, (heads[0].start() if heads else len(text))


def _reads_as_covenant(label: str, text: str) -> bool:
    """A labelled paragraph reads as a covenant, not as narrative: it uses the wording of one, and where its label is
    an ordinary noun as well ("Merger: Merger Sub will merge with and into the Company ...") it says what is restricted."""
    if not _COVENANT_WORDS_RE.search(label + " " + text):
        return False
    return bool(_RESTRICTS_LABEL_RE.search(label) or _RESTRICTIVE_WORDS_RE.search(text))


def _label_topics(label: str, inner: bool = False) -> list[str]:
    """Covenant topics a row label names. "Guarantees" alone is the credit support and "Loans" the facility's own loans,
    unless the label reads as a covenant ("Loans and guarantees", "Permitted Guarantees") or is a sub-heading of the
    covenant section (``inner``)."""
    if inner:
        return [n for _, n in _topics_in(label.lower(), _NEG_TOPICS)]
    if _NOT_A_ROW_RE.search(label):
        return []
    if _LOANS_LABEL_RE.search(label):
        label = label.lower()
    topics = [n for _, n in _topics_in(label, _NEG_TOPICS + ("hoarding", "mfn"))]
    if "guarantees" in topics and len(topics) == 1 and not _RESTRICTS_RE.search(label):
        topics.remove("guarantees")
    return topics


def _row_fields(row: _Row) -> list[tuple[str, bool]]:
    """Template rows a table row belongs to by its label: [(field id, liens and debt baskets given together)]."""
    topics = _label_topics(row.label, row.inner)
    if "liens" in topics and "debt" in topics:
        # liens and indebtedness baskets given together: unsecured ones are debt baskets, the rest sit with the liens
        if _UNSECURED_RE.search(row.label):
            return [("permitted_indebtedness", False)]
        return [("negative_pledge", True)]
    fids: list[tuple[str, bool]] = []
    for t in topics:
        fid = _FIELD_OF_TOPIC.get(t, _OTHER)
        if (fid, False) not in fids:
            fids.append((fid, False))
    return fids


def _assign_rows(ctx: Ctx, state: _State) -> dict[str, list[_Use]]:
    """Template row -> the table rows and labelled sections that feed it, in document order."""
    uses: dict[str, list[_Use]] = {}
    rows = list(state.rows)
    # labelled covenant sections outside amendment tables ("Negative Pledge:", "Limitation on asset sales:")
    pkg = state.package
    sweeps = ctx.all(_PREPAYMENT_LABEL)
    for b in ctx.all(*_ROW_LABELS, _ROW_LABEL_TAIL):
        # (a label that wraps in a narrow left column - "Permitted Financial" / "Indebtedness:" - is found by its last
        # line; either way the whole label must be one of the row labels)
        if not any(re.fullmatch(p, _norm(b.label).rstrip(": "), re.IGNORECASE) for p in _ROW_LABELS):
            continue
        top_level = not b.inline and b.mode in ("column", "plain") and state.is_section(b)
        if b.page in state.amend_pages or not b.text or len(b.label) > 60 or not top_level:
            continue  # a sub-heading of some other section, or slide prose
        if pkg is not None and pkg.block is not None and pkg.block.line.n <= b.line.n <= pkg.block.end:
            continue  # part of the covenant section, which is read as a whole
        b = state.clean(b)
        if len(b.text) < 12 or SAME_AS_EXISTING_RE.match(b.text) or not _reads_as_covenant(b.label, b.text):
            continue  # "Acquisitions: completed five bolt-ons in 2025" is not a covenant
        if _SWEEP_RE.search(b.text[:300]) or any(s.line.n < b.line.n <= s.end for s in sweeps):
            continue  # "Asset Sales: 100% of the net cash proceeds ..." is a mandatory prepayment, not the covenant
        rows.append(_Row(label=_norm(b.label), page=b.page, existing=None, proposed=b))
    if pkg is not None and pkg.block is not None:
        inner, first = _inner_sections(pkg.block)
        if len(inner) >= 2:
            # the covenant section is written under sub-headings ("Indebtedness: ...", "Liens: ..."), not as a list: each
            # sub-heading is a row, and what the list reader made of the section is not relied on, so a covenant without
            # a sub-heading is by reference or not stated, never an express "none". The section's introduction is what
            # stands before the first sub-heading.
            rows += inner
            pkg.items, pkg.extras, pkg.closed_match, pkg.closed_block = [], [], None, None
            pkg.sub_headed, pkg.aside, pkg.aside_span = True, "", None
            pkg.intro = _DANGLING_END_RE.sub("", " " + _norm(pkg.block.text[:first]).strip(" ,;:.")).strip()
            if pkg.ref_match is not None and pkg.ref_block is pkg.block and pkg.ref_match.start() >= first:
                pkg.ref_phrase, pkg.ref_block, pkg.ref_match = "", None, None  # the pointer belongs to one sub-heading only
            elif pkg.ref_match is not None and pkg.ref_block is pkg.block:
                pkg.ref_in_intro = True  # (the introduction now runs up to the first sub-heading)
    for row in rows:
        # a row of a one-column summary table is only a covenant if it reads as one ("Asset sales  100% of net proceeds to
        # be applied in prepayment" is a sweep, "Investments  $45mm in joint ventures" a description)
        text = row.proposed.text if row.plain and row.proposed is not None else ""
        if row.plain and not row.unsure and (not _reads_as_covenant(row.label, text) or _SWEEP_RE.search(text[:300])):
            row.unsure = not re.fullmatch(_NEG_LABEL + "|" + _GEN_LABEL, row.label, re.IGNORECASE)
    targets = [[] if row.unsure else _row_fields(row) for row in rows]
    for i, row in enumerate(rows):
        # a row with no subject of its own between two rows of one subject is a basket of that subject
        if targets[i] or row.unsure or _BUCKET_LABEL_RE.search(row.label) or not 0 < i < len(rows) - 1:
            continue
        if _CORE_LABEL_RE.match(row.label) or _NOT_A_ROW_RE.search(row.label):
            continue  # "Facility", "Maturity", "Pricing" ... are terms in their own right wherever they stand
        before, after = rows[i - 1], rows[i + 1]
        size = len(row.proposed.text if row.proposed else "") + len(row.existing.text if row.existing else "")
        if (before.page == row.page == after.page and row.existing is not None and before.existing is not None
                and len(targets[i - 1]) == 1 and targets[i - 1][0][1] and len(targets[i + 1]) == 1 and targets[i + 1][0][1]
                and size <= 160 and _has_figure((row.proposed.text if row.proposed else "") + " " + row.existing.text)):
            targets[i] = list(targets[i - 1])
    for row, fields in zip(rows, targets):
        if row.unsure:
            continue
        ex_items, pr_items = _cell_items(row.existing), _cell_items(row.proposed)
        if not fields and _BUCKET_LABEL_RE.search(row.label) and not _NOT_A_ROW_RE.search(row.label):
            # an "Additional Amendments" kind of row: each item goes where its own wording puts it
            by_topic: dict[str, tuple[list, list]] = {}
            for side, items in ((0, ex_items), (1, pr_items)):
                for text, span in items:
                    found = _topics_in(text, _NEG_TOPICS)
                    if found:
                        by_topic.setdefault(found[0][1], ([], []))[side].append((text, span))
            for topic, (ex, pr) in by_topic.items():
                if pr or (row.same and ex):
                    uses.setdefault(_FIELD_OF_TOPIC.get(topic, _OTHER), []).append(_Use(row, ex, pr))
            continue
        topics = _label_topics(row.label, row.inner)
        if len(fields) > 1 and len(pr_items) == 1 and not ex_items:
            # one undivided passage for several covenants ("Loans and guarantees: No Obligor shall ..."): it is given in the
            # first of their rows and the others point there, so that nothing is repeated
            own = [fid for fid, _ in fields if fid in _SPECS]
            if own:
                uses.setdefault(own[0], []).append(_Use(row, [], pr_items))
                for fid in own[1:]:
                    uses.setdefault(fid, []).append(_Use(row, [], pr_items, see=_SPECS[own[0]].see))
                continue
        for fid, combined in fields:
            mine = {t for t in topics if _FIELD_OF_TOPIC.get(t, _OTHER) == fid}
            others = set(topics) - mine

            def belongs(text: str) -> bool:
                found = {n for _, n in _topics_in(text, tuple(topics))}
                return bool(found & mine) or not (found & others)

            split = len(fields) > 1
            ex = [it for it in ex_items if not split or belongs(it[0])]
            pr = [it for it in pr_items if not split or belongs(it[0])]
            if pr or (row.same and ex):
                uses.setdefault(fid, []).append(_Use(row, ex, pr, combined=combined))
    return uses


def _diff_note(new: str, old: str) -> tuple[str, str]:
    """How the proposed item differs from the existing one it matches: ("unchanged", the item), ("changed", the item with
    each replaced word followed by what it replaces - "Net Leverage < 1.75x (existing: 1.00x), (iii) Liquidity ...") or
    ("amended", the item) when the difference is more than a few words. The old figure is put straight after the new
    one, so that it cannot be read as belonging to another condition of the same item."""
    a, b = old.split(), new.split()
    bare = lambda words: [w.strip(",;.") for w in words]  # noqa: E731
    if bare(a) == bare(b):
        return "unchanged", _line(new)
    out, changed = [], 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, bare(a), bare(b), autojunk=False).get_opcodes():
        if op == "equal":
            out += b[j1:j2]
            continue
        if op != "replace" or i2 - i1 != j2 - j1:
            return "amended", _line(new)
        changed += i2 - i1
        tail = b[j2 - 1][len(b[j2 - 1].rstrip(",;.")):]  # the punctuation that closes the replaced words
        words = b[j1:j2 - 1] + [b[j2 - 1].rstrip(",;.")]
        out.append(" ".join(words) + " (existing: " + _line(" ".join(bare(a[i1:i2]))) + ")" + tail)
    if not changed or changed > 3:
        return "amended", _line(new)
    return "changed", _line(" ".join(out), LINE + 60)


def _match_existing(text: str, existing: list[tuple[str, _Span]]) -> str | None:
    """The existing item a proposed item restates: the one under the same sub-label ("General basket: $75mm" for
    "General basket: $125mm"), else the one most of whose words it repeats; None if there is none."""
    name = re.match(r"([^:]{2,40}):\s", text)
    if name:
        same = [e for e, _ in existing if e.lower().startswith(name.group(0).lower())]
        if len(same) == 1:
            return same[0]
    ratio = lambda e: SequenceMatcher(None, text.split(), e.split(), autojunk=False).ratio()  # noqa: E731
    best = max((e for e, _ in existing), key=ratio, default=None)
    return best if best is not None and ratio(best) >= 0.6 else None


def _render_use(use: _Use) -> list[str]:
    """House-style lines for one table row: the proposed terms, and how they differ from the existing ones."""
    label = use.row.label.rstrip(":")
    lead = f"{label}: " if label else ""
    if use.see:
        return [f"Dealt with in the same passage of the term sheet ('{label}') - see {use.see}"]

    def lay_out(texts: list[str], note: str = "") -> list[str]:
        one = lead + "; ".join(texts) + note
        if len(one) <= LINE or len(texts) == 1:
            return [_line(one, LINE + 30)]
        return [_line((lead if i == 0 else "") + t + note, LINE + 30) for i, t in enumerate(texts)]

    if use.row.same:
        return lay_out([_line(t) for t, _ in use.existing], " (same as existing)")
    if use.row.existing is None:  # a section with a single value column
        return lay_out([_line(t) for t, _ in use.proposed])
    pairs = [(text, _match_existing(text, use.existing)) for text, _ in use.proposed]
    existing = [t for t, _ in use.existing if not _NONE_CELL_RE.match(t)]
    if len(pairs) == 1 and len(existing) == 1 and not pairs[0][1] and max(len(pairs[0][0]), len(existing[0])) <= 60 \
            and _has_figure(pairs[0][0]) and _has_figure(existing[0]):
        return lay_out([f"{_line(pairs[0][0])} (existing: {_line(existing[0])})"])  # a single amount replaced by another
    if not any(old for _, old in pairs):
        # the proposed cell is written as instructions (or the row is new): what exists, then what is proposed
        out = [("Existing: " + _line(t, LINE - 10)) for t in existing] + [("Proposed: " + _line(t, LINE - 10)) for t, _ in use.proposed]
        if out and label:
            out[0] = _line(f"{label} - {out[0]}", LINE + 60)
        return out
    notes = [_diff_note(text, old) if old else ("unmatched", _line(text)) for text, old in pairs]
    if all(kind == "unchanged" for kind, _ in notes):
        return lay_out([text for _, text in notes], " (unchanged)")
    said = {"unchanged": " (unchanged)", "changed": "", "amended": " (amended)", "unmatched": " (no matching existing term)"}
    return lay_out([text + said[kind] for kind, text in notes])


def _points_only(use: _Use) -> bool:
    """The row gives no term of its own: all it says is where the term is to be found or that it is still to be agreed."""
    text = " ".join(t for t, _ in (use.existing if use.row.same else use.proposed))
    if use.see or not 0 < len(text) <= 200 or _has_amount(text):
        return False
    return _reference(text) is not None or bool(_ONLY_BLANK_RE.match(text))


def _use_evidence(ctx: Ctx, use: _Use) -> list[dict]:
    """Quotes for one table row: its proposed items, then the existing ones (first where the proposed cell adopts them)."""
    sides = [(use.row.existing, use.existing)] if use.row.same else [(use.row.proposed, use.proposed), (use.row.existing, use.existing)]
    out = []
    for block, items in sides:
        for text, span in items:
            if block is not None and not _NONE_CELL_RE.match(text):
                out.append(_item_quote(ctx, block, span))
    return [q for q in out if q]


# ---- the rules -----------------------------------------------------------------------------------------

def _quotes(*items) -> list[dict]:
    """Up to three distinct quotes, in the order given."""
    seen, out = set(), []
    for q in items:
        if q and q["quote"] not in seen:
            seen.add(q["quote"])
            out.append(q)
    return out[:3]


def _spread(evidence: list[dict]) -> list[dict]:
    """At most three quotes, taken from across the list rather than from its start only."""
    seen, uniq = set(), []
    for q in evidence:
        if q and q["quote"] not in seen:
            seen.add(q["quote"])
            uniq.append(q)
    if len(uniq) <= 3:
        return uniq
    return [uniq[0], uniq[len(uniq) // 2], uniq[-1]]


def _wrap(prefix: str, parts: list[str], limit: int = LINE, max_lines: int = 2, sep: str = "; ") -> list[str]:
    """"prefix a; b; c" as lines of at most about ``limit`` characters, broken between parts. A part may run over a
    little rather than be broken; one too long for any line is carried over several lines, broken where a clause of it
    ends (``_pieces``), and a long prefix that leaves no room for the first part stands on a line of its own - nothing
    is cut in mid-phrase. Lines beyond ``max_lines`` are left out and the last line kept says so (" …")."""
    room = limit + 90
    lines, cur, fresh = [], prefix, True
    for part in parts:
        if not fresh and len(cur) + len(sep) + len(part) > limit:
            lines.append(cur)
            cur, fresh = "(cont.) ", True
        if fresh and len(cur) + len(part) > room:
            if len(cur) > 60 and not cur.startswith("(cont.)"):
                lines.append(cur.rstrip())
                cur = "(cont.) "
            if len(cur) + len(part) > room:
                *whole, part = _pieces(part, limit - len(cur), limit - 8)
                for piece in whole:
                    lines.append(cur + piece)
                    cur = "(cont.) "
        cur += part if fresh else sep + part
        fresh = False
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] += sep.strip() + " …"
    return [_line(ln, limit + 90) for ln in lines]


def _pieces(text: str, first: int, limit: int) -> list[str]:
    """A passage too long for one line as consecutive pieces (the first of at most ``first`` characters, the others of
    ``limit``), each ending where a clause ends: before a number of its own ("(x)", "(B)") or after a semicolon, failing
    that after a comma, and only where it has neither at a blank."""
    out = []
    room = max(first, 40)
    while len(text) > room:
        window = text[:room + 1]
        cuts: list[int] = []
        for pattern, least in ((r"\s+(?=\(\w{1,5}\)\s)|(?<=;)\s+", room // 3), (r"(?<=,)\s+", room // 3),
                               (r"\s+(?=(?:and|or|but|so\s+long\s+as|provided|subject\s+to|unless|which|including)\b)", room // 3),
                               (r"\s+", room // 2)):
            cuts = [m.start() for m in re.finditer(pattern, window) if m.start() >= least]
            if cuts:
                break
        if not cuts:
            break
        out.append(text[:cuts[-1]].rstrip())
        text = text[cuts[-1]:].lstrip()
        room = limit
    out.append(text)
    return out


def _split_aside(text: str) -> tuple[str, str]:
    """(the passage without its long bracket, what the bracket says) when a passage is too long for a line because of a
    bracketed aside: "Substantially similar to the Existing Credit Agreement (subject to changes ...), which are ..."."""
    if len(text) <= LINE - 20:
        return text, ""
    start = text.find("(")
    while start >= 0:
        depth, end = 0, -1
        for i in range(start, len(text)):
            depth += (text[i] == "(") - (text[i] == ")")
            if depth == 0:
                end = i
                break
        if end < 0:
            break
        if end - start > 80:
            main = _norm(text[:start].rstrip() + text[end + 1:])
            return main, _cap(text[start + 1:end].strip())
        start = text.find("(", end + 1)
    return text, ""


def _bare(text: str) -> str:
    """A list item without "limitation on": "limitations on liens" -> "liens"."""
    return _low(_LIMITATION_PREFIX_RE.sub("", text))


def _listed_as(pkg: _Package, name: str, items: list[_Item]) -> str:
    """"Limitation on liens (listed as a negative covenant)" / "... (listed as "liens, to be consistent with ...")"."""
    shown = [it.text if len(it.text) <= 170 else squeeze(it.text, 170) for it in items if len(_bare(it.text).split()) > 2]
    if not shown:
        return f"{name} (listed as a negative covenant)" if pkg.negative_only else f"{name} (listed among the covenants)"
    return f"{name} (listed as " + "; ".join(f"\"{s}\"" for s in shown) + ")"


def _fall_line(pkg: _Package, items: list[_Item]) -> str:
    """"Of no further force and effect from a Covenant Fall-Away Event" for the listed covenants the sentence switches off."""
    gone = [it for it in items if it.terminated]
    if not gone:
        return ""
    event = f"a {pkg.fall_event}" if pkg.fall_event else "the fall-away event described in the term sheet"
    which = "" if len(gone) == len(items) else ": " + "; ".join(_head(it.text) for it in gone)
    return f"Of no further force and effect from {event}{which} (see [Other])"


def _package_quotes(ctx: Ctx, pkg: _Package, *first) -> list[dict]:
    """Quotes that carry a by-reference or closed-list answer: those passed in, then the words that point elsewhere and
    the words that close the list."""
    out = list(first)
    if pkg.ref_block is not None and pkg.ref_match is not None:
        out.append(ctx.quote(pkg.ref_block, pkg.ref_match))
    if pkg.closed_block is not None:
        out.append(ctx.quote(pkg.closed_block, pkg.closed_match))
    if pkg.block is not None and not any(out):
        out.append(ctx.quote(pkg.block))
    return _quotes(*out)


def _list_quote(ctx: Ctx, pkg: _Package, item: _Item | None = None) -> dict | None:
    """A quote showing a listed covenant in its list. An item of a word or two is quoted with its neighbours; with no
    item the quote is the negative covenants of the list (as many as fit)."""
    if item is not None and len(item.text) >= 25:
        if item.end - item.start > 280:  # a covenant given with its baskets: the words that name it and open its detail
            return ctx.quote(item.block, _Span(item.start, item.start + 200)) or ctx.quote(item.block, item.span)
        return ctx.quote(item.block, item.span)
    pool = [it for it in pkg.items if item is None or it.block is item.block]
    if item is None:
        pool = [it for it in pkg.negatives()] or pool
    if not pool:
        return None

    def grow(i: int) -> int:  # the last item that a quote starting at item i still takes in
        j = i
        while j + 1 < len(pool) and pool[j + 1].end - pool[i].start <= 200:
            j += 1
        return j

    i = pool.index(item) if item in pool else 0
    j = grow(i)
    if item is None and j == i and len(pool) > 2:
        # the list opens on an item with its detail: quote the stretch of the list that shows the most covenants
        i = max(range(len(pool)), key=lambda k: (grow(k) - k, -k))
        j = grow(i)
    while i > 0 and item is not None and pool[j].end - pool[i - 1].start <= 200:  # ... and to the left, while it stays short
        i -= 1
    return ctx.quote(pool[i].block, _Span(pool[i].start, pool[j].end)) or (ctx.quote(item.block, item.span) if item is not None else None)


def _ref_clause(pkg: _Package) -> str:
    """What the section says its covenants follow, for use after "covenants are ...": the short phrase, or the whole
    introduction in quotes when that says more and is short."""
    intro = pkg.intro if pkg.ref_in_intro else ""
    if intro and len(intro) <= 150 and len(intro) > len(pkg.ref_phrase) + 12 and "(" not in intro:
        return f"'{_low(intro)}'"
    return pkg.ref_phrase


def _own_limbs(text: str) -> list[tuple[int, int, int]] | None:
    """The numbered exceptions of a covenant as (start of the number, start of its text, end of it): numbered in the
    covenant's own text, or inside one long bracket of it - "indebtedness (with exceptions including (i) ..., (ii) ...)".
    A bracket that is never closed runs to the end of the text."""
    limbs = _marked_items(text, 0, len(text))
    at = text.find("(")
    while not limbs and at >= 0:
        close = _closing_bracket(text, at)
        end = close if close >= 0 else len(text)
        inner = _marked_items(text, at + 1, end) if end - at > 80 else None
        if inner:
            limbs = inner[:-1] + [(inner[-1][0], inner[-1][1], len(text))]  # the last one takes the bracket that closes
        if close < 0:
            break
        at = text.find("(", close + 1)
    return limbs


def _head_name(text: str) -> str:
    """The name a list item gives its covenant: its head, without the punctuation that ties it to what follows."""
    return _head(text).strip(" ,;:")


def _detail_lines(text: str, max_lines: int = 3) -> list[str]:
    """A covenant given with its baskets as lines: whole if it fits, otherwise broken between its numbered exceptions
    (or its semicolons), never in the middle of one."""
    text = _norm(text)
    if len(text) <= LINE:
        return [_cap(_line(text))]
    limbs = _own_limbs(text)
    if limbs:
        parts = [text[mark:end].strip() for mark, _, end in limbs]  # with their "and" / "or": the wording stays as written
        stem = text[:limbs[0][0]].strip(" ,;")
        return [_cap(ln) for ln in _wrap(stem + " " if stem else "", parts, max_lines=max_lines, sep=" ")]
    parts = [_strip_item(text[a:b]) for a, b in _split_semicolons(text, 0, len(text))]
    return [_cap(ln) for ln in _wrap("", [x for x in parts if x], max_lines=max_lines)]


def _home_limbs(home: _Item, topic: str) -> list[tuple[str, _Span]]:
    """What a listed covenant says of a subject it deals with (acquisitions inside investments, guarantees inside
    indebtedness): those of its numbered exceptions that open on the subject, each as a line in the term sheet's words -
    the covenant's lead-in, a mark of omission, the exception - with its place in the block. An exception that would not
    fit on a line with the lead-in is left to the row of the covenant itself."""
    text = _norm(home.text)
    limbs = _own_limbs(text)
    if not limbs:
        return []
    stem = text[:limbs[0][0]].strip(" ,;")
    opened = _unclosed(stem)
    # where the lead-in is long, the covenant's name and the bracket that opens its exceptions: "Indebtedness … (which
    # shall permit, among other things, the incurrence and/or existence of … (iv) guarantees of ..."
    short = f"{_head_name(text)} … {stem[opened[-1]:]}" if opened and opened[-1] > len(_head_name(text)) else ""
    out = []
    for k, (mark, a, b) in enumerate(limbs):
        opening = _NOT_A_TOPIC_RE.sub(lambda m: " " * len(m.group(0)), text[a:min(b, a + 70)])
        if not _TOPIC_RES[topic].search(opening):
            continue
        limb = _strip_item(text[mark:b])
        more = "" if k == len(limbs) - 1 or limb.count("(") < limb.count(")") else "; …"
        # (its place in the block, for the quote: where its opening words stand in the item)
        words = r"\s+".join(re.escape(w) for w in text[a:b].split()[:6])
        at = re.search(words, home.block.text[home.start:home.end]) if words else None
        span = _Span(home.start + at.start(), min(home.end, home.start + at.start() + 220)) if at else home.span
        for lead in (stem, short):
            line = f"{lead} … {limb}{more}"
            if lead and len(_norm(line)) <= LINE + 90:
                out.append((_cap(_line(line, LINE + 90)), span))
                break
    return out


def _names(items: list[_Item]) -> str:
    """The listed covenants by name, for "limited to ...": in full when they are short, otherwise without their detail."""
    full = [_bare(it.text) for it in items]
    if all(len(t) <= 80 and not _has_figure(t) for t in full):
        return "; ".join(full)
    return "; ".join(_bare(_head_name(it.text)) for it in items)


_UNREAD_NOTE = "The covenant section could not be read to its end (the text read breaks off in mid-phrase or leaves a bracket open);"
_UNREAD_PART_NOTE = "The covenant section has a part headed 'Negative Covenants' that the rules could not tell apart from the rest of the section;"


def _unread(pkg: _Package) -> str:
    """The opening of the reviewer note for a section that was not read to its end: why."""
    return _UNREAD_PART_NOTE if pkg.unread_part else _UNREAD_NOTE


def _from_package(ctx: Ctx, spec: _Spec, pkg: _Package, related: list[str]) -> dict:
    """A row answered from the covenant list: listed, expressly absent (closed list), by reference, or silent."""
    if pkg.none:
        return stated([_none_line(pkg)], _line_quote(ctx, pkg.block))
    if pkg.blank:
        return by_reference([_none_line(pkg)], _line_quote(ctx, pkg.block))
    items = pkg.with_topic(spec.topic)
    extras = [x for x in pkg.extras if x.topic == spec.topic]
    lines: list[str] = []
    quotes: list[dict | None] = []
    label = pkg.label.lower()
    more = " - see [Other]" if pkg.ref_in_intro and len(pkg.intro) > len(pkg.ref_phrase) + 12 and _ref_clause(pkg) == pkg.ref_phrase else ""
    if more and _TOPIC_RES[spec.topic].search(_NOT_A_TOPIC_RE.sub(lambda m: " " * len(m.group(0)), pkg.intro)):
        # the words that follow the pointer speak of this covenant ("Same as the Existing Credit Agreement, except that the
        # limitation on restricted payments shall be deleted ..."): the row does not give the pointer without them
        more = ", save for what the term sheet says of this covenant - see [Other]"
    fall = _fall_line(pkg, items)
    cap = MAX_FIELD_LINES
    # for a covenant that is not listed, the section points elsewhere only if it does so for the package: words that leave
    # the exceptions of the listed covenants to the definitive documents say nothing of a covenant that is not listed
    points = bool(pkg.ref_phrase) and not (pkg.ref_deferred and bool(pkg.items or pkg.sub_headed))
    blank = lambda s: _NOT_A_TOPIC_RE.sub(lambda m: " " * len(m.group(0)), s)  # noqa: E731
    said_after = False
    elsewhere: list[_Extra] = []
    if items:
        # an item that only names its covenant (and at most points elsewhere for the rest) is "listed"; one that goes on to
        # say what is excepted or permitted is given in its own words, like one that gives its baskets
        simple = [it for it in items if len(it.text) <= 170 and not _has_figure(it.text) and not _qualified(it.text)]
        detailed = [it for it in items if it not in simple]
        if simple:
            head = _listed_as(pkg, spec.name, simple)
            ref = f": {pkg.ref_phrase}" if pkg.ref_phrase and not any(_REF_RE.search(it.text) for it in simple) else ""
            # (where the text read breaks off after the item, it is not said that the term sheet leaves the detail out;
            # nor where a sentence after the list that no row gives speaks of this covenant)
            unread = pkg.cut_off and any(it is pkg.items[-1] for it in simple)
            section = pkg.block.text if pkg.block is not None else ""
            said_after = any(_TOPIC_RES[spec.topic].search(blank(section[a:b])) and _has_terms(section[a:b]) for a, b in pkg.unplaced)
            # ... nor where a clause given in another row (the row of the covenant it names first) speaks of this one too
            elsewhere = [x for x in pkg.extras if x.topic != spec.topic and _TOPIC_RES[spec.topic].search(blank(x.about or x.text))
                         and _has_terms(x.text)]
            absent = "" if unread or said_after or elsewhere else f"; {spec.detail} not detailed in term sheet" + (" other than as set out below" if extras else "")
            line = f"{head}{ref}{absent}"
            if len(line) > LINE + 20 and ref:
                lines += [f"{head}{absent}", _cap(f"{pkg.label} are {pkg.ref_phrase}")]
            else:
                lines.append(line)
        # a covenant given with its baskets takes the lines the row has left beside its other points
        room = _ROW_LINES - bool(pkg.ref_phrase) - min(2, len(extras)) - bool(fall) - len(related)
        cap = _ROW_LINES if len(detailed) == 1 else MAX_FIELD_LINES
        for it in detailed:
            lines += _detail_lines(it.text, max(3, room) if len(detailed) == 1 else 2)
        if detailed and not simple and pkg.ref_phrase:
            if pkg.aside and len(pkg.aside) <= LINE and not pkg.ref_in_intro:
                lines.append(f"{pkg.label}: {_low(pkg.aside)}")  # in the words the list is opened with
            else:
                lines.append(f"{pkg.label} otherwise {pkg.ref_phrase}")
        quotes += [_list_quote(ctx, pkg, it) for it in items[:2]]
    elif (extras or (points and not pkg.items)) and not pkg.cut_off:
        ref = f"; {label} are {_ref_clause(pkg)}{more}" if points else ""
        lines.append(f"{spec.name}: not itemised in term sheet{ref}")
    elif points and not pkg.items:
        # the section breaks off in the text read: where it points is known, whether it goes on to list covenants is not
        lines.append(f"{spec.name}: {label} are {pkg.ref_phrase}")
    for x in extras:
        lines += _detail_lines(_keep_names(x.text), 2)
        quotes.append(ctx.quote(x.block, x.span))
    for see in dict.fromkeys(_SPECS[_FIELD_OF_TOPIC[x.topic]].see if x.topic in _FIELD_OF_TOPIC else "[Other]" for x in elsewhere):
        lines.append(f"The term sheet says more of this covenant in a clause given under {see}")
    if fall:
        lines.append(fall)
        quotes.append(ctx.quote(pkg.fall_block, pkg.fall_span) if pkg.fall_block is not None and pkg.fall_span is not None else None)
    if lines:
        lines = (lines + related)[:cap]
        evidence = _package_quotes(ctx, pkg, *quotes)
        detailed_here = any(_has_terms(it.text) for it in items)
        note = _unread(pkg) + " what follows was not read." if pkg.cut_off else ""
        if said_after and not note:
            note = "The covenant section says more of this covenant after its list, in a sentence the rules did not place in a row; check the term sheet."
        return by_reference(lines, evidence, note) if pkg.ref_phrase and not detailed_here else stated(lines, evidence, note)

    # not a covenant of its own on the list, but dealt with inside one that is ("limitations on investments, including
    # permitted acquisitions ..."): say where, and leave the baskets to that row
    homes = [it for it in pkg.items if it.neg and it.neg[0] in _HOME_TOPICS.get(spec.topic, ())
             and _TOPIC_RES[spec.topic].search(blank(it.text))]
    if homes:
        home = homes[0]
        see = _SPECS[_FIELD_OF_TOPIC[home.neg[0]]].see if home.neg[0] in _FIELD_OF_TOPIC else "[Other]"
        lines = [f"{spec.name}: no covenant of its own listed; dealt with in the covenant listed as \"{_head_name(home.text)}\" - see {see}"]
        quotes = [_list_quote(ctx, pkg, home)]
        for line, span in _home_limbs(home, spec.topic)[:2]:  # what that covenant says of this row's subject, in its words
            lines.append(line)
            quotes.insert(0, ctx.quote(home.block, span))
        evidence = _package_quotes(ctx, pkg, *quotes)
        return by_reference(lines, evidence) if pkg.ref_phrase and not any(_has_terms(ln) for ln in lines[1:]) else stated(lines, evidence)

    if pkg.cut_off:
        # the section breaks off in the text read: what is missing from the list read may stand in the part that was lost
        return not_stated(note=_unread(pkg) + " this row could not be answered from it.")

    # the topic is not on the list. It is only an express "none" if the list is closed and the section never names it
    section = pkg.block.text if pkg.block is not None else ""
    for it in pkg.items:
        if "pari" in it.notable and it.block is pkg.block:
            section = section[:it.start] + " " * (it.end - it.start) + section[it.end:]
    if pkg.closed:
        section = blank(section)
        if _TOPIC_RES[spec.topic].search(section) or _LOOSE_TOPIC_RES[spec.topic].search(section):
            # the closed list has no such item, yet the section speaks of the subject: neither "none" nor "listed" is safe
            return not_stated(note=f"The covenant list is closed and has no {spec.none}, but the covenant section mentions the subject; "
                                   "check the term sheet.")
        listed = _names(pkg.negatives())
        scope = f"negative covenants limited to {squeeze(listed, 140)}" if listed else "the list is closed"
        lines = [f"None: not among the covenants listed in the term sheet ({scope}) - no {spec.none}"] + related
        return stated(lines, _quotes(ctx.quote(pkg.closed_block, pkg.closed_match), _list_quote(ctx, pkg)))
    if points:
        if pkg.items:
            how = f"the list is open ('{_shown_opener(pkg)}') and " if _OPEN_RE.search(pkg.opener) else ""
            lines = [f"Not among the covenants listed in the term sheet; {how}{label} are {pkg.ref_phrase}"]
        else:
            lines = [f"{spec.name}: not itemised in term sheet; {label} are {_ref_clause(pkg)}{more}"]
        opener_block = pkg.opener_block or pkg.block
        opener = ctx.quote(opener_block, re.escape(pkg.opener.split(",")[0])) if pkg.opener and opener_block is not None else None
        return by_reference(lines + related, _package_quotes(ctx, pkg, None, opener))
    return not_stated()


def _shown_opener(pkg: _Package) -> str:
    """The words that open the list as a line quotes them: without the aside that is given on a line of its own, and
    without a bracket left hanging."""
    opener = pkg.opener
    if pkg.aside:
        opener = _norm(re.sub(r"\s*\([^()]*\)", "", opener))
    while opener.count(")") > opener.count("("):
        opener = opener[:opener.rindex(")")] + opener[opener.rindex(")") + 1:]
    return opener.strip(" ,;:(")


def _none_line(pkg: _Package) -> str:
    """The line for a section that says there is nothing ("None: the term sheet says there are no negative covenants
    ('Negative Covenants: None')") or that is left blank ("Negative Covenants: [ ] - left blank in term sheet")."""
    which = "negative covenants" if pkg.negative_only else "covenants"
    said = _norm(pkg.block.text).strip(" .") if pkg.block is not None else "None"
    if pkg.blank:  # "Negative Covenants: [ ] - left blank in term sheet"
        return f"{pkg.label}: {said} - left blank in term sheet"
    return f"None: the term sheet says there are no {which} ('{pkg.label}: {said}')"


def _line_quote(ctx: Ctx, block: Block | None) -> dict | None:
    """The whole source line a section starts on, as a quote: a value of a word or two ("None") is too short to cut."""
    if block is None or not block.lines:
        return None
    ln = block.lines[0]
    return ctx.quote(Block(label=block.label, line=ln, lines=[ln], parts=[ln.text], inline=False, mode=block.mode))


def _related_lines(spec: _Spec, pkg: _Package) -> list[str]:
    """Cross-references a row needs so that nothing is repeated: the neighbouring listed covenant that bears on it."""
    has = lambda t: bool(pkg.with_topic(t))  # noqa: E731
    out = []
    if spec.fid == "permitted_acquisitions":
        if not has("acquisitions") and has("investments"):
            out.append("An investments covenant is listed; the term sheet does not say whether it covers acquisitions (see Permitted Loans)")
        if has("mergers"):
            out.append("A mergers / fundamental changes covenant is listed - see [Other]")
    elif spec.fid == "permitted_disposals" and not has("disposals") and has("mergers"):
        out.append("A mergers / fundamental changes covenant is listed; the term sheet does not say whether it covers sales of all or "
                   "substantially all assets - see [Other]")
    elif spec.fid == "permitted_guarantees" and not has("guarantees"):
        homes = [(what, see) for t, what, see in (("debt", "indebtedness", "Permitted Financial Indebtedness"),
                                                 ("investments", "investments", "Permitted Loans")) if has(t)]
        if homes:
            out.append("Term sheet does not say whether guarantees fall under the listed " + " or ".join(w for w, _ in homes)
                       + " covenant (see " + " and ".join(s for _, s in homes) + ")")
    elif spec.fid == "permitted_indebtedness" and not has("debt"):
        if any(re.search(r"secured\s+(?:debt|indebtedness)", it.text, re.IGNORECASE) for it in pkg.with_topic("liens")):
            out.append("Secured debt is limited together with liens - see Negative Pledge")
    elif spec.fid == "permitted_payments" and not has("payments") and has("rp") and not pkg.closed:
        out.append("A restricted payments covenant is listed - see Permitted Distributions")
    return out


def _step_up(ctx: Ctx, state: _State) -> tuple[str, dict] | None:
    """(line, quote) if a financial covenant allows a higher level after an acquisition: the Permitted Acquisitions row
    points to it rather than repeating the levels."""
    blocks = [state.clean(b) for b in ctx.all(_FINCOV_LABEL) if b.text]
    if state.package is not None and state.package.block is not None:
        blocks.append(state.package.block)
    for block in blocks:
        for a, b in _sentences(block.text, 0, len(block.text)):
            sentence = block.text[a:b]
            m = _ACQUISITION_STEP_RE.search(sentence)
            if m and _RATIO_LEVEL_RE.search(sentence):
                q = ctx.quote(block, _Span(a + m.start(), a + m.end()))
                if q:
                    # a step-up that has to be chosen ("may be increased at the Company's option", "upon the election of
                    # ...") is not one that simply applies
                    how = "may be stepped up by election" if _AT_OPTION_RE.search(sentence) else "steps up"
                    return f"A financial covenant level {how} after certain acquisitions - see Financial Covenants", q
    return None


def _rule(fid: str):
    """The rule for one "Permitted ..." row: its own rows in the term sheet if it has any, otherwise the covenant list."""
    spec = _SPECS[fid]

    def rule(ctx: Ctx) -> dict:
        try:
            state = _state(ctx)
            uses = state.uses.get(fid, [])
            pkg = state.package
            combined = [u for u in state.uses.get("negative_pledge", []) if u.combined]
            if uses:
                lines: list[str] = []
                evidence: list[dict] = []
                for use in uses:
                    lines += _render_use(use)
                    evidence += _use_evidence(ctx, use)[:3]
                lines = _note_blanks(lines[:MAX_FIELD_LINES])
                if fid == "negative_pledge" and combined:
                    lines.append("Liens and indebtedness baskets are given together in the term sheet - see also Permitted Financial Indebtedness")
                if fid == "permitted_indebtedness" and combined:
                    lines.append("Secured and junior debt: the term sheet gives these baskets together with the liens - see Negative Pledge")
                if all(_points_only(use) for use in uses):
                    return by_reference(lines, _spread(evidence))  # "Negative pledge: customary, exceptions to be agreed"
                return stated(lines, _spread(evidence))
            if fid == "permitted_indebtedness" and combined:
                return stated(["Baskets for indebtedness are given together with the liens that may secure it - see Negative Pledge"],
                              _use_evidence(ctx, combined[0])[:1])
            if pkg is None:
                return not_stated()
            entry = _from_package(ctx, spec, pkg, _related_lines(spec, pkg))
            if entry["status"] != "not_stated":
                entry["lines"] = _note_blanks(entry["lines"])
            if fid == "permitted_acquisitions" and entry["status"] != "not_stated" and len(entry["lines"]) < MAX_FIELD_LINES:
                step = _step_up(ctx, state)
                if step:
                    entry["lines"].append(step[0])
                    if len(entry["evidence"]) < 3:
                        entry["evidence"].append(step[1])
            return entry
        except Exception:  # a document the rule cannot read is left to the analyst, never guessed
            if DEBUG:
                raise
            return not_stated()

    rule.__name__ = fid
    rule.__doc__ = f"{spec.name}: its own row in the term sheet if it has one, otherwise what the covenant list says."
    return rule


def other_covenants(ctx: Ctx) -> dict:
    """The [Other] row: the covenant list as the term sheet gives it, undertakings that have no row of their own
    (mergers, affiliates, change of business, sanctions ...), general changes to baskets, fall-away mechanics, and
    table rows such as "Anti cash hoarding"."""
    try:
        state = _state(ctx)
        pkg, uses = state.package, state.uses.get(_OTHER, [])
        lines: list[str] = []
        quotes: list[dict | None] = []
        for use in uses:
            lines += _render_use(use)
            quotes += _use_evidence(ctx, use)[:1]
        if pkg is None:
            return stated(lines[:MAX_FIELD_LINES], _quotes(*quotes)) if lines else not_stated()
        if pkg.none or pkg.blank:
            entry = stated((lines + [_none_line(pkg)])[:MAX_FIELD_LINES], _quotes(*quotes, _line_quote(ctx, pkg.block)))
            if pkg.blank and not lines and entry["status"] == "stated":
                entry["status"] = "by_reference"  # left open, to be filled in: not a statement of the term
            return entry
        negatives = pkg.negatives()
        if negatives:
            kind = "closed list" if pkg.closed else (f"open list - '{_shown_opener(pkg)}'" if _OPEN_RE.search(pkg.opener) else "as listed")
            if pkg.cut_off:
                kind = "as far as the list could be read"
            texts = [_low(it.text) for it in negatives]
            if sum(len(t) + 2 for t in texts) > 2 * LINE - 60 or any(_has_figure(t) for t in texts) or any(_qualified(it.text) for it in negatives):
                # too long to give in full, or an item carries terms of its own (given in its row): the covenants by name
                texts = [_low(_head_name(it.text)) for it in negatives]
            lines += _wrap(f"Negative covenants ({kind}): ", texts, max_lines=3)
            quotes.append(_list_quote(ctx, pkg))
            if pkg.closed:
                quotes.append(ctx.quote(pkg.closed_block, pkg.closed_match))
            for it in negatives:  # undertakings with no row of their own that the list qualifies
                own_row = any(t in _FIELD_OF_TOPIC for t in it.neg)
                if it.neg and not own_row and it.text != _head_name(it.text) and len(lines) < 5:
                    named = re.match(r"[A-Z][\w /&\-]{2,40}[:.]\s", it.text)  # the item carries its own heading: "Mergers: ..."
                    lines += _detail_lines(it.text if named else f"{_OTHER_NAMES.get(it.neg[0], 'Other')}: {it.text}", 1)
        if not pkg.negative_only:
            also = [it for it in pkg.items if it.notable and not it.neg]
            for it in [it for it in also if len(it.text) > 100]:
                lines.append(_cap(_line(re.sub(r"^that\s+", "", it.text))))
                quotes.append(ctx.quote(it.block, it.span))
            short = [it for it in also if len(it.text) <= 100]
            if short:
                only_sanctions = all(it.notable == ("sanctions",) for it in short)
                lead = "Sanctions / anti-corruption: " if only_sanctions else "Also listed: "
                lines.append(_line(lead + "; ".join(_low(it.text) for it in short)))
                quotes.append(ctx.quote(short[0].block, short[0].span))
        # what the section says of the package as a whole: where it points, or - with no covenant listed - its opening
        # words (an introduction that neither points anywhere nor stands for a missing list says nothing)
        if pkg.aside and len(pkg.aside) <= LINE and not (pkg.ref_phrase and pkg.ref_in_intro):
            # ... in the words the list is opened with: "(in each case subject to exceptions ... consistent with ...)"
            lines.append(_line(f"{pkg.label}: {_low(pkg.aside)}"))
            quotes.append(ctx.quote(pkg.block, pkg.aside_span))
        elif pkg.ref_phrase or (pkg.intro and not negatives and not pkg.cut_off):
            # (an introduction that does not hold the pointer - "The negative covenants will" - is not given for it)
            intro = pkg.intro if (pkg.ref_in_intro or not pkg.ref_phrase) and not (pkg.cut_off and not negatives and pkg.ref_phrase) else ""
            main, aside = _split_aside(intro or pkg.ref_phrase)
            missing = "" if negatives or pkg.cut_off else ("; negative covenants not listed" if pkg.affirmative else "; individual covenants not listed")
            lines.append(_line(f"{pkg.label}: {_low(main)}{missing}"))
            if aside:
                lines += _wrap("", [s.strip() for s in re.split(r",\s+(?![^()]*\))", aside) if s.strip()], max_lines=3, sep=", ")
            if pkg.ref_block is not None:
                quotes.append(ctx.quote(pkg.ref_block, pkg.ref_match))
        for x in pkg.extras:
            if x.topic not in _FIELD_OF_TOPIC:
                lines += _detail_lines(_keep_names(x.text), 2)
                quotes.append(ctx.quote(x.block, x.span))
        if pkg.fall_block is not None and pkg.fall_span is not None:
            # the fall-away: what the event is, then which covenants it switches off (the rows point here for it)
            text = pkg.fall_block.text
            if pkg.fall_def is not None and pkg.fall_event:
                lines += _detail_lines(f"{pkg.fall_event}: " + text[pkg.fall_def.start():pkg.fall_def.end()].strip(" ,"), 2)
                quotes.append(ctx.quote(pkg.fall_block, pkg.fall_def))
            gone = [_head_name(it.text) for it in pkg.items if it.terminated]
            event = f"a {pkg.fall_event}" if pkg.fall_event else "that event"
            if gone:
                lines += _wrap(f"Of no further force and effect from {event}: ", gone, max_lines=1)
            else:
                lines.append(_cap(_line(text[pkg.fall_span.start():pkg.fall_span.end()])))
            quotes.append(ctx.quote(pkg.fall_block, pkg.fall_span))
        plain = []
        for it in pkg.affirmative:
            if it.neg and pkg.negative_only:  # e.g. transactions with affiliates listed among the affirmative covenants
                lines.append(_cap(_line(f"{it.text} (listed as an affirmative covenant)")))
            elif not re.search(r"\d", it.text):
                plain.append(_low(it.text))
        if plain and lines:
            lines += _wrap("Affirmative covenants listed: ", plain, max_lines=1)
        if not lines:
            return not_stated()
        if pkg.block is not None and not any(quotes):
            quotes.append(ctx.quote(pkg.block))
        evidence, lines = _quotes(*quotes), lines[:8]
        # a list of covenants that points to another agreement for what they say is by reference; a closed list, and one
        # that only leaves its exceptions to the definitive documents, is what the term sheet states
        if pkg.ref_phrase and not (negatives and pkg.closed) and not (pkg.ref_deferred and (negatives or pkg.sub_headed)):
            return by_reference(lines, evidence)
        return stated(lines, evidence)
    except Exception:
        if DEBUG:
            raise
        return not_stated()


def _checked(rule):
    """The rule with its answer checked before it leaves the module: a quote must be one contiguous passage, so one
    that carries an ellipsis of the page's own ("ample liquidity… Build-up") is dropped, and an entry left without a
    quote reads "not stated". Whatever goes wrong here ends as "not stated" too."""
    @wraps(rule)
    def run(ctx: Ctx) -> dict:
        try:
            entry = rule(ctx)
            if not isinstance(entry, dict) or entry.get("status") == "not_stated":
                return entry if isinstance(entry, dict) else not_stated()
            evidence = [q for q in entry.get("evidence") or [] if q and not _ELLIPSIS_RE.search(q.get("quote") or "")]
            if not evidence:
                return not_stated()
            entry["evidence"] = evidence[:3]
            return entry
        except Exception:
            if DEBUG:
                raise
            return not_stated()
    return run


RULES: dict = {fid: _checked(_rule(fid)) for fid in _SPECS}
RULES[_OTHER] = _checked(other_covenants)
