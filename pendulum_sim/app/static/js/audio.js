// Optional sonification. An artistic/educational mapping of simulation
// observables to synthesized sound — the pendulum does not emit these sounds.
//
//   pitch   ← |ω₂| (log-mapped to 110–880 Hz)
//   volume  ← endpoint speed |v₂|
//   timbre  ← kinetic-energy fraction T/Tmax (low-pass cutoff)
//   stereo  ← horizontal position x₂ / (L₁+L₂)
//   clicks  ← each over-the-top rotation of either arm

import { lerpAt, state } from "./state.js";

let ac = null, osc, osc2, gain, filt, pan, master;
let lastFi = null;

function init() {
  ac = new (window.AudioContext || window.webkitAudioContext)();
  master = ac.createGain(); master.gain.value = 0;
  pan = ac.createStereoPanner ? ac.createStereoPanner() : ac.createGain();
  filt = ac.createBiquadFilter(); filt.type = "lowpass"; filt.Q.value = 6;
  gain = ac.createGain(); gain.gain.value = 0;
  osc = ac.createOscillator(); osc.type = "sawtooth";
  osc2 = ac.createOscillator(); osc2.type = "sine";
  osc.connect(filt); osc2.connect(filt); filt.connect(gain); gain.connect(pan); pan.connect(master); master.connect(ac.destination);
  osc.start(); osc2.start();
}

export function setSound(on) {
  if (on && !ac) init();
  if (!ac) return;
  if (on) ac.resume();
  master.gain.setTargetAtTime(on ? state.prefs.volume : 0, ac.currentTime, 0.05);
}

export function setVolume(v) {
  if (ac && state.prefs.sound) master.gain.setTargetAtTime(v, ac.currentTime, 0.05);
}

function click(strength = 1) {
  const n = ac.createBufferSource();
  const buf = ac.createBuffer(1, ac.sampleRate * 0.06, ac.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (ac.sampleRate * 0.008));
  n.buffer = buf;
  const g = ac.createGain(); g.gain.value = 0.5 * strength;
  n.connect(g); g.connect(master); n.start();
}

/** Update the voice for the current playback position (fractional sample index). */
export function sonify(fi, playing) {
  const s = state.sim;
  if (!ac || !state.prefs.sound || !s) return;
  const now = ac.currentTime;
  if (!playing) { gain.gain.setTargetAtTime(0, now, 0.05); lastFi = fi; return; }
  const w2 = Math.abs(lerpAt(s.w2, fi));
  const f = 110 * Math.pow(8, Math.min(1, Math.log1p(w2) / Math.log1p(20)));
  osc.frequency.setTargetAtTime(f, now, 0.03);
  osc2.frequency.setTargetAtTime(f * 0.5, now, 0.03);
  const sp = lerpAt(s.speed2, fi) / (s.maxSpeed || 1);
  gain.gain.setTargetAtTime(0.05 + 0.25 * sp, now, 0.04);
  const ke = lerpAt(s.T, fi) / (s.maxT || 1);
  filt.frequency.setTargetAtTime(300 + 4000 * ke, now, 0.05);
  const R = s.p.L1 + s.p.L2;
  if (pan.pan) pan.pan.setTargetAtTime(Math.max(-1, Math.min(1, lerpAt(s.x2, fi) / R)), now, 0.05);
  if (lastFi !== null && Math.abs(fi - lastFi) < 400) {
    const wi = (a) => Math.floor((a + Math.PI) / (2 * Math.PI));
    for (const arr of [s.th1, s.th2]) if (wi(lerpAt(arr, lastFi)) !== wi(lerpAt(arr, fi))) click(arr === s.th1 ? 1 : 0.6);
  }
  lastFi = fi;
}
