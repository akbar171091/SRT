"""Term sheet vs credit agreement reconciliation: Streamlit front end.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from recon import inventory, pdftext, quotes, results, rules
from recon.config import (CHECKLIST_NAMES, DEFAULT_DOCS_DIR, ENGINES, STATUS_ORDER, STATUSES, UPLOAD_DIR)

st.set_page_config(page_title="TS ↔ CA Reconciliation", page_icon="📑", layout="wide")

HEAT = {
    "match": "#2da44e", "match_minor_drafting": "#7cc49a", "ts_open_filled_in_ca": "#6fa8dc", "review": "#e3b341",
    "differs": "#cf222e", "not_in_ca": "#fb8f44", "not_in_ts": "#c9ccd1", "not_applicable": "#eef0f2", "missing_document": "#6e1a1a",
}
ISSUE_STATUSES = [s for s, v in STATUSES.items() if v["issue"]]
LABEL_TO_STATUS = {v["label"]: k for k, v in STATUSES.items()}

st.markdown(
    """
    <style>
      .chip {display:inline-block;padding:2px 10px;border-radius:999px;font-size:0.82rem;font-weight:600;margin:0 6px 6px 0;}
      .evidence {font-family: ui-monospace, Consolas, monospace; font-size: 0.82rem; white-space: pre-wrap;
                 background: rgba(127,127,127,0.08); padding: 8px 10px; border-radius: 6px;}
      div[data-testid="stMetricValue"] {font-size: 1.6rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- cached helpers
@st.cache_data(show_spinner=False)
def page_count(path: str, mtime: float) -> int:
    from pypdf import PdfReader
    try:
        return len(PdfReader(path).pages)
    except Exception:
        return 0


@st.cache_data(show_spinner=False, max_entries=64)
def pages_of(path: str, mtime: float) -> list[str]:
    return pdftext.extract_pages(Path(path))


def doc_pages(p: Path | None) -> list[str] | None:
    return pages_of(str(p), p.stat().st_mtime) if p else None


def chip(status: str, text: str | None = None) -> str:
    s = STATUSES.get(status, STATUSES["review"])
    return f'<span class="chip" style="background:{s["bg"]};color:{s["color"]};">{text or s["label"]}</span>'


def status_label(s: str) -> str:
    return STATUSES.get(s, STATUSES["review"])["label"]


def style_by_status(df: pd.DataFrame, col: str = "Status"):
    def row_style(row):
        st_key = LABEL_TO_STATUS.get(row[col], "review")
        s = STATUSES[st_key]
        return [f"background-color: {s['bg']}; color: #1f2328" if c != col else
                f"background-color: {s['bg']}; color: {s['color']}; font-weight: 700" for c in row.index]
    return df.style.apply(row_style, axis=1)


def quote_mark(v) -> str:
    return {True: "✅", False: "❌", None: "–"}.get(v, "–")


def md(text: str) -> str:
    """Escape text for st.markdown: '$' would otherwise start LaTeX ('$1bn ... $2bn' renders as maths)."""
    return str(text or "").replace("\\", "\\\\").replace("$", "\\$")


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes | None:
    """Workbook bytes, or None if the export fails (the page must not crash because of an export)."""
    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            for name, df in sheets.items():
                df = df.map(lambda v: _CTRL.sub(" ", v) if isinstance(v, str) else v)  # openpyxl rejects control chars
                sty = style_by_status(df) if "Status" in df.columns else df.style
                sty.to_excel(xw, sheet_name=name[:31], index=False)
                ws = xw.sheets[name[:31]]
                for col_cells in ws.columns:
                    width = min(60, max(10, *(len(str(c.value or "")) for c in col_cells[:50])))
                    ws.column_dimensions[col_cells[0].column_letter].width = width
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        st.warning(f"Excel export unavailable: {type(e).__name__}: {e}")
        return None


def excel_button(label: str, sheets: dict[str, pd.DataFrame], file_name: str, where=st):
    data = to_excel(sheets)
    if data is not None:
        where.download_button(label, data, file_name=file_name)


def rows_frame(payload: dict) -> pd.DataFrame:
    recs = []
    for r in payload.get("rows", []):
        recs.append({
            "ID": r.get("id", ""),
            "Attribute": CHECKLIST_NAMES.get(r.get("id", ""), r.get("attribute", "")),
            "Status": status_label(r.get("status", "review")),
            "Term sheet says": r.get("ts_value", ""),
            "Credit agreement says": r.get("ca_value", ""),
            "Explanation": r.get("explanation", ""),
            "Materiality": r.get("materiality", ""),
            "Favours": (r.get("direction") or "").replace("_", " "),
            "TS location": r.get("ts_location", ""),
            "CA location": r.get("ca_location", ""),
            "TS quote ✓": quote_mark(r.get("ts_quote_found")),
            "CA quote ✓": quote_mark(r.get("ca_quote_found")),
        })
    return pd.DataFrame(recs)


# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("📑 TS ↔ CA Reconciliation")
    docs_dir = Path(st.text_input("Documents folder", value=str(DEFAULT_DOCS_DIR),
                                  help="Folder of PDFs named '<Client> <Year> CA.pdf' and '<Client> <Year> TS.pdf'.")
                    .strip().strip('"').strip("'").strip())
    uploaded = st.file_uploader("Add PDFs (saved to the app's uploads folder)", type="pdf", accept_multiple_files=True)
    if uploaded:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for f in uploaded:
            (UPLOAD_DIR / Path(f.name).name).write_bytes(f.getbuffer())
        st.caption(f"Saved {len(uploaded)} file(s) to `{UPLOAD_DIR.name}/`.")
    deals, unclassified = inventory.scan([docs_dir, UPLOAD_DIR])
    if "engine_next" in st.session_state:  # switch source after a run / import
        st.session_state["engine"] = st.session_state.pop("engine_next")
    if "engine" not in st.session_state:  # default to the richest source that has results
        st.session_state["engine"] = next((e for e in ENGINES if results.load_all(e, deals)), "rules")
    engine = st.radio("Results source", list(ENGINES), format_func=ENGINES.get, key="engine",
                      help="Agent reconciliation: multi-agent reconciliation, each group re-checked by an adversarial verifier. "
                           "Claude API: run a fresh AI reconciliation. Rules engine: instant offline screening.")
    st.divider()
    st.caption("Status legend")
    st.markdown("".join(chip(s) for s in STATUS_ORDER), unsafe_allow_html=True)

if not deals and not unclassified:
    st.error(f"No PDFs found in `{docs_dir}`. Point the sidebar at the folder of term sheets and credit agreements.")
    st.stop()

if msg := st.session_state.pop("flash", None):
    st.success(msg)

payloads = results.load_all(engine, deals)

tab_docs, tab_overview, tab_deal, tab_exc, tab_run = st.tabs(
    ["📁 Documents", "📊 Overview", "🔍 Deal detail", "⚠️ Exceptions", "▶️ Run checks"])


# --------------------------------------------------------------------------- documents tab
with tab_docs:
    complete = [d for d in deals.values() if d.status == "complete"]
    miss_ts = [d for d in deals.values() if d.status == "missing_ts"]
    miss_ca = [d for d in deals.values() if d.status == "missing_ca"]
    c = st.columns(5)
    c[0].metric("Clients / deals", len(deals))
    c[1].metric("Complete CA + TS pairs", len(complete))
    c[2].metric("Missing term sheet", len(miss_ts))
    c[3].metric("Missing credit agreement", len(miss_ca))
    c[4].metric("Unrecognised files", len(unclassified))
    for d in miss_ts + miss_ca:
        st.error(f"**{d.key}** is missing its **{' and '.join(d.missing)}**, so it cannot be reconciled.", icon="🚫")
    for d in deals.values():
        if d.duplicates:
            st.warning(f"**{md(d.key)}** has more than one file of the same type: {md(', '.join(p.name for p in d.duplicates))}", icon="⚠️")
        if d.replaced:
            st.info(f"**{md(d.key)}**: an uploaded file replaces the folder copy of {md(', '.join(p.name for p in d.replaced))}.", icon="📤")

    recs = []
    for d in deals.values():
        recs.append({
            "Deal": d.key,
            "Credit agreement (CA)": d.ca.name if d.ca else "❌ MISSING",
            "CA pages": page_count(str(d.ca), d.ca.stat().st_mtime) if d.ca else None,
            "Term sheet (TS)": d.ts.name if d.ts else "❌ MISSING",
            "TS pages": page_count(str(d.ts), d.ts.stat().st_mtime) if d.ts else None,
            "Status": {"complete": "Complete", "missing_ts": "Missing TS", "missing_ca": "Missing CA"}[d.status],
            "Reconciled": "✅" if d.key in payloads else ("–" if d.status != "complete" else "not yet"),
        })
    inv = pd.DataFrame(recs)

    def inv_style(row):
        bad = row["Status"] != "Complete"
        return ["background-color: #fbd5d2; color: #b42318; font-weight: 600" if bad and ("MISSING" in str(row[c]) or c == "Status")
                else ("background-color: #d1f2dc" if c == "Status" else "") for c in row.index]

    st.dataframe(inv.style.apply(inv_style, axis=1), hide_index=True, width="stretch")
    if unclassified:
        st.warning("These PDFs could not be classified as a CA or TS. Name files '<Deal> CA.pdf' / '<Deal> TS.pdf':\n\n"
                   + "\n".join(f"- {p.name}" for p in unclassified))


# --------------------------------------------------------------------------- overview tab
def all_rows_frame(payloads: dict[str, dict]) -> pd.DataFrame:
    recs = []
    for key, d in deals.items():
        if d.status != "complete":
            recs.append({"Deal": key, "ID": "DOC", "Attribute": "Document set", "status": "missing_document",
                         "Status": status_label("missing_document"), "TS": "MISSING" if not d.ts else d.ts.name,
                         "CA": "MISSING" if not d.ca else d.ca.name, "Explanation": f"Missing {' and '.join(d.missing)}",
                         "Materiality": "material"})
            continue
        for r in payloads.get(key, {}).get("rows", []):
            recs.append({"Deal": key, "ID": r.get("id", ""), "Attribute": CHECKLIST_NAMES.get(r.get("id", ""), r.get("attribute", "")),
                         "status": r.get("status", "review"), "Status": status_label(r.get("status", "review")),
                         "TS": r.get("ts_value", ""), "CA": r.get("ca_value", ""), "Explanation": r.get("explanation", ""),
                         "Materiality": r.get("materiality", "")})
    return pd.DataFrame(recs)


with tab_overview:
    st.subheader(f"Reconciliation overview · {ENGINES[engine]}")
    done = [k for k in deals if k in payloads]
    todo = [k for k, d in deals.items() if d.status == "complete" and k not in payloads]
    if not done:
        st.info("No results for this source yet. Open **▶️ Run checks** to run the rules engine or Claude, "
                "or import the agent-verified results.", icon="ℹ️")
    else:
        df = all_rows_frame(payloads)
        rec_rows = df[df["status"] != "missing_document"]
        q_checked = sum(p.get("quote_check", {}).get("ts_checked", 0) + p.get("quote_check", {}).get("ca_checked", 0) for p in payloads.values())
        q_found = sum(p.get("quote_check", {}).get("ts_found", 0) + p.get("quote_check", {}).get("ca_found", 0) for p in payloads.values())
        m = st.columns(6)
        m[0].metric("Deals reconciled", f"{len(done)} / {sum(d.status == 'complete' for d in deals.values())}")
        m[1].metric("Attributes checked", len(rec_rows))
        m[2].metric("Differences", int((rec_rows["status"] == "differs").sum()),
                    help="Substantive differences between the term sheet and the credit agreement.")
        m[3].metric("Missing from CA", int((rec_rows["status"] == "not_in_ca").sum()))
        m[4].metric("Missing documents", int((df["status"] == "missing_document").sum()))
        m[5].metric("Quotes verified in PDFs", f"{q_found / q_checked:.0%}" if q_checked else "–",
                    help="Share of quoted excerpts found verbatim (normalised) in the source PDF text.")
        if todo:
            st.caption(f"Not yet reconciled with this source: {', '.join(todo)}")

        # Per-deal summary
        summary = []
        for key, d in deals.items():
            if d.status != "complete":
                summary.append({"Deal": key, "Documents": f"Missing {' & '.join(d.missing)}"})
                continue
            if key not in payloads:
                summary.append({"Deal": key, "Documents": "Complete", "Result": "not run"})
                continue
            cnt = results.status_counts(payloads[key])
            mat = sum(1 for r in payloads[key]["rows"] if r.get("status") in ("differs", "not_in_ca") and r.get("materiality") == "material")
            summary.append({"Deal": key, "Documents": "Complete", "Result": "✅",
                            **{status_label(s): cnt.get(s, 0) for s in STATUS_ORDER if s != "missing_document"},
                            "Material differences": mat})
        sdf = pd.DataFrame(summary)
        count_cols = [c for c in sdf.columns if c not in ("Deal", "Documents", "Result")]
        sdf[count_cols] = sdf[count_cols].astype("Int64")
        sdf["Result"] = sdf.get("Result", pd.Series(dtype=str)).fillna("–")
        issue_cols = [status_label(s) for s in ("differs", "not_in_ca", "review")] + ["Material differences"]

        def positive(v) -> bool:
            return not pd.isna(v) and pd.api.types.is_number(v) and v > 0

        def sum_style(row):
            out = []
            for c in row.index:
                if c == "Documents" and str(row[c]).startswith("Missing"):
                    out.append("background-color:#b42318;color:white;font-weight:700")
                elif c in issue_cols and positive(row[c]):
                    out.append("background-color:#fbd5d2;color:#b42318;font-weight:700")
                elif c == status_label("match") and positive(row[c]):
                    out.append("background-color:#d1f2dc;color:#1a7f37")
                else:
                    out.append("")
            return out

        st.dataframe(sdf.style.apply(sum_style, axis=1), hide_index=True, width="stretch")

        st.markdown("##### Attribute heatmap")
        heat = df.copy()
        heat["Attr"] = heat["ID"] + " " + heat["Attribute"].str.slice(0, 28)
        order = [s for s in STATUS_ORDER]
        chart = (
            alt.Chart(heat)
            .mark_rect(stroke="white", strokeWidth=1)
            .encode(
                x=alt.X("Attr:N", title=None, sort=sorted(heat["Attr"].unique()), axis=alt.Axis(labelAngle=-60, labelLimit=180)),
                y=alt.Y("Deal:N", title=None),
                color=alt.Color("Status:N", scale=alt.Scale(domain=[status_label(s) for s in order], range=[HEAT[s] for s in order]),
                                legend=alt.Legend(orient="bottom", columns=5, title=None)),
                tooltip=["Deal", "ID", "Attribute", "Status", alt.Tooltip("TS:N", title="Term sheet"),
                         alt.Tooltip("CA:N", title="Credit agreement"), "Explanation"],
            )
            .properties(height=max(260, 30 * heat["Deal"].nunique()))
        )
        st.altair_chart(chart, width="stretch")


# --------------------------------------------------------------------------- deal detail tab
with tab_deal:
    keys = list(deals)
    default_idx = next((i for i, k in enumerate(keys) if k in payloads), 0)
    key = st.selectbox("Deal", keys, index=default_idx, key="deal_sel")
    d = deals[key]
    left, right = st.columns(2)
    left.markdown(f"**Credit agreement:** {'`' + d.ca.name + '`' if d.ca else '❌ **missing**'}")
    right.markdown(f"**Term sheet:** {'`' + d.ts.name + '`' if d.ts else '❌ **missing**'}")
    if d.status != "complete":
        st.error(f"Cannot reconcile **{key}**: the {' and '.join(d.missing)} is missing. "
                 "Add the missing document to the folder (or upload it in the sidebar) and run the checks.", icon="🚫")
    elif key not in payloads:
        st.info("No results for this deal from the selected source. Run it in **▶️ Run checks**.", icon="ℹ️")
    else:
        p = payloads[key]
        cnt = results.status_counts(p)
        st.markdown("".join(chip(s, f"{status_label(s)}: {n}") for s, n in cnt.items() if n), unsafe_allow_html=True)
        meta = []
        if p.get("generated_at"):
            meta.append(f"generated {p['generated_at']}")
        if p.get("model"):
            meta.append(p["model"])
        if p.get("usd") is not None:
            meta.append(f"API cost ≈ ${p['usd']}")
        if p.get("confidence"):
            meta.append(p["confidence"])
        qc = p.get("quote_check")
        if qc:
            meta.append(f"quotes verified: TS {qc.get('ts_found', 0)}/{qc.get('ts_checked', 0)}, CA {qc.get('ca_found', 0)}/{qc.get('ca_checked', 0)}")
        st.caption(" · ".join(md(m) for m in meta))
        for err in p.get("errors", []):
            st.warning(f"Partial result: {md(err)}")
        if p.get("cost_note"):
            st.caption(md(p["cost_note"]))
        if p.get("document_notes"):
            with st.expander("Document notes", expanded=False):
                st.write(p["document_notes"])

        f1, f2 = st.columns([3, 1])
        chosen = f1.multiselect("Show statuses", [status_label(s) for s in STATUS_ORDER if cnt.get(s)],
                                default=[status_label(s) for s in STATUS_ORDER if cnt.get(s)], key=f"filter_{engine}_{key}")
        only_issues = f2.toggle("Only issues", value=False, key=f"issues_{engine}_{key}")
        frame = rows_frame(p)
        if not frame.empty:
            frame = frame[frame["Status"].isin(chosen)]
            if only_issues:
                frame = frame[frame["Status"].isin([status_label(s) for s in ISSUE_STATUSES])]
            st.dataframe(style_by_status(frame), hide_index=True, width="stretch", height=min(900, 40 + 35 * len(frame)),
                         column_config={"Explanation": st.column_config.TextColumn(width="large"),
                                        "Term sheet says": st.column_config.TextColumn(width="medium"),
                                        "Credit agreement says": st.column_config.TextColumn(width="medium")})
            excel_button("⬇️ Download this deal (Excel)", {key[:31]: frame}, f"{results.slug(key)}_reconciliation.xlsx")

        st.markdown("##### Evidence")
        issue_rows = [r for r in p["rows"] if r.get("status") in ISSUE_STATUSES] if only_issues else p["rows"]
        for r in issue_rows:
            if status_label(r.get("status", "review")) not in chosen:
                continue
            title = f"{r.get('id')} · {CHECKLIST_NAMES.get(r.get('id', ''), r.get('attribute', ''))} — {status_label(r.get('status', 'review'))}"
            with st.expander(title):
                st.markdown(chip(r.get("status", "review")) + " " + html.escape(r.get("explanation", "")), unsafe_allow_html=True)
                a, b = st.columns(2)
                for col, side, name in ((a, "ts", "Term sheet"), (b, "ca", "Credit agreement")):
                    found = r.get(f"{side}_quote_found")
                    badge = {True: "✅ quote found in PDF text", False: "❌ quote NOT found in PDF text", None: "– no quote"}[found]
                    pages = r.get(f"{side}_quote_pages") or []
                    col.markdown(f"**{name}** · {md(r.get(f'{side}_location', ''))}  \n{badge}" + (f" (p. {', '.join(map(str, pages))})" if pages else ""))
                    col.markdown(f"_{md(r.get(f'{side}_value', ''))}_")
                    if r.get(f"{side}_quote"):
                        col.markdown(f'<div class="evidence">{html.escape(r[f"{side}_quote"])}</div>', unsafe_allow_html=True)

        if engine == "rules" and p.get("trace"):
            st.markdown("##### Figure traceability: every number in the term sheet, looked up in the credit agreement")
            tr = pd.DataFrame(p["trace"])
            t1, t2 = st.columns(2)
            only_terms = t1.toggle("Only figures in credit-term context", value=True, key=f"tctx_{key}")
            only_missing = t2.toggle("Only figures NOT found in CA", value=False, key=f"tmiss_{key}")
            if only_terms:
                tr = tr[tr["credit_term_context"]]
            if only_missing:
                tr = tr[~tr["found_in_ca"]]
            found_rate = tr["found_in_ca"].mean() if len(tr) else 0
            st.caption(f"{int(tr['found_in_ca'].sum())} of {len(tr)} figures found in the CA ({found_rate:.0%}).")
            tr = tr.assign(**{"Found in CA": tr["found_in_ca"].map({True: "✅", False: "❌"})}).drop(columns=["found_in_ca", "credit_term_context"])
            st.dataframe(tr.style.apply(lambda row: ["background-color:#fbd5d2" if row["Found in CA"] == "❌" else "" for _ in row], axis=1),
                         hide_index=True, width="stretch",
                         column_config={"context": st.column_config.TextColumn("TS context", width="large"),
                                        "ts_text": "TS text", "normalised": "Normalised", "ts_page": "TS page", "ca_pages": "CA pages", "type": "Type"})


# --------------------------------------------------------------------------- exceptions tab
with tab_exc:
    st.subheader("Exceptions across all deals")
    df = all_rows_frame(payloads)
    if df.empty:
        st.info("No results for this source yet.")
    else:
        e1, e2, e3 = st.columns([2, 2, 1])
        stat_sel = e1.multiselect("Statuses", [status_label(s) for s in ISSUE_STATUSES],
                                  default=[status_label(s) for s in ("differs", "not_in_ca", "missing_document")])
        deal_sel = e2.multiselect("Deals", sorted(df["Deal"].unique()), default=[])
        mat_only = e3.toggle("Material only", value=False)
        ex = df[df["Status"].isin(stat_sel)]
        if deal_sel:
            ex = ex[ex["Deal"].isin(deal_sel)]
        if mat_only:
            ex = ex[ex["Materiality"] == "material"]
        ex = ex.drop(columns=["status"]).rename(columns={"TS": "Term sheet says", "CA": "Credit agreement says"})
        st.caption(f"{len(ex)} exception(s)")
        st.dataframe(style_by_status(ex), hide_index=True, width="stretch", height=min(900, 40 + 35 * max(1, len(ex))),
                     column_config={"Explanation": st.column_config.TextColumn(width="large")})
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Exceptions (CSV)", ex.to_csv(index=False).encode("utf-8-sig"), file_name="ts_ca_exceptions.csv")
        full = df.drop(columns=["status"]).rename(columns={"TS": "Term sheet says", "CA": "Credit agreement says"})
        excel_button("⬇️ Full reconciliation workbook (Excel)", {"Exceptions": ex, "All rows": full}, "ts_ca_reconciliation.xlsx", c2)


# --------------------------------------------------------------------------- run tab
def finalize(engine_name: str, deal: inventory.Deal, payload: dict) -> None:
    ts_p, ca_p = doc_pages(deal.ts), doc_pages(deal.ca)
    payload["quote_check"] = quotes.verify_rows(payload["rows"], ts_p, ca_p)
    results.save(engine_name, deal, payload)


with tab_run:
    runnable = [k for k, d in deals.items() if d.status == "complete"]
    st.subheader("Rules engine (offline, deterministic)")
    st.write("Locates 15 headline terms in both documents (by term-sheet label, CA definition, section heading, pricing table "
             "or cover page), normalises amounts, rates, ratios and dates, and compares them. It also traces every figure in the "
             "term sheet through the whole credit agreement. Instant and free; flags candidates for review.")
    sel_rules = st.multiselect("Deals", runnable, default=runnable, key="rules_sel")
    if st.button("Run rules engine", type="primary", disabled=not sel_rules):
        bar = st.progress(0.0)
        for i, k in enumerate(sel_rules, 1):
            dl = deals[k]
            bar.progress((i - 0.5) / len(sel_rules), text=f"{k}: extracting text and comparing…")
            ts_p, ca_p = doc_pages(dl.ts), doc_pages(dl.ca)
            payload = {"rows": rules.check_deal(ts_p, ca_p, pdftext.extract_layout(dl.ts)), "trace": rules.trace_figures(ts_p, ca_p),
                       "document_notes": ("The term sheet file looks like a lender presentation or slides rather than a formal term sheet; "
                                          "expect more 'review' flags.") if pdftext.looks_like_presentation(ts_p) else ""}
            finalize("rules", dl, payload)
            bar.progress(i / len(sel_rules), text=f"{k}: done")
        st.session_state["flash"] = f"Rules engine finished for {len(sel_rules)} deal(s). Showing rules-engine results."
        st.session_state["engine_next"] = "rules"
        st.rerun()

    st.divider()
    st.subheader("Claude API (full semantic reconciliation)")
    st.write("Sends each term sheet and credit agreement to Claude (`claude-opus-5-5`) and reconciles the 36-attribute checklist "
             "plus every other term the term sheet states, with verbatim quotes and page references. Every quote is then "
             "checked mechanically against the PDF text.")
    key_in = st.text_input("Anthropic API key (optional if ANTHROPIC_API_KEY or an `ant auth login` profile is set)",
                           type="password", value="")
    has_env = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    st.caption("Credentials: " + ("key entered above" if key_in else ("found in environment" if has_env else
               "none in environment; the SDK will try an `ant auth login` profile")))
    sel_llm = st.multiselect("Deals", runnable, default=[], key="llm_sel")
    effort = st.select_slider("Effort", options=["low", "medium", "high", "xhigh"], value="high")
    if sel_llm:
        from recon import llm
        est = [{"Deal": k, **llm.estimate_cost(doc_pages(deals[k].ts), doc_pages(deals[k].ca))} for k in sel_llm]
        edf = pd.DataFrame(est).rename(columns={"input_tokens": "≈ input tokens", "output_tokens": "≈ output tokens", "usd": "≈ USD"})
        st.dataframe(edf, hide_index=True, width="stretch")
        st.caption(f"Estimated total ≈ ${edf['≈ USD'].sum():.2f} (indicative list pricing; actual usage is recorded per deal).")
    if st.button("Run Claude reconciliation", type="primary", disabled=not sel_llm):
        from recon import llm
        for k in sel_llm:
            dl = deals[k]
            with st.status(f"{k}: reconciling with Claude…", expanded=True) as status_box:
                try:
                    t0 = time.time()
                    out = llm.reconcile_deal(doc_pages(dl.ts), doc_pages(dl.ca), k, api_key=key_in or None, effort=effort,
                                             progress=lambda msg: status_box.write(msg))
                    finalize("claude", dl, out)
                    status_box.update(label=f"{k}: done in {time.time() - t0:.0f}s (≈ ${out['usd']})", state="complete", expanded=False)
                except Exception as e:  # surface API / credential errors in the UI
                    status_box.update(label=f"{k}: failed", state="error", expanded=True)
                    st.error(f"{type(e).__name__}: {e}")
        if results.load_all("claude", {k: deals[k] for k in sel_llm}):
            st.button("Show Claude results", on_click=lambda: st.session_state.update(engine="claude"))

    st.divider()
    st.subheader("Agent-verified results (import)")
    st.write("Import the output of the multi-agent reconciliation run (independent reconciler + adversarial verifier per "
             "attribute group). Quotes are re-checked against the PDFs on import.")
    default_json = Path(__file__).parent / "data" / "verified_reconciliation.json"
    up = st.file_uploader("Workflow output JSON", type="json", key="verified_up")
    src = None
    if up is not None:
        src = json.loads(up.getvalue().decode("utf-8-sig"))
    elif default_json.exists():
        st.caption(f"Bundled file found: `data/{default_json.name}`")
    if st.button("Import verified results", disabled=(up is None and not default_json.exists())):
        if src is None:
            src = json.loads(default_json.read_text(encoding="utf-8-sig"))
        unmatched: list[str] = []
        written = results.import_workflow_output(src, deals, unmatched)
        for k in written:
            p = results.load_all("verified", {k: deals[k]}).get(k)
            if p:
                finalize("verified", deals[k], p)
        st.session_state["flash"] = f"Imported agent-verified results for {len(written)} deal(s)." + (
            f" Could not match: {', '.join(unmatched)}." if unmatched else "")
        st.session_state["engine_next"] = "verified"
        st.rerun()

    st.divider()
    st.subheader("Re-check quotes")
    if st.button(f"Re-verify quotes for '{ENGINES[engine]}' against the PDFs", disabled=not payloads):
        for k, p in payloads.items():
            finalize(engine, deals[k], p)
        st.session_state["flash"] = "Quote verification refreshed."
        st.rerun()
