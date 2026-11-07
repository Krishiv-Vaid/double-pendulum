// Trail palettes (artistic) and scientific colormaps.
// All palettes are colour stops sampled by u in [0, 1].

const hex = (h) => {
  const n = parseInt(h.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

export const PALETTES = {
  rainbow: { label: "Rainbow", stops: ["#ff3c6e", "#ff9f1c", "#ffe14d", "#39ff88", "#00e5ff", "#5b6cff", "#a855f7", "#ff3cac"] },
  neon: { label: "Neon", stops: ["#00e5ff", "#a855f7", "#ff3cac"] },
  cyan: { label: "Cyan glow", stops: ["#004b5c", "#00e5ff", "#d4fbff"] },
  magenta: { label: "Magenta glow", stops: ["#4a0038", "#ff3cac", "#ffd6ee"] },
  purple: { label: "Purple glow", stops: ["#24104a", "#a855f7", "#efe2ff"] },
  fire: { label: "Fire", stops: ["#3a0500", "#c81d00", "#ff6a00", "#ffb300", "#fff4c2"] },
  ice: { label: "Ice", stops: ["#021a3a", "#0063d1", "#38b6ff", "#a8ecff", "#ffffff"] },
  plasma: { label: "Plasma", stops: ["#0d0887", "#46039f", "#7201a8", "#9c179e", "#bd3786", "#d8576b", "#ed7953", "#fb9f3a", "#fdca26", "#f0f921"] },
  aurora: { label: "Aurora", stops: ["#0b3d2e", "#39ff88", "#00e5ff", "#a855f7"] },
  gold: { label: "Gold", stops: ["#3d2a00", "#b8860b", "#ffd166", "#fff4d6"] },
  mono: { label: "Monochrome", stops: ["#5d6475", "#ffffff"] },
  viridis: { label: "Viridis (CVD-safe)", stops: ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"] },
  cividis: { label: "Cividis (CVD-safe)", stops: ["#00224e", "#123570", "#3b496c", "#575d6d", "#707173", "#8a8779", "#a69d75", "#c4b56c", "#e4cf5b", "#fee838"] },
  custom: { label: "Custom", stops: ["#00e5ff", "#a855f7", "#ff3cac"] },
};

export const COLORMAPS = {
  viridis: PALETTES.viridis.stops,
  magma: ["#000004", "#180f3d", "#440f76", "#721f81", "#9e2f7f", "#cd4071", "#f1605d", "#fd9668", "#feca8d", "#fcfdbf"],
  inferno: ["#000004", "#1b0c41", "#4a0c6b", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06", "#f7d13d", "#fcffa4"],
  plasma: PALETTES.plasma.stops,
  cividis: PALETTES.cividis.stops,
  turbo: ["#30123b", "#4662d7", "#36aaf9", "#1ae4b6", "#72fe5e", "#c8ef34", "#faba39", "#f66b19", "#ca2a04", "#7a0403"],
  twilight: ["#e2d9e2", "#9ebbc9", "#6276ba", "#5a3c9a", "#2f1436", "#5a1d38", "#a6503a", "#d1a07e", "#e2d9e2"],
  neon: ["#070910", "#2a0f5c", "#a855f7", "#ff3cac", "#ffd166", "#ffffff"],
  gray: ["#000000", "#ffffff"],
};

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

export function paletteStops(name, custom) {
  if (name === "custom" && custom && custom.length >= 2) return custom;
  return (PALETTES[name] || PALETTES.rainbow).stops;
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
  return lut(COLORMAPS[name] || COLORMAPS.viridis);
}
