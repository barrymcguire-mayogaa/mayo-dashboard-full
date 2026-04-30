const fs = require('fs');
const parseGaelicInsightsXml = require('./parseGaelicInsightsXml');

const xmlText = fs.readFileSync('/Users/barrymcguire/Downloads/gaeilc_insights_usfc_qf_fermanagh_v_armagh.xml', 'utf-8');

const result = parseGaelicInsightsXml({
  xmlText,
  homeTeam: 'Fermanagh',
  awayTeam: 'Armagh',
  half1Video: 55,
  half2Video: 2349,
});

console.log('STATUS:', result.status);
console.log('\nWHISTLE BOUNDARIES:');
console.log(JSON.stringify(result.diagnostics.whistleBoundaries, null, 2));
console.log('\nVIDEO TIMING ANCHORS:');
console.log(JSON.stringify(result.diagnostics.videoTimingAnchors, null, 2));
console.log('\nFIRST EVENT (FULL):');
console.log(JSON.stringify(result.events[0], null, 2));
