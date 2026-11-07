// Monochrome ramps, mirroring chaos_lab.rendering.palettes.GRADIENTS.
// There is deliberately no hue anywhere in the interface: series and
// trajectories are told apart by grey level, opacity and dash pattern.

const hex = (h) => {
  const n = parseInt(h.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

export const PALETTES = {
  auto: { label: "Theme", stops: null }, // white on dark, black on light
  white: { label: "White", stops: ["#3c3c3c", "#ffffff"] }, // trails on black
  silver: { label: "Silver", stops: ["#262626", "#c8c8c8"] },
  black: { label: "Black", stops: ["#bdbdbd", "#000000"] }, // trails on white
  gray: { label: "Gray", stops: ["#000000", "#ffffff"] },
};

// Scientific maps: a single greyscale ramp per theme. The ramp starts at fg_4
// (not pure bg) so that NaN pixels ("no event") stay distinguishable.
export const COLORMAPS = {
  auto: null,
  gray: ["#2e2e2e", "#ffffff"],
  "gray-light": ["#d6d6d6", "#000000"],
  "gray-full": ["#000000", "#ffffff"],
};

export function isLight() { return document.documentElement.dataset.theme === "light"; }

/** Resolve a palette name to stops that stay legible on the given background. */
export function paletteStops(name, _custom, light = isLight()) {
  if (!PALETTES[name] || name === "auto") return light ? PALETTES.black.stops : PALETTES.white.stops;
  if (light && (name === "white" || name === "silver")) return PALETTES.black.stops;
  if (!light && name === "black") return PALETTES.white.stops;
  return PALETTES[name].stops;
}

const cache = new Map();
function lut(stops, n = 256) {
  const key = stops.join(",");
  if (cache.has(key)) return cache.get(key);
  const rgb = stops.map(hex);
  const out = new Uint8ClampedArray(n * 3);
  for (let i = 0; i < n; i++) {
    const u = (i / (n - 1)) * (rgb.length - 1);
    const k = Math.min(rgb.length - 2, Math.floor(u));
    const f = u - k;
    for (let c = 0; c < 3; c++) out[i * 3 + c] = rgb[k][c] + (rgb[k + 1][c] - rgb[k][c]) * f;
  }
  cache.set(key, out);
  return out;
}

export function sampler(stops) {
  const L = lut(stops);
  return (u) => {
    const i = Math.max(0, Math.min(255, Math.round((Number.isFinite(u) ? u : 0) * 255))) * 3;
    return [L[i], L[i + 1], L[i + 2]];
  };
}

/** n distinguishable grey tones for ensembles (bright → mid grey on dark, inverse on light). */
export function distinct(n, light = isLight()) {
  const lo = light ? 0 : 255, hi = light ? 150 : 90;
  return Array.from({ length: n }, (_, k) => { const v = Math.round(lo + (hi - lo) * (n === 1 ? 0 : k / (n - 1))); return [v, v, v]; });
}

export function cssGradient(stops) {
  return `linear-gradient(90deg, ${stops.map((s, i) => `${s} ${(i / (stops.length - 1)) * 100}%`).join(", ")})`;
}

export function rgba([r, g, b], a = 1) {
  return `rgba(${r | 0},${g | 0},${b | 0},${a})`;
}

export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

export function colormapLUT(name) {
  if (!COLORMAPS[name]) return lut(isLight() ? COLORMAPS["gray-light"] : COLORMAPS.gray);
  return lut(COLORMAPS[name]);
}

/** Background colour for NaN map pixels: the page background. */
export function nanRGB() { return isLight() ? [255, 255, 255] : [0, 0, 0]; }

/** Dash patterns used to separate chart series without colour. */
export const DASHES = [[], [6, 4], [2, 3], [10, 3, 2, 3], [1, 2], [14, 4]];

/** Grey levels (as CSS tokens) cycled with DASHES for multi-series charts. */
export function seriesStyle(i) {
  return { color: token(["fg", "fg-2", "fg-3", "fg-2", "fg", "fg-3"][i % 6]), dash: DASHES[i % DASHES.length] };
}
