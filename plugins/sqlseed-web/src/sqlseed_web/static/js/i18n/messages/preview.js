import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./preview.json', import.meta.url));
