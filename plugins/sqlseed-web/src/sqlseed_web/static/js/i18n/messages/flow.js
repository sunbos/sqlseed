import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./flow.json', import.meta.url));
