import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./labels.json', import.meta.url));
