from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
import re

from router import TopicRouter, RouteDecision


CATEGORY_OPTIONS = (
    "1) İstek ve Şikayet\n"
    "2) Bilgi/Hizmetler (yakında)\n"
    "3) E-Belediye (yakında)"
)

CATEGORY_PROMPT = (
    "Sultangazi Belediyesi Kamu Destek Hattına hoş geldiniz.\n"
    "Size nasıl yardımcı olalım?\n"
    f"{CATEGORY_OPTIONS}\n\n"
    "Lütfen 1, 2 veya 3 yazın."
)

REQUEST_SELECTED = "İstek ve Şikayet seçildi. Lütfen talebinizi yazın."

@dataclass
class Session:
    stage: str  # "awaiting_category" | "awaiting_request" | "awaiting_details"
    last_seen: datetime
    last_unit: Optional[str] = None


class WhatsAppBot:
    """
    Basit durum makinesi:
      - Yeni oturumda ilk cevap: kategori seçimi
      - Sonraki mesajda konu/birim eşleştirip yönlendir

    WhatsApp'ta 'app açıldı' olayı yoktur. Bu yüzden yeni oturumu:
      - İlk mesaj
      - veya TTL aşımı (örn 30 dk)
    ile simüle ediyoruz.
    """

    def __init__(self, router: TopicRouter, session_ttl_minutes: int = 30):
        self.router = router
        self.ttl = timedelta(minutes=session_ttl_minutes)
        self.sessions: Dict[str, Session] = {}

    def _should_send_welcome(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        normalized = text.strip().lower()
        greetings = {
            "merhaba",
            "selam",
            "selamlar",
            "günaydın",
            "iyi günler",
            "iyi akşamlar",
            "iyi geceler",
            "hello",
            "hi",
            "hey",
        }
        return normalized in greetings

    def _parse_category_choice(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return None

        if normalized in {"1", "1.", "istek", "istek ve sikayet", "sikayet"}:
            return "request"
        if normalized in {"2", "2.", "bilgi", "bilgi/hizmetler", "bilgi hizmetler", "hizmet", "hizmetler"}:
            return "info"
        if normalized in {"3", "3.", "e-belediye", "ebelediye", "e belediye"}:
            return "ebelediye"
        return None

    def _is_category_only(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        tokens = normalized.split()
        category_tokens = {
            "1",
            "2",
            "3",
            "istek",
            "sikayet",
            "bilgi",
            "hizmetler",
            "hizmet",
            "e",
            "belediye",
            "e-belediye",
            "ebelediye",
            "ve",
        }
        rest = [t for t in tokens if t not in category_tokens]
        return len(rest) == 0

    def _looks_like_municipal(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        keywords = {
            "cop",
            "temizlik",
            "konteyner",
            "yol",
            "asfalt",
            "cukur",
            "kaldirim",
            "park",
            "bahce",
            "yesil",
            "agac",
            "budama",
            "sokak",
            "mahalle",
            "cadde",
            "lamba",
            "aydinlatma",
            "zabita",
            "gurultu",
            "trafik",
            "otopark",
            "ruhsat",
            "pazar",
            "sosyal",
            "yardim",
            "su",
            "kanal",
            "kanalizasyon",
            "altyapi",
            "sokak hayvani",
            "hayvan",
        }

        if normalized in keywords:
            return True

        for key in keywords:
            if " " in key and key in normalized:
                return True

        tokens = set(normalized.split())
        return bool(tokens & keywords)

    def _normalize_text(self, text: str) -> str:
        lowered = text.casefold()
        lowered = lowered.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
        lowered = lowered.replace("ü", "u").replace("ö", "o").replace("ç", "c")
        cleaned = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(cleaned.split())

    def _get_session(self, user_id: str) -> Optional[Session]:
        s = self.sessions.get(user_id)
        if not s:
            return None
        if datetime.utcnow() - s.last_seen > self.ttl:
            self.sessions.pop(user_id, None)
            return None
        return s

    def _confirmation_message(self, unit: str) -> str:
        return (
            f"Teşekkürler. Talebiniz '{unit}' birimine bildirilmiştir.\n"
            "Daha hızlı destek için açık adres/mahalle ve mümkünse fotoğraf paylaşabilir misiniz?"
        )

    def _details_received_message(self, unit: Optional[str]) -> str:
        if unit:
            return (
                f"Teşekkürler. Paylaştığınız ek bilgileri '{unit}' birimine ilettim.\n"
                "Başka bir talebiniz varsa yazabilirsiniz."
            )
        return "Teşekkürler. Ek bilgiler alındı. Başka bir talebiniz varsa yazabilirsiniz."

    def handle_message(self, user_id: str, text: str) -> str:
        now = datetime.utcnow()
        s = self._get_session(user_id)

        # Yeni oturum
        if s is None:
            s = Session(stage="awaiting_category", last_seen=now)
            self.sessions[user_id] = s
            if self._should_send_welcome(text):
                return CATEGORY_PROMPT

        # Oturum güncelle
        s.last_seen = now

        # Kategori seçimi bekleniyorsa
        if s.stage == "awaiting_category":
            if not text or not text.strip():
                return CATEGORY_PROMPT
            choice = self._parse_category_choice(text)
            if choice == "request":
                s.stage = "awaiting_request"
                if self._is_category_only(text):
                    return REQUEST_SELECTED
            elif choice in {"info", "ebelediye"}:
                return (
                    "Şu an yalnızca İstek ve Şikayet hizmeti veriyoruz.\n\n"
                    f"{CATEGORY_OPTIONS}\n\n"
                    "Lütfen 1 yazarak devam edin."
                )
            else:
                # Seçim yapılmadıysa, isteği direkt İstek/Şikayet olarak işle
                s.stage = "awaiting_request"

        # Önceki adımda detay istenmişse: gelen her yanıtı detay kabul et
        if s.stage == "awaiting_details":
            s.stage = "awaiting_request"
            reply = self._details_received_message(s.last_unit)
            s.last_unit = None
            return reply

        # Talep al ve yönlendir
        decision: RouteDecision = self.router.route(text)
        result = decision.result

        if not result.matched:
            s.stage = "awaiting_request"
            if self._looks_like_municipal(text):
                return (
                    "Mesajınızı anlayamadım. Lütfen talebinizi daha anlaşılır ve detaylı yazın.\n"
                    "Örn: \"Mahallemizde çöp alınmadı\" veya \"Sokakta çukur var\""
                )
            return (
                "Bu hat yalnızca belediye istek ve şikayetleri içindir.\n"
                "Lütfen belediye hizmetleriyle ilgili bir talep yazın."
            )

        s.stage = "awaiting_details"
        s.last_unit = result.unit
        return self._confirmation_message(result.unit)
