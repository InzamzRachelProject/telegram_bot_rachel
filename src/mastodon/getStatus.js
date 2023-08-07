import got from 'got';
import { logger } from '../logger.js';

export { getStatusByAccountsId };

async function getStatusByAccountsId(id, limit = 1, since_id = 0, exclude_replies = true, exclude_reblogs = true) {
    try {
        const response = await got(`https://m.cmx.im/api/v1/accounts/${id}/statuses?limit=${limit}&since_id=${since_id}&exclude_replies=${exclude_replies}&exclude_reblogs=${exclude_reblogs}`, {
            headers: {
                Authorization: `Bearer ${process.env.MASTODON_ACCESS_TOKEN}`,
            },
        });
        if (response.statusCode !== 200) {
            logger.error('[GetStatusByAccountsId]', response.body);
            return;
        }
        const statuses = JSON.parse(response.body);
        logger.info('[GetStatusByAccountsId] success');
        logger.info(`[GetStatusByAccountsId] ${JSON.stringify(statuses, null, 2)}`);
        return statuses;
    } catch (error) {
        console.error('Error:', error.message);
    }
}
