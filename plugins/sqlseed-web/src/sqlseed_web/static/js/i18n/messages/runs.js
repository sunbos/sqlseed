import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./runs.json', import.meta.url));
