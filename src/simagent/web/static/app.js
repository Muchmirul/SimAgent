// SimAgent reasoning notebook.
//
// A math problem goes in as text (or a bundled problem id); an embodied agent
// session runs server-side; this page streams the mind trace as notebook
// cells — thought, act, the rendered scene, the harness's equation translation
// of that scene, and a diff vs the previous step. Clicking a cell's image
// opens the interactive 3D scene (three.js) for that exact step. The page
// renders kernel state only; it never mints verdicts.
import * as THREE from 'three';
import { OrbitControls } from '/static/OrbitControls.js';

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ---------------------------------------------------------------- notebook --
const nb = {
  run: null,        // run currently displayed
  total: 0,         // highest step rendered
  done: false,
  job: false,       // true when this page started the session (status endpoint exists)
  tracePoll: null,
  statusPoll: null,
};

function stopPolling() {
  if (nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
  if (nb.statusPoll) { clearInterval(nb.statusPoll); nb.statusPoll = null; }
}

function resetNotebook() {
  stopPolling();
  nb.run = null; nb.total = 0; nb.done = false; nb.job = false;
  nb.approach = null; nb.approachIdea = null; nb.finishSummary = null;
  $('cells').replaceChildren();
  $('statementWrap').style.display = 'none';
  $('verdictWrap').style.display = 'none';
  $('statusWrap').style.display = 'none';
  $('btnStop').disabled = true;
}

function nearBottom() {
  return window.innerHeight + window.scrollY > document.body.offsetHeight - 260;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function showStatement(spec) {
  if (!spec) return;
  const s = $('statement');
  s.replaceChildren();
  s.appendChild(el('h2', null, spec.title ?? spec.id ?? ''));
  if (spec.conjecture) s.appendChild(el('div', 'conj', spec.conjecture));
  if (spec.latex) s.appendChild(el('div', 'latex mono', spec.latex));
  if (spec.quantifier) s.appendChild(el('div', 'conj mono', `quantifier: ${spec.quantifier}`));
  s.style.display = 'block';
  $('statementWrap').style.display = 'block';
}

function thoughtBlock(step) {
  const t = el('div', 'thought');
  const parts = [...(step.thought ?? [])];
  if (step.tool === 'finish' && step.args?.summary) {
    parts.push({ kind: 'summary', text: step.args.summary });
  }
  if (!parts.length) return null;
  for (const p of parts) {
    t.appendChild(el('span', 'kind', p.kind === 'thinking' ? 'thinking' : p.kind === 'summary' ? 'final summary (narrative)' : 'says'));
    t.appendChild(el('span', p.kind === 'thinking' ? 'think' : 'say', p.text));
  }
  return t;
}

function actLine(step) {
  const a = el('div', 'act mono');
  let argsText = '';
  if (step.tool === 'finish') argsText = '';
  else if (step.args && Object.keys(step.args).length) argsText = JSON.stringify(step.args);
  a.appendChild(el('span', null, step.tool ? `${step.tool}(${argsText})` : '— narrative only —'));
  if (step.error) a.appendChild(el('span', 'err', '  ✗ error'));
  for (const [k, v] of Object.entries(step.extra ?? {})) {
    if (['view', 'expect', 'resolved_expectations', 'construct'].includes(k)) continue; // rendered as chips/badges in Out
    a.appendChild(el('span', 'badge', `  ${k}=${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`));
  }
  return a;
}

function diffBlock(step) {
  const lines = [];
  for (const c of step.diff?.changed ?? []) {
    const where = c.row === null || c.row === undefined ? c.var : `${c.var}[${c.row}]`;
    lines.push(['del', `- ${where} = ${c.before ?? '(new)'}`]);
    lines.push(['add', `+ ${where} = ${c.after}`]);
  }
  const m = step.diff?.margin;
  if (m && m.before !== m.after && (m.before !== null || m.after !== null)) {
    const f = (x) => (x === null || x === undefined ? '—' : Number(x).toFixed(4));
    lines.push([m.after !== null && m.after > 0 ? 'add' : 'del', `~ margin ${f(m.before)} → ${f(m.after)}`]);
  }
  if (!lines.length) return null;
  const d = el('div', 'diffblock mono');
  for (const [cls, text] of lines) d.appendChild(el('div', cls, text));
  return d;
}

function statBadge(check) {
  if (!check) return null;
  if (check.error) return el('span', 'stat dim', `degenerate — ${check.error}`);
  const m = check.margin;
  const b = el('span', `stat ${check.holds ? 'good' : 'bad'}`,
    `${check.holds ? 'PROPERTY HOLDS' : 'PROPERTY FAILS'}${m === null || m === undefined ? '' : ` · margin ${m >= 0 ? '+' : ''}${Number(m).toFixed(4)}`}`);
  return b;
}

function imagineCell(step) {
  // Thought experiment: dashed cell, ghost image, per-op outcomes — and an
  // explicit "mainline unchanged" note. The Einstein move, visible.
  const cell = el('article', 'cell imagine');
  cell.appendChild(el('div', 'gut im', `Im [${step.step}]:`));
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);
  const inner = el('div');
  inner.appendChild(el('div', 'imnote', 'thought experiment — the real configuration is unchanged'));
  const ops = step.branch?.ops ?? step.args?.ops ?? [];
  const act = el('div', 'act mono');
  act.textContent = `imagine(${ops.map((o) => `${o.op} ${o.target ?? o.name ?? ''}`).join(' · ')})`;
  inner.appendChild(act);
  if (step.image) {
    const img = el('img', 'sceneimg');
    img.loading = 'lazy';
    img.alt = `imagined scene at step ${step.step}`;
    img.src = `/api/trace/${encodeURIComponent(nb.run)}/file/${step.image}`;
    img.onerror = () => img.remove();
    if (Array.isArray(step.scene) && step.scene.length) img.onclick = () => open3d(step);
    inner.appendChild(img);
    inner.appendChild(el('div', 'caption', 'ghost view: grey = real state · solid = imagined'));
  }
  for (const oc of step.branch?.outcomes ?? []) {
    const line = el('div', 'imoutcome mono');
    if (oc.error) {
      line.appendChild(el('span', 'bad', `op ${oc.op}: ${oc.error}`));
    } else if (oc.check?.error) {
      line.appendChild(el('span', 'bad', `op ${oc.op}: degenerate — ${oc.check.error}`));
    } else {
      const m = oc.check?.margin;
      const holds = oc.check?.holds;
      const span = el('span', holds ? 'good' : 'bad',
        `op ${oc.op}: would ${holds ? 'HOLD' : 'FAIL'}${m === null || m === undefined ? '' : ` (margin ${Number(m).toFixed(4)})`}`);
      line.appendChild(span);
    }
    inner.appendChild(line);
  }
  const eqLines = step.equation?.text ?? [];
  if (eqLines.length) inner.appendChild(el('div', 'eq mono', eqLines.join('\n')));
  body.appendChild(inner);
  cell.appendChild(body);
  $('cells').appendChild(cell);
  return cell;
}

function annotationCell(step) {
  // plan/expect ride tool steps; free annotations (user_comment, provenance)
  // land here — rendered like an approach box, tagged with their kind.
  const cell = el('article', 'cell');
  cell.appendChild(el('div', 'gut', `— [${step.step}]`));
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);
  const box = el('div', 'planbox');
  box.appendChild(el('div', 'pm', step.kind === 'user_comment' ? 'comment (steering — never verdict material)' : (step.kind ?? 'annotation')));
  if (step.text) box.appendChild(el('div', 'pi', step.text));
  if (step.target) box.appendChild(el('div', 'pi', `on: ${JSON.stringify(step.target)}`));
  body.appendChild(box);
  cell.appendChild(body);
  $('cells').appendChild(cell);
  return cell;
}

function appendStep(step) {
  if (step.mode === 'imagine') return imagineCell(step);
  if (step.mode === 'annotation') return annotationCell(step);
  const cell = el('article', 'cell');
  const gut = el('div', 'gut in', `In [${step.step}]:`);
  cell.appendChild(gut);
  const body = el('div');
  const th = thoughtBlock(step);
  if (th) body.appendChild(th);

  // A declared line of attack renders as its own approach cell — intent,
  // clearly distinct from the acts. The kernel still stamps the verdict.
  if (step.tool === 'plan') {
    const box = el('div', 'planbox');
    if (step.error) {
      box.appendChild(el('div', 'pm', 'approach — (invalid declaration)'));
      box.appendChild(el('div', 'perr', step.result ?? '✗ error'));
    } else {
      nb.approach = step.extra?.declared_method ?? step.args?.method ?? null;
      nb.approachIdea = step.extra?.idea ?? step.args?.idea ?? null;
      box.appendChild(el('div', 'pm', `approach — ${nb.approach}`));
      if (nb.approachIdea) box.appendChild(el('div', 'pi', nb.approachIdea));
    }
    body.appendChild(box);
    cell.appendChild(body);
    $('cells').appendChild(cell);
    return cell;
  }

  body.appendChild(actLine(step));

  const out = el('div', 'outblock');
  // FUTURE band: declared predictions (pending) and their mechanical scoring
  const exp = step.extra?.expect;
  if (exp) {
    out.appendChild(el('span', 'chip pending',
      `◌ expects margin ${exp.relation} ${exp.value ?? ''}${exp.note ? ` — ${exp.note}` : ''}`));
  }
  const resolved = step.extra?.resolved_expectations;
  if (resolved?.length) {
    const box = el('div');
    for (const r of resolved) {
      box.appendChild(el('span', `chip ${r.ok ? 'ok' : 'bad'}`,
        `${r.ok ? '✓' : '✗'} #${r.id} margin ${r.relation} ${r.value ?? ''} → ${r.actual}`));
    }
    out.appendChild(box);
  }
  const built = step.extra?.construct;
  if (built) {
    out.appendChild(el('span', 'chip pending',
      `✎ ${built.name} = ${built.ctor}(${(built.args ?? []).join(', ')})${built.degenerate ? ' — degenerate here' : ''}`));
  }
  const vmeta = step.extra?.view;
  if (vmeta) {
    const b = el('div');
    b.appendChild(el('span', 'viewbadge', `view: ${vmeta.kind}`));
    const bits = [];
    if (vmeta.zero_contour) bits.push('zero-contour visible — the boundary has a shape');
    if (vmeta.fail_fraction !== undefined) bits.push(`FAILS on ${(vmeta.fail_fraction * 100).toFixed(0)}% of the slice`);
    if (vmeta.min_margin !== undefined) bits.push(`min margin ${Number(vmeta.min_margin).toFixed(4)}`);
    if (vmeta.zero_crossings?.length) bits.push(`${vmeta.zero_crossings.length} zero crossing(s)`);
    if (vmeta.final_margin !== undefined) bits.push(`final margin ${Number(vmeta.final_margin).toFixed(4)}`);
    if (bits.length) b.appendChild(el('span', 'caption', '  ' + bits.join(' · ')));
    out.appendChild(b);
  }
  const hasScene = Array.isArray(step.scene) && step.scene.length;
  if (step.tool) {
    const img = el('img', 'sceneimg');
    img.loading = 'lazy';
    img.alt = `scene at step ${step.step}`;
    img.src = step.image
      ? `/api/trace/${encodeURIComponent(nb.run)}/file/${step.image}`
      : `/api/trace/${encodeURIComponent(nb.run)}/render/${step.step}`;
    img.onerror = () => { img.remove(); cap.remove(); };
    const cap = el('div', 'caption',
      step.image ? 'what the agent saw (its own eyes) — click for interactive 3D'
                 : 'scene after this step — click for interactive 3D');
    if (hasScene) img.onclick = () => open3d(step);
    out.appendChild(img);
    out.appendChild(cap);
  }
  const eqLines = step.equation?.text ?? [];
  if (eqLines.length) out.appendChild(el('div', 'eq mono', eqLines.join('\n')));
  const df = diffBlock(step);
  if (df) out.appendChild(df);
  const st = statBadge(step.check);
  if (st) out.appendChild(st);
  if (out.children.length) {
    const og = el('div', 'gut out', `Out[${step.step}]:`);
    // nested output block; its gutter label reaches back into the left column
    const outCell = el('div', 'cell');
    outCell.style.margin = '8px 0 0';
    outCell.style.paddingLeft = '0';
    og.style.top = '0';
    og.style.left = '-86px';
    outCell.appendChild(og);
    outCell.appendChild(out);
    body.appendChild(outCell);
  }
  cell.appendChild(body);
  $('cells').appendChild(cell);
  return cell;
}

function showVerdict(tr, finishSummary) {
  const v = $('verdict');
  v.replaceChildren();
  v.className = '';
  let cls = 'none';
  if (tr.proof) {
    const text = tr.verdict ?? tr.proof.claim ?? 'kernel-grade result on record';
    if (/DISPROVED|counterexample/i.test(text)) cls = 'bad';
    else if (/PROVED|witness/i.test(text)) cls = 'good';
    v.appendChild(el('h2', null, 'Kernel verdict'));
    v.appendChild(el('div', 'vd', text));
    v.appendChild(el('div', 'meta',
      `method: ${tr.proof.method} · verified by ${tr.proof.verified_by}`
      + (tr.proof.statement_review && tr.proof.statement_review !== 'bundled-trusted'
        ? ` · statement review: ${tr.proof.statement_review}` : '')));
  } else {
    v.appendChild(el('h2', null, 'No kernel-grade result'));
    v.appendChild(el('div', 'meta',
      'Nothing was certified or kernel-checked in this session. The narrative above is not a proof.'));
    if (finishSummary) v.appendChild(el('div', 'meta', `agent's own summary: ${finishSummary}`));
  }
  // Declared intent vs what the kernel actually stamped — divergence is
  // honest information (the plan failed; the machinery caught something else).
  if (nb.approach) {
    const est = tr.proof?.method;
    v.appendChild(el('div', 'meta',
      !est ? `declared approach: ${nb.approach} (nothing kernel-established)`
        : est === nb.approach ? `declared and established: ${est}`
        : `declared: ${nb.approach} → established: ${est}`));
  }
  v.classList.add(cls === 'bad' ? 'bad' : cls === 'none' ? 'none' : 'good');
  v.style.display = 'block';
  $('verdictWrap').style.display = 'block';
}

function setStatus(text, logLines) {
  $('statusWrap').style.display = 'block';
  $('statusText').textContent = text + (nb.approach ? ` · approach: ${nb.approach}` : '');
  $('logTail').textContent = (logLines ?? []).slice(-6).join('\n');
}

function hideStatus() { $('statusWrap').style.display = 'none'; }

async function pullTrace() {
  const tr = await api(`/api/trace/${encodeURIComponent(nb.run)}?after=${nb.total}`);
  if (tr.spec && $('statementWrap').style.display === 'none') showStatement(tr.spec);
  let last = null;
  for (const s of tr.steps) {
    const cell = appendStep(s);
    nb.total = Math.max(nb.total, s.step);
    if (s.tool === 'finish' && s.args?.summary) nb.finishSummary = s.args.summary;
    last = cell;
  }
  if (last && nearBottom()) last.scrollIntoView({ block: 'end', behavior: 'smooth' });
  if (tr.done && !nb.done) {
    nb.done = true;
    if (nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
    hideStatus();
    showVerdict(tr, nb.finishSummary);
  }
  return tr;
}

async function openRun(run) {
  resetNotebook();
  nb.run = run;
  history.replaceState(null, '', `?run=${encodeURIComponent(run)}`);
  try {
    await pullTrace();
  } catch (e) {
    setStatus(`could not open ${run}: ${e.message}`);
    return;
  }
  if (!nb.done) {
    setStatus('agent is thinking… (following the live trace)');
    $('statusGut').textContent = '⋯';
    nb.tracePoll = setInterval(() => pullTrace().catch(() => {}), 1400);
  }
}

// --------------------------------------------------------------- run agent --
const TERMINAL = ['done', 'failed', 'stopped'];

async function runSession(body) {
  $('btnRun').disabled = true;
  $('runMsg').textContent = 'starting…';
  try {
    const { run } = await api('/api/agent/start', body);
    resetNotebook();
    nb.run = run; nb.job = true; nb.lastStartBody = body;
    history.replaceState(null, '', `?run=${encodeURIComponent(run)}`);
    $('runMsg').textContent = `session: ${run}`;
    $('btnStop').disabled = false;
    $('btnRestart').disabled = false;
    setStatus(body.conjecture ? 'formalizing your conjecture into a spec…' : 'agent session starting…');
    // status poller (job state + log tail) and trace poller (cells)
    nb.statusPoll = setInterval(async () => {
      try {
        const st = await api(`/api/agent/${encodeURIComponent(run)}/status`);
        if (!nb.done) {
          const label = { formalizing: 'formalizing your conjecture into a spec…',
                          running: 'agent is thinking…',
                          stopping: 'stopping — letting the session wind down…',
                          stopped: 'session stopped (kernel results so far were kept)',
                          done: 'finalizing…',
                          failed: 'session failed' }[st.status] ?? st.status;
          setStatus(label, st.log);
        }
        if (st.status === 'failed') {
          stopPolling();
          setStatus(`session failed: ${st.error ?? 'unknown error'}`
            + ' — free-text conjectures need Claude API auth; bundled problems also run on the `claude` login (backend claude-code).', st.log);
          $('statusGut').classList.remove('pulse');
        }
        if (TERMINAL.includes(st.status)) {
          clearInterval(nb.statusPoll); nb.statusPoll = null;
          $('btnStop').disabled = true;
          refreshRuns().catch(() => {});
          // a session stopped before any trace existed will never produce cells
          setTimeout(() => {
            if (!nb.done && nb.tracePoll) { clearInterval(nb.tracePoll); nb.tracePoll = null; }
          }, 6000);
        }
      } catch { /* transient */ }
    }, 1200);
    nb.tracePoll = setInterval(() => pullTrace().catch(() => { /* trace not on disk yet */ }), 1400);
  } catch (e) {
    $('runMsg').textContent = e.status === 409 ? `busy: ${e.message}` : `error: ${e.message}`;
  } finally {
    $('btnRun').disabled = false;
  }
}

function startAgent() {
  const problemId = $('problemSel').value;
  const conjecture = $('conjText').value.trim();
  const body = { backend: $('backendSel').value || null, max_turns: parseInt($('maxTurns').value, 10) || 40 };
  if (conjecture) body.conjecture = conjecture;
  else if (problemId) body.problem_id = problemId;
  else { $('runMsg').textContent = 'pick a problem or type a conjecture'; return; }
  runSession(body);
}

async function stopSession() {
  if (!nb.run || !nb.job) return;
  $('btnStop').disabled = true;
  try {
    await api(`/api/agent/${encodeURIComponent(nb.run)}/stop`, {});
    setStatus('stopping — letting the session wind down…');
  } catch (e) {
    $('runMsg').textContent = `stop: ${e.message}`;
    $('btnStop').disabled = false;
  }
}

async function restartSession() {
  const body = nb.lastStartBody;
  if (!body) { $('runMsg').textContent = 'nothing to restart — run a session first'; return; }
  $('btnRestart').disabled = true;
  try {
    // stop the current session (if ours and still going), wait for it to end
    if (nb.run && nb.job && !nb.done) {
      try { await api(`/api/agent/${encodeURIComponent(nb.run)}/stop`, {}); } catch { /* already terminal */ }
      setStatus('restarting — stopping the current session first…');
      const deadline = Date.now() + 120000;
      while (Date.now() < deadline) {
        try {
          const st = await api(`/api/agent/${encodeURIComponent(nb.run)}/status`);
          if (TERMINAL.includes(st.status)) break;
        } catch { break; }
        await new Promise((r) => setTimeout(r, 800));
      }
    }
    await runSession(body); // fresh notebook, fresh session, same problem
  } finally {
    $('btnRestart').disabled = false;
  }
}

// ------------------------------------------------------------ runs & init --
async function refreshRuns() {
  const runs = await api('/api/runs');
  const sel = $('runSel');
  const keep = sel.value;
  sel.length = 1;
  for (const r of runs) {
    const o = document.createElement('option');
    o.value = r.run;
    o.textContent = r.title ? `${r.run} — ${r.title}` : r.run;
    sel.appendChild(o);
  }
  if (runs.some((r) => r.run === keep)) sel.value = keep;
}

async function init() {
  const problems = await api('/api/problems').catch(() => []);
  const psel = $('problemSel');
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '— choose a bundled problem, or type below —';
  psel.appendChild(none);
  for (const p of problems) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = `${p.title} [${p.quantifier}]`;
    psel.appendChild(o);
  }
  await refreshRuns().catch(() => {});
  const params = new URLSearchParams(location.search);
  const wanted = params.get('run');
  if (wanted) {
    $('runSel').value = wanted;
    openRun(wanted).catch(() => {});
  }
  const problem = params.get('problem');
  if (problem) psel.value = problem;
}

$('btnRun').onclick = () => startAgent();
$('btnStop').onclick = () => stopSession();
$('btnRestart').onclick = () => restartSession();
$('btnRefresh').onclick = () => refreshRuns().catch(() => {});
$('runSel').onchange = () => { if ($('runSel').value) openRun($('runSel').value).catch(() => {}); };
$('conjText').addEventListener('input', () => { if ($('conjText').value.trim()) $('problemSel').value = ''; });
$('problemSel').addEventListener('change', () => { if ($('problemSel').value) $('conjText').value = ''; });

// ------------------------------------------------------------- 3D overlay --
// One lazy WebGL context; each open builds the clicked step's scene graph.
let ov = null; // { renderer, scene, camera, controls, group, open }

function ensureOverlay() {
  if (ov) return ov;
  const frame = $('ovFrame');
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  frame.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e0e12);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
  camera.position.set(3.2, 2.4, 3.2);
  camera.up.set(0, 0, 1); // math convention: z up
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  const grid = new THREE.GridHelper(6, 12, 0x2a2a32, 0x1b1b22);
  grid.rotation.x = Math.PI / 2; // xy-plane, z up
  scene.add(grid);
  const group = new THREE.Group();
  scene.add(group);
  ov = { renderer, scene, camera, controls, group, open: false };
  const loop = () => {
    if (!ov.open) return;
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  };
  ov.startLoop = loop;
  window.addEventListener('resize', sizeOverlay);
  return ov;
}

function sizeOverlay() {
  if (!ov || !ov.open) return;
  const frame = $('ovFrame');
  const w = frame.clientWidth, h = frame.clientHeight;
  ov.renderer.setSize(w, h);
  ov.camera.aspect = w / h;
  ov.camera.updateProjectionMatrix();
}

function clearOverlayGroup() {
  for (const child of ov.group.children) {
    child.geometry?.dispose();
    if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
    else child.material?.dispose();
  }
  ov.group.clear();
}

const V = (p) => new THREE.Vector3(p[0], p[1], p[2]);

function buildOverlayScene(prims) {
  clearOverlayGroup();
  const labels = [];
  for (const prim of prims) {
    if (prim.type === 'points') {
      for (const p of prim.coords) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(prim.radius ?? 0.05, 18, 14),
          new THREE.MeshBasicMaterial({ color: prim.color }),
        );
        m.position.copy(V(p));
        ov.group.add(m);
      }
    } else if (prim.type === 'segments') {
      const pts = [];
      for (const [a, b] of prim.pairs) pts.push(V(a), V(b));
      const g = new THREE.BufferGeometry().setFromPoints(pts);
      ov.group.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: prim.color })));
    } else if (prim.type === 'polygon' || prim.type === 'mesh') {
      const positions = [];
      if (prim.type === 'polygon') {
        const c = prim.coords;
        for (let i = 1; i + 1 < c.length; i++) positions.push(...c[0], ...c[i], ...c[i + 1]);
      } else {
        for (const f of prim.faces) for (const idx of f) positions.push(...prim.vertices[idx]);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      g.computeVertexNormals();
      ov.group.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({
        color: prim.color, transparent: true, opacity: prim.opacity ?? 0.3,
        side: THREE.DoubleSide, depthWrite: false,
      })));
    } else if (prim.type === 'sphere') {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(prim.radius, 40, 24),
        new THREE.MeshBasicMaterial({
          color: prim.color, transparent: true,
          opacity: Math.max(prim.opacity ?? 0.12, 0.06), depthWrite: false,
        }),
      );
      m.position.copy(V(prim.center));
      ov.group.add(m);
    } else if (prim.type === 'label') {
      labels.push(prim.text);
    }
  }
  return labels;
}

function open3d(step) {
  try {
    ensureOverlay();
  } catch {
    return; // no WebGL — the PNG is already on the page
  }
  const labels = buildOverlayScene(step.scene ?? []);
  $('ovCap').textContent =
    `step ${step.step} · ${step.tool ?? 'narrative'}` + (labels.length ? ` — ${labels.join(' · ')}` : '');
  $('overlay').style.display = 'block';
  ov.open = true;
  sizeOverlay();
  // fit camera to content
  const box = new THREE.Box3().setFromObject(ov.group);
  if (!box.isEmpty()) {
    const center = box.getCenter(new THREE.Vector3());
    const span = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
    ov.controls.target.copy(center);
    const dir = ov.camera.position.clone().sub(center).normalize();
    if (!dir.lengthSq()) dir.set(1, 1, 1).normalize();
    ov.camera.position.copy(center.clone().add(dir.multiplyScalar(span * 1.15)));
  }
  ov.startLoop();
}

function close3d() {
  if (!ov) return;
  ov.open = false;
  $('overlay').style.display = 'none';
}

$('ovClose').onclick = close3d;
$('overlay').addEventListener('click', (e) => { if (e.target === $('overlay')) close3d(); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') close3d(); });

init().catch((e) => setStatus(`init failed: ${e.message}`));
