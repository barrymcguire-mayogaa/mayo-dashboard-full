/**
 * Gaelic Insights XML Timing Parser
 *
 * Parses Gaelic Insights XML files and anchors events to NA Whistle timestamps.
 * Supports automatic 4-whistle detection and manual fallback.
 *
 * Input: raw XML text, game metadata, optional selected whistles
 * Output: structured events, diagnostics, warnings, and selection status
 */

function parseGaelicInsightsXml({
  xmlText,
  homeTeam,
  awayTeam,
  half1Video,
  half2Video,
  selectedWhistles = null,
  seekPrerollSeconds = 2,
}) {
  // ========== STEP 1: Parse XML ==========
  let xmlDoc;
  try {
    if (typeof DOMParser !== 'undefined') {
      // Browser environment
      const parser = new DOMParser();
      xmlDoc = parser.parseFromString(xmlText, 'application/xml');

      // Check for parsing errors in browser
      if (xmlDoc.documentElement.nodeName === 'parsererror') {
        throw new Error('Invalid XML structure');
      }
    } else {
      // Node.js environment - use regex-based parsing
      xmlDoc = parseXmlRegex(xmlText);
    }
  } catch (err) {
    return {
      status: 'error',
      events: [],
      whistles: [],
      warnings: [],
      diagnostics: {},
      error: `XML parsing failed: ${err.message}`,
    };
  }

  // Select all instance nodes
  let instanceNodes;
  if (xmlDoc.querySelectorAll) {
    instanceNodes = xmlDoc.querySelectorAll('instance');
  } else {
    instanceNodes = xmlDoc.instances || [];
  }

  if (!instanceNodes || instanceNodes.length === 0) {
    return {
      status: 'error',
      events: [],
      whistles: [],
      warnings: [],
      diagnostics: {},
      error: 'No instances found in XML',
    };
  }

  // ========== STEP 2: Group Duplicate Instances By ID ==========
  const eventMap = new Map();

  for (const instanceNode of instanceNodes) {
    // Handle both DOM and regex-based parsing
    const idElement = instanceNode.querySelector('ID') || { textContent: '' };
    const startElement = instanceNode.querySelector('start') || { textContent: '0' };
    const endElement = instanceNode.querySelector('end') || { textContent: '0' };
    const codeElement = instanceNode.querySelector('code') || { textContent: '' };

    const id = idElement.textContent?.trim?.() || idElement.textContent || '';
    const start = parseFloat(startElement.textContent?.trim?.() || startElement.textContent || '0');
    const end = parseFloat(endElement.textContent?.trim?.() || endElement.textContent || '0');
    const code = codeElement.textContent?.trim?.() || codeElement.textContent || '';

    if (!id) continue;

    if (!eventMap.has(id)) {
      eventMap.set(id, {
        id,
        start,
        end,
        code,
        labels: {},
      });
    }

    // Merge labels
    const labelElements = instanceNode.querySelectorAll('label') || [];
    for (const labelElement of labelElements) {
      const groupEl = labelElement.querySelector('group') || { textContent: '' };
      const textEl = labelElement.querySelector('text') || { textContent: '' };
      const group = groupEl.textContent?.trim?.() || groupEl.textContent || '';
      const text = textEl.textContent?.trim?.() || textEl.textContent || '';

      if (group && text) {
        const current = eventMap.get(id);
        eventMap.set(id, {
          ...current,
          labels: {
            ...current.labels,
            [group]: text,
          },
        });
      }
    }
  }

  const groupedEvents = Array.from(eventMap.values());

  // ========== STEP 3: Sort Events ==========
  groupedEvents.sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    const aId = parseInt(a.id, 10);
    const bId = parseInt(b.id, 10);
    if (!isNaN(aId) && !isNaN(bId)) return aId - bId;
    return a.id.localeCompare(b.id);
  });

  // ========== STEP 4: Identify Whistles ==========
  const whistles = groupedEvents
    .filter((e) => e.code === 'NA Whistle')
    .map((w, index) => {
      // Find previous and next non-whistle events
      let previousEvent = null;
      let nextEvent = null;

      for (let i = groupedEvents.length - 1; i >= 0; i--) {
        if (groupedEvents[i].start < w.start && groupedEvents[i].code !== 'NA Whistle') {
          previousEvent = groupedEvents[i];
          break;
        }
      }

      for (let i = 0; i < groupedEvents.length; i++) {
        if (groupedEvents[i].start > w.start && groupedEvents[i].code !== 'NA Whistle') {
          nextEvent = groupedEvents[i];
          break;
        }
      }

      return {
        id: w.id,
        index,
        start: w.start,
        time: formatSeconds(w.start),
        previousEvent: previousEvent
          ? {
              id: previousEvent.id,
              start: previousEvent.start,
              time: formatSeconds(previousEvent.start),
              code: previousEvent.code,
            }
          : null,
        nextEvent: nextEvent
          ? {
              id: nextEvent.id,
              start: nextEvent.start,
              time: formatSeconds(nextEvent.start),
              code: nextEvent.code,
            }
          : null,
      };
    });

  // ========== STEP 5: Automatic Anchor Detection ==========
  let half1Whistle = null;
  let half2Whistle = null;
  let halftimeWhistle = null;
  let autoDetectionUsed = false;
  let manualSelectionUsed = false;
  let detectionReason = '';
  const validationMessages = [];

  if (selectedWhistles) {
    // User provided manual selection
    manualSelectionUsed = true;

    // Resolve half1
    if (selectedWhistles.half1) {
      const sel = selectedWhistles.half1;
      if (sel.id) {
        half1Whistle = whistles.find((w) => w.id === sel.id);
      } else if (typeof sel.start === 'number') {
        half1Whistle = whistles.find((w) => Math.abs(w.start - sel.start) < 0.1);
      }
    }

    // Resolve half2
    if (selectedWhistles.half2) {
      const sel = selectedWhistles.half2;
      if (sel.id) {
        half2Whistle = whistles.find((w) => w.id === sel.id);
      } else if (typeof sel.start === 'number') {
        half2Whistle = whistles.find((w) => Math.abs(w.start - sel.start) < 0.1);
      }
    }

    if (!half1Whistle || !half2Whistle) {
      return {
        status: 'error',
        events: [],
        whistles,
        warnings: [],
        diagnostics: {
          parser: 'gaelic-insights',
          rawInstanceCount: instanceNodes.length,
          uniqueEventCount: groupedEvents.length,
          whistleCount: whistles.length,
          autoDetectionUsed,
          manualSelectionUsed,
        },
        error: 'Could not resolve manually selected whistles',
      };
    }

    // Manual validation
    if (half1Whistle.id === half2Whistle.id) {
      return {
        status: 'error',
        events: [],
        whistles,
        warnings: ['Selected 1H and 2H whistles are the same'],
        diagnostics: {
          parser: 'gaelic-insights',
          rawInstanceCount: instanceNodes.length,
          uniqueEventCount: groupedEvents.length,
          whistleCount: whistles.length,
          autoDetectionUsed,
          manualSelectionUsed,
        },
        error: 'Selected 1H and 2H whistles must be different',
      };
    }

    if (half2Whistle.start <= half1Whistle.start) {
      return {
        status: 'error',
        events: [],
        whistles,
        warnings: ['Selected 2H whistle occurs before or at selected 1H whistle'],
        diagnostics: {
          parser: 'gaelic-insights',
          rawInstanceCount: instanceNodes.length,
          uniqueEventCount: groupedEvents.length,
          whistleCount: whistles.length,
          autoDetectionUsed,
          manualSelectionUsed,
        },
        error: 'Selected 2H whistle must occur after selected 1H whistle',
      };
    }

    // Find halftime whistle (latest whistle before 2H)
    halftimeWhistle = null;
    for (let i = whistles.length - 1; i >= 0; i--) {
      if (whistles[i].start > half1Whistle.start && whistles[i].start < half2Whistle.start) {
        halftimeWhistle = whistles[i];
        break;
      }
    }

    validationMessages.push('Manual selection used');
  } else {
    // Automatic detection
    if (whistles.length < 2) {
      return {
        status: 'error',
        events: [],
        whistles,
        warnings: [`Found only ${whistles.length} whistle(s); need at least 2`],
        diagnostics: {
          parser: 'gaelic-insights',
          rawInstanceCount: instanceNodes.length,
          uniqueEventCount: groupedEvents.length,
          whistleCount: whistles.length,
          autoDetectionUsed,
          manualSelectionUsed,
        },
        error: 'Not enough NA Whistle events to anchor both halves',
      };
    }

    if (whistles.length === 4) {
      // Validate 4-whistle pattern
      const W1 = whistles[0];
      const W2 = whistles[1];
      const W3 = whistles[2];
      const W4 = whistles[3];

      const h1Duration = W2.start - W1.start;
      const h2Duration = W4.start - W3.start;
      const halftimeGap = W3.start - W2.start;

      // Validation rules
      const h1DurationOk = h1Duration >= 1800 && h1Duration <= 2700;
      const h2DurationOk = h2Duration >= 1800 && h2Duration <= 3000;
      const sequenceOk = W3.start > W2.start;

      if (h1DurationOk && h2DurationOk && sequenceOk) {
        // All validation passes
        half1Whistle = W1;
        half2Whistle = W3;
        halftimeWhistle = W2;
        autoDetectionUsed = true;
        detectionReason = 'Auto-detected 4-whistle pattern';
        validationMessages.push(
          `H1 duration: ${(h1Duration / 60).toFixed(1)} min`,
          `H2 duration: ${(h2Duration / 60).toFixed(1)} min`,
          `Halftime gap: ${halftimeGap.toFixed(2)} sec`
        );
      } else {
        // Validation failed
        if (!h1DurationOk) {
          validationMessages.push(
            `H1 duration ${(h1Duration / 60).toFixed(1)} min out of range (30-45 min)`
          );
        }
        if (!h2DurationOk) {
          validationMessages.push(
            `H2 duration ${(h2Duration / 60).toFixed(1)} min out of range (30-50 min)`
          );
        }
        if (!sequenceOk) {
          validationMessages.push('W3 does not occur after W2');
        }

        return {
          status: 'needs_whistle_selection',
          events: [],
          whistles,
          warnings: validationMessages,
          diagnostics: {
            parser: 'gaelic-insights',
            rawInstanceCount: instanceNodes.length,
            uniqueEventCount: groupedEvents.length,
            whistleCount: whistles.length,
            autoDetectionUsed: false,
            manualSelectionUsed: false,
            validation: {
              fourWhistlePattern: false,
              firstHalfDurationSeconds: h1Duration,
              secondHalfDurationSeconds: h2Duration,
              halftimeGapSeconds: halftimeGap,
              messages: validationMessages,
            },
          },
          reason: 'Four-whistle validation failed; manual selection required',
        };
      }
    } else {
      // Not exactly 4 whistles
      return {
        status: 'needs_whistle_selection',
        events: [],
        whistles,
        warnings: [`Found ${whistles.length} whistle(s); expected 4. Manual selection required.`],
        diagnostics: {
          parser: 'gaelic-insights',
          rawInstanceCount: instanceNodes.length,
          uniqueEventCount: groupedEvents.length,
          whistleCount: whistles.length,
          autoDetectionUsed: false,
          manualSelectionUsed: false,
        },
        reason: `Ambiguous whistle count (${whistles.length}); please select 1H and 2H anchors manually`,
      };
    }
  }

  // ========== STEP 7: Offset Calculation ==========
  const offset1H = half1Video - half1Whistle.start;
  const offset2H = half2Video - half2Whistle.start;

  // ========== STEP 9: Event Classification & Step 10: Event Timing ==========
  const SECOND_HALF_PRE_WHISTLE_TOLERANCE_SECONDS = 10;

  const parsedEvents = [];

  for (const event of groupedEvents) {
    // Skip whistles
    if (event.code === 'NA Whistle') continue;

    // Classify into half
    let half = '1st Half';
    if (event.start > halftimeWhistle?.start ?? half2Whistle.start - 1000) {
      // Default: if after halftime whistle (or 2H whistle if no halftime)
      half = '2nd Half';
    }

    // Apply tolerance for pre-2H events
    if (
      halftimeWhistle &&
      event.start > halftimeWhistle.start &&
      event.start >= half2Whistle.start - SECOND_HALF_PRE_WHISTLE_TOLERANCE_SECONDS
    ) {
      half = '2nd Half';
    } else if (
      !halftimeWhistle &&
      event.start >= half2Whistle.start - SECOND_HALF_PRE_WHISTLE_TOLERANCE_SECONDS
    ) {
      half = '2nd Half';
    }

    // Calculate timing
    let rawGameClockSeconds;
    let offset;
    if (half === '1st Half') {
      offset = offset1H;
      rawGameClockSeconds = event.start - half1Whistle.start;
    } else {
      offset = offset2H;
      rawGameClockSeconds = event.start - half2Whistle.start;
    }

    const trueVideoTime = event.start + offset;
    const gameClockSeconds = Math.max(0, Math.round(rawGameClockSeconds));

    // Format game clock
    const minutes = Math.floor(gameClockSeconds / 60);
    const seconds = gameClockSeconds % 60;
    const gameTime = `${half.split(' ')[0].charAt(0)}H ${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

    // Extract team and other fields
    const team = extractTeam(event.code, homeTeam, awayTeam);
    const player = event.labels['Player'] || '';
    const outcome = event.labels['Outcome'] || '';
    const subtype = event.labels['Description'] || event.labels['Kickout_Length'] || '';
    const category = extractCategory(event.code);

    parsedEvents.push({
      id: event.id,
      start: Math.round(event.start),
      end: Math.round(event.end),
      half,
      gameTime,
      code: event.code,
      team,
      player,
      outcome,
      subtype,
      category,
      driveT: Math.max(0, Math.round(trueVideoTime) - seekPrerollSeconds),
      videoT: Math.max(0, Math.round(trueVideoTime)),
      labels: event.labels,
    });
  }

  // ========== STEP 12: Build Sample Events ==========
  const sampleEvents = {
    firstHalf: parsedEvents.filter((e) => e.half === '1st Half').slice(0, 3),
    secondHalf: parsedEvents.filter((e) => e.half === '2nd Half').slice(0, 3),
  };

  // ========== STEP 13: Diagnostics ==========
  const diagnostics = {
    parser: 'gaelic-insights',
    rawInstanceCount: instanceNodes.length,
    uniqueEventCount: groupedEvents.length,
    whistleCount: whistles.length,
    autoDetectionUsed,
    manualSelectionUsed,
    selectedAnchors: {
      half1: {
        id: half1Whistle.id,
        xmlStart: half1Whistle.start,
        xmlTime: half1Whistle.time,
        userVideoStart: half1Video,
        offset: offset1H,
      },
      half2: {
        id: half2Whistle.id,
        xmlStart: half2Whistle.start,
        xmlTime: half2Whistle.time,
        userVideoStart: half2Video,
        offset: offset2H,
      },
      halftime: halftimeWhistle
        ? {
            id: halftimeWhistle.id,
            xmlStart: halftimeWhistle.start,
            xmlTime: halftimeWhistle.time,
          }
        : null,
    },
    validation: {
      fourWhistlePattern: whistles.length === 4,
      firstHalfDurationSeconds: whistles.length >= 2 ? whistles[1].start - whistles[0].start : null,
      secondHalfDurationSeconds:
        whistles.length >= 4 ? whistles[3].start - whistles[2].start : null,
      halftimeGapSeconds: whistles.length >= 3 ? whistles[2].start - whistles[1].start : null,
      messages: validationMessages,
    },
    sampleEvents,
  };

  // ========== STEP 14: Warnings ==========
  const warnings = [];
  if (whistles.length !== 4 && !manualSelectionUsed) {
    warnings.push(
      `Expected exactly 4 NA Whistle events but found ${whistles.length}. Manual selection required.`
    );
  }

  // Check for pre-2H tolerance violations
  for (const event of parsedEvents) {
    if (event.half === '2nd Half') {
      const xmlStart = groupedEvents.find((e) => e.id === event.id)?.start;
      if (xmlStart && xmlStart < half2Whistle.start) {
        const gap = half2Whistle.start - xmlStart;
        if (gap > 0 && gap <= SECOND_HALF_PRE_WHISTLE_TOLERANCE_SECONDS) {
          warnings.push(
            `Event ${event.id} (${event.code}) starts ${gap.toFixed(2)}s before 2H whistle; classified using tolerance`
          );
        }
      }
    }
  }

  return {
    status: 'ok',
    events: parsedEvents,
    whistles,
    warnings,
    diagnostics,
  };
}

// ========== Helper Functions ==========

function parseXmlRegex(xmlText) {
  // Simple regex-based XML parser for Node.js environment
  // Extracts instances and their child elements
  const instances = [];
  const instanceRegex = /<instance>([\s\S]*?)<\/instance>/g;
  let match;

  while ((match = instanceRegex.exec(xmlText)) !== null) {
    const instanceContent = match[1];
    const instance = {};

    // Extract ID
    const idMatch = instanceContent.match(/<ID>(.*?)<\/ID>/);
    instance.ID = idMatch ? idMatch[1].trim() : '';

    // Extract start
    const startMatch = instanceContent.match(/<start>(.*?)<\/start>/);
    instance.start = startMatch ? startMatch[1].trim() : '0';

    // Extract end
    const endMatch = instanceContent.match(/<end>(.*?)<\/end>/);
    instance.end = endMatch ? endMatch[1].trim() : '0';

    // Extract code
    const codeMatch = instanceContent.match(/<code>(.*?)<\/code>/);
    instance.code = codeMatch ? codeMatch[1].trim() : '';

    // Extract labels
    instance.labels = {};
    const labelRegex = /<label>([\s\S]*?)<\/label>/g;
    let labelMatch;
    while ((labelMatch = labelRegex.exec(instanceContent)) !== null) {
      const labelContent = labelMatch[1];
      const groupMatch = labelContent.match(/<group>(.*?)<\/group>/);
      const textMatch = labelContent.match(/<text>(.*?)<\/text>/);
      const group = groupMatch ? groupMatch[1].trim() : '';
      const text = textMatch ? textMatch[1].trim() : '';
      if (group && text) {
        instance.labels[group] = text;
      }
    }

    instances.push(instance);
  }

  // Create pseudo-DOM nodes with querySelector support
  const nodeList = instances.map((i) => createPseudoDOMNode(i));

  // Return pseudo-DOM object
  return {
    querySelectorAll: (selector) => {
      if (selector === 'instance') {
        return nodeList;
      }
      return [];
    },
  };
}

function createPseudoDOMNode(data) {
  return {
    querySelector: (q) => {
      const field = q.toLowerCase();
      let value = '';
      if (field === 'id') value = data.ID;
      else if (field === 'start') value = data.start;
      else if (field === 'end') value = data.end;
      else if (field === 'code') value = data.code;
      else if (data.labels && data.labels[field]) value = data.labels[field];

      return {
        textContent: value,
      };
    },
    querySelectorAll: (q) => {
      if (q === 'label') {
        return Object.entries(data.labels || {}).map(([group, text]) => ({
          querySelector: (qq) => {
            return {
              textContent: qq === 'group' ? group : text,
            };
          },
        }));
      }
      return [];
    },
  };
}

function formatSeconds(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 100);

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
  }
  return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
}

function extractTeam(code, homeTeam, awayTeam) {
  const upperCode = code.toUpperCase();
  const upperHome = homeTeam.toUpperCase();
  const upperAway = awayTeam.toUpperCase();

  if (upperCode.startsWith(upperHome)) return upperHome;
  if (upperCode.startsWith(upperAway)) return upperAway;
  return '';
}

function extractCategory(code) {
  if (code.includes('Shot')) return 'Shots & Scores';
  if (code.includes('Kickout')) return 'Kickouts';
  if (code.includes('Turnover')) return 'Turnovers';
  return 'Player Actions';
}

// Export for Node.js or browser
if (typeof module !== 'undefined' && module.exports) {
  module.exports = parseGaelicInsightsXml;
}
