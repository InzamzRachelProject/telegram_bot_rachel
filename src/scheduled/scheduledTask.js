import { schedule } from 'node-cron';
import { logger } from '../logger.js';
import { getStatusByAccountsId } from '../mastodon/getStatus.js';
import { simpleBot } from '../tgbot/init.js';
import { getMastodonInfoFromJSON, updateMastodonInfoFromJSON } from '../../conf/config.js';

const MASTODON_ID = process.env.MASTODON_ID;

const sendStatusToTelegramTask = schedule('* * * * *', async () => {
    logger.info('[ScheduledTask] sendStatusToTelegramTask');
    let mastodonInfo = getMastodonInfoFromJSON();
    var statuses;
    if (mastodonInfo.last_status_id != undefined) {
        statuses = await getStatusByAccountsId(MASTODON_ID, 1, mastodonInfo.last_status_id + 1);
    }
    else statuses = await getStatusByAccountsId(MASTODON_ID, 1, 0);
    sendStatusToTelegram(statuses);
});

async function sendStatusToTelegram(statuses) {
    let mastodonInfo = getMastodonInfoFromJSON();
    logger.info(`[ScheduledTask] last_status_id: ${mastodonInfo.last_status_id}`);
    if (statuses === undefined || statuses.length === 0) return logger.info('[ScheduledTask] no new status found');
    if (mastodonInfo.last_status_id === undefined || mastodonInfo.last_status_id !== statuses[0].id) {
        logger.info('[ScheduledTask] new status found');
        logger.info(`[ScheduledTask] ${JSON.stringify(statuses[0], null, 2)}`);
        simpleBot.sendMessage(process.env.TELEGRAM_CHAT_ID, statuses[0].content);
        mastodonInfo.last_status_id = statuses[0].id;
        updateMastodonInfoFromJSON(mastodonInfo);
    }
}

export function startScheduledTask() {
    sendStatusToTelegramTask.start();
    logger.info('[ScheduledTask] startScheduledTask');
}