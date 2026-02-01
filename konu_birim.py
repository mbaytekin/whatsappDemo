from __future__ import annotations

from dataclasses import dataclass
from typing import List
import logging
import re
import unicodedata
import pandas as pd


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicRow:
    id: int
    konu: str
    birim: str
    match_text: str


def _clean_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.strip().split())


def _normalize_match(text: str) -> str:
    text = _clean_text(text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _parse_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def load_topics(excel_path: str) -> List[TopicRow]:
    """
    Excel'den aktif (Evet) kayıtları çekip TopicRow listesi döndürür.

    Beklenen sütunlar:
      - ID
      - Konu
      - Birim
    Opsiyonel:
      - Aktif  (Evet/Hayır) -> varsa sadece Evet olanları alır
    """
    df = pd.read_excel(excel_path)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"ID", "Konu", "Birim"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Excel'de eksik sütun(lar): {sorted(missing)}. Mevcut sütunlar: {list(df.columns)}"
        )

    if "Aktif" in df.columns:
        active = df["Aktif"].astype(str).str.strip().str.lower()
        df = df[active.isin({"evet", "true", "1", "yes", "aktif"})]

    df = df.dropna(subset=["ID", "Konu", "Birim"]).copy()
    df["Konu"] = df["Konu"].apply(_clean_text)
    df["Birim"] = df["Birim"].apply(_clean_text)

    keyword_columns = [
        "AnahtarKelimeler",
        "Anahtar",
        "Etiketler",
        "Keywords",
        "Keyword",
        "Açıklama",
        "Aciklama",
    ]
    existing_keyword_columns = [c for c in keyword_columns if c in df.columns]

    topics: List[TopicRow] = []
    seen_ids: set[int] = set()
    seen_pairs: set[tuple[str, str]] = set()
    skipped = 0

    for _, r in df.iterrows():
        rid = _parse_int(r["ID"])
        if rid is None:
            skipped += 1
            continue

        konu = _clean_text(r["Konu"])
        birim = _clean_text(r["Birim"])
        if len(konu) < 2 or len(birim) < 2:
            skipped += 1
            continue

        if rid in seen_ids:
            logger.warning("Excel'de tekrar eden ID: %s (ilk kayıt korunuyor).", rid)
            continue

        pair_key = (konu.lower(), birim.lower())
        if pair_key in seen_pairs:
            continue

        extra_parts: list[str] = []
        for col in existing_keyword_columns:
            val = r.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            text = _clean_text(val)
            if text:
                extra_parts.append(text)

        match_source = " ".join([konu, birim] + extra_parts)
        match_text = _normalize_match(match_source) or _normalize_match(konu)

        topics.append(TopicRow(id=rid, konu=konu, birim=birim, match_text=match_text))
        seen_ids.add(rid)
        seen_pairs.add(pair_key)

    if not topics:
        raise ValueError("Excel'den hiç aktif konu bulunamadı (Aktif=Evet).")

    if skipped:
        logger.warning("Excel'den %s satır veri kalitesi nedeniyle atlandı.", skipped)

    return topics
