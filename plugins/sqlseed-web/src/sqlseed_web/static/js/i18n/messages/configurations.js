import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./configurations.json', import.meta.url));
