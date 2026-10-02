"""Write Working_Paper_Result and Dashboard to Google Sheets (SPEC §3.1, §3.2)."""
import json
import math
import os
import re

import gspread
from dotenv import load_dotenv
from gspread.utils import a1_range_to_grid_range, a1_to_rowcol

from matcher import status

load_dotenv()

WP, DASH = "Working_Paper_Result", "Dashboard"
HDR = 6  # header rows 6-7 like the source WP; data keeps its Excel row numbers (8..22)
# ponytail: entity header is fixed for this client; read WP rows 1-4 if other entities use the tool
ENTITY, ACCOUNT, ACCOUNT_NO = "PT. SETIAWAN DWI TUNGGAL", "Uang Muka Pihak Ketiga Lainnya", "110.040.040.000 Advances - Other"

NAVY, INK, MUTED, LINE, PANEL, BAND, WHITE = "#1F3864", "#202124", "#5F6368", "#D9DEE7", "#EEF1F6", "#F8F9FB", "#FFFFFF"
STATUS_STYLE = {  # bg, text
    "Settled": ("#E6F4EA", "#137333"),
    "Outstanding": ("#FEF7E0", "#B06000"),
    "Over-settled": ("#FCE8E6", "#C5221F"),
    "Unsettled": ("#F1F3F4", "#5F6368"),
}
DATE, MONEY, SALDO = "dd-mmm-yyyy", "#,##0", "#,##0;[Red]-#,##0"
STATUS_F = '=IF(G{r}="","Unsettled",IF(H{r}=0,"Settled",IF(H{r}>0,"Outstanding","Over-settled")))'


def rgb(h: str) -> dict:
    return {"red": int(h[1:3], 16) / 255, "green": int(h[3:5], 16) / 255, "blue": int(h[5:7], 16) / 255}


def _mask(d: dict, path: str):
    for k, v in d.items():
        if isinstance(v, dict) and k not in ("backgroundColor", "foregroundColor", "numberFormat"):
            yield from _mask(v, f"{path}.{k}")
        else:
            yield f"{path}.{k}"


class Tab:
    """Values and format requests for one worksheet; sent in one values call + one batch_update."""

    def __init__(self, sid: int):
        self.sid, self.cells, self.reqs = sid, {}, []

    def put(self, a1, *values):
        r, c = a1_to_rowcol(a1)
        for i, v in enumerate(values):
            self.cells[(r, c + i)] = v

    def values(self) -> list[list]:
        rows, cols = max(r for r, _ in self.cells), max(c for _, c in self.cells)
        return [[self.cells.get((r, c), "") for c in range(1, cols + 1)] for r in range(1, rows + 1)]

    def grid(self, a1=None) -> dict:
        return a1_range_to_grid_range(a1, self.sid) if a1 else {"sheetId": self.sid}

    def fmt(self, a1, bg=None, fg=None, size=None, bold=None, italic=None, font=None,
            align=None, valign=None, wrap=False, num=None):
        t = {k: v for k, v in (("foregroundColor", fg and rgb(fg)), ("fontSize", size), ("bold", bold),
                               ("italic", italic), ("fontFamily", font)) if v is not None}
        f = {k: v for k, v in (("backgroundColor", bg and rgb(bg)), ("horizontalAlignment", align),
                               ("verticalAlignment", valign), ("wrapStrategy", wrap and "WRAP")) if v}
        if t:
            f["textFormat"] = t
        if num:
            f["numberFormat"] = {"type": "DATE" if "yy" in num else "PERCENT" if "%" in num else "NUMBER", "pattern": num}
        self.reqs.append({"repeatCell": {"range": self.grid(a1), "cell": {"userEnteredFormat": f},
                                         "fields": ",".join(_mask(f, "userEnteredFormat"))}})

    def merge(self, *a1s):
        self.reqs += [{"mergeCells": {"range": self.grid(a), "mergeType": "MERGE_ALL"}} for a in a1s]

    def border(self, a1, **sides):  # side=(style, hex)
        self.reqs.append({"updateBorders": {"range": self.grid(a1),
                                            **{k: {"style": s, "color": rgb(c)} for k, (s, c) in sides.items()}}})

    def band(self, a1):
        self.reqs.append({"addBanding": {"bandedRange": {"range": self.grid(a1), "rowProperties": {
            "firstBandColor": rgb(WHITE), "secondBandColor": rgb(BAND)}}}})

    def chips(self, a1):
        """Status colors as conditional rules, so they follow the formulas if a value is edited."""
        self.fmt(a1, align="CENTER", bold=True, size=9)
        self.reqs += [{"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [self.grid(a1)], "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": s}]},
            "format": {"backgroundColor": rgb(bg), "textFormat": {"foregroundColor": rgb(fg)}}}}}}
            for s, (bg, fg) in STATUS_STYLE.items()]

    def size(self, dim, start, pixels):  # start = 0-based index
        self.reqs += [{"updateDimensionProperties": {
            "range": {"sheetId": self.sid, "dimension": dim, "startIndex": start + i, "endIndex": start + i + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}} for i, px in enumerate(pixels)]

    def autofit_rows(self, start, end):
        self.reqs.append({"autoResizeDimensions": {"dimensions": {
            "sheetId": self.sid, "dimension": "ROWS", "startIndex": start, "endIndex": end}}})

    def props(self, frozen=0):
        self.reqs.append({"updateSheetProperties": {"properties": {
            "sheetId": self.sid, "tabColorStyle": {"rgbColor": rgb(NAVY)},
            "gridProperties": {"frozenRowCount": frozen, "hideGridlines": True}},
            "fields": "tabColorStyle,gridProperties.frozenRowCount,gridProperties.hideGridlines"}})


def _basis(m) -> str:
    if m is None:
        return ""
    return {"po": "PO code", "keyword": "Keyword rule"}.get(m.method, f"Phrase ({m.score:.2f})" if m.method == "phrase" else m.method)


def build_wp(t: Tab, advances, matches):
    first, last = advances[0].row, advances[-1].row
    tot = last + 1
    t.put("A1", ENTITY)
    t.put("A2", ACCOUNT)
    t.put("A3", f"{ACCOUNT_NO}  ·  Settlement period: April 2026")
    t.put(f"A{HDR}", "Date", "Voucher No", "Description", "Amount", "Realization", "", "", "Saldo",
          "Description", "Status", "Match basis")
    t.put(f"E{HDR + 1}", "Date", "No. Voucher", "Amount")
    for a in advances:
        m, r = matches.get(a.row), a.row
        t.put(f"A{r}", a.date.isoformat(), a.voucher, a.desc, a.amount,
              m.date.isoformat() if m else "", m.vouchers if m else "", m.total if m else "",
              f"=D{r}-G{r}", a.note, STATUS_F.format(r=r), _basis(m))
    t.put(f"A{tot}", "TOTAL", "", "", f"=SUM(D{first}:D{last})", "", "", f"=SUM(G{first}:G{last})",
          f"=SUM(H{first}:H{last})")
    t.put(f"A{tot + 2}", "Saldo = Amount − Realization Amount.   Settled: saldo 0  ·  Outstanding: saldo > 0  ·  "
                         "Over-settled: saldo < 0  ·  Unsettled: no GL credit found.")

    t.fmt(None, font="Arial", size=10, fg=INK, valign="MIDDLE")
    t.fmt("A1", size=14, bold=True, fg=NAVY)
    t.fmt("A2:A3", fg=MUTED)
    t.merge(*(f"{c}{HDR}:{c}{HDR + 1}" for c in "ABCDHIJK"), f"E{HDR}:G{HDR}", f"A{tot}:C{tot}")
    t.fmt(f"A{HDR}:K{HDR + 1}", bg=NAVY, fg=WHITE, bold=True, align="CENTER", wrap=True)
    t.border(f"A{HDR}:K{HDR + 1}", innerVertical=("SOLID", "#3A5488"), innerHorizontal=("SOLID", "#3A5488"))

    body = f"A{first}:K{last}"
    t.band(body)
    t.border(body, innerHorizontal=("SOLID", LINE), bottom=("SOLID", LINE))
    for c in "CFI":
        t.fmt(f"{c}{first}:{c}{last}", wrap=True)
    for c in "AE":
        t.fmt(f"{c}{first}:{c}{last}", num=DATE, align="CENTER")
    for c in "BF":
        t.fmt(f"{c}{first}:{c}{last}", font="Roboto Mono", size=9)
    for c in "DG":
        t.fmt(f"{c}{first}:{c}{tot}", num=MONEY)
    t.fmt(f"H{first}:H{tot}", num=SALDO)
    t.chips(f"J{first}:J{last}")
    t.fmt(f"K{first}:K{last}", fg=MUTED, size=9)

    t.fmt(f"A{tot}:K{tot}", bg=PANEL, bold=True)
    t.fmt(f"A{tot}", align="CENTER")
    t.border(f"A{tot}:K{tot}", top=("SOLID_MEDIUM", NAVY), bottom=("DOUBLE", NAVY))
    t.fmt(f"A{tot + 2}", italic=True, size=9, fg=MUTED)

    t.autofit_rows(first - 1, last)
    t.size("COLUMNS", 0, [95, 135, 330, 115, 95, 260, 115, 115, 140, 110, 130])  # ~1640 px: fits 1080p
    t.size("ROWS", 0, [30])
    t.size("ROWS", HDR - 1, [24, 24])
    t.size("ROWS", tot - 1, [28])
    t.props(frozen=HDR + 1)


def _table(t: Tab, top, title, headers, rows, money="", chip="", wrap="", mono="", total=None) -> int:
    """Section title, navy header, banded body and optional total row from column B. Returns the next free row."""
    end = chr(ord("A") + len(headers))
    t.put(f"B{top}", title)
    t.fmt(f"B{top}", size=12, bold=True, fg=NAVY)
    t.border(f"B{top}:{end}{top}", bottom=("SOLID_MEDIUM", NAVY))
    t.put(f"B{top + 1}", *headers)
    t.fmt(f"B{top + 1}:{end}{top + 1}", bg=NAVY, fg=WHITE, bold=True, align="CENTER")
    rows = rows or [["None"]]
    b0, b1 = top + 2, top + 1 + len(rows)
    for i, row in enumerate(rows, b0):
        t.put(f"B{i}", *row)
    t.band(f"B{b0}:{end}{b1}")
    t.border(f"B{b0}:{end}{b1}", innerHorizontal=("SOLID", LINE), bottom=("SOLID", LINE))
    t.autofit_rows(b0 - 1, b1)
    for c in wrap:
        t.fmt(f"{c}{b0}:{c}{b1}", wrap=True)
    for c in mono:
        t.fmt(f"{c}{b0}:{c}{b1}", font="Roboto Mono", size=9)
    if chip:
        t.chips(f"{chip}{b0}:{chip}{b1}")
    last = b1
    if total:
        last += 1
        t.put(f"B{last}", *total)
        t.fmt(f"B{last}:{end}{last}", bg=PANEL, bold=True)
        t.border(f"B{last}:{end}{last}", top=("SOLID_MEDIUM", NAVY), bottom=("DOUBLE", NAVY))
    for c in money:
        t.fmt(f"{c}{b0}:{c}{last}", num=SALDO)
    return last + 2


def _plain(md: str) -> str:
    """Sheets cells show raw text: drop Markdown marks, keep the structure."""
    s = re.sub(r"\*\*|^#+\s*", "", md or "", flags=re.M)
    return re.sub(r"^\s*[-*]\s+", "•  ", s, flags=re.M).strip()


def build_dash(t: Tab, advances, matches, unmatched, summary: str, generated_at: str):
    first, last = advances[0].row, advances[-1].row
    tot = last + 1
    col = lambda c: f"'{WP}'!{c}{first}:{c}{last}"

    t.put("B2", "Advances Settlement Dashboard")
    t.put("B3", f"{ENTITY}  ·  {ACCOUNT_NO}  ·  April 2026")
    t.put("B6", "TOTAL ADVANCE", "", "TOTAL REALIZATION · APR 2026", "TOTAL SALDO", "", "REALIZATION RATE")
    t.put("B7", f"='{WP}'!D{tot}", "", f"='{WP}'!G{tot}", f"='{WP}'!H{tot}", "", "=IFERROR(D7/B7,0)")

    t.fmt(None, font="Arial", size=10, fg=INK, valign="MIDDLE")
    t.fmt("B2", size=18, bold=True, fg=NAVY)
    t.fmt("B3", fg=MUTED)
    t.merge("B6:C6", "B7:C7", "E6:F6", "E7:F7", "G6:H6", "G7:H7")
    t.fmt("B6:H6", bg=PANEL, fg=MUTED, size=8, bold=True, align="CENTER", valign="BOTTOM")
    t.fmt("B7:H7", bg=PANEL, fg=NAVY, size=18, bold=True, align="CENTER", num=MONEY)
    t.fmt("G7", num="0.0%")
    t.border("B6:H7", innerVertical=("SOLID_THICK", WHITE), top=("SOLID_MEDIUM", NAVY))

    nxt = _table(t, 9, "Settlement status", ["Status", "Rows", "Saldo (IDR)"],
                 [[s, f'=COUNTIF({col("J")},"{s}")', f'=SUMIF({col("J")},"{s}",{col("H")})'] for s in STATUS_STYLE],
                 money="D", chip="B", total=["Total", "=SUM(C11:C14)", "=SUM(D11:D14)"])
    t.fmt("C11:C15", align="CENTER")

    text = _plain(summary) or "Not generated yet. Click Generate AI Summary in the app, then push again."
    t.put(f"B{nxt}", "AI Executive Summary")
    t.put(f"H{nxt}", f"Generated {generated_at}" if generated_at else "")
    t.put(f"B{nxt + 1}", text)
    t.fmt(f"B{nxt}", size=12, bold=True, fg=NAVY)
    t.fmt(f"H{nxt}", italic=True, size=9, fg=MUTED, align="RIGHT")
    t.border(f"B{nxt}:H{nxt}", bottom=("SOLID_MEDIUM", NAVY))
    t.merge(f"B{nxt + 1}:H{nxt + 1}")
    t.fmt(f"B{nxt + 1}", bg=BAND, wrap=True, valign="TOP")
    t.border(f"B{nxt + 1}:H{nxt + 1}", left=("SOLID_THICK", NAVY), bottom=("SOLID", LINE))
    # merged cells do not auto-fit: B:H is ~1160 px, about 170 Arial-10 chars per line
    lines = sum(max(1, math.ceil(len(x) / 170)) for x in text.split("\n"))
    summary_row = nxt  # 0-based index of the text row
    nxt += 3

    exc = []
    for a in advances:
        m = matches.get(a.row)
        real = m.total if m else 0
        if a.amount != real:
            exc.append([a.row, a.voucher, a.desc, a.amount, real, a.amount - real, status(a, m)])
    nxt = _table(t, nxt, f"Exceptions: saldo ≠ 0  ({len(exc)})",
                 ["WP row", "Voucher", "Description", "Advance", "Realization", "Saldo", "Status"],
                 exc, money="EFG", chip="H", wrap="D", mono="C")
    t.fmt(f"B{nxt - len(exc or [0]) - 2}:B{nxt - 2}", align="CENTER")

    top = nxt
    un = [[c.date.isoformat(), c.voucher, c.desc, c.amount] for c in unmatched]
    nxt = _table(t, top, f"Not in Working Paper: new April advances  ({len(un)})",
                 ["Date", "Voucher", "Description", "Amount"], un, money="E", wrap="D", mono="C",
                 total=["", "", f"Total ({len(un)} GL credits)",
                        f"=SUM(E{top + 2}:E{top + 1 + max(len(un), 1)})"])
    t.fmt(f"B{top + 2}:B{top + 1 + len(un)}", num=DATE, align="CENTER")
    t.put(f"B{nxt}", f"KPI and status figures are live formulas on '{WP}'.")
    t.fmt(f"B{nxt}", italic=True, size=9, fg=MUTED)

    t.size("COLUMNS", 0, [24, 115, 175, 340, 135, 135, 135, 125])
    t.size("ROWS", 0, [16, 34, 22])
    t.size("ROWS", 5, [26, 48])
    t.size("ROWS", summary_row, [16 * lines + 24])
    t.props()


def _client() -> gspread.Client:
    """Service account from a JSON file path, or from inline JSON (Streamlit secrets)."""
    sa = os.environ["GOOGLE_SA_JSON"]
    if sa.lstrip().startswith("{"):
        return gspread.service_account_from_dict(json.loads(sa))
    return gspread.service_account(filename=sa)


def _reset(book, meta, title, rows, cols, index) -> gspread.Worksheet:
    """Empty, unformatted tab. Keeps the tab id, so shared links to the tab stay valid."""
    old = next((s for s in meta["sheets"] if s["properties"]["title"] == title), None)
    if old is None:
        return book.add_worksheet(title, rows, cols, index)
    sid = old["properties"]["sheetId"]
    reqs = [{"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}} for b in old.get("bandedRanges", [])]
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}} for _ in old.get("conditionalFormats", [])]
    reqs += [
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "*"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "index": index, "gridProperties": {
            "rowCount": rows, "columnCount": cols, "frozenRowCount": 0}},
            "fields": "index,gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount"}},
    ]
    book.batch_update({"requests": reqs})
    return book.get_worksheet_by_id(sid)


def push(advances, matches, unmatched, summary: str, generated_at: str) -> str:
    book = _client().open_by_key(os.environ["SHEET_ID"])
    meta = book.fetch_sheet_metadata({"fields": "sheets(properties,bandedRanges,conditionalFormats)"})

    ws = _reset(book, meta, WP, advances[-1].row + 4, 11, 1)
    wp = Tab(ws.id)
    build_wp(wp, advances, matches)
    ws.update(wp.values(), "A1", value_input_option="USER_ENTERED")

    rows = 40 + len(advances) + len(unmatched)
    ds = _reset(book, meta, DASH, rows, 8, 0)
    dash = Tab(ds.id)
    build_dash(dash, advances, matches, unmatched, summary, generated_at)
    ds.update(dash.values(), "A1", value_input_option="USER_ENTERED")

    book.batch_update({"requests": wp.reqs + dash.reqs})
    for w in book.worksheets():  # drop the blank default tab
        if w.title == "Sheet1" and not w.get_all_values():
            book.del_worksheet(w)
    return book.url
