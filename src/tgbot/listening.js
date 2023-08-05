import TelegramBot from 'node-telegram-bot-api';
import { logger } from '../logger.js';

export function listeningLog(bot) {
    simpleLog(bot, 'message', logger.info);
    simpleLog(bot, 'edited_message', logger.info);
    simpleLog(bot, 'channel_post', logger.info);
    simpleLog(bot, 'edited_channel_post', logger.info);
    simpleLog(bot, 'polling_error', logger.error);
    simpleLog(bot, 'webhook_error', logger.error);
    logger.info(`[TELEGRAM_BOT] listeningLog registered`);
}

function simpleLog(bot, msgType, logFunc) {
    bot.on(msgType, (msg) => {
        logFunc(`[${msgType}]` + JSON.stringify(msg, null, 2));
    });
    logger.info(`[TELEGRAM_BOT] register [${msgType}]`);
}

