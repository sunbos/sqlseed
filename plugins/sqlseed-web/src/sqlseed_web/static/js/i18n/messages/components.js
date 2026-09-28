import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./components.json', import.meta.url));
