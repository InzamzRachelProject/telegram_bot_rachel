import got from 'got';
import TelegramBot from 'node-telegram-bot-api';
import { logger } from './src/logger.js';
import { start } from './src/tgbot/listening.js';

const channelId = process.env.TELEGRAM_CHANNEL_ID;
const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

start(bot);

got('https://m.cmx.im/api/v1/accounts/109261092826441759/statuses?limit=1', {
    headers: {
        Authorization: `Bearer ${process.env.MASTODON_ACCESS_TOKEN}`,
    },
}).then((response) => {
    // json 序列化
    if (response.statusCode !== 200) {
        logger.error('[GET_MASTODON_STATUS]', response.body);
        return;
    }
    logger.info('[GET_MASTODON_STATUS] success');
    logger.debug(`[GET_MASTODON_STATUS] ${response.body}`);
    const statuses = JSON.parse(response.body);
    for (const status of statuses) {
        logger.debug('[GET_MASTODON_STATUS]', status);
        // send message to the channel
        // bot.sendMessage(channelId, status.content);
        // logger.info(`[TELEGRAM_BOT] send message [${status.content}] to [${channelId}]`);
    }
}).catch((error) => {
    logger.error(`[GET_MASTODON_STATUS] ${error}`);
});
