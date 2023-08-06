import TelegramBot from 'node-telegram-bot-api';
import { logger } from '../logger.js';
import { listeningLog } from './listening.js';
import { echoRegiser } from './echo.js';

export const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN);

function registerCommand(bot) {
    echoRegiser(bot);
    logger.info('[TELEGRAM_BOT] register command [echo]');
}

export function start(bot) {
    const welcome_log = "\n\
     _   _      _ _         __  __ _           _         \n\
    | | | | ___| | | ___   |  \\/  (_)___  __ _| | ____ _ \n\
    | |_| |/ _ \\ | |/ _ \\  | |\\/| | / __|/ _` | |/ / _` |\n\
    |  _  |  __/ | | (_) | | |  | | \\__ \\ (_| |   < (_| |\n\
    |_| |_|\\___|_|_|\\___/  |_|  |_|_|___/\\__,_|_|\\_\\__,_|\n\
                                                        \n"
    logger.info(welcome_log);
    logger.info('[TelegramBot] start listening');
    listeningLog(bot);
    registerCommand(bot);
}