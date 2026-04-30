#!/usr/bin/env node

/**
 * Validation Script for Gaelic Insights Parser
 *
 * Tests the parser against real XML files and reports:
 * - filename
 * - whistle count
 * - auto-detected / manual required
 * - first 3 events in each half
 * - offsets
 * - warnings
 */

const fs = require('fs');
const path = require('path');

// Load the parser
let parseGaelicInsightsXml;
try {
  parseGaelicInsightsXml = require('../parseGaelicInsightsXml');
} catch (e) {
  console.error('Error loading parser:', e.message);
  process.exit(1);
}

// Test data: filename, homeTeam, awayTeam, half1Video, half2Video
const testCases = [
  {
    file: '/Users/barrymcguire/Downloads/gaeilc_insights_nfl_d2r7_cork_v_Kildare.xml',
    homeTeam: 'Cork',
    awayTeam: 'Kildare',
    half1Video: 55,
    half2Video: 2349,
    description: 'Cork v Kildare (D2R7)',
  },
  {
    file: '/Users/barrymcguire/Downloads/gaeilc_insights_nfl_d2r6_tyrone_v_cork.xml',
    homeTeam: 'Tyrone',
    awayTeam: 'Cork',
    half1Video: 100,
    half2Video: 2300,
    description: 'Tyrone v Cork (D2R6)',
  },
  {
    file: '/Users/barrymcguire/Downloads/gaeilc_insights_nfl_d2r5_derry_v_cork.xml',
    homeTeam: 'Derry',
    awayTeam: 'Cork',
    half1Video: 110,
    half2Video: 2350,
    description: 'Derry v Cork (D2R5)',
  },
  {
    file: '/Users/barrymcguire/Downloads/gaeilc_insights_nfl_d2r4_cork_v_meath.xml',
    homeTeam: 'Cork',
    awayTeam: 'Meath',
    half1Video: 90,
    half2Video: 2400,
    description: 'Cork v Meath (D2R4)',
  },
  {
    file: '/Users/barrymcguire/Downloads/gaeilc_insights_nfl_d2r3_offaly_v_cork.xml',
    homeTeam: 'Offaly',
    awayTeam: 'Cork',
    half1Video: 75,
    half2Video: 2325,
    description: 'Offaly v Cork (D2R3)',
  },
];

console.log('\n========== GAELIC INSIGHTS PARSER VALIDATION ==========\n');

let passCount = 0;
let failCount = 0;

for (const testCase of testCases) {
  console.log(`\n--- ${testCase.description} ---`);

  // Check if file exists
  if (!fs.existsSync(testCase.file)) {
    console.log(`⚠️  File not found: ${testCase.file}`);
    failCount++;
    continue;
  }

  // Read XML
  let xmlText;
  try {
    xmlText = fs.readFileSync(testCase.file, 'utf-8');
  } catch (err) {
    console.log(`❌ Error reading file: ${err.message}`);
    failCount++;
    continue;
  }

  // Parse
  const result = parseGaelicInsightsXml({
    xmlText,
    homeTeam: testCase.homeTeam,
    awayTeam: testCase.awayTeam,
    half1Video: testCase.half1Video,
    half2Video: testCase.half2Video,
  });

  // Report
  console.log(`Status: ${result.status}`);
  console.log(`Whistles found: ${result.whistles.length}`);
  console.log(`Events parsed: ${result.events.length}`);

  if (result.diagnostics.selectedAnchors) {
    const a = result.diagnostics.selectedAnchors;
    console.log(`1H Anchor: ID=${a.half1.id} @ ${a.half1.xmlTime} (offset: ${a.half1.offset.toFixed(2)}s)`);
    console.log(`2H Anchor: ID=${a.half2.id} @ ${a.half2.xmlTime} (offset: ${a.half2.offset.toFixed(2)}s)`);
  }

  if (result.diagnostics.autoDetectionUsed) {
    console.log('✓ Auto-detected 4-whistle pattern');
    passCount++;
  } else if (result.status === 'needs_whistle_selection') {
    console.log('⚠️  Manual whistle selection required');
    console.log(`Reason: ${result.reason}`);
  } else if (result.status === 'ok') {
    console.log('✓ Successfully parsed');
    passCount++;
  } else {
    console.log(`❌ Error: ${result.error}`);
    failCount++;
  }

  // Show first few events per half
  if (result.diagnostics.sampleEvents) {
    const { firstHalf, secondHalf } = result.diagnostics.sampleEvents;

    if (firstHalf.length > 0) {
      console.log(`\n  First Half Sample (${firstHalf.length} shown):`);
      for (const evt of firstHalf) {
        console.log(
          `    - ${evt.gameTime}: ${evt.code} (${evt.team}) [videoT: ${evt.videoT}s, driveT: ${evt.driveT}s]`
        );
      }
    }

    if (secondHalf.length > 0) {
      console.log(`\n  Second Half Sample (${secondHalf.length} shown):`);
      for (const evt of secondHalf) {
        console.log(
          `    - ${evt.gameTime}: ${evt.code} (${evt.team}) [videoT: ${evt.videoT}s, driveT: ${evt.driveT}s]`
        );
      }
    }
  }

  // Show warnings
  if (result.warnings && result.warnings.length > 0) {
    console.log(`\nWarnings (${result.warnings.length}):`);
    for (const warning of result.warnings) {
      console.log(`  ⚠️  ${warning}`);
    }
  }
}

console.log(`\n\n========== SUMMARY ==========`);
console.log(`Passed: ${passCount}`);
console.log(`Failed: ${failCount}`);
console.log(`Total:  ${passCount + failCount}`);
console.log('================================\n');

process.exit(failCount > 0 ? 1 : 0);
