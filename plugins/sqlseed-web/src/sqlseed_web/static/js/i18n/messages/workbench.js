import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./workbench.json', import.meta.url));
