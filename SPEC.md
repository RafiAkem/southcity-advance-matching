# SPEC — Advances Settlement Matching & Dashboard

Take-home test: Junior AI & Automation Engineer, SouthCity IT.
This file is the source of truth. Code and AI-assistant prompts refer to it by section (for example "SPEC §5").

## 1. Goal

Build a Python tool that:

1. Reads the GL credit (KREDIT) transactions for April 2026.
2. Matches each credit to a row in the Working Paper (WP).
3. Fills WP columns E (Realization Date), F (Realization No. Voucher), and G (Realization Amount). Column H (Saldo) = D − G.
4. Uses an LLM to write an Executive Summary.
5. Writes the results to Google Sheets (`Working_Paper_Result`, `Dashboard`).
6. Shows all results in a Streamlit dashboard.

## 2. Inputs

| File | Sheet | Layout |
|---|---|---|
| `data/GL - Advances Other - April 2026.xls` | `Sheet1` | Row 1 = header: `TANGGAL, NO JURNAL, DESKRIPSI, DEBET-IDR, KREDIT-IDR, SALDO-IDR`. 63 data rows. |
| `data/Working Paper Advances and Prepayment-Soal.xlsx` | `Sheet1` | Header in rows 6–7 (merged cells). Data in **Excel rows 8–22** (15 advances). Columns: A Date, B Voucher No, C Description, D Amount, E–G Realization (empty), H Saldo (`=D-G`), I Description. |

Rules:
- The brief says "Row 6 to 20". That is not correct. The data is in rows 8–22. Find the data rows from the header (`Date` in column A). Do not hardcode the row numbers.
- Use only GL rows where `KREDIT-IDR > 0` (39 rows). Ignore DEBET rows. Example: `KK/HO/2604/0006` is a DEBET of 40,000 with a "Styling SM 1127" description. It is not a settlement.
- Ignore cell A3 (`=#REF!`).

## 3. Outputs

### 3.1 Google Sheet `Working_Paper_Result`
- Copy WP columns A–D and I without changes. Write E, F, and G.
- H = the formula `=D{r}-G{r}`. Do not write a fixed value.
- Add a TOTAL row below the last data row: `=SUM()` for D, G, and H.
- Format: E as `dd-mmm-yyyy`, D/G/H as `#,##0`.

### 3.2 Google Sheet `Dashboard`
- KPI cells as formulas that refer to `Working_Paper_Result`: Total Advance, Total Realization, Total Saldo, and the count of rows for each status.
- Table: rows where saldo ≠ 0, with the status (§6).
- Table: unmatched GL credits (§5.6).
- Cell: the AI Executive Summary text and the time it was made.

### 3.3 Streamlit page (`app.py`)
- Sidebar: file upload for GL and WP (the files in `data/` are the default), model select box (§8), and the buttons **Run Matching**, **Generate AI Summary**, and **Push to Google Sheets**.
- KPI cards: Total Advance, Total Realization, Total Saldo, and the Settled / Outstanding / Over-settled counts.
- WP result table (A–H) with a status color: green = settled, amber = outstanding, red = over-settled.
- Match detail: for each WP row, the vouchers, the method (`po`, `phrase`, `keyword`), and the score.
- Unmatched GL credits table.
- AI Executive Summary panel.

## 4. Data model

```python
@dataclass
class Advance:          # one WP row
    row: int            # Excel row number (8..22)
    date: date
    voucher: str
    desc: str
    amount: int
    po_codes: set[str]

@dataclass
class GLCredit:         # one GL row with KREDIT > 0
    date: date
    voucher: str        # NO JURNAL
    desc: str
    amount: int         # KREDIT-IDR
    po_codes: set[str]

@dataclass
class Match:
    row: int                    # Advance.row
    credits: list[GLCredit]
    method: str                 # "po" | "phrase" | "keyword"
    score: float                # 1.0 for po/keyword

    # derived
    date     -> max(c.date for c in credits)
    vouchers -> ", ".join(c.voucher for c in credits)   # in GL order
    total    -> sum(c.amount for c in credits)
```

Use integers for money (IDR has no decimals). Do not use float.

## 5. Matching rules

### 5.1 Normalization (both sides)
- Change to uppercase. Collapse whitespace.
- Remove the trailing reference `\(P-SDT/[^)]*\)`.
- Remove these leading prefixes: `PENGEMBALIAN KELEBIHAN DANA UM`, `TRANSFER KEKURANGAN DANA UM`, `PELUNASAN TAGIHAN`, `UM`.
- Get the PO/WO codes with the regex `\b[A-Z0-9]+/(?:PO|WO)/\d{8}\b`. Remove them from the phrase text.

### 5.2 Pass 1: PO code
A GL credit matches a WP row if the two have **any** PO code in common.
A GL description can contain more than one code. Example: `FR01/PO/26010011 ... (REVISI PO FR01/PO/26030017)`.

### 5.3 Pass 2: phrase
- Use this pass only for GL credits with no match from Pass 1.
- Compare only with **WP rows that have no PO code**. This stops `FURNITURE & STYLING ... SM 1132` from matching row 8 (Bar Stool).
- Score = token Jaccard of the normalized phrases. Numbers and month names are tokens. They decide matches such as `1132` vs `1127` and `MARET` vs `APRIL`.
- Hard rule: if both sides have a month name, the months must be the same.
- Accept the best WP row if its score ≥ `PHRASE_THRESHOLD = 0.45`. Tested on the data: the lowest true match is 0.50 (`ADV/BK/2604/0012`). The highest wrong candidate is 0.40 (PBB, which Pass 3 handles), then 0.26. A threshold of 0.5 is exactly on the edge, so do not use it.

### 5.4 Pass 3: keyword
For known cases where the phrase is too different. Use a small map in code:

| GL keyword (all required) | WP keyword (all required) |
|---|---|
| `PBB`, `JV 2` | `PBB`, `JV 2` |
| `DROPBOX` | `DROPBOX` |

### 5.5 Multi-voucher settlement: Single Row
If one WP row has more than one credit: F = the vouchers joined with `", "`, G = the sum of the amounts, E = the latest date.
The insert-row option is out of scope (§10).

### 5.6 Unmatched credits
Do not drop GL credits with no match. List them on the Dashboard as "Not in Working Paper (new April advances)".

## 6. Status

| Status | Rule |
|---|---|
| Settled | saldo = 0 |
| Outstanding | saldo > 0 |
| Over-settled | saldo < 0 |
| Unsettled | no match (G empty) |

## 7. Acceptance (expected result)

I checked this table against the GL data by hand. `test_match.py` must assert every row and every total.

| Row | Advance | Vouchers (F) | Date (E) | G | H | Method |
|---|---|---|---|---|---|---|
| 8 | TP01/PO/26010005 Bar Stool | ADV/BK/2604/0004 | 2026-04-02 | 2,500,000 | 0 | po |
| 9 | Styling SM 1132 (2BR) | ADV/BK/2604/0012, 0013, 0014, 0015, 0016, 0017, 0018, PMT2/BM/2604/0007 (8 vouchers) | 2026-04-17 | 25,695,900 | 0 | phrase |
| 10 | Styling SM 1127 (Studio) | ADV/BK/2604/0019, ADV/BK/2604/0020, PMT2/BM/2604/0008 | 2026-04-17 | 1,583,700 | 0 | phrase |
| 11 | Paket Meeting Kirana | ADV/BK/2604/0005 | 2026-04-02 | 1,750,000 | 0 | phrase |
| 12 | Talenta Business Flat | ADV/BK/2604/0008 | 2026-04-17 | 10,355,000 | 0 | phrase |
| 13 | FR01/PO/26010011 Wikipedia | ADV/BK/2604/0007 | 2026-04-09 | 304,000 | 0 | po |
| 14 | FR01/PO/26010007 EO Pameran | ADV/BK/2604/0003 | 2026-04-09 | 25,070,000 | 0 | po |
| 15 | PBB JV 2 Summarecon | BCA1/BM/2604/0069 | 2026-04-23 | 315,869,963 | **107,104,216** | keyword |
| 16 | HLJC/PO/26030003 Bordir Seragam | ADV/BK/2604/0009 | 2026-04-07 | 2,790,000 | 0 | po |
| 17 | HLJC/PO/26030002 Seragam | ADV/BK/2604/0001 | 2026-04-07 | 3,780,000 | 0 | po |
| 18 | Sewa Space Kampung Kecil | ADV/BK/2604/0006 | 2026-04-07 | 4,202,100 | 0 | phrase |
| 19 | TP01/PO/26010003 Lemari Kids Room | ADV/BK/2604/0010 | 2026-04-14 | 6,600,000 | **−3,300,000** | po |
| 20 | Buka Puasa Bersama | PMT2/BK/2604/0006 | 2026-04-02 | 3,500,000 | 0 | phrase |
| 21 | Dropbox (BCA card) | BCA2/BK/2604/0026 | 2026-04-01 | 60,000,000 | 0 | keyword |
| 22 | Complimentary Show Unit **Maret** | PMT2/BM/2604/0006 | 2026-04-08 | 2,602,000 | 0 | phrase |

Totals: D = **570,406,879**, G = **466,602,663**, H = **103,804,216**.
Counts: 39 GL credits = 24 matched + 15 unmatched. Status: 13 Settled, 1 Outstanding (row 15), 1 Over-settled (row 19).

Expected unmatched GL credits (15):
`BCA2/BM/2604/0003, PMT2/BM/2604/0004, PMT2/BM/2604/0005, PMT2/BM/2604/0009, ADV/BK/2604/0011, ADV/BK/2604/0021, ADV/BK/2604/0022, ADV/BK/2604/0025, ADV/BK/2604/0023, PMT2/BM/2604/0014, ADV/BK/2604/0024, PMT2/BM/2604/0012, PMT2/BM/2604/0013, ADV/BK/2604/0026, PMT2/BM/2604/0015`

### 7.1 Traps (each needs one assert)
| # | Trap | Required result |
|---|---|---|
| T1 | "SERAGAM TENAGA KERJA HARIAN" is a substring of "BORDIR SERAGAM ..." | 0001 → row 17, 0009 → row 16 (Pass 1 runs before Pass 2) |
| T2 | GL row 0007 has 2 PO codes (revisi) | → row 13 |
| T3 | Complimentary Maret and April are both in the GL | 2604/0006 → row 22. 2604/0015 is unmatched. |
| T4 | `FURNITURE & STYLING ... SM 1132 - IKEA`, PO not in WP | → row 9, not row 8 |
| T5 | DEBET `KK/HO/2604/0006` "Styling SM 1127" | Not in any match |
| T6 | Lemari: GL 6.6M vs WP 3.3M ("PELUNASAN 50%") | H = −3,300,000, status Over-settled. Do not cap or hide this. |

## 8. AI Executive Summary

- Client: the `[OI]` Python SDK. Two providers, picked by the model id:
  ```
  # router / OpenAI-compatible -> any model id that is not gemini-*
  AI_API_KEY=...
  AI_BASE_URL=https://api.openai.com/v1
  AI_MODEL=gpt-5.6-luna

  # Gemini -> Google AI Studio directly, with its own key (not via the router)
  GEMINI_API_KEY=...
  GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
  GEMINI_MODEL=gemini-2.5-flash
  ```
- `ai.provider(model)` routes on the id: `gemini-*` goes to AI Studio, everything
  else goes to the router. Separate keys on purpose, so one provider being down
  or out of credit does not remove the other option from the dropdown.
- The model select box shows the model name only (`GPT 6 Luna`, `Gemini 2.5
  Flash`), never the provider prefix.
- The code calculates all numbers. The LLM gets only this JSON and must not do any math:
  ```json
  {
    "period": "April 2026",
    "total_advance": 570406879,
    "total_realization": 466602663,
    "total_saldo": 103804216,
    "counts": {"settled": 13, "outstanding": 1, "over_settled": 1, "unsettled": 0},
    "exceptions": [
      {"row": 15, "desc": "...", "amount": 0, "realization": 0, "saldo": 0, "status": "Outstanding"}
    ],
    "unmatched_credits": [{"voucher": "...", "desc": "...", "amount": 0}]
  }
  ```
- Output: Bahasa Indonesia, max 200 words, in 3 parts: (1) Total Advance, (2) Total Realisasi April 2026, (3) Outstanding / anomaly items with one follow-up action each.
- Example follow-up actions for the model:
  - Row 15 PBB: ask Summarecon about the 107.1M shortfall.
  - Row 19 Lemari: check if the 50% DP from an earlier period is in another WP. If not, reclassify the overpayment.
- Settings: `temperature` low. If the API call fails, show the error in the UI and in the Dashboard cell. Do not stop the pipeline. Sheets data must still be written.
- Keys come only from `.env` or Streamlit secrets. `.env` is in `.gitignore`.

## 9. Repo layout

```
README.md          install, test, matching logic, AI-assistant usage
SPEC.md            this file
docs/ai-usage.md   log of prompts and fixes (§11)
data/              the 3 source files
matcher.py         load + normalize + match (§2, §4–§6)
ai.py              summary (§8)
sheets.py          gspread writer (§3.1, §3.2)
app.py             Streamlit (§3.3)
test_match.py      asserts for §7 (plain assert, no framework)
requirements.txt   pandas, xlrd, openpyxl, gspread, openai, streamlit, python-dotenv
.env.example
```

Google auth: a service account JSON (`GOOGLE_SA_JSON`) and `SHEET_ID`. Share the sheet with the service account email. Then set the sheet to "Anyone with the link: Viewer".

## 10. Out of scope
- Insert-row (multi-row) option.
- n8n / Make workflow.
- React or Next.js UI.
- Writing back to SQL Server.
- An LLM for matching. The rules match all 15 rows. LLM parsing can be added later if new descriptions do not match.

## 11. AI coding assistant log

Add an entry to `docs/ai-usage.md` after each task:

```
- Task:     <SPEC section>
  Prompt:   <short>
  AI output:<what it made>
  Problem:  <what was wrong / which test failed>
  Fix:      <what you changed or told it>
```

The README section is a summary of this log: the tools, the workflow (spec → prompt → test → fix), 2–3 good examples, and the parts you wrote by hand.

## 12. Plan

| Day | Work | Done when |
|---|---|---|
| 1 | `matcher.py` and `test_match.py` | All §7 asserts pass |
| 2 | `sheets.py`, `ai.py`, `app.py` | One click in Streamlit fills both sheets and the summary |
| 3 | Deploy to Streamlit Cloud, write README, share the sheet, make the repo public | Reviewer links work in a private browser window |
