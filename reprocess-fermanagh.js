const fs = require('fs');
const path = require('path');
const parseGaelicInsightsXml = require('./parseGaelicInsightsXml');

const xmlFile = '/Users/barrymcguire/Downloads/gaeilc_insights_usfc_qf_fermanagh_v_armagh.xml';
const xmlText = fs.readFileSync(xmlFile, 'utf-8');

const result = parseGaelicInsightsXml({
  xmlText,
  homeTeam: 'Fermanagh',
  awayTeam: 'Armagh',
  half1Video: 55,
  half2Video: 2349,
});

if (result.status !== 'ok') {
  console.error('Parsing failed:', result.error);
  process.exit(1);
}

// Ensure games directory exists
if (!fs.existsSync('games')) {
  fs.mkdirSync('games', { recursive: true });
}

// Save events
fs.writeFileSync('games/fermanagh-armagh-2024-usfc-qf.json', JSON.stringify(result.events, null, 2));
console.log(`✓ Saved ${result.events.length} events to games/fermanagh-armagh-2024-usfc-qf.json`);

// Create/update games.json
let gamesFile = { games: [] };
const gamesPath = 'games/games.json';
if (fs.existsSync(gamesPath)) {
  gamesFile = JSON.parse(fs.readFileSync(gamesPath, 'utf-8'));
  if (!Array.isArray(gamesFile.games)) {
    gamesFile.games = [];
  }
}

// Remove existing Fermanagh entry if present
gamesFile.games = gamesFile.games.filter(g => g.id !== 'fermanagh-armagh-2024-usfc-qf');

// Add updated entry
const gameEntry = {
  id: 'fermanagh-armagh-2024-usfc-qf',
  title: 'Fermanagh v Armagh',
  date: '2024-10-26',
  competition: 'Ulster SFC',
  round: 'Quarter-Final',
  homeTeam: 'Fermanagh',
  awayTeam: 'Armagh',
  colors: { home: '#FF6600', away: '#FFFF00' },
  youtubeId: 'h-hC7gF9dXk',
  half1Start: 55,
  half2Start: 2349,
  eventCount: result.events.length,
  parser: 'gaelic-insights',
  whistles: {
    half1: {
      id: result.diagnostics.whistleBoundaries.half1Whistle.id,
      xmlTime: result.diagnostics.whistleBoundaries.half1Whistle.xmlStart,
    },
    half2: {
      id: result.diagnostics.whistleBoundaries.half2Whistle.id,
      xmlTime: result.diagnostics.whistleBoundaries.half2Whistle.xmlStart,
    },
  },
  videoAnchors: {
    half1: {
      eventId: result.diagnostics.videoTimingAnchors.half1.eventId,
      xmlStart: result.diagnostics.videoTimingAnchors.half1.xmlStart,
      offset: result.diagnostics.videoTimingAnchors.half1.offset,
    },
    half2: {
      eventId: result.diagnostics.videoTimingAnchors.half2.eventId,
      xmlStart: result.diagnostics.videoTimingAnchors.half2.xmlStart,
      offset: result.diagnostics.videoTimingAnchors.half2.offset,
    },
  },
};

gamesFile.games.push(gameEntry);
fs.writeFileSync(gamesPath, JSON.stringify(gamesFile, null, 2));
console.log(`✓ Updated games/games.json with Fermanagh v Armagh metadata`);

console.log('\n✓ Reprocessing complete!');
console.log(`  First event: videoT=${result.events[0].videoT}, driveT=${result.events[0].driveT}, gameTime=${result.events[0].gameTime}`);
