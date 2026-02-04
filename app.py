import os
import logging
import sys
import tempfile
import subprocess
import asyncio
from pathlib import Path
from typing import Optional
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("whatsapp_bot")
    if logger.handlers:
        return logger

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_file = os.getenv("LOG_FILE")
    if log_file:
        file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logging()

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from twilio.twiml.messaging_response import MessagingResponse

try:
    import requests
except Exception:
    requests = None

from konu_birim import load_topics
from router import TopicRouter
from bot import WhatsAppBot

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

EXCEL_PATH = os.getenv("KONU_BIRIM_EXCEL", "data/Konular.xlsx")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

topics = load_topics(EXCEL_PATH)
router = TopicRouter(topics, model=MODEL, use_gemini=True)
bot = WhatsAppBot(router)

app = FastAPI(title="Sultangazi WhatsApp Bot Demo")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup_event():
    """Uygulama başlangıcında Whisper modelini yükle."""
    if WhisperModel is not None:
        logger.info("Whisper model startup'ta yükleniyor...")
        # Thread pool'da yükle, main thread'i bloke etme
        await asyncio.to_thread(_get_whisper_model)
        logger.info("Startup tamamlandı.")


def _resolve_whisper_device() -> str:
    device = os.getenv("WHISPER_DEVICE", "auto").lower()
    if device == "auto":
        cuda_env = os.getenv("CUDA_VISIBLE_DEVICES")
        if cuda_env and cuda_env.strip() not in {"", "-1"}:
            return "cuda"
        return "cpu"
    if device in {"cpu", "cuda"}:
        return device
    return "cpu"


def _resolve_whisper_compute_type(device: str) -> str:
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "auto").lower()
    if compute_type == "auto":
        # CPU için int8 daha hızlı ve stabil
        return "int8" if device == "cpu" else "float16"
    if compute_type in {"int8", "float16", "int8_float16", "float32"}:
        return compute_type
    return "int8" if device == "cpu" else "float16"


@lru_cache(maxsize=1)
def _get_whisper_model() -> Optional[WhisperModel]:
    if WhisperModel is None:
        logger.error("faster-whisper modülü import edilemedi. pip install faster-whisper çalıştırın.")
        return None
    try:
        # base model CPU'da hızlı ve Türkçe için yeterli
        # small veya medium daha iyi kalite ama daha yavaş
        model_name = os.getenv("WHISPER_MODEL", "base")
        device = _resolve_whisper_device()
        compute_type = _resolve_whisper_compute_type(device)
        logger.info(f"Whisper model yükleniyor: {model_name}, device: {device}, compute_type: {compute_type}")
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        logger.info("Whisper model başarıyla yüklendi.")
        return model
    except Exception as e:
        logger.exception("Whisper model yüklenemedi: %s", e)
        return None


def _transcribe_audio(file_path: Path) -> str:
    model = _get_whisper_model()
    if model is None:
        raise RuntimeError("faster-whisper yüklü değil.")
    segments, _info = model.transcribe(
        str(file_path),
        language="tr",
        vad_filter=False,  # onnxruntime DLL hatası nedeniyle geçici olarak devre dışı
        beam_size=5,
    )
    texts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    return " ".join(texts).strip()


def _probe_duration_seconds(file_path: Path) -> Optional[float]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(file_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        value = result.stdout.strip()
        return float(value) if value else None
    except FileNotFoundError:
        logger.warning("ffprobe bulunamadı. Ses süresi kontrol edilemiyor. FFmpeg yükleyin: https://ffmpeg.org/")
        return None
    except Exception as e:
        logger.warning("ffprobe hatası: %s. Ses süresi kontrol edilemiyor.", e)
        return None


@app.get("/", response_class=HTMLResponse)
async def chat_interface(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/chat")
async def chat_api(request: Request):
    try:
        data = await request.json()
        user_message = data.get("message", "").strip()
        user_id = data.get("user_id", "web_user")

        if not user_message:
            logger.warning("Boş mesaj reddedildi. user_id=%s", user_id)
            return JSONResponse({"error": "Mesaj boş olamaz"}, status_code=400)

        logger.info("Chat mesajı alındı. user_id=%s len=%s", user_id, len(user_message))
        reply = bot.handle_message(user_id=user_id, text=user_message)

        return JSONResponse({
            "reply": reply,
            "user_message": user_message
        })
    except Exception as e:
        logger.exception("chat_api hata verdi.")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/transcribe")
async def transcribe_api(
    file: UploadFile = File(...),
    user_id: str = Form("web_user"),
):
    logger.info("Transcribe isteği alındı. Content-Type: %s, Filename: %s", file.content_type, file.filename)

    # Content-Type'dan parametreleri (codecs=opus vb.) ayıklayıp temizleyelim
    content_type_clean = "unknown"
    if file.content_type:
        content_type_clean = file.content_type.split(';')[0].strip().lower()

    allowed_types = {
        "audio/webm",
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/ogg",
        "video/webm",
        "application/octet-stream",
    }
    
    # Dosya uzantısı kontrolü için liste
    allowed_extensions = {".webm", ".wav", ".mp3", ".ogg", ".mp4", ".mpeg", ".m4a"}

    is_allowed = False
    if content_type_clean in allowed_types or content_type_clean.startswith("audio/"):
        is_allowed = True
    
    # Tip eşleşmezse uzantıya bak
    if not is_allowed and file.filename:
        if Path(file.filename).suffix.lower() in allowed_extensions:
            is_allowed = True
            logger.info("Dosya uzantısına göre izin verildi.")

    if not is_allowed:
        logger.warning("Desteklenmeyen format: %s", file.content_type)
        return JSONResponse({"error": f"Desteklenmeyen ses formatı: {file.content_type}"}, status_code=400)

    max_mb = float(os.getenv("WHISPER_MAX_MB", "15"))
    max_bytes = int(max_mb * 1024 * 1024)
    contents = await file.read()
    if len(contents) > max_bytes:
        return JSONResponse({"error": "Ses kaydı çok büyük."}, status_code=400)

    temp_path: Optional[Path] = None
    converted_path: Optional[Path] = None
    try:
        temp_dir = Path(os.getenv("TMPDIR", tempfile.gettempdir()))
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Gelen dosyayı geçici olarak kaydet
        suffix = Path(file.filename or "").suffix or ".webm"
        with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(contents)

        # Süre kontrolü
        max_seconds = int(os.getenv("WHISPER_MAX_SECONDS", "90"))
        duration = _probe_duration_seconds(temp_path)
        if duration is not None and duration > max_seconds:
            return JSONResponse({"error": f"Ses kaydı {max_seconds} saniyeyi aşıyor."}, status_code=400)

        # TRANSCODING: Her ihtimale karşı dosyayı Whisper'ın en sevdiği format olan 16kHz WAV'a çevirelim
        converted_path = temp_path.with_suffix(".converted.wav")
        logger.info("Dosya WAV formatına dönüştürülüyor...")
        
        convert_cmd = [
            "ffmpeg", "-y", "-i", str(temp_path),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(converted_path)
        ]
        
        result = subprocess.run(convert_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("FFmpeg dönüştürme hatası: %s", result.stderr)
            # Eğer çevirme başarısız olursa orijinal dosya ile devam etmeyi dene
            process_path = temp_path
        else:
            process_path = converted_path

        # Transcription
        logger.info("Ses transkripsiyon başlıyor...")
        transcript = await asyncio.to_thread(_transcribe_audio, process_path)
        logger.info("Ses transkripsiyon tamamlandı: %s karakter", len(transcript) if transcript else 0)
        
        if not transcript:
            return JSONResponse({"error": "Transkript boş geldi."}, status_code=400)

        reply = bot.handle_message(user_id=user_id, text=transcript)
        return JSONResponse({"transcript": transcript, "reply": reply})
    except Exception as e:
        logger.exception("transcribe_api hata verdi.")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        for p in [temp_path, converted_path]:
            if p and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


@app.post("/twilio/whatsapp")
async def twilio_whatsapp(request: Request):
    form = await request.form()
    incoming_msg = (form.get("Body") or "").strip()
    from_number = (form.get("From") or "unknown").strip()
    num_media = int(form.get("NumMedia") or 0)

    logger.info("Twilio mesajı alındı. from=%s len=%s", from_number, len(incoming_msg))
    reply = bot.handle_message(user_id=from_number, text=incoming_msg)

    if num_media > 0:
        media_url = (form.get("MediaUrl0") or "").strip()
        media_type = (form.get("MediaContentType0") or "").strip()
        if media_url and media_type.startswith("audio/"):
            if WhisperModel is None:
                reply = "Ses mesajı alındı ancak transkripsiyon için faster-whisper kurulu değil."
            elif requests is None:
                reply = "Ses mesajı alındı ancak indirme için gerekli kütüphane eksik."
            else:
                sid = os.getenv("TWILIO_ACCOUNT_SID")
                token = os.getenv("TWILIO_AUTH_TOKEN")
                if not sid or not token:
                    reply = "Ses mesajı alındı ancak Twilio erişim bilgileri eksik."
                else:
                    temp_path: Optional[Path] = None
                    try:
                        resp = requests.get(media_url, auth=(sid, token), timeout=20)
                        resp.raise_for_status()
                        suffix = Path(media_url).suffix or ".wav"
                        temp_dir = Path(os.getenv("TMPDIR", tempfile.gettempdir()))
                        temp_dir.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=suffix, delete=False) as tmp:
                            temp_path = Path(tmp.name)
                            tmp.write(resp.content)
                        max_seconds = int(os.getenv("WHISPER_MAX_SECONDS", "90"))
                        duration = _probe_duration_seconds(temp_path)
                        if duration is not None and duration > max_seconds:
                            reply = f"Ses mesajı {max_seconds} saniyeyi aşıyor."
                        else:
                            transcript = _transcribe_audio(temp_path)
                            if transcript:
                                reply = bot.handle_message(user_id=from_number, text=transcript)
                            else:
                                reply = "Ses mesajı alındı ancak transkript üretilemedi."
                    except Exception:
                        logger.exception("Twilio ses indirimi/transkripsiyonu başarısız.")
                        reply = "Ses mesajı alındı ancak işlenirken hata oluştu."
                    finally:
                        if temp_path and temp_path.exists():
                            try:
                                temp_path.unlink()
                            except OSError:
                                logger.warning("Geçici dosya silinemedi: %s", temp_path)

    resp = MessagingResponse()
    if reply:
        resp.message(reply)

    return PlainTextResponse(str(resp), media_type="application/xml")
