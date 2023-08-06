import got from 'got';
import { logger } from '../logger.js';

function getStatusByAccountsId(id, limit = 3) {
    got(`https://m.cmx.im/api/v1/accounts/${id}/statuses?limit=${limit}`, {
        headers: {
            Authorization: `Bearer ${process.env.MASTODON_ACCESS_TOKEN}`,
        },
    }).then((response) => {
        if (response.statusCode !== 200) {
            logger.error('[GetStatusByAccountsId]', response.body);
            return;
        }
        logger.info('[GetStatusByAccountsId] success');
        logger.debug(`[GetStatusByAccountsId] ${response.body}`);
        const statuses = JSON.parse(response.body);
        for (const status of statuses) {
            logger.debug('[GetStatusByAccountsId]', status);
        }
    }).catch((error) => {
        logger.error(`[GetStatusByAccountsId] ${error}`);
    });
}