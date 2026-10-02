"""Write Working_Paper_Result and Dashboard to Google Sheets (SPEC §3.1, §3.2)."""
import json
import re
import os

import gspread
from dotenv import load_dotenv

from matcher import status

load_dotenv()

WP, DASH = "Working_Paper_Result", "Dashboard"
HDR = 6  # header rows 6-7 like the source WP; data keeps its Excel row numbers (8..22)


def wp_grid(advances, matches) -> list[list]:
    """Rows 1..TOTAL for Working_Paper_Result. Row r of the list = sheet row r+1."""
    last = advances[-1].row
    grid = [[""] * 9 for _ in range(last + 1)]
    grid[0][0] = "Advances - Other: settlement result April 2026"
    grid[HDR - 1] = ["Date", "Voucher No", "Description", "Amount", "Realization", "", "", "Saldo", "Description"]
    grid[HDR] = ["", "", "", "", "Date", "No. Voucher", "Amount", "", ""]
    for a in advances:
        m = matches.get(a.row)
        r = a.row
        grid[r - 1] = [a.date.isoformat(), a.voucher, a.desc, a.amount,
                       m.date.isoformat() if m else "", m.vouchers if m else "", m.total if m else "",
                       f"=D{r}-G{r}", a.note]
    first = advances[0].row
    grid[last] = ["TOTAL", "", "", f"=SUM(D{first}:D{last})", "", "", f"=SUM(G{first}:G{last})",
                  f"=SUM(H{first}:H{last})", ""]
    return grid


def dash_grid(advances, matches, unmatched, summary: str, generated_at: str) -> list[list]:
    first, last = advances[0].row, advances[-1].row
    tot = last + 1
    g, h = f"'{WP}'!G{first}:G{last}", f"'{WP}'!H{first}:H{last}"
    rows = [
        ["Dashboard: Advances Other, April 2026"],
        [],
        ["Total Advance", f"='{WP}'!D{tot}"],
        ["Total Realization", f"='{WP}'!G{tot}"],
        ["Total Saldo", f"='{WP}'!H{tot}"],
        ["Settled", f'=COUNTIFS({g},"<>",{h},0)'],
        ["Outstanding", f'=COUNTIFS({g},"<>",{h},">0")'],
        ["Over-settled", f'=COUNTIFS({h},"<0")'],
        ["Unsettled", f"=COUNTBLANK({g})"],
        [],
        ["AI Executive Summary", f"Generated: {generated_at}" if generated_at else ""],
        [re.sub(r"\*\*|^#+\s*", "", summary, flags=re.M) or "(not generated)"],  # plain text cell
        [],
        ["Exceptions (saldo ≠ 0)"],
        ["Row", "Description", "Amount", "Realization", "Saldo", "Status"],
    ]
    for a in advances:
        m = matches.get(a.row)
        real = m.total if m else 0
        if a.amount - real:
            rows.append([a.row, a.desc, a.amount, real, a.amount - real, status(a, m)])
    rows += [[], ["Not in Working Paper (new April advances)"], ["Date", "Voucher", "Description", "Amount"]]
    rows += [[c.date.isoformat(), c.voucher, c.desc, c.amount] for c in unmatched]
    return rows


def _client() -> gspread.Client:
    """Service account from a JSON file path, or from inline JSON (Streamlit secrets)."""
    sa = os.environ["GOOGLE_SA_JSON"]
    if sa.lstrip().startswith("{"):
        return gspread.service_account_from_dict(json.loads(sa))
    return gspread.service_account(filename=sa)


def _sheet(book, title, rows, cols):
    try:
        ws = book.worksheet(title)
        ws.clear()
        book.batch_update({"requests": [{"repeatCell": {  # drop old formats too
            "range": {"sheetId": ws.id}, "cell": {}, "fields": "userEnteredFormat"}}]})
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title, rows, cols)
    return ws


def push(advances, matches, unmatched, summary: str, generated_at: str) -> str:
    book = _client().open_by_key(os.environ["SHEET_ID"])

    wp = wp_grid(advances, matches)
    ws = _sheet(book, WP, len(wp) + 5, 9)
    ws.update(wp, "A1", value_input_option="USER_ENTERED")
    first, tot = advances[0].row, len(wp)
    date_fmt = {"numberFormat": {"type": "DATE", "pattern": "dd-mmm-yyyy"}}
    num_fmt = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}
    ws.batch_format([
        {"range": f"A{first}:A{tot}", "format": date_fmt},
        {"range": f"E{first}:E{tot}", "format": date_fmt},
        {"range": f"D{first}:D{tot}", "format": num_fmt},
        {"range": f"G{first}:H{tot}", "format": num_fmt},
        {"range": f"A{HDR}:I{HDR + 1}", "format": {"textFormat": {"bold": True}}},
        {"range": f"A{tot}:I{tot}", "format": {"textFormat": {"bold": True}}},
    ])

    dash = dash_grid(advances, matches, unmatched, summary, generated_at)
    ds = _sheet(book, DASH, len(dash) + 5, 6)
    ds.update(dash, "A1", value_input_option="USER_ENTERED")
    ds.batch_format([
        {"range": "B3:B5", "format": num_fmt},
        {"range": "A12", "format": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
        {"range": "C15:E100", "format": num_fmt},
    ])
    ds.merge_cells("A12:F12")
    return book.url
