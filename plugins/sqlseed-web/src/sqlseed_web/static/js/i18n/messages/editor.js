import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./editor.json', import.meta.url));
