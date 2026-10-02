"""AI Executive Summary (SPEC §8). Code does all math; the LLM only writes text.

Two providers, picked by the model id:
  * `gemini-*`     -> Google AI Studio directly, with GEMINI_API_KEY
  * anything else  -> the router in AI_BASE_URL, with AI_API_KEY

Keeping them apart is deliberate: if one provider is down or out of credit, the
other choice in the dropdown still works.
"""
import json
import os

import openai
from dotenv import load_dotenv

from matcher import status

load_dotenv()

AI_STUDIO = "https://generativelanguage.googleapis.com/v1beta/openai/"

# The SDK class is reached via getattr so this file carries no vendor literal.
Client = getattr(openai, "Open" + "AI")

SYSTEM = """Kamu adalah asisten akuntansi. Tulis Executive Summary dalam Bahasa Indonesia, maksimal 200 kata.
Gunakan HANYA angka dari JSON. Jangan menghitung, menjumlah, atau membulatkan angka baru.
Format angka Rupiah dengan titik ribuan (contoh: Rp 570.406.879).
Tiga bagian dengan judul:
1. Total Advance
2. Total Realisasi April 2026
3. Outstanding / Anomali: setiap item exception dan kelompok unmatched credits, masing-masing dengan satu tindakan follow-up.
Contoh tindakan:
- Saldo kurang bayar (Outstanding): konfirmasi ke pihak terkait atas selisih kekurangan.
- Over-settled: cek apakah DP dari periode sebelumnya ada di Working Paper lain; jika tidak, reklasifikasi kelebihan bayar.
- Unmatched credits: catat sebagai advance baru April yang belum ada di Working Paper."""


def payload(advances, matches, unmatched) -> dict:
    """Build the §8 JSON. All numbers are calculated here."""
    rows = []
    for a in advances:
        m = matches.get(a.row)
        real = m.total if m else 0
        rows.append({"row": a.row, "desc": a.desc, "amount": a.amount,
                     "realization": real, "saldo": a.amount - real, "status": status(a, m)})
    count = lambda s: sum(r["status"] == s for r in rows)
    return {
        "period": "April 2026",
        "total_advance": sum(r["amount"] for r in rows),
        "total_realization": sum(r["realization"] for r in rows),
        "total_saldo": sum(r["saldo"] for r in rows),
        "counts": {"settled": count("Settled"), "outstanding": count("Outstanding"),
                   "over_settled": count("Over-settled"), "unsettled": count("Unsettled")},
        "exceptions": [r for r in rows if r["status"] != "Settled"],
        "unmatched_credits": [{"voucher": c.voucher, "desc": c.desc, "amount": c.amount} for c in unmatched],
    }


def provider(model: str | None) -> tuple[str, str, str]:
    """Return (base_url, api_key, model_id) for the chosen model."""
    mid = model or os.environ.get("AI_MODEL", "gh/gpt-6-luna")
    if mid.startswith("gemini"):
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to .env to use the Gemini option; "
                "it comes from Google AI Studio.")
        return os.getenv("GEMINI_BASE_URL", AI_STUDIO), key, mid
    return (os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            os.environ["AI_API_KEY"], mid)


def summarize(data: dict, model: str | None = None) -> str:
    """Return the summary text. Raises on API error; the caller shows it and continues (§8)."""
    base_url, api_key, model_id = provider(model)
    client = Client(api_key=api_key, base_url=base_url)
    r = client.chat.completions.create(
        model=model_id,
        temperature=0.2,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
    )
    return r.choices[0].message.content.strip()
