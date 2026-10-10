// ── Camera maths shared by the battle and playback pages ────────────────────
// Pure functions over a camera { x, y, zoom }: x/y is the screen position of the
// world origin, and one cell is cellPx * zoom pixels wide. They touch no DOM and
// import nothing, so they can be checked in isolation (node) and each page passes
// in its own limits from state.js.

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Zoom by a wheel delta, keeping the world point under (sx, sy) fixed on screen. */
export function zoomAt(camera, sx, sy, deltaY, { min, max, speed }) {
    const oldZoom = camera.zoom;
    camera.zoom = clamp(oldZoom - deltaY * speed * oldZoom, min, max);
    const k = camera.zoom / oldZoom;
    camera.x = sx - (sx - camera.x) * k;
    camera.y = sy - (sy - camera.y) * k;
}

/**
 * The part of the viewport no overlay covers: the band right of every left-side
 * panel, left of every right-side one, below the top ones and above the bottom ones.
 * Overlays are DOMRect-like ({ left, right, top, bottom }). If the band is too small
 * to show anything (a narrow window), the whole viewport is returned instead, since
 * a board drawn under the panels beats one squeezed to nothing.
 */
export function uncoveredRect(viewport, overlays, { margin = 0, minSize = 160 } = {}) {
    const { left = [], right = [], top = [], bottom = [] } = overlays;
    const l = Math.max(0, ...left.map((r) => r.right)) + margin;
    const r = Math.min(viewport.width, ...right.map((o) => o.left)) - margin;
    const t = Math.max(0, ...top.map((o) => o.bottom)) + margin;
    const b = Math.min(viewport.height, ...bottom.map((o) => o.top)) - margin;
    if (r - l < minSize || b - t < minSize) {
        return { left: 0, top: 0, width: viewport.width, height: viewport.height };
    }
    return { left: l, top: t, width: r - l, height: b - t };
}

/** Centre world bounds (in cells) in a screen rect, at the largest zoom that fits. */
export function fitToRect(camera, bounds, rect, { cellPx, pad, min, max, maxFit }) {
    const worldW = (bounds.maxX - bounds.minX) + pad * 2;
    const worldH = (bounds.maxY - bounds.minY) + pad * 2;
    const zoom = clamp(
        Math.min(rect.width / (worldW * cellPx), rect.height / (worldH * cellPx), maxFit),
        min, max,
    );
    camera.zoom = zoom;
    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    camera.x = rect.left + rect.width / 2 - cx * cellPx * zoom;
    camera.y = rect.top + rect.height / 2 - cy * cellPx * zoom;
}
