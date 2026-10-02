"""Load GL + Working Paper, normalize, match (SPEC §2, §4–§6)."""
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

PHRASE_THRESHOLD = 0.45  # SPEC §5.3
PO_RE = re.compile(r"\b[A-Z0-9]+/(?:PO|WO)/\d{8}\b")
REF_RE = re.compile(r"\(P-SDT/[^)]*\)\s*$")
PREFIX_RE = re.compile(
    r"^(?:PENGEMBALIAN KELEBIHAN DANA UM|TRANSFER KEKURANGAN DANA UM|PELUNASAN TAGIHAN|UM)\b\s*"
)
MONTHS = {"JANUARI", "FEBRUARI", "MARET", "APRIL", "MEI", "JUNI", "JULI",
          "AGUSTUS", "SEPTEMBER", "OKTOBER", "NOVEMBER", "DESEMBER"}
KEYWORDS = [({"PBB", "JV 2"}, {"PBB", "JV 2"}), ({"DROPBOX"}, {"DROPBOX"})]  # SPEC §5.4


@dataclass
class Advance:
    row: int
    date: date
    voucher: str
    desc: str
    amount: int
    po_codes: set[str] = field(default_factory=set)
    note: str = ""  # WP column I, copied unchanged to the result sheet


@dataclass
class GLCredit:
    date: date
    voucher: str
    desc: str
    amount: int
    po_codes: set[str] = field(default_factory=set)


@dataclass
class Match:
    row: int
    credits: list[GLCredit]
    method: str
    score: float

    @property
    def date(self) -> date:
        return max(c.date for c in self.credits)

    @property
    def vouchers(self) -> str:
        return ", ".join(c.voucher for c in self.credits)

    @property
    def total(self) -> int:
        return sum(c.amount for c in self.credits)


def normalize(text: str) -> tuple[str, set[str]]:
    """Return (phrase, po_codes). SPEC §5.1."""
    s = " ".join(str(text).upper().split())
    s = REF_RE.sub("", s)
    codes = set(PO_RE.findall(s))
    s = " ".join(PO_RE.sub(" ", s).split())
    return PREFIX_RE.sub("", s), codes


def tokens(phrase: str) -> set[str]:
    return set(re.findall(r"\w+", phrase))


def jaccard(a: set[str], b: set[str]) -> float:
    if (a & MONTHS) and (b & MONTHS) and (a & MONTHS) != (b & MONTHS):
        return 0.0  # hard month rule
    return len(a & b) / len(a | b) if a | b else 0.0


def _day(v) -> date:
    return pd.Timestamp(v).date()


def load_gl(src) -> list[GLCredit]:
    df = pd.read_excel(src, sheet_name="Sheet1")
    out = []
    for r in df[df["KREDIT-IDR"] > 0].itertuples(index=False):
        _, codes = normalize(r[2])
        out.append(GLCredit(_day(r[0]), str(r[1]).strip(), str(r[2]).strip(), int(r[4]), codes))
    return out


def load_wp(src) -> list[Advance]:
    df = pd.read_excel(src, sheet_name="Sheet1", header=None)
    hdr = df.index[df[0].astype(str).str.strip() == "Date"][0]
    out = []
    for i in range(hdr + 1, len(df)):
        a, b, c, d = df.iloc[i, :4]
        if pd.isna(a) or pd.isna(d):
            continue  # second header row / blanks
        _, codes = normalize(c)
        note = df.iloc[i, 8] if df.shape[1] > 8 and pd.notna(df.iloc[i, 8]) else ""
        out.append(Advance(i + 1, _day(a), str(b).strip(), str(c).strip(), int(d), codes, str(note)))
    return out


def match(advances: list[Advance], credits: list[GLCredit]) -> tuple[dict[int, Match], list[GLCredit]]:
    """Return ({row: Match}, unmatched credits). Credits keep GL order inside each Match."""
    hits: dict[int, tuple[str, float]] = {}  # credit index -> (row, method, score)
    phr = {a.row: tokens(normalize(a.desc)[0]) for a in advances}

    for i, c in enumerate(credits):  # Pass 1: PO
        a = next((a for a in advances if a.po_codes & c.po_codes), None)
        if a:
            hits[i] = (a.row, "po", 1.0)

    no_po = [a for a in advances if not a.po_codes]
    for i, c in enumerate(credits):  # Pass 2: phrase
        if i in hits or not no_po:
            continue
        t = tokens(normalize(c.desc)[0])
        score, a = max(((jaccard(t, phr[a.row]), a) for a in no_po), key=lambda x: x[0])
        if score >= PHRASE_THRESHOLD:
            hits[i] = (a.row, "phrase", round(score, 2))

    for i, c in enumerate(credits):  # Pass 3: keyword
        if i in hits:
            continue
        up = " ".join(c.desc.upper().split())
        for gl_kw, wp_kw in KEYWORDS:
            if all(k in up for k in gl_kw):
                a = next((a for a in advances if all(k in a.desc.upper() for k in wp_kw)), None)
                if a:
                    hits[i] = (a.row, "keyword", 1.0)
                    break

    matches: dict[int, Match] = {}
    for i, (row, method, score) in hits.items():
        m = matches.setdefault(row, Match(row, [], method, score))
        m.credits.append(credits[i])
        m.score = min(m.score, score)
        if method != m.method:
            m.method = f"{m.method}+{method}"  # ponytail: mixed methods per row are not in the data; shown as joined
    for m in matches.values():
        m.credits.sort(key=credits.index)
    return matches, [c for i, c in enumerate(credits) if i not in hits]


def status(advance: Advance, m: Match | None) -> str:
    """SPEC §6."""
    if m is None:
        return "Unsettled"
    saldo = advance.amount - m.total
    return "Settled" if saldo == 0 else "Outstanding" if saldo > 0 else "Over-settled"


GL_PATH = "data/GL - Advances Other - April 2026.xls"
WP_PATH = "data/Working Paper Advances and Prepayment-Soal.xlsx"


def run(gl_src=GL_PATH, wp_src=WP_PATH):
    advances = load_wp(wp_src)
    matches, unmatched = match(advances, load_gl(gl_src))
    return advances, matches, unmatched
