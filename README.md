# Advances Settlement Matching & Dashboard

Take-home test, Junior AI & Automation Engineer, SouthCity IT.
Python tool that matches April 2026 GL credits to the Advances Working Paper, fills columns E–H, writes an AI Executive Summary, and pushes everything to Google Sheets. Full requirements: [SPEC.md](SPEC.md).

- Google Sheet (view): https://docs.google.com/spreadsheets/d/1S-WdI8w8uxqCaZFxh7H_PAvYexSPDbH5DjW3V67ISdc
- Sheets: `Working_Paper_Result` (columns A–I, H and TOTAL as formulas) and `Dashboard` (KPI formulas, exceptions, unmatched credits, AI summary)

## Install

Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in the values
```

| Variable | Use |
|---|---|
| `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL` | Any OpenAI-compatible endpoint (OpenAI, Gemini free tier, a router). Change provider with env only. |
| `GOOGLE_SA_JSON` | Path to the service-account JSON file, or the JSON text itself (for Streamlit secrets). |
| `SHEET_ID` | ID from the sheet URL. Share the sheet with the service-account email as Editor. |

## Test and run

```bash
python test_match.py        # asserts every row, total, and trap in SPEC §7 -> "all §7 asserts pass"
streamlit run app.py        # Run Matching -> Generate AI Summary -> Push to Google Sheets
```

The matcher also works without Streamlit:

```python
import matcher, sheets, ai
adv, matches, unmatched = matcher.run()
summary = ai.summarize(ai.payload(adv, matches, unmatched))
sheets.push(adv, matches, unmatched, summary, "2026-04-30 17:00")
```

## Files

| File | Job |
|---|---|
| `matcher.py` | Load GL + WP, normalize, 3-pass matching, status |
| `ai.py` | Build the summary JSON (all numbers calculated in code), call the LLM |
| `sheets.py` | Write `Working_Paper_Result` and `Dashboard` with gspread |
| `app.py` | Streamlit dashboard |
| `test_match.py` | Plain-assert acceptance test for SPEC §7 |

`data/` holds the two source files and the brief that SouthCity sent with this
test, kept here so the pipeline runs end to end without any setup. They are the
inputs of the exercise only; no other data from the company is in this repo.

## Matching logic

Rule-based: regex + token similarity. No LLM in the matching, so the result is the same on every run and every match can be explained.

1. **Load.** GL: only rows with `KREDIT-IDR > 0` (39 rows). DEBET rows are new advances, not settlements. WP: the header row is found by `Date` in column A, so the data rows are found, not hardcoded. The brief says "Row 6 to 20", but the data is in rows 8–22.
2. **Normalize** both descriptions: uppercase, one space, remove the `(P-SDT/...)` reference, remove prefixes such as `PENGEMBALIAN KELEBIHAN DANA UM` and `UM`. Extract PO/WO codes with `\b[A-Z0-9]+/(?:PO|WO)/\d{8}\b`.
3. **Pass 1, PO code.** A credit matches a WP row that has any PO code in common. One GL row can have two codes (`... REVISI PO FR01/PO/26030017`).
4. **Pass 2, phrase.** Only for credits with no match in Pass 1, and only against WP rows with no PO code. Score = Jaccard similarity of the word tokens. Numbers and month names are tokens, so `SM 1132` ≠ `SM 1127`. If both sides have a month, the months must be the same (`MARET` ≠ `APRIL`). Accept when score ≥ 0.45: the lowest true match is 0.50, the highest wrong candidate is 0.40.
5. **Pass 3, keyword.** Two known cases where the text is too different: `PBB` + `JV 2`, and `DROPBOX`.
6. **Multi-voucher (Single Row option).** F = vouchers joined with `, `, G = sum, E = latest date. Row 9 (Styling SM 1132) has 8 vouchers.
7. **Unmatched credits** are not dropped. They go to the Dashboard as "Not in Working Paper (new April advances)" (15 credits).

Status: Settled (saldo 0), Outstanding (> 0), Over-settled (< 0), Unsettled (no match).

Result: 15/15 rows matched. 24 credits matched, 15 not in the WP. 13 Settled, 1 Outstanding (row 15, PBB JV 2: 107,104,216), 1 Over-settled (row 19, Lemari: −3,300,000, shown as is, not capped).

Traps covered by the test: Pass 1 runs before Pass 2, so `SERAGAM ...` does not match `BORDIR SERAGAM ...`; the 2-PO revision row; the Complimentary Maret vs April rows; the IKEA PO that is not in the WP; the DEBET row with a "Styling SM 1127" text; the over-settled Lemari row.

## AI Executive Summary

The code calculates every number and sends only a small JSON (totals, counts, exceptions, unmatched credits) to the LLM. The LLM only writes the text: Bahasa Indonesia, max 200 words, 3 parts, one follow-up action for each exception. Temperature is low. If the API call fails, the error is shown in the app and written to the Dashboard cell, and the sheet data is still written.

## AI coding assistant usage

Full log: [docs/ai-usage.md](docs/ai-usage.md).

**Tools.** Claude Opus in the omp coding harness for the matching engine, the Sheets writer, and review. A cheaper DeepSeek V4.1 Flash subagent for the well-specified parts (`test_match.py`, `app.py`, `requirements.txt`, `.env.example`).

**Workflow: spec → prompt → test → fix.**
1. I wrote [SPEC.md](SPEC.md) first. I checked the expected result (SPEC §7) against the GL data by hand: every row, total, and trap.
2. Each prompt points to a SPEC section, for example "implement matcher.py from SPEC §2, §4–§6".
3. `test_match.py` asserts the §7 table. A change is done only when it passes.
4. I checked the UI in a browser and read the Google Sheet values back after a push.

**Good examples.**
- The phrase threshold. Testing the scores on the data showed the lowest true match is 0.50, so 0.5 is exactly on the edge. The spec uses 0.45.
- The flash subagent made the test table from SPEC §7 in one pass. I gave it the exact table and the module API, and told it not to change the expected values if a test failed.
- The AI-generated `app.py` used `use_container_width`, which Streamlit deprecates. I found it in the server log and changed it to `width="stretch"`.

**Done by hand.** The SPEC, the hand-checked expected results, the match rules and the threshold, the choice to keep the LLM out of matching, and the review of every AI output against the tests and the live sheet.
