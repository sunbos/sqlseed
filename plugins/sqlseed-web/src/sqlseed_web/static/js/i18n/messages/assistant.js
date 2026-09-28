import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./assistant.json', import.meta.url));
