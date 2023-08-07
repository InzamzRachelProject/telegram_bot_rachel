
import { readFileSync, writeFileSync } from 'fs';

export function getMastodonInfoFromJSON() {
    return JSON.parse(readFileSync('./conf/mastodonInfo.json', 'utf-8'));
}

export function updateMastodonInfoFromJSON(mastodonInfo) {
    return JSON.parse(writeFileSync('./conf/mastodonInfo.json', JSON.stringify(mastodonInfo, null, 2), 'utf-8'));
}
