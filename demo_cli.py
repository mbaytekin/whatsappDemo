import argparse

from konu_birim import load_topics
from router import TopicRouter
from bot import WhatsAppBot


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--excel", required=True, help="Konu-Birim Excel yolu")
    p.add_argument("--model", default="gemini-2.5-pro", help="Gemini model adı (örn: gemini-2.5-pro)")
    p.add_argument("--no-gemini", action="store_true", help="Gemini çağırmadan sadece TF-IDF ile demo")
    args = p.parse_args()

    topics = load_topics(args.excel)
    router = TopicRouter(topics, model=args.model, use_gemini=not args.no_gemini)
    bot = WhatsAppBot(router)

    user_id = "demo_user"

    # Yeni oturum: karşılama
    print("BOT:", bot.handle_message(user_id, ""))

    while True:
        try:
            msg = input("SİZ: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÇıkılıyor.")
            return

        if not msg:
            continue
        if msg.lower() in {"exit", "quit", "cikis", "çıkış"}:
            print("Çıkılıyor.")
            return

        print("BOT:", bot.handle_message(user_id, msg))


if __name__ == "__main__":
    main()
