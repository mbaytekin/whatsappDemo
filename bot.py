from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
import re

from router import TopicRouter, RouteDecision


CATEGORY_OPTIONS = (
    "1) İstek/Şikâyet Bildir\n"
    "2) Bilgi Al\n"
    "3) Başvuru Sorgula"
)

CATEGORY_PROMPT = (
    "Sultangazi Belediyesi’ne hoş geldiniz. Size nasıl yardımcı olabilirim?\n\n"
    f"{CATEGORY_OPTIONS}"
)

REQUEST_SELECTED = "İstek/Şikâyet Bildirimi seçildi. Lütfen talebinizi yazın."

DETAILS_PROMPT = (
    "Teşekkürler. Talebinizi iletmem için lütfen:\n"
    "- Açık adres (mahalle/sokak/no) veya konum paylaşın.\n"
    "- Varsa fotoğraf ekleyebilirsiniz."
)

MENU_AFTER_DETAILS = (
    "Başka bir talebiniz var mı?\n\n"
    "1) Yeni talep\n"
    "2) Başvuru sorgula\n"
    "3) Menü"
)

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

    def _generate_ticket_no(self) -> str:
        import random
        from datetime import datetime
        year = datetime.now().year
        rand_id = random.randint(100000, 999999)
        return f"SGZ-{year}-{rand_id}"

    def _parse_category_choice(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return None

        if normalized in {"1", "1.", "istek", "sikayet", "bildir", "istek ve sikayet"}:
            return "request"
        if normalized in {"2", "2.", "bilgi", "bilgi al"}:
            return "info"
        if normalized in {"3", "3.", "sorgula", "basvuru sorgula", "sorgu"}:
            return "query"
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

    def _is_valid_address(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
            
        address_keywords = {
            "mahalle", "mah", "sokak", "sok", "cadde", "cad", "bulvar", "blv",
            "no", "numara", "daire", "kat", "blok", "sitesi", "apartmani",
            "mevkii", "karsisi", "yani", "arkasi"
        }
        
        tokens = set(normalized.split())
        # En az bir adres anahtar kelimesi geçmeli VEYA metin yeterince uzun olmalı
        return bool(tokens & address_keywords) or len(text.strip()) > 20

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
            f"Anladım, bu konu '{unit}' ile ilgili.\n\n"
            f"{DETAILS_PROMPT}"
        )

    def _details_received_message(self, unit: Optional[str]) -> str:
        ticket_no = self._generate_ticket_no()
        prefix = f"Teşekkürler. Talebiniz '{unit}' birimine iletilmiştir.\n" if unit else "Teşekkürler, bilgileri ilettim.\n"
        msg = (
            f"{prefix}"
            f"Kayıt No: {ticket_no}\n\n"
            f"{MENU_AFTER_DETAILS}"
        )
        return msg

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
            elif choice in {"info", "query"}:
                return (
                    "Bu hizmet şu an geliştirme aşamasındadır. Yakında hizmete açılacaktır.\n\n"
                    f"{CATEGORY_OPTIONS}"
                )
            else:
                # Seçim değilse, direkt talep olarak işle
                s.stage = "awaiting_request"

        # Önceki adımda detay istenmişse: adres doğrulaması yap
        if s.stage == "awaiting_details":
            if self._is_valid_address(text):
                s.stage = "awaiting_request"
                reply = self._details_received_message(s.last_unit)
                s.last_unit = None
                return reply
            else:
                return (
                    "Lütfen geçerli bir adres (mahalle, sokak, numara) belirtiniz. "
                    "Talebinizi iletebilmemiz için konum bilgisi zorunludur."
                )

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
