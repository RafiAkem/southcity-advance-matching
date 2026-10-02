"""Asserts for SPEC §7 (expected result) and §7.1 (traps). Plain assert, no framework."""
from datetime import date

from matcher import run, status

advances, matches, unmatched = run()
by_row = {a.row: a for a in advances}

# voucher -> row, from every matched credit
voucher_row: dict[str, int] = {}
for m in matches.values():
    for c in m.credits:
        voucher_row[c.voucher] = m.row

unmatched_vouchers = {c.voucher for c in unmatched}

# SPEC §7 table: row 8..22
# (row, vouchers F, date E, G, H, method)
EXPECTED = [
    (8, "ADV/BK/2604/0004", date(2026, 4, 2), 2_500_000, 0, "po"),
    (9,
     "ADV/BK/2604/0012, ADV/BK/2604/0013, ADV/BK/2604/0014, ADV/BK/2604/0015, "
     "ADV/BK/2604/0016, ADV/BK/2604/0017, ADV/BK/2604/0018, PMT2/BM/2604/0007",
     date(2026, 4, 17), 25_695_900, 0, "phrase"),
    (10, "ADV/BK/2604/0019, ADV/BK/2604/0020, PMT2/BM/2604/0008",
     date(2026, 4, 17), 1_583_700, 0, "phrase"),
    (11, "ADV/BK/2604/0005", date(2026, 4, 2), 1_750_000, 0, "phrase"),
    (12, "ADV/BK/2604/0008", date(2026, 4, 17), 10_355_000, 0, "phrase"),
    (13, "ADV/BK/2604/0007", date(2026, 4, 9), 304_000, 0, "po"),
    (14, "ADV/BK/2604/0003", date(2026, 4, 9), 25_070_000, 0, "po"),
    (15, "BCA1/BM/2604/0069", date(2026, 4, 23), 315_869_963, 107_104_216, "keyword"),
    (16, "ADV/BK/2604/0009", date(2026, 4, 7), 2_790_000, 0, "po"),
    (17, "ADV/BK/2604/0001", date(2026, 4, 7), 3_780_000, 0, "po"),
    (18, "ADV/BK/2604/0006", date(2026, 4, 7), 4_202_100, 0, "phrase"),
    (19, "ADV/BK/2604/0010", date(2026, 4, 14), 6_600_000, -3_300_000, "po"),
    (20, "PMT2/BK/2604/0006", date(2026, 4, 2), 3_500_000, 0, "phrase"),
    (21, "BCA2/BK/2604/0026", date(2026, 4, 1), 60_000_000, 0, "keyword"),
    (22, "PMT2/BM/2604/0006", date(2026, 4, 8), 2_602_000, 0, "phrase"),
]

for row, vouchers, d, g, h, method in EXPECTED:
    m = matches[row]
    adv = by_row[row]
    assert m.vouchers == vouchers, f"row {row} vouchers: {m.vouchers!r} != {vouchers!r}"
    assert m.date == d, f"row {row} date: {m.date!r} != {d!r}"
    assert m.total == g, f"row {row} G: {m.total} != {g}"
    assert adv.amount - m.total == h, f"row {row} H: {adv.amount - m.total} != {h}"
    assert m.method == method, f"row {row} method: {m.method!r} != {method!r}"

# Totals D, G, H (SPEC §7)
total_d = sum(a.amount for a in advances)
total_g = sum(m.total for m in matches.values())
assert total_d == 570_406_879, f"D: {total_d} != 570406879"
assert total_g == 466_602_663, f"G: {total_g} != 466602663"
assert total_d - total_g == 103_804_216, f"H: {total_d - total_g} != 103804216"

# Credit counts and unmatched set
matched_credits = sum(len(m.credits) for m in matches.values())
assert matched_credits == 24, f"matched credits: {matched_credits} != 24"
assert len(unmatched) == 15, f"unmatched: {len(unmatched)} != 15"

expected_unmatched = {
    "BCA2/BM/2604/0003", "PMT2/BM/2604/0004", "PMT2/BM/2604/0005", "PMT2/BM/2604/0009",
    "ADV/BK/2604/0011", "ADV/BK/2604/0021", "ADV/BK/2604/0022", "ADV/BK/2604/0025",
    "ADV/BK/2604/0023", "PMT2/BM/2604/0014", "ADV/BK/2604/0024", "PMT2/BM/2604/0012",
    "PMT2/BM/2604/0013", "ADV/BK/2604/0026", "PMT2/BM/2604/0015",
}
assert unmatched_vouchers == expected_unmatched, (
    f"unmatched vouchers differ: {unmatched_vouchers ^ expected_unmatched}"
)

# Status counts (SPEC §7)
counts = {"Settled": 0, "Outstanding": 0, "Over-settled": 0, "Unsettled": 0}
for a in advances:
    counts[status(a, matches.get(a.row))] += 1
assert counts["Settled"] == 13, f"Settled: {counts['Settled']} != 13"
assert counts["Outstanding"] == 1, f"Outstanding: {counts['Outstanding']} != 1"
assert counts["Over-settled"] == 1, f"Over-settled: {counts['Over-settled']} != 1"
assert counts["Unsettled"] == 0, f"Unsettled: {counts['Unsettled']} != 0"

# §7.1 traps
# T1: "SERAGAM TENAGA KERJA HARIAN" is a substring of "BORDIR SERAGAM ..."
assert voucher_row["ADV/BK/2604/0001"] == 17, f"T1: 0001 -> {voucher_row.get('ADV/BK/2604/0001')}"
assert voucher_row["ADV/BK/2604/0009"] == 16, f"T1: 0009 -> {voucher_row.get('ADV/BK/2604/0009')}"

# T2: GL row 0007 has 2 PO codes (revisi)
assert voucher_row["ADV/BK/2604/0007"] == 13, f"T2: 0007 -> {voucher_row.get('ADV/BK/2604/0007')}"

# T3: Complimentary Maret and April both in GL
assert voucher_row["PMT2/BM/2604/0006"] == 22, f"T3: 2604/0006 -> {voucher_row.get('PMT2/BM/2604/0006')}"
assert "PMT2/BM/2604/0015" in unmatched_vouchers, "T3: 2604/0015 should be unmatched"

# T4: FURNITURE & STYLING ... SM 1132 - IKEA (PO not in WP) -> row 9, not row 8
assert voucher_row["ADV/BK/2604/0012"] == 9, f"T4: 0012 -> {voucher_row.get('ADV/BK/2604/0012')}"
assert voucher_row["ADV/BK/2604/0012"] != 8, "T4: 0012 must not land on row 8"

# T5: DEBET KK/HO/2604/0006 "Styling SM 1127" not in any match
assert "KK/HO/2604/0006" not in voucher_row, "T5: KK/HO/2604/0006 must not be matched"

# T6: Lemari GL 6.6M vs WP 3.3M -> H = -3,300,000, Over-settled, not capped
assert by_row[19].amount - matches[19].total == -3_300_000, "T6: row 19 H"
assert status(by_row[19], matches[19]) == "Over-settled", "T6: row 19 status"

print("all §7 asserts pass")
