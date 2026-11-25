// Turns raw strokes into the compact feature vector the backend's emotion model uses.
// A stroke is { color: '#rrggbb', width: px, points: [{ x, y, t }] } with t in ms.

const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);

/** Resamples a polyline to points `step` px apart so jitter doesn't count as jaggedness. */
export function resample(points, step = 8) {
  if (points.length < 2) return points.slice();
  const out = [points[0]];
  let acc = 0;
  for (let i = 1; i < points.length; i++) {
    const d = dist(points[i - 1], points[i]);
    acc += d;
    if (acc >= step) {
      out.push(points[i]);
      acc = 0;
    }
  }
  if (out[out.length - 1] !== points[points.length - 1]) out.push(points[points.length - 1]);
  return out;
}

export function strokeLength(points) {
  let len = 0;
  for (let i = 1; i < points.length; i++) len += dist(points[i - 1], points[i]);
  return len;
}

/** Mean absolute turning angle between consecutive segments, normalized to 0..1. */
export function turning(points) {
  const p = resample(points);
  let sum = 0;
  let n = 0;
  for (let i = 2; i < p.length; i++) {
    const a1 = Math.atan2(p[i - 1].y - p[i - 2].y, p[i - 1].x - p[i - 2].x);
    const a2 = Math.atan2(p[i].y - p[i - 1].y, p[i].x - p[i - 1].x);
    let d = Math.abs(a2 - a1);
    if (d > Math.PI) d = 2 * Math.PI - d;
    sum += d;
    n++;
  }
  return n ? sum / n / Math.PI : 0;
}

export function extractFeatures(strokes, width, height) {
  const real = strokes.filter((s) => s.points.length > 1);
  if (!real.length) return null;

  const inkByColor = {};
  let totalLen = 0;
  let totalTime = 0;
  let jagSum = 0;
  let jagWeight = 0;
  let ink = 0;
  let widthSum = 0;

  for (const s of real) {
    const len = strokeLength(s.points);
    const time = Math.max(1, s.points[s.points.length - 1].t - s.points[0].t);
    const area = len * s.width;
    inkByColor[s.color] = (inkByColor[s.color] || 0) + area;
    totalLen += len;
    totalTime += time;
    ink += area;
    widthSum += s.width;
    if (len > 20) {
      jagSum += turning(s.points) * len;
      jagWeight += len;
    }
  }

  const colors = Object.entries(inkByColor)
    .map(([hex, a]) => ({ hex, weight: +(a / ink).toFixed(4) }))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 8);

  const first = real[0].points[0].t;
  const last = real[real.length - 1].points.at(-1).t;

  return {
    colors,
    strokeCount: real.length,
    avgSpeed: +(totalLen / totalTime).toFixed(3), // px per ms while the pen is down
    jaggedness: +(jagWeight ? Math.min(1, (jagSum / jagWeight) * 2.5) : 0).toFixed(3),
    coverage: +Math.min(1, ink / (width * height)).toFixed(4),
    avgWidth: +(widthSum / real.length).toFixed(1),
    durationMs: Math.round(last - first),
  };
}
