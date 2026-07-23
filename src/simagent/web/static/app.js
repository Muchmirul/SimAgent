// SimAgent browser sandbox: three.js live view over the server's scene graph.
// The server is authoritative — every mutation returns full state (vars +
// scene + check) and this file just re-renders it. Dragging a vertex streams
// throttled /api/set calls so dependent geometry (circumcenters, spheres)
// follows the pointer live.
import * as THREE from 'three';
import { OrbitControls } from '/static/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const logEl = $('log');

function log(msg) {
  logEl.textContent += (logEl.textContent ? '\n' : '') + msg;
  logEl.scrollTop = logEl.scrollHeight;
}

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return r.json();
}

// ---------------------------------------------------------------- three.js --
const viewport = $('viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
viewport.appendChild(renderer.domElement);

const scene3 = new THREE.Scene();
scene3.background = new THREE.Color(0x0e0e12);
const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
camera.position.set(3.2, 2.4, 3.2);
camera.up.set(0, 0, 1); // math convention: z up
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.mouseButtons = {
  LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE,
};

const grid = new THREE.GridHelper(6, 12, 0x2a2a32, 0x1b1b22);
grid.rotation.x = Math.PI / 2; // into the xy-plane (z up)
scene3.add(grid);

const contentGroup = new THREE.Group();
const handlesGroup = new THREE.Group();
scene3.add(contentGroup, handlesGroup);

function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene3, camera);
}

function clearGroup(group) {
  for (const child of group.children) {
    child.geometry?.dispose();
    if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
    else child.material?.dispose();
  }
  group.clear();
}

const V = (p) => new THREE.Vector3(p[0], p[1], p[2]);

function buildContent(prims) {
  clearGroup(contentGroup);
  const labels = [];
  for (const prim of prims) {
    if (prim.type === 'points') {
      for (const p of prim.coords) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(prim.radius ?? 0.05, 18, 14),
          new THREE.MeshBasicMaterial({ color: prim.color }),
        );
        m.position.copy(V(p));
        contentGroup.add(m);
      }
    } else if (prim.type === 'segments') {
      const pts = [];
      for (const [a, b] of prim.pairs) pts.push(V(a), V(b));
      const g = new THREE.BufferGeometry().setFromPoints(pts);
      contentGroup.add(new THREE.LineSegments(
        g, new THREE.LineBasicMaterial({ color: prim.color }),
      ));
    } else if (prim.type === 'polygon' || prim.type === 'mesh') {
      const positions = [];
      if (prim.type === 'polygon') {
        const c = prim.coords;
        for (let i = 1; i + 1 < c.length; i++) positions.push(...c[0], ...c[i], ...c[i + 1]);
      } else {
        for (const f of prim.faces) {
          for (const idx of f) positions.push(...prim.vertices[idx]);
        }
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      g.computeVertexNormals();
      contentGroup.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({
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
      contentGroup.add(m);
    } else if (prim.type === 'label') {
      labels.push(prim.text);
    }
  }
  $('labels').textContent = labels.join('   ·   ');
}

// Draggable handles: one invisible-ish sphere per row of each point-set var.
function buildHandles(state) {
  clearGroup(handlesGroup);
  for (const dv of state.spec.domain) {
    if (dv.shape.length !== 2 || dv.shape[1] < 2 || dv.shape[1] > 3) continue;
    const rows = state.vars[dv.name];
    rows.forEach((row, i) => {
      const h = new THREE.Mesh(
        new THREE.SphereGeometry(0.12, 12, 10),
        new THREE.MeshBasicMaterial({ color: 0x4a90d9, transparent: true, opacity: 0.0 }),
      );
      h.position.set(row[0], row[1], dv.shape[1] === 3 ? row[2] : 0);
      h.userData = { name: dv.name, row: i, is2d: dv.shape[1] === 2 };
      handlesGroup.add(h);
    });
  }
}

function fitCamera(prims) {
  const box = new THREE.Box3();
  contentGroup.updateWorldMatrix(true, true);
  box.setFromObject(contentGroup);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const span = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
  controls.target.copy(center);
  const dir = camera.position.clone().sub(controls.target).normalize();
  if (!dir.lengthSq()) dir.set(1, 1, 1).normalize();
  camera.position.copy(center.clone().add(dir.multiplyScalar(span * 1.1)));
}

// ------------------------------------------------------------------- state --
let state = null;
let dragging = null;

function statusText(check) {
  const el = $('status');
  el.classList.remove('good', 'bad');
  if (!check) { el.textContent = '—'; return; }
  if (check.error) { el.textContent = `degenerate — ${check.error}`; return; }
  const m = check.margin;
  el.classList.add(check.holds ? 'good' : 'bad');
  el.innerHTML = `${check.holds ? 'PROPERTY HOLDS' : 'PROPERTY FAILS'}
    <span class="margin">${m === null ? 'discrete check (no margin)' : `margin ${m >= 0 ? '+' : ''}${m.toFixed(4)}`}</span>`;
}

function applyState(st, { refit = false } = {}) {
  state = st;
  buildContent(st.scene);
  if (!dragging) buildHandles(st);
  statusText(st.check);
  if (refit) fitCamera(st.scene);
}

// ------------------------------------------------------------------ dragging --
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let setInFlight = false;
let pendingSet = null;

function pointerRay(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  pointer.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
  pointer.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}

async function pushSet(name, row, values) {
  pendingSet = { name, row, values };
  if (setInFlight) return;
  setInFlight = true;
  while (pendingSet) {
    const req = pendingSet;
    pendingSet = null;
    try {
      applyState(await api('/api/set', req));
    } catch (e) { log(`set failed: ${e.message}`); }
  }
  setInFlight = false;
}

renderer.domElement.addEventListener('pointerdown', (ev) => {
  if (ev.button !== 0 || !state) return;
  pointerRay(ev);
  const hit = raycaster.intersectObjects(handlesGroup.children)[0];
  if (!hit) return;
  const h = hit.object;
  const normal = h.userData.is2d
    ? new THREE.Vector3(0, 0, 1)
    : camera.getWorldDirection(new THREE.Vector3());
  dragging = {
    handle: h,
    plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, h.position.clone()),
  };
  h.material.opacity = 0.35;
  controls.enabled = false;
  renderer.domElement.setPointerCapture(ev.pointerId);
});

renderer.domElement.addEventListener('pointermove', (ev) => {
  if (!dragging) return;
  pointerRay(ev);
  const p = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(dragging.plane, p)) return;
  const { name, row, is2d } = dragging.handle.userData;
  if (is2d) p.z = 0;
  dragging.handle.position.copy(p);
  pushSet(name, row, is2d ? [p.x, p.y] : [p.x, p.y, p.z]);
});

renderer.domElement.addEventListener('pointerup', () => {
  if (!dragging) return;
  dragging.handle.material.opacity = 0.0;
  dragging = null;
  controls.enabled = true;
  if (state) buildHandles(state);
});

// hover affordance
renderer.domElement.addEventListener('pointermove', (ev) => {
  if (dragging || !state) return;
  pointerRay(ev);
  const hit = raycaster.intersectObjects(handlesGroup.children)[0];
  for (const h of handlesGroup.children) h.material.opacity = 0.0;
  if (hit) { hit.object.material.opacity = 0.22; renderer.domElement.style.cursor = 'grab'; }
  else renderer.domElement.style.cursor = 'default';
});

// ------------------------------------------------------------------ actions --
function busy(on) {
  for (const id of ['btnSample', 'btnRefine', 'btnHunt', 'btnCertify', 'btnManimStill', 'btnManimVideo']) {
    $(id).disabled = on;
  }
}

async function action(fn) {
  busy(true);
  try { await fn(); } catch (e) { log(`error: ${e.message}`); }
  busy(false);
}

$('btnSample').onclick = () => action(async () => {
  applyState(await api('/api/sample', {}), { refit: true });
  log('sampled a new configuration');
});

$('btnRefine').onclick = () => action(async () => {
  const r = await api('/api/refine', { steps: 300 });
  applyState(r.state, { refit: true });
  log(`refined ${r.result.steps} steps -> margin ${r.result.margin?.toFixed(4)}`);
});

$('btnHunt').onclick = () => action(async () => {
  const trials = parseInt($('trials').value, 10) || 1500;
  const r = await api('/api/hunt', { trials });
  applyState(r.state, { refit: true });
  const res = r.result;
  log(`hunt(${trials}): ${res.verdict}${res.certified !== null ? ` (certified=${res.certified})` : ''}`);
  if (res.loaded_witness) log('witness loaded into the view');
  for (const n of res.notes) log(`  ${n}`);
});

$('btnCertify').onclick = () => action(async () => {
  const r = await api('/api/certify');
  log(`certify: numeric holds=${r.holds}`);
  if (r.certified === null) log('no exact certifier on this spec — numeric only');
  else if (r.certified) {
    log(`CERTIFIED (exact rationals): property ${r.holds ? 'HOLDS' : 'FAILS'} here`);
    for (const [name, mat] of Object.entries(r.exact ?? {})) {
      log(`${name} = ${JSON.stringify(mat)}`);
    }
  } else log('certification failed (rational snap crossed the boundary)');
  for (const n of r.notes) log(`  ${n}`);
});

// -------------------------------------------------------------------- manim --
async function renderManim(video) {
  const msg = $('manimMsg'), out = $('manimOut');
  const start = await api('/api/manim', { video });
  if (!start.available) { msg.textContent = start.message; return; }
  msg.textContent = video
    ? 'Manim is rendering the rotating scene… (a minute or two)'
    : 'Manim is rendering a still…';
  const t0 = Date.now();
  const poll = async () => {
    const st = await api(`/api/manim/${start.job}`);
    if (st.status === 'running') { setTimeout(poll, 1500); return; }
    if (st.status === 'failed') { msg.textContent = st.message; return; }
    msg.textContent = `Manim render done in ${((Date.now() - t0) / 1000).toFixed(0)}s`;
    out.style.display = 'block';
    out.innerHTML = video
      ? `<video src="${st.url}?t=${Date.now()}" autoplay loop muted controls></video>`
      : `<img src="${st.url}?t=${Date.now()}">`;
  };
  poll();
}
$('btnManimStill').onclick = () => action(() => renderManim(false));
$('btnManimVideo').onclick = () => action(() => renderManim(true));

// --------------------------------------------------------------------- init --
async function loadProblem(id) {
  const st = await api('/api/load', { problem_id: id });
  $('conjecture').textContent = st.spec.conjecture;
  $('manimOut').style.display = 'none';
  $('manimMsg').textContent = '';
  applyState(st, { refit: true });
  log(`loaded: ${st.spec.title}`);
}

async function init() {
  resize();
  animate();
  const problems = await api('/api/problems');
  const sel = $('problem');
  for (const p of problems) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.title;
    sel.appendChild(o);
  }
  const params = new URLSearchParams(location.search);
  const wanted = params.get('problem');
  const def = problems.find((p) => p.id === wanted)?.id
    ?? problems.find((p) => p.id === 'circumcenter-in-tetrahedron')?.id
    ?? problems[0]?.id;
  if (def) { sel.value = def; await loadProblem(def); }
  sel.onchange = () => action(() => loadProblem(sel.value));
}
init().catch((e) => log(`init failed: ${e.message}`));
