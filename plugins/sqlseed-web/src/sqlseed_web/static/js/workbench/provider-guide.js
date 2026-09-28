import { tr } from '../i18n.js';
import '../i18n/messages/providerGuide.js';
// Verified against sqlseed's provider adapters and the linked upstream docs.
// Examples illustrate formats only; this module never runs a provider or edits
// the selected configuration. Recommendation is guidance, not a default change.
export function providerGuide(provider,locale='zh_CN') {
  const chinese=String(locale).startsWith('zh');
  const exampleNote=tr('providerGuide.exampleNote');
  const commonLimit=tr('providerGuide.commonLimit');
  if(provider==='faker')return {
    id:provider,title:'Faker',choice:tr('providerGuide.fakerChoice'),recommended:true,
    summary:tr('providerGuide.fakerSummary'),
    features:[tr('providerGuide.fakerLocale'),tr('providerGuide.fakerNative')],
    limits:[tr('providerGuide.fakerFallback'),commonLimit],
    examples:[{label:tr('providerGuide.name'),value:chinese?'王小明':'Alex Morgan'},{label:tr('providerGuide.integerRange'),value:'3'}],
    exampleNote,sources:[{label:tr('providerGuide.fakerDocs'),url:'https://faker.readthedocs.io/en/master/'}],
  };
  if(provider==='mimesis')return {
    id:provider,title:'Mimesis',choice:tr('providerGuide.mimesisChoice'),recommended:false,
    summary:tr('providerGuide.mimesisSummary'),
    features:[tr('providerGuide.mimesisSource'),tr('providerGuide.mimesisNative')],
    limits:[tr('providerGuide.speedLimit'),tr('providerGuide.benchmarkLimit'),commonLimit],
    examples:[{label:tr('providerGuide.name'),value:chinese?'陈子涵':'Taylor Reed'},{label:tr('providerGuide.integerRange'),value:'3'}],
    exampleNote,sources:[{label:tr('providerGuide.mimesisFeatures'),url:'https://mimesis.name/master/about.html'},{label:tr('providerGuide.mimesisBenchmarks'),url:'https://mimesis.name/master/benchmarks.html'},{label:tr('providerGuide.mimesisLocales'),url:'https://mimesis.name/master/locales.html'}],
  };
  if(provider==='base')return {
    id:provider,title:'Base',choice:tr('providerGuide.baseChoice'),recommended:false,
    summary:tr('providerGuide.baseSummary'),
    features:[tr('providerGuide.baseValues'),tr('providerGuide.baseBuiltIn')],
    limits:[tr('providerGuide.baseLocale'),commonLimit],
    examples:[{label:tr('providerGuide.name'),value:'first_001_1234 last_001_1234'},{label:tr('providerGuide.integerRange'),value:'3'}],
    exampleNote,sources:[],
  };
  return {id:provider,title:provider ? String(provider) : tr('providerGuide.none'),choice:tr('providerGuide.custom'),recommended:false,summary:tr('providerGuide.customSummary'),features:[],limits:[commonLimit],examples:[],exampleNote,sources:[]};
}
