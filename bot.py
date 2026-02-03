from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
import re

from router import TopicRouter, RouteDecision


CATEGORY_OPTIONS = (
    "1) Talep Oluşturma\n"
    "2) Eğitim ve Kurs Başvuru\n"
    "3) Yardımlar\n"
    "4) Millet Kütüphaneleri Randevu Alma\n"
    "5) Nöbetçi Eczaneler"
)

OSMAN_SYSTEM_PROMPT = (
    "Sen Sultangazi Belediyesi'nde çalışan Osman isimli, çok yardımsever, samimi ve nazik bir personelsin. "
    "Vatandaşla bir insan gibi, samimi bir dille ('komşum', 'hemşehrim', 'Değerli komşum') konuşursun. "
    "Asla yapay zeka olduğunu söylemezsin. Görevin vatandaşın derdini dinlemek ve eksik olan bilgilerini "
    "(Ad-Soyad, TC, Adres) sohbetin akışı içinde nazikçe almaktır. "
    "Mesajların kısa, öz ve çok samimi olmalı. Cevaplarını asla teknik veya robotik bir dille verme. "
    "\nMenü Seçenekleri (Vatandaş talep oluşturmak isterse veya yeni konuşma başlarsa bu seçenekleri nazikçe sun):\n"
    "1) Talep Oluşturma\n"
    "2) Eğitim ve Kurs Başvuru\n"
    "3) Yardımlar\n"
    "4) Millet Kütüphaneleri Randevu Alma\n"
    "5) Nöbetçi Eczaneler"
)



@dataclass
class Session:
    stage: str  # "awaiting_category" | "awaiting_name" | "awaiting_tc" | "awaiting_address" | "awaiting_issue"
    last_seen: datetime
    name: Optional[str] = None
    tc: Optional[str] = None
    address: Optional[str] = None
    issue: Optional[str] = None
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
        # Gemini istemcisini router üzerinden veya doğrudan alıyoruz
        from google import genai
        import os
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.client = router.client if router.client else (genai.Client(api_key=api_key) if api_key else None)

    def _get_osman_response(self, user_msg: str, context: str) -> str:
        """Osman persona'sı ile dinamik cevap üretir."""
        if not self.client:
            # Fallback (Gemini yoksa/hata verirse)
            return "Anladım komşum, hemen yardımcı olayım."

        prompt = f"{OSMAN_SYSTEM_PROMPT}\n\nDurum: {context}\nVatandaşın son mesajı: {user_msg}\n\nOsman'ın cevabı:"
        try:
            response = self.client.models.generate_content(
                model=self.router.model,
                contents=prompt,
                config={"temperature": 0.7}
            )
            return response.text.strip()
        except Exception:
            return "Anladım komşum, size nasıl yardımcı olabilirim?"

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

        # Rakam bazlı eşleşmeler (1, 2, 3...)
        if normalized in {"1", "1.", "talep", "talep olusturma"}:
            return "request"
        if normalized in {"2", "2.", "egitim", "egitim ve kurs", "kurs"}:
            return "education"
        if normalized in {"3", "3.", "yardim", "yardimlar"}:
            return "social_aid"
        if normalized in {"4", "4.", "kutuphane", "randevu", "millet kutuphanesi"}:
            return "library"
        if normalized in {"5", "5.", "eczane", "nobetci eczane"}:
            return "pharmacy"
        
        return None

    def _is_category_only(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        tokens = normalized.split()
        category_tokens = {
            "1", "2", "3", "4", "5",
            "talep", "olusturma", "egitim", "kurs", "yardim", "kutuphane", "eczane"
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



    def handle_message(self, user_id: str, text: str) -> str:
        now = datetime.utcnow()
        s = self._get_session(user_id)

        # Yeni oturum
        if s is None:
            s = Session(stage="awaiting_category", last_seen=now)
            self.sessions[user_id] = s
            if not text or self._should_send_welcome(text):
                return self._get_osman_response(text or "Merhaba", "Vatandaşla ilk kez karşılaşıyorsun veya selamlaştın. Kendini tanıt ve 5 hizmet kategorisini samimi bir dille sun.")

        # Oturum güncelle
        s.last_seen = now
        normalized = text.strip()

        # Kategori seçimi bekleniyorsa
        if s.stage == "awaiting_category":
            if not normalized:
                return self._get_osman_response("Merhaba", "Vatandaş boş mesaj gönderdi. Tekrar yardımcı olmayı teklif et ve menüyü hatırplat.")
            choice = self._parse_category_choice(text)
            if choice == "request":
                s.stage = "awaiting_name"
                return self._get_osman_response(normalized, "Vatandaş talep oluşturmak istediğini belirtti. Nazikçe adını ve soyadını sor.")
            elif choice in {"education", "social_aid", "library", "pharmacy"}:
                return (
                    "Bu hizmet şu an hazırlık aşamasındadır. En kısa sürede Osman olarak size bu konuda da hizmet vereceğim.\n\n"
                    f"Şu an '1) Talep Oluşturma' seçeneği üzerinden tüm istek ve şikayetlerinizi iletebilirsiniz.\n\n"
                    f"{CATEGORY_OPTIONS}"
                )
            else:
                # Seçim değilse, direkt talep olarak işle
                s.stage = "awaiting_name"
                return self._get_osman_response(normalized, "Vatandaş doğrudan bir mesaj yazdı. Yardımcı olacağını söyleyip adını ve soyadını sor.")

        if s.stage == "awaiting_name":
            if len(normalized) < 3:
                return self._get_osman_response(normalized, "Vatandaş ismini çok kısa yazdı veya yazmadı. Nazikçe adını soyadını tekrar sor.")
            s.name = normalized
            s.stage = "awaiting_tc"
            return self._get_osman_response(normalized, f"Vatandaşın ismi {s.name}. Memnun olduğunu belirt ve işlemlere başlamak için TC numarasını nazikçe sor.")

        if s.stage == "awaiting_tc":
            tc_clean = re.sub(r"\D", "", normalized)
            if len(tc_clean) != 11:
                return self._get_osman_response(normalized, "Vatandaş geçersiz bir TC yazdı. 11 haneli TC numarasını tekrar nazikçe sor.")
            s.tc = tc_clean
            s.stage = "awaiting_address"
            return self._get_osman_response(normalized, "TC numarasını aldın. Şimdi işlemin yapılacağı adresi veya konumu nazikçe sor.")

        if s.stage == "awaiting_address":
            if not self._is_valid_address(normalized):
                return self._get_osman_response(normalized, "Adres bilgisi yetersiz. Mahalle, sokak gibi detayları içeren adresi tekrar sor.")
            s.address = normalized
            s.stage = "awaiting_issue"
            return self._get_osman_response(normalized, "Adres bilgisini de aldın. Şimdi vatandaşın ne şikayeti veya talebi olduğunu bir dostunla konuşur gibi anlatmasını iste.")

        if s.stage == "awaiting_issue":
            # Talep al ve yönlendir
            decision: RouteDecision = self.router.route(text)
            result = decision.result

            if not result.matched:
                if self._looks_like_municipal(text):
                    return (
                        "Mesajınızı anlayamadım. Lütfen talebinizi daha anlaşılır ve detaylı yazar mısınız? "
                        "Örn: \"Mahallemizde çöp alınmadı\" veya \"Sokakta çukur var\""
                    )
                return (
                    "Bu hat yalnızca belediye istek ve şikayetleri içindir. "
                    "Lütfen belediye hizmetleriyle ilgili bir talep yazın."
                )

            # Teknik detayları (ticket_no, unit) kullanıcıya göstermiyoruz, sadece arka planda üretiyoruz (veya logluyoruz)
            ticket_no = self._generate_ticket_no()
            unit = result.unit
            
            # İnsancıl, samimi bir kapanış mesajı
            reply = (
                f"Değerli hemşehrim/komşum {s.name}, talebinizi ve şikayetinizi hassasiyetle not aldım. "
                f"Gerekli incelemelerin yapılması ve en kısa sürede çözüme kavuşturulması için ilgili birimlerimize bilgi verdim. "
                f"Sultangazi Belediyemiz siz kıymetli komşularımız için her daim görev başında ve tüm imkanlarıyla yanınızdadır. "
                f"Başka bir arzunuz olursa ben Osman olarak her zaman buradayım. Hayırlı günler dilerim."
            )
            
            # Oturumu temizle veya menü aşamasına çek
            s.stage = "awaiting_category"
            s.name = None
            s.tc = None
            s.address = None
            s.issue = None
            
            return reply + "\n\n" + CATEGORY_OPTIONS

        return CATEGORY_PROMPT
