import os
import logging
import sys
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

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from twilio.twiml.messaging_response import MessagingResponse

from konu_birim import load_topics
from router import TopicRouter
from bot import WhatsAppBot

EXCEL_PATH = os.getenv("KONU_BIRIM_EXCEL", "data/Konular.xlsx")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

topics = load_topics(EXCEL_PATH)
router = TopicRouter(topics, model=MODEL, use_gemini=True)
bot = WhatsAppBot(router)

app = FastAPI(title="Sultangazi WhatsApp Bot Demo")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def chat_interface(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/chat")
async def chat_api(request: Request):
    try:
        data = await request.json()
        user_message = data.get("message", "").strip()
        user_id = data.get("user_id", "web_user")

        logger.info("Chat mesajı alındı. user_id=%s len=%s", user_id, len(user_message))
        reply = bot.handle_message(user_id=user_id, text=user_message)

        return JSONResponse({
            "reply": reply,
            "user_message": user_message
        })
    except Exception as e:
        logger.exception("chat_api hata verdi.")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/twilio/whatsapp")
async def twilio_whatsapp(request: Request):
    form = await request.form()
    incoming_msg = (form.get("Body") or "").strip()
    from_number = (form.get("From") or "unknown").strip()

    logger.info("Twilio mesajı alındı. from=%s len=%s", from_number, len(incoming_msg))
    reply = bot.handle_message(user_id=from_number, text=incoming_msg)

    resp = MessagingResponse()
    resp.message(reply)

    return PlainTextResponse(str(resp), media_type="application/xml")
