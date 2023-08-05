import TelegramBot from 'node-telegram-bot-api';

export function echoRegiser(bot){
    bot.onText(/\/echo (.+)/, (msg, match) => {
        const chatId = msg.chat.id;
        const resp = match[1];
        bot.sendMessage(chatId, resp);
        logger.info(`[TELEGRAM_BOT] send message [${resp}] to [${chatId}]`);
    });
}