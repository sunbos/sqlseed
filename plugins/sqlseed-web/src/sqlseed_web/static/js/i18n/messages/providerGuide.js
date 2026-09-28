import {loadMessages} from '../../i18n.js';

await loadMessages(new URL('./providerGuide.json', import.meta.url));
