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

HUMAN_WELCOME_MESSAGE = (
    "Selam komşum, ben Osman. Sultangazi Belediyesi'nden yazıyorum. Sizlere yardımcı olmak için buradayım.\n\n"
    "Şu başlıklarda yardımcı olabilirim:\n\n"
    f"{CATEGORY_OPTIONS}\n\n"
    "İsteğinizi veya şikayetinizi doğrudan yazabilirsiniz."
)

OSMAN_SYSTEM_PROMPT = (
    "Sen Sultangazi Belediyesi'nde çalışan Osman isimli, çok yardımsever, samimi ve nazik bir personelsin. "
    "Vatandaşla bir insan gibi, samimi bir dille ('komşum', 'Değerli komşum') konuşursun. "
    "Asla yapay zeka olduğunu söylemezsin. "
    "Vatandaşın soyadını asla tekrar etme; sadece adıyla hitap et. "
    "Memnuniyet ifadelerinde 'Sizlere yardımcı olmak için buradayım' gibi bir dil kullan; tek tip, tutarlı olsun. "
    "Talep alırken adım adım ilerle: (1) Önce ad soyad, (2) sonra TC kimlik no, (3) gerekiyorsa mahalle/sokak gibi adres bilgileri, "
    "(4) en sonda talebin açık ve net bir şekilde yazılmasını iste. Bu sırayı değiştirme. "
    "Vatandaş beklenen bilgiyi vermediğinde ASLA 'Anladım' deme; o anda neye ihtiyaç duyulduğunu net söyle. "
    "Sadece belediyenin yardımcı olduğu konularda yardımcı ol: Talep oluşturma, Eğitim/Kurs, Yardımlar, Millet Kütüphanesi randevu, Nöbetçi eczaneler. "
    "Belediye hizmeti dışındaki veya internetten/ sistemden bulamayacağın bilgiler için nazikçe 'Bu konuda maalesef hizmet veremiyorum' de; "
    "belediyenin sunduğu hizmetlere yönlendir. Örn: Millet Kütüphanesi konumu gibi bazı bilgiler verilebilir, ama menüdeki diğer bazı seçenekler için bilgi yoksa 'bu konuda hizmet veremiyorum' de. "
    "Mesajların kısa, öz ve samimi olsun."
)



@dataclass
class Session:
    stage: str  # "awaiting_category" | "awaiting_name" | "awaiting_tc" | "awaiting_address" | "awaiting_issue" | "awaiting_followup"
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

    def __init__(self, router: TopicRouter, session_ttl_seconds: int = 30, inactivity_timeout_seconds: int = 60):
        self.router = router
        self.ttl = timedelta(seconds=session_ttl_seconds)
        self.inactivity_timeout = timedelta(seconds=inactivity_timeout_seconds)
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
            "lambasi",
            "yanmiyor",
            "yanmadi",
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
            if key in normalized:
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

        tokens = set(normalized.split())
        area_tokens = {"mahalle", "mahallesi", "mah"}
        street_tokens = {"sokak", "sokagi", "sok", "cadde", "caddesi", "cad", "bulvar", "bulvari", "blv"}
        number_tokens = {"no", "numara", "daire", "kat", "blok"}

        has_area = bool(tokens & area_tokens)
        has_street = bool(tokens & street_tokens)
        has_number = bool(re.search(r"\b\d{1,4}\b", normalized)) and bool(tokens & number_tokens)

        # En az iki adres bileşeni varsa adres kabul et
        return (has_area and has_street) or (has_area and has_number) or (has_street and has_number)

    def _maybe_store_issue(self, s: Session, text: str) -> None:
        if s.issue:
            return
        if self._looks_like_municipal(text) and not self._is_valid_address(text):
            s.issue = text.strip()

    def _is_out_of_scope_or_abuse(self, text: str) -> bool:
        """Para isteği, yapay zeka kimlik sorgulama, hakaret vb. — talep akışına sokma, kapsamda kal."""
        normalized = self._normalize_text(text)
        if not normalized or len(normalized) < 4:
            return False
        # Para / ödeme istekleri
        money_related = (
            "tl yolla", "tl gonder", "tl gonderin", "para yolla", "para gonder", "havale", "eft", "iban",
            "bin tl", "bintl", "lira yolla", "acil para", "para lazim", "borc", "odeme", "yatir", "gonder bana",
            "yolla bana", "gonder bana", "50bin", "50 bin", "100bin", "1000tl"
        )
        for phrase in money_related:
            if phrase in normalized:
                return True
        # Rakam + tl/yolla (örn. 50bin tl, 50bintl, 1000 tl yolla)
        if re.search(r"\d+\s*bin\s*tl", normalized) or re.search(r"\d+bintl", normalized):
            return True
        if re.search(r"\d+\s*tl\s*yolla", normalized) or re.search(r"yolla\s*\d+", normalized):
            return True
        # Yapay zeka / bot / kimlik sorgulama
        identity_probe = (
            "yapay zeka", "yapayzeka", "robot musun", "bot musun", "gercek kimlik", "gercek kmiilgini",
            "kimsin", "aslinda ne", "aslinda nesin", "ai misin", "yapay zeka misin", "soylemiyorsun"
        )
        tokens = set(normalized.split())
        probe_words = {"yapay", "zeka", "robot", "bot", "kimlik", "kimsin", "aslinda", "ai", "yapayzeka"}
        if tokens & probe_words:
            return True
        for phrase in identity_probe:
            if phrase in normalized:
                return True
        return False

    def _looks_like_confusion_or_rejection(self, text: str) -> bool:
        """Soru, red, karışıklık ifadeleri — bunları asla ad/TC/talep olarak kabul etme."""
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        confusion = {
            "neyi", "neden", "nasil", "ne", "niye", "anladin", "anlamadim", "anlamiyorum",
            "diyorsun", "yapiyorsun", "istemiyorum", "hayir", "olmaz", "yok", "gerek yok",
            "ne yapmak", "ne istiyorsun", "ne diyorsun", "secmedim", "secmedim ki",
            "komsum", "komsum", "selam", "merhaba",
        }
        tokens = set(normalized.split())
        if tokens & confusion:
            return True
        for phrase in ("ne diyorsun", "neyi anladin", "ne yapmak istedigimi", "anlamadin ki"):
            if phrase in normalized:
                return True
        return False

    def _is_valid_name(self, text: str) -> bool:
        """
        İsim doğrulama: sadece ad-soyad formatı kabul.
        Soru/red/karışıklık veya çok uzun/cümle ise reddet.
        """
        normalized = text.strip()
        if len(normalized) < 3:
            return False
        if self._looks_like_confusion_or_rejection(text):
            return False
        # Çok uzun veya çok kelime = muhtemelen cümle, isim değil (ad soyad genelde 2-4 kelime)
        words = normalized.split()
        if len(words) > 4:
            return False
        if len(normalized) > 40:
            return False
        if normalized.isdigit():
            return False
        dangerous_chars = {"<", ">", "/", "\\", "{", "}", ";", "(", ")"}
        if any(ch in dangerous_chars for ch in normalized):
            return False
        if not any(ch.isalpha() for ch in normalized):
            return False
        return True

    def _normalize_text(self, text: str) -> str:
        lowered = text.casefold()
        lowered = lowered.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
        lowered = lowered.replace("ü", "u").replace("ö", "o").replace("ç", "c")
        cleaned = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(cleaned.split())

    def _first_name(self, full_name: str) -> str:
        if not full_name:
            return "komşum"
        parts = full_name.strip().split()
        return parts[0] if parts else "komşum"

    def _followup_question(self) -> str:
        return "Başka yardımcı olabileceğim bir şey var mı?"

    def _is_negative_response(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        negatives = {
            "hayir",
            "yok",
            "gerek yok",
            "yok tesekkurler",
            "tesekkur",
            "tesekkurler",
            "yok sagol",
            "sagol",
            "yok sagolun",
            "sag olun",
            "yok istemiyorum",
        }
        if normalized in negatives:
            return True
        for phrase in negatives:
            if " " in phrase and phrase in normalized:
                return True
        return False

    def _get_session(self, user_id: str) -> Optional[Session]:
        s = self.sessions.get(user_id)
        if not s:
            return None
        if datetime.utcnow() - s.last_seen > self.ttl:
            self.sessions.pop(user_id, None)
            return None
        return s

    def _finalize_request(self, s: Session, issue_text: str) -> str:
        decision: RouteDecision = self.router.route(issue_text)
        result = decision.result

        if not result.matched:
            if self._looks_like_municipal(issue_text):
                s.stage = "awaiting_issue"
                return (
                    "Mesajınızı anlayamadım. Lütfen talebinizi daha anlaşılır ve detaylı yazar mısınız? "
                    "Örn: \"Mahallemizde çöp alınmadı\" veya \"Sokakta çukur var\""
                )
            s.stage = "awaiting_issue"
            return (
                "Bu hat yalnızca belediye istek ve şikayetleri içindir. "
                "Lütfen belediye hizmetleriyle ilgili bir talep yazın."
            )

        # Kısa onay + follow-up sorusu
        s.stage = "awaiting_followup"
        s.name = None
        s.tc = None
        s.address = None
        s.issue = None

        return (
            "Talebinizi aldım, gerekli düzenlemeleri yapacağız. "
            + self._followup_question()
        )



    def handle_message(self, user_id: str, text: str) -> str:
        now = datetime.utcnow()
        s = self._get_session(user_id)

        # Yeni oturum
        if s is None:
            s = Session(stage="awaiting_category", last_seen=now)
            self.sessions[user_id] = s
            if not text or self._should_send_welcome(text):
                return HUMAN_WELCOME_MESSAGE
        else:
            # 60 saniye inaktivite kontrolü: eğer son mesajdan 60 saniye geçmişse session'ı sıfırla
            time_since_last = now - s.last_seen
            if time_since_last > self.inactivity_timeout:
                # Session'ı sıfırla ve welcome mesajı dön
                self.sessions.pop(user_id, None)
                s = Session(stage="awaiting_category", last_seen=now)
                self.sessions[user_id] = s
                if not text or self._should_send_welcome(text):
                    return HUMAN_WELCOME_MESSAGE

        # Oturum güncelle
        s.last_seen = now
        normalized = text.strip()

        if s.stage in {"awaiting_category", "awaiting_name", "awaiting_tc"}:
            self._maybe_store_issue(s, normalized)

        # Kategori/talep aşaması — kullanıcı sorununu anlatırsa (sokak lambası, çöp vb.) doğrudan talep olarak al, menü seçtirme
        if s.stage == "awaiting_category":
            if not normalized:
                return self._get_osman_response(
                    "",
                    "Vatandaş boş mesaj gönderdi. Nazikçe nasıl yardımcı olabileceğini sor, istek/şikayet yazabileceğini belirt. Menü numarası isteme."
                )
            choice = self._parse_category_choice(text)
            if choice == "request":
                s.stage = "awaiting_name"
                if s.issue:
                    return "Talebinizi not aldım komşum. İşlemi başlatmak için adınızı ve soyadınızı alabilir miyim?"
                return "Size yardımcı olacağım komşum. Başlayalım: Adınız ve soyadınız?"
            if choice in {"education", "social_aid", "library", "pharmacy"}:
                return (
                    "Bu hizmet şu an hazırlık aşamasındadır. En kısa sürede Osman olarak size bu konuda da hizmet vereceğim.\n\n"
                    "İstek ve şikayetlerinizi doğrudan yazabilirsiniz (ör: sokak lambası, çöp, yol)."
                )
            # Kapsam dışı / kötüye kullanım: para isteği, yapay zeka sorgulama vb. — talep başlatma
            if self._is_out_of_scope_or_abuse(text):
                return (
                    "Bu konuda yardımcı olamıyorum komşum. Ben sadece belediyemizin hizmetleriyle ilgili konularda "
                    "yardımcı olabiliyorum: talep oluşturma, eğitim/kurs, yardımlar, kütüphane randevusu, nöbetçi eczaneler. "
                    "Bu konularda bir isteğiniz varsa yazabilirsiniz."
                )
            # Önce belediye talebi mi anla — sokak lambası, çöp, yol vb. ise doğrudan talep olarak al, menü seçtirme
            if self._looks_like_municipal(text):
                s.issue = normalized  # ilk mesajdaki talebi sakla
                s.stage = "awaiting_name"
                return "Talebinizi not aldım komşum. İşlemi başlatmak için adınızı ve soyadınızı alabilir miyim?"
            # Selam / belirsiz: ne yapabileceğini söyle, numara zorunlu değil
            if self._looks_like_confusion_or_rejection(text):
                return self._get_osman_response(
                    normalized,
                    "Vatandaş selamlaştı veya genel bir şey yazdı. Samimi karşıla, nasıl yardımcı olabileceğini kısaca söyle. "
                    "İstek ve şikayetlerini doğrudan yazabileceğini belirt (sokak lambası, çöp, yol vb.). Numara yazmasını isteme."
                )
            return self._get_osman_response(
                normalized,
                "Vatandaşın ne istediği tam belli değil. Nazikçe belediye ile ilgili istek veya şikayetini yazabileceğini söyle "
                "(ör: sokak lambası yanmıyor, çöp alınmadı). Numara seçtirme."
            )

        if s.stage == "awaiting_name":
            if self._is_out_of_scope_or_abuse(text):
                s.stage = "awaiting_category"
                return (
                    "Bu konuda yardımcı olamıyorum komşum. Sadece belediye hizmetleriyle ilgili taleplerde yardımcı olabiliyorum. "
                    "Belediye hizmetleri için isteğinizi yazabilirsiniz."
                )
            if not self._is_valid_name(normalized):
                issue_note = f" Vatandaşın talebi zaten alındı: '{s.issue}'. ASLA talep sorma." if s.issue else ""
                return self._get_osman_response(
                    normalized,
                    f"Vatandaş ad-soyad yerine başka bir şey yazdı (soru, red, cümle). 'Anladım' deme. "
                    f"Nazikçe sadece ad ve soyad yazmasını iste (ör: Ahmet Yılmaz).{issue_note}"
                )
            s.name = normalized
            s.stage = "awaiting_tc"
            first_name = self._first_name(s.name)
            return f"Teşekkür ederim {first_name} komşum. Şimdi de 11 haneli TC kimlik numaranızı rica edebilir miyim?"

        if s.stage == "awaiting_tc":
            if self._is_out_of_scope_or_abuse(text):
                s.stage = "awaiting_category"
                return (
                    "Bu konuda yardımcı olamıyorum komşum. Sadece belediye hizmetleriyle ilgili taleplerde yardımcı olabiliyorum. "
                    "Belediye hizmetleri için isteğinizi yazabilirsiniz."
                )
            tc_clean = re.sub(r"\D", "", normalized)
            issue_note = f" Vatandaşın talebi zaten alındı: '{s.issue}'. ASLA talep sorma." if s.issue else ""
            if len(tc_clean) == 11:
                s.tc = tc_clean
                s.stage = "awaiting_address"
                return self._get_osman_response(
                    normalized,
                    f"TC numarasını aldın. Şimdi mahalle, sokak, bina no gibi adres bilgilerini nazikçe sor.{issue_note}"
                )
            if self._looks_like_confusion_or_rejection(normalized):
                return self._get_osman_response(
                    normalized,
                    f"Vatandaş TC yazmadı; soru veya red ifadesi kullandı. 'Anladım' veya 'geçersiz' deme. "
                    f"Nazikçe işleme devam için 11 haneli TC kimlik numarasını (sadece rakam) yazması gerektiğini söyle.{issue_note}"
                )
            return self._get_osman_response(
                normalized,
                f"Vatandaş 11 haneli TC formatında yazmadı. 'Anladım' deme. "
                f"Nazikçe 11 haneli TC kimlik numarasını (sadece rakam) yazmasını iste.{issue_note}"
            )

        if s.stage == "awaiting_address":
            if not self._is_valid_address(normalized):
                issue_note = f" Vatandaşın talebi zaten alındı: '{s.issue}'. ASLA talep sorma." if s.issue else ""
                return self._get_osman_response(normalized, f"Adres bilgisi yetersiz. Mahalle, sokak gibi detayları içeren adresi tekrar sor.{issue_note}")
            s.address = normalized
            # Eğer talep zaten konuşmanın başında verilmişse, direkt işlemi sonuçlandır
            if s.issue:
                return self._finalize_request(s, s.issue)
            # Talep yoksa sor
            s.stage = "awaiting_issue"
            return (
                "Adres bilgisini aldım komşum. Son adım: Lütfen talebinizi açık ve net bir şekilde yazar mısınız? "
                "(Örn: Sokak lambaları yanmıyor, Mahallemizde çöp toplanmadı.)"
            )

        if s.stage == "awaiting_issue":
            return self._finalize_request(s, normalized)

        if s.stage == "awaiting_followup":
            if self._is_negative_response(text):
                s.stage = "awaiting_category"
                return "Rica ederim komşum. Başka bir isteğiniz olursa yazabilirsiniz."
            normalized_follow = self._normalize_text(text)
            if normalized_follow in {"evet", "var", "tabii", "peki", "olur"}:
                s.stage = "awaiting_category"
                return "Elbette komşum. Yeni bir istek veya şikayetinizi yazabilirsiniz."
            if self._looks_like_municipal(text):
                s.issue = normalized
                s.stage = "awaiting_name"
                return self._get_osman_response(normalized, "Yeni bir talep var. Nazikçe adını ve soyadını sor.")
            s.stage = "awaiting_category"
            return "Başka bir isteğiniz varsa doğrudan yazabilirsiniz."

        return "Nasıl yardımcı olabilirim? İsteğinizi veya şikayetinizi yazabilirsiniz."
