// Checks for web/static/js/camera.js, run by tests/test_web_camera.py under node.
// The pytest wrapper copies camera.js beside this file as camera.mjs, so node
// loads both as ES modules without a package.json in the served static folder.
import assert from 'node:assert/strict';
import { zoomAt, uncoveredRect, fitToRect } from './camera.mjs';
const lim = { min: 0.1, max: 8, speed: 0.001 };

// zoomAt matches the battle page's original formula, and keeps the point under the cursor fixed.
const cam = { x: 100, y: 50, zoom: 1 };
const before = { wx: (300 - cam.x) / cam.zoom, wy: (200 - cam.y) / cam.zoom };
zoomAt(cam, 300, 200, -100, lim);
assert.equal(cam.zoom, 1 + 100 * 0.001 * 1);
assert.ok(Math.abs((300 - cam.x) / cam.zoom - before.wx) < 1e-9);
assert.ok(Math.abs((200 - cam.y) / cam.zoom - before.wy) < 1e-9);
// clamped at the limits
const c2 = { x: 0, y: 0, zoom: 7.9 }; zoomAt(c2, 0, 0, -1e6, lim); assert.equal(c2.zoom, 8);
const c3 = { x: 0, y: 0, zoom: 0.2 }; zoomAt(c3, 0, 0, 1e6, lim); assert.equal(c3.zoom, 0.1);

// uncoveredRect: the band between panels
const vp = { width: 1600, height: 900 };
const r = uncoveredRect(vp, {
    left: [{ left: 16, right: 356, top: 64, bottom: 804 }],
    right: [{ left: 1350, right: 1580, top: 200, bottom: 700 }],
    top: [{ left: 500, right: 1100, top: 14, bottom: 90 }],
    bottom: [{ left: 500, right: 1100, top: 820, bottom: 876 }],
}, { margin: 10 });
assert.deepEqual(r, { left: 366, top: 100, width: 974, height: 710 });
// no overlays: whole viewport
assert.deepEqual(uncoveredRect(vp, {}), { left: 0, top: 0, width: 1600, height: 900 });
// a squeezed band falls back to the whole viewport
assert.deepEqual(
    uncoveredRect({ width: 500, height: 900 }, { left: [{ right: 300 }], right: [{ left: 350 }] }),
    { left: 0, top: 0, width: 500, height: 900 });

// fitToRect: bounds land centred in the rect, wholly inside it
const cam2 = { x: 0, y: 0, zoom: 1 };
const b = { minX: 2, maxX: 12, minY: 0, maxY: 4 };
fitToRect(cam2, b, r, { cellPx: 50, pad: 1.5, min: 0.1, max: 8, maxFit: 1.4 });
const sx = (x) => x * 50 * cam2.zoom + cam2.x, sy = (y) => y * 50 * cam2.zoom + cam2.y;
assert.ok(Math.abs((sx(2) + sx(12)) / 2 - (r.left + r.width / 2)) < 1e-9);
assert.ok(Math.abs((sy(0) + sy(4)) / 2 - (r.top + r.height / 2)) < 1e-9);
assert.ok(sx(2) >= r.left && sx(12) <= r.left + r.width && sy(0) >= r.top && sy(4) <= r.top + r.height);
console.log('camera.js: all checks pass');
