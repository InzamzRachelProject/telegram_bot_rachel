import TelegramBot from 'node-telegram-bot-api';
import { logger } from '../logger.js';
import { listeningLog } from './listening.js';
import { echoRegiser } from './echo.js';

function registerCommand(bot) {
    echoRegiser(bot);
    logger.info('[TELEGRAM_BOT] register command [echo]');
}

export function start(bot) {
    const welcome_log = "\n\
     _   _      _ _         ____            _          _ \n\
    | | | | ___| | | ___   |  _ \\ __ _  ___| |__   ___| |\n\
    | |_| |/ _ \\ | |/ _ \\  | |_) / _` |/ __| '_ \\ / _ \\ |\n\
    |  _  |  __/ | | (_) | |  _ < (_| | (__| | | |  __/ |\n\
    |_| |_|\\___|_|_|\\___/  |_| \\_\\__,_|\\___|_| |_|\\___|_|\n\
                                                    \
    "
    logger.info(welcome_log);
    logger.info('[TELEGRAM_BOT] start listening');
    listeningLog(bot);
    registerCommand(bot);
}