from __future__ import annotations

from typing import List, Optional
from dataclasses import dataclass
import logging
import os

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from pydantic import BaseModel, Field

from google import genai

from konu_birim import TopicRow

logger = logging.getLogger(__name__)

class RouteResult(BaseModel):
    matched: bool = Field(description="Eşleşme bulunup bulunmadığı.")
    topic_id: Optional[int] = Field(default=None, description="Seçilen konu ID")
    topic: Optional[str] = Field(default=None, description="Seçilen konu adı")
    unit: Optional[str] = Field(default=None, description="İlgili birim")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 güven skoru")
    clarification_question: Optional[str] = Field(
        default=None,
        description="Eşleşme zayıfsa vatandaşa sorulacak netleştirici soru",
    )


@dataclass
class Candidate:
    id: int
    konu: str
    birim: str
    score: float


@dataclass
class RouteDecision:
    result: RouteResult
    options: List[Candidate]


class TopicRouter:

    def __init__(
        self,
        topics: List[TopicRow],
        model: str = "gemini-2.5-flash",
        top_k: int = 8,
        min_confidence: float = 0.55,
        min_score: float = 0.18,
        ambiguous_gap: float = 0.05,
        use_gemini: bool = True,
    ):
        self.topics = topics
        self.model = model
        self.top_k = top_k
        self.min_confidence = min_confidence
        self.min_score = min_score
        self.ambiguous_gap = ambiguous_gap
        self.use_gemini = use_gemini

        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
        )
        self.topic_texts = [t.match_text or t.konu for t in topics]
        self.topic_matrix = self.vectorizer.fit_transform(self.topic_texts)

        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if use_gemini and not api_key:
            logger.warning("GOOGLE_API_KEY bulunamadı; Gemini devre dışı, TF-IDF fallback kullanılıyor.")
            self.use_gemini = False

        self.client = genai.Client() if self.use_gemini else None

    def _candidates(self, text: str) -> List[Candidate]:
        q = self.vectorizer.transform([text])
        sims = cosine_similarity(q, self.topic_matrix).ravel()
        idxs = sims.argsort()[::-1][: self.top_k]

        out: List[Candidate] = []
        for i in idxs:
            t = self.topics[int(i)]
            out.append(Candidate(id=t.id, konu=t.konu, birim=t.birim, score=float(sims[int(i)])))
        return out

    def route(self, user_text: str) -> RouteDecision:
        if len(user_text.strip()) < 4:
            result = RouteResult(
                matched=False,
                topic_id=None,
                topic=None,
                unit=None,
                confidence=0.0,
                clarification_question=None,
            )
            return RouteDecision(result=result, options=[])

        letters = sum(1 for ch in user_text if ch.isalpha())
        if letters >= 4:
            vowels = "aeiouıİöÖüÜoOeEaAıIuU"
            vowel_count = sum(1 for ch in user_text if ch in vowels)
            if vowel_count == 0:
                result = RouteResult(
                    matched=False,
                    topic_id=None,
                    topic=None,
                    unit=None,
                    confidence=0.0,
                    clarification_question=None,
                )
                return RouteDecision(result=result, options=[])

        candidates = self._candidates(user_text)
        if not candidates:
            result = RouteResult(
                matched=False,
                topic_id=None,
                topic=None,
                unit=None,
                confidence=0.0,
                clarification_question=None,
            )
            return RouteDecision(result=result, options=[])

        best = candidates[0]
        if best.score < self.min_score:
            result = RouteResult(
                matched=False,
                topic_id=None,
                topic=None,
                unit=None,
                confidence=float(best.score),
                clarification_question=None,
            )
            return RouteDecision(result=result, options=[])

        if not self.use_gemini:
            conf = min(0.95, max(0.2, best.score))
            result = RouteResult(
                matched=True,
                topic_id=best.id,
                topic=best.konu,
                unit=best.birim,
                confidence=conf,
                clarification_question=None,
            )
            return RouteDecision(result=result, options=[])

        cand_lines = "\n".join([f"- {c.id} | {c.konu} | {c.birim}" for c in candidates])

        prompt = f"""\
Sen Sultangazi Belediyesi Kamu Destek Hattı yönlendirme asistanısın.
Görevin: Vatandaşın mesajını aşağıdaki aday konular arasından EN UYGUN olan ile eşleştirip ilgili birimi dönmek.

Kurallar:
- Sadece aşağıdaki adaylardan seçim yap.
- Emin değilsen de en yakın olanı seç (matched=true) ve confidence düşük ver.
- confidence 0.0-1.0 arası olsun.

Vatandaş mesajı:
{user_text}

Adaylar (ID | Konu | Birim):
{cand_lines}
"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": RouteResult,
                "temperature": 0.2,
            },
        )

        parsed = getattr(response, "parsed", None)
        if parsed is None:
            # SDK'nın text döndürdüğü durumlar için robust parse
            try:
                parsed = RouteResult.model_validate_json(response.text)
            except Exception:
                logger.warning("Gemini JSON parse başarısız; text fallback deneniyor.")
                txt = (response.text or "").strip()
                start = txt.find("{")
                end = txt.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = RouteResult.model_validate_json(txt[start : end + 1])
                else:
                    # Tamamen bozulduysa TF-IDF ile dön
                    logger.warning("Gemini response tamamen bozuldu; TF-IDF fallback kullanıldı.")
                    best = candidates[0]
                    result = RouteResult(
                        matched=True,
                        topic_id=best.id,
                        topic=best.konu,
                        unit=best.birim,
                        confidence=min(0.6, max(0.2, best.score)),
                        clarification_question=None,
                    )
                    return RouteDecision(result=result, options=[])

        result: RouteResult = parsed

        # ID doğrula ve birimi Excel'den otorite olarak çek
        tmap = {t.id: t for t in self.topics}
        if result.matched and result.topic_id in tmap and float(result.confidence) >= self.min_confidence:
            t = tmap[result.topic_id]
            result = RouteResult(
                matched=True,
                topic_id=t.id,
                topic=t.konu,
                unit=t.birim,
                confidence=float(result.confidence),
                clarification_question=None,
            )
            return RouteDecision(result=result, options=[])

        # Belirsizse/uygunsuzsa: en iyi adayı geri ver
        best = candidates[0]
        result = RouteResult(
            matched=True,
            topic_id=best.id,
            topic=best.konu,
            unit=best.birim,
            confidence=min(0.6, max(0.2, best.score)),
            clarification_question=None,
        )
        return RouteDecision(result=result, options=[])
