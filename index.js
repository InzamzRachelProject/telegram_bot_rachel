import { getStatusByAccountsId } from './src/mastodon/getStatus.js';
import { startScheduledTask } from './src/scheduled/scheduledTask.js';
import { start,bot } from './src/tgbot/init.js';
import { logger } from './src/logger.js';

start(bot); 
startScheduledTask();