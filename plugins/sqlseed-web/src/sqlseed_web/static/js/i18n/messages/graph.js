import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./graph.json', import.meta.url));
