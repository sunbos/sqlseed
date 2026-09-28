import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./shell.json', import.meta.url));
