import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./settings.json', import.meta.url));
