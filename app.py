"""Streamlit dashboard (SPEC §3.3). Reads, matches, summarizes, and pushes to Sheets."""
import os
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Advances Matching", layout="wide")

# Copy Streamlit secrets into env so ai.py / sheets.py work on Streamlit Cloud.
# st.secrets raises when there is no secrets file (e.g. local dev with .env only).
try:
    for k, v in st.secrets.items():
        if isinstance(v, str):
            os.environ.setdefault(k, v)
except Exception:
    pass

import ai
import matcher
import sheets


# Model id -> what the reviewer reads. The id is what the API needs; the label
# never carries a provider prefix. Gemini is served by Google AI Studio, the
# rest by the router; ai.py routes on the id.
MODELS = {
    "gh/gpt-6-luna": "GPT 6 Luna",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
}


def label(model_id: str) -> str:
    """Display name for a model id, for anything the user sees."""
    if model_id in MODELS:
        return MODELS[model_id]
    return model_id.split("/")[-1].replace("-", " ").title()


def model_options() -> list[str]:
    """The env model first, then the known options; order kept, duplicates dropped."""
    first = os.getenv("AI_MODEL") or next(iter(MODELS))
    return list(dict.fromkeys([first, *MODELS]))


STATUS_COLORS = {"Settled": "#d4edda", "Outstanding": "#fff3cd", "Over-settled": "#f8d7da"}

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Inputs")
    gl_file = st.file_uploader("GL — Advances Other (April 2026)", type=["xls"])
    wp_file = st.file_uploader("Working Paper (Advances & Prepayment)", type=["xlsx"])
    model = st.selectbox("Model", model_options(), format_func=label)

    st.divider()
    run_btn = st.button("Run Matching", width="stretch")
    ai_btn = st.button("Generate AI Summary", width="stretch")
    push_btn = st.button("Push to Google Sheets", width="stretch")

# ---------------------------------------------------------------- state
if "summary" not in st.session_state:
    st.session_state.summary = ""
if "generated_at" not in st.session_state:
    st.session_state.generated_at = ""

# Run matching on button click, or on first load when no result is in state.
if run_btn or "res" not in st.session_state:
    gl_src = gl_file if gl_file is not None else matcher.GL_PATH
    wp_src = wp_file if wp_file is not None else matcher.WP_PATH
    with st.spinner("Matching GL credits to the Working Paper…"):
        st.session_state.res = matcher.run(gl_src, wp_src)

if ai_btn:
    if "res" not in st.session_state:
        st.warning("Run matching first.")
    else:
        try:
            with st.spinner(f"Generating summary with {label(model)}…"):
                st.session_state.summary = ai.summarize(
                    ai.payload(*st.session_state.res), model
                )
        except Exception as e:  # SPEC §8: show the error, do not stop the pipeline
            st.error(str(e))
            st.session_state.summary = f"AI summary failed: {e}"
        st.session_state.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

if push_btn:
    if "res" not in st.session_state:
        st.warning("Run matching first.")
    else:
        try:
            with st.spinner("Pushing to Google Sheets…"):
                url = sheets.push(
                    *st.session_state.res,
                    st.session_state.summary or "",
                    st.session_state.generated_at or "",
                )
            st.success(f"Pushed to Google Sheets — [{url}]({url})")
        except Exception as e:
            st.error(str(e))

# ---------------------------------------------------------------- main
st.title("Advances Settlement Matching — April 2026")

res = st.session_state.get("res")
if res is None:
    st.info("No result yet. Click **Run Matching** in the sidebar.")
    st.stop()

advances, matches, unmatched = res
data = ai.payload(*res)

# KPI cards — numbers come from ai.payload, never recomputed here.
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Advance", f"{data['total_advance']:,}")
k2.metric("Total Realization", f"{data['total_realization']:,}")
k3.metric("Total Saldo", f"{data['total_saldo']:,}")
k4.metric("Settled", data["counts"]["settled"])
k5.metric("Outstanding", data["counts"]["outstanding"])
k6.metric("Over-settled", data["counts"]["over_settled"])

# ------------------------------------------------ Working Paper result
st.subheader("Working Paper result")
wp_rows = []
for a in advances:
    m = matches.get(a.row)
    real = m.total if m else 0
    wp_rows.append({
        "Row": a.row,
        "Date": a.date,
        "Voucher": a.voucher,
        "Description": a.desc,
        "Amount": a.amount,
        "Real. Date": m.date if m else None,
        "Real. Voucher": m.vouchers if m else None,
        "Real. Amount": real if m else None,
        "Saldo": a.amount - real,
        "Status": matcher.status(a, m),
    })
wp_df = pd.DataFrame(wp_rows)


def color_status(row: pd.Series) -> list[str]:
    bg = STATUS_COLORS.get(row["Status"])
    style = f"background-color: {bg}" if bg else ""
    return [style] * len(row)


wp_styler = (
    wp_df.style.apply(color_status, axis=1)
    .format({"Amount": "{:,}", "Real. Amount": "{:,}", "Saldo": "{:,}"}, na_rep="")
)
st.dataframe(wp_styler, hide_index=True, width="stretch")

# ---------------------------------------------------------------- match detail
st.subheader("Match detail")
match_rows = [
    {
        "Row": a.row,
        "Vouchers": matches[a.row].vouchers,
        "Method": matches[a.row].method,
        "Score": matches[a.row].score,
        "Credits": len(matches[a.row].credits),
    }
    for a in advances
    if a.row in matches
]
st.dataframe(pd.DataFrame(match_rows), hide_index=True, width="stretch")

# ---------------------------------------------------------------- unmatched
st.subheader("Unmatched GL credits — Not in Working Paper (new April advances)")
unmatched_rows = [
    {"Date": c.date, "Voucher": c.voucher, "Description": c.desc, "Amount": c.amount}
    for c in unmatched
]
st.dataframe(pd.DataFrame(unmatched_rows), hide_index=True, width="stretch")

# ---------------------------------------------------------------- AI summary
st.subheader("AI Executive Summary")
if st.session_state.summary:
    if st.session_state.generated_at:
        st.caption(st.session_state.generated_at)
    st.markdown(st.session_state.summary)
else:
    st.info("Click Generate AI Summary")
