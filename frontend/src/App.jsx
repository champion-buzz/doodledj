import { useCallback, useEffect, useRef, useState } from 'react';
import { extractFeatures } from './features.js';

const PALETTE = [
  { hex: '#ffd400', name: 'Sunshine' },
  { hex: '#ff7a00', name: 'Tangerine' },
  { hex: '#e63946', name: 'Red' },
  { hex: '#ff6fb5', name: 'Pink' },
  { hex: '#7b2cbf', name: 'Violet' },
  { hex: '#3a86ff', name: 'Blue' },
  { hex: '#a8d8ea', name: 'Sky' },
  { hex: '#2a9d8f', name: 'Teal' },
  { hex: '#80c904', name: 'Lime' },
  { hex: '#1b1f3b', name: 'Midnight' },
  { hex: '#6c757d', name: 'Grey' },
];
const SIZES = [3, 8, 16, 30];

function getSessionId() {
  const KEY = 'doodledj.session';
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

// ------------------------------------------------------------------ canvas

function SketchPad({ color, size, strokes, setStrokes, onStrokeEnd }) {
  const canvasRef = useRef(null);
  const current = useRef(null);

  const redraw = useCallback(() => {
    const c = canvasRef.current;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    const all = current.current ? [...strokes, current.current] : strokes;
    for (const s of all) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      s.points.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      if (s.points.length === 1) ctx.lineTo(s.points[0].x + 0.1, s.points[0].y);
      ctx.stroke();
    }
  }, [strokes]);

  // keep the canvas crisp on high-DPI screens while drawing in CSS pixels
  useEffect(() => {
    const c = canvasRef.current;
    const resize = () => {
      const { width, height } = c.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      c.width = width * dpr;
      c.height = height * dpr;
      c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
      redraw();
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, [redraw]);

  useEffect(redraw, [redraw]);

  const point = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now() };
  };

  const down = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    current.current = { color, width: size, points: [point(e)] };
    redraw();
  };
  const move = (e) => {
    if (!current.current) return;
    const events = e.nativeEvent.getCoalescedEvents ? e.nativeEvent.getCoalescedEvents() : [e];
    for (const ev of events) current.current.points.push(point(ev));
    redraw();
  };
  const up = () => {
    if (!current.current) return;
    const done = current.current;
    current.current = null;
    const next = [...strokes, done];
    setStrokes(next);
    onStrokeEnd(next, canvasRef.current.getBoundingClientRect());
  };

  return (
    <canvas
      ref={canvasRef}
      className="pad"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      aria-label="Drawing canvas"
    />
  );
}

// ------------------------------------------------------------------ mood + playlist

function MoodPlane({ valence, arousal }) {
  const x = 50 + valence * 42;
  const y = 50 - arousal * 42;
  return (
    <svg viewBox="0 0 100 100" className="plane" role="img" aria-label="Mood on the valence-arousal plane">
      <rect x="0" y="0" width="100" height="100" rx="8" className="plane-bg" />
      <line x1="50" y1="6" x2="50" y2="94" className="axis" />
      <line x1="6" y1="50" x2="94" y2="50" className="axis" />
      <text x="50" y="5" className="lbl" textAnchor="middle">energetic</text>
      <text x="50" y="99" className="lbl" textAnchor="middle">calm</text>
      <text x="2" y="53" className="lbl">sad</text>
      <text x="98" y="53" className="lbl" textAnchor="end">happy</text>
      <circle cx={x} cy={y} r="5" className="dot" />
    </svg>
  );
}

function MoodCard({ data, loading }) {
  if (!data) {
    return (
      <div className="card mood empty">
        <p>{loading ? 'Listening to your doodle…' : 'Start drawing. Your colors and strokes set the mood.'}</p>
      </div>
    );
  }
  const { mood, genres, timings } = data;
  return (
    <div className={`card mood mood-${mood.label}`}>
      <div className="mood-head">
        <span className="emoji">{mood.emoji}</span>
        <div>
          <h2>{mood.label}</h2>
          <p className="desc">{mood.description}</p>
        </div>
        <MoodPlane valence={mood.valence} arousal={mood.arousal} />
      </div>
      <div className="chips">
        {genres.map((g) => <span key={g} className="chip">{g}</span>)}
        <span className="chip subtle" title="How the mood was decided">{mood.source === 'llm' ? '🤖 LLM' : '🎨 color + motion model'}</span>
        <span className="chip subtle" title="Server time for this update">⚡ {Math.round(timings.totalMs)} ms</span>
      </div>
    </div>
  );
}

function Playlist({ tracks, playing, onPlay }) {
  if (!tracks?.length) return null;
  return (
    <ol className="card playlist">
      {tracks.map((t) => (
        <li key={t.id} className={playing === t.id ? 'playing' : ''}>
          {t.cover ? <img src={t.cover} alt="" loading="lazy" /> : <div className="cover-ph" />}
          <div className="meta">
            <strong>{t.title}</strong>
            <span>{t.artist}</span>
          </div>
          {t.preview && (
            <button className="play" onClick={() => onPlay(t)} aria-label={playing === t.id ? 'Pause preview' : 'Play preview'}>
              {playing === t.id ? '❚❚' : '▶'}
            </button>
          )}
          {t.link && <a className="open" href={t.link} target="_blank" rel="noreferrer" aria-label="Open on Deezer">↗</a>}
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------------ app

export default function App() {
  const [color, setColor] = useState(PALETTE[0].hex);
  const [size, setSize] = useState(8);
  const [strokes, setStrokes] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);
  const [playing, setPlaying] = useState(null);
  const audio = useRef(null);
  const inflight = useRef(null);
  const timer = useRef(null);
  const sessionId = useRef(getSessionId());

  const loadHistory = useCallback(() => {
    fetch(`/api/history/${sessionId.current}`)
      .then((r) => r.json())
      .then((d) => setHistory(d.items || []))
      .catch(() => {});
  }, []);

  useEffect(loadHistory, [loadHistory]);

  const requestPlaylist = useCallback((allStrokes, rect) => {
    const features = extractFeatures(allStrokes, rect.width, rect.height);
    if (!features) return;
    inflight.current?.abort(); // newest sketch wins
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setLoading(true);
    fetch('/api/playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ features, sessionId: sessionId.current }),
      signal: ctrl.signal,
    })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || 'Request failed');
        setData(body);
        setError(null);
        setTimeout(loadHistory, 150);
      })
      .catch((e) => e.name !== 'AbortError' && setError(e.message))
      .finally(() => inflight.current === ctrl && setLoading(false));
  }, [loadHistory]);

  // short debounce: a burst of quick strokes triggers one update
  const onStrokeEnd = useCallback((all, rect) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => requestPlaylist(all, rect), 250);
  }, [requestPlaylist]);

  const play = (t) => {
    if (!audio.current) {
      audio.current = new Audio();
      audio.current.onended = () => setPlaying(null);
    }
    if (playing === t.id) {
      audio.current.pause();
      setPlaying(null);
      return;
    }
    audio.current.src = t.preview;
    audio.current.play().then(() => setPlaying(t.id)).catch(() => setPlaying(null));
  };

  const undo = () => {
    const next = strokes.slice(0, -1);
    setStrokes(next);
    if (next.length) onStrokeEnd(next, document.querySelector('.pad').getBoundingClientRect());
    else setData(null);
  };
  const clear = () => {
    setStrokes([]);
    setData(null);
  };

  return (
    <div className="app">
      <header>
        <h1>🎧 DoodleDJ</h1>
        <p>Draw how you feel and get a matching playlist. Your colors, speed and stroke style set the mood.</p>
      </header>

      <main>
        <section className="left">
          <div className="toolbar">
            <div className="palette" role="radiogroup" aria-label="Color">
              {PALETTE.map((c) => (
                <button key={c.hex} role="radio" aria-checked={color === c.hex} aria-label={c.name} title={c.name}
                  className={`swatch ${color === c.hex ? 'active' : ''}`} style={{ background: c.hex }}
                  onClick={() => setColor(c.hex)} />
              ))}
            </div>
            <div className="sizes" role="radiogroup" aria-label="Brush size">
              {SIZES.map((s) => (
                <button key={s} role="radio" aria-checked={size === s} aria-label={`${s}px`}
                  className={`size ${size === s ? 'active' : ''}`} onClick={() => setSize(s)}>
                  <span style={{ width: Math.min(s, 22), height: Math.min(s, 22), background: color, boxShadow: '0 0 0 1px rgba(255,255,255,0.35)' }} />
                </button>
              ))}
            </div>
            <div className="actions">
              <button onClick={undo} disabled={!strokes.length}>Undo</button>
              <button onClick={clear} disabled={!strokes.length}>Clear</button>
            </div>
          </div>
          <SketchPad color={color} size={size} strokes={strokes} setStrokes={setStrokes} onStrokeEnd={onStrokeEnd} />
          <p className="hint">Tip: slow, smooth pastel strokes feel calm. Fast, jagged reds feel intense.</p>
        </section>

        <section className="right">
          {error && <div className="error">⚠️ {error}</div>}
          <MoodCard data={data} loading={loading} />
          {data && !data.tracks.length && <div className="card muted">No tracks found right now. Try again in a moment.</div>}
          <Playlist tracks={data?.tracks} playing={playing} onPlay={play} />
          {history.length > 0 && (
            <div className="card history">
              <h3>Your mood trail</h3>
              <div className="trail">
                {history.slice(0, 20).reverse().map((h, i) => (
                  <span key={i} title={`${h.mood.label} · ${new Date(h.createdAt).toLocaleTimeString()}`}>{h.mood.emoji}</span>
                ))}
              </div>
            </div>
          )}
        </section>
      </main>
      <footer>Music previews by Deezer · mood model: color psychology + stroke dynamics, optionally refined by an open-source LLM</footer>
    </div>
  );
}
