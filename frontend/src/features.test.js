import { describe, expect, test } from 'vitest';
import { extractFeatures, turning } from './features.js';

const line = (n, dx, dy, dt, color = '#ff0000', width = 6) => ({
  color,
  width,
  points: Array.from({ length: n }, (_, i) => ({ x: 10 + i * dx, y: 10 + i * dy, t: i * dt })),
});

const zigzag = (n, color = '#000000') => ({
  color,
  width: 6,
  points: Array.from({ length: n }, (_, i) => ({ x: 10 + i * 12, y: i % 2 ? 40 : 10, t: i * 5 })),
});

describe('features', () => {
  test('straight lines have ~0 turning, zigzags have high turning', () => {
    expect(turning(line(50, 4, 0, 10).points)).toBeLessThan(0.05);
    expect(turning(zigzag(40).points)).toBeGreaterThan(0.4);
  });

  test('speed reflects pen speed', () => {
    const slow = extractFeatures([line(50, 2, 0, 20)], 800, 600);
    const fast = extractFeatures([line(50, 10, 0, 5)], 800, 600);
    expect(fast.avgSpeed).toBeGreaterThan(slow.avgSpeed * 10);
  });

  test('color weights are proportional to ink and sum to 1', () => {
    const f = extractFeatures([line(50, 4, 0, 10, '#ff0000'), line(50, 4, 0, 10, '#0000ff', 18)], 800, 600);
    expect(f.colors[0].hex).toBe('#0000ff');
    expect(f.colors[0].weight).toBeCloseTo(0.75, 2);
    expect(f.colors.reduce((a, c) => a + c.weight, 0)).toBeCloseTo(1, 3);
  });

  test('empty canvas gives null', () => {
    expect(extractFeatures([], 800, 600)).toBeNull();
    expect(extractFeatures([{ color: '#fff', width: 4, points: [{ x: 1, y: 1, t: 0 }] }], 800, 600)).toBeNull();
  });
});
