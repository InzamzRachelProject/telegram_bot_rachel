import logging
import os

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

tgbot_token = ""
debug = True
master_id = 0
channel_report = 0
channel_sleep = 0

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm Rachel.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I'm Rachel.",
        reply_to_message_id=update.message.id,
    )


def main():
    # 读取环境变量
    global tgbot_token, debug, master_id, channel_report, channel_sleep
    tgbot_token = os.getenv("TGBOT_TOKEN")
    debug = os.getenv("DEBUG").lower() == "true"
    master_id = int(os.getenv("MASTER_ID"))
    channel_report = int(os.getenv("CHANNEL_REPORT"))
    channel_sleep = int(os.getenv("CHANNEL_SLEEP"))

    application = ApplicationBuilder().token(tgbot_token).build()
    start_handler = CommandHandler('start', start)
    start_handler = CommandHandler('echo', echo)
    application.add_handler(start_handler)
    application.run_polling()


if __name__ == '__main__':
    main()
