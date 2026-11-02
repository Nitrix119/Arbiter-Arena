// Checks for initialMatch in web/static/js/playback-data.js, run by
// tests/test_web_playback_site.py under node. The pytest wrapper copies
// playback-data.js beside this file as playback-data.mjs.
import assert from 'node:assert/strict';
import { initialMatch } from './playback-data.mjs';

const featured = [
    { file: 'first.jsonl', label: 'First' },
    { file: 'second.jsonl', label: 'Second' },
];
const FALLBACK = 'sample_match.jsonl';

// A valid ?match= name wins, featured or not, so any bundled match can be linked.
assert.equal(initialMatch('second.jsonl', featured, FALLBACK), 'second.jsonl');
assert.equal(initialMatch('other_match.jsonl', featured, FALLBACK), 'other_match.jsonl');

// No ?match=: open the first featured match, so a visitor lands on something worth seeing.
assert.equal(initialMatch(null, featured, FALLBACK), 'first.jsonl');
assert.equal(initialMatch('', featured, FALLBACK), 'first.jsonl');

// No featured list (missing or failed to load): the bundled sample.
assert.equal(initialMatch(null, [], FALLBACK), FALLBACK);
assert.equal(initialMatch(null, null, FALLBACK), FALLBACK);

// Anything that is not a bare .jsonl name is ignored, so the page never fetches
// outside the matches folder.
for (const bad of ['../secrets.jsonl', 'a/b.jsonl', 'x.json', 'https://e.com/a.jsonl', 'a b.jsonl']) {
    assert.equal(initialMatch(bad, featured, FALLBACK), 'first.jsonl', bad);
}

console.log('playback checks passed');
