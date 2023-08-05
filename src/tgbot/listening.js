import TelegramBot from 'node-telegram-bot-api';
import { logger } from '../logger.js';

let commandDist = {
    '/echo': echo,
    '/log': listen,
}

function listen(bot) {
    simpleLog(bot, 'message', logger.info);
    simpleLog(bot, 'edited_message', logger.info);
    simpleLog(bot, 'channel_post', logger.info);
    simpleLog(bot, 'edited_channel_post', logger.info);
    simpleLog(bot, 'polling_error', logger.error);
    simpleLog(bot, 'webhook_error', logger.error);
}

export function start(bot){
    let welcome_log = "\n\
     _   _      _ _         ____            _          _ \n\
    | | | | ___| | | ___   |  _ \\ __ _  ___| |__   ___| |\n\
    | |_| |/ _ \\ | |/ _ \\  | |_) / _` |/ __| '_ \\ / _ \\ |\n\
    |  _  |  __/ | | (_) | |  _ < (_| | (__| | | |  __/ |\n\
    |_| |_|\\___|_|_|\\___/  |_| \\_\\__,_|\\___|_| |_|\\___|_|\n\
                                                    \
    "
    logger.info(welcome_log);
    logger.info('[TELEGRAM_BOT] start');
    registerCommandList(bot);
    listen(bot);
}

function registerCommand(bot, command, callback) {
    bot.onText(command, (msg, match) => {
        const chatId = msg.chat.id;
        callback(chatId, match);
    });
}

function registerCommandList(bot){
    for (const command in commandDist) {
        registerCommand(bot, command, commandDist[command]);
    }
}

function echo(bot){
    bot.onText(/\/echo (.+)/, (msg, match) => {
        const chatId = msg.chat.id;
        const resp = match[1];
        bot.sendMessage(chatId, resp);
        logger.info(`[TELEGRAM_BOT] send message [${resp}] to [${chatId}]`);
    });
}

function simpleLog(bot, msgType, logFunc){
    bot.on(msgType, (msg) => {
        logFunc(`[${msgType}] ${msg}`);
    });
}

