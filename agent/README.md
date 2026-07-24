# SimAgent pi runtime

This package is SimAgent's thin TypeScript control plane. It uses exact-pinned
`@earendil-works/pi-coding-agent` 0.82.0 and keeps Python as the only
world, proof, and verdict authority.

## Boundary

- **Pi:** provider authentication, model turns, event streaming, steering, and
  conversation sessions/branches.
- **Python:** mutable world, search, exact certification, Lean checking,
  journal replay, and finalization.
- **Transport:** private strict LF-delimited JSONL subprocesses. The pi service
  owns one Python kernel process per session.

Only the closed SimAgent tool set is exposed. Built-in coding tools and
resource discovery are disabled. Product sessions allow one kernel action per
model turn, which makes every recorded tool cell a settled branch point.
Comments are sent with `session.steer()` and separately journaled as
`user_comment`; annotation is required to preserve the kernel state hash.

## Install and verify

Node 22.19 or newer and the repository `.venv` are required.

```bash
cd agent
npm ci --ignore-scripts
npm run build
PI_OFFLINE=1 npm test
```

The tests use pi's faux provider and make no model or network calls.

## Authentication

Use normal pi authentication. The service reads pi's standard model and auth
locations, including `~/.pi/agent/auth.json`.

```bash
pi
/login
```

Inspect configuration without printing credentials:

```bash
node dist/cli.js auth-check --provider anthropic --model claude-sonnet-4-6
```

## Run

The Python commands launch this runtime automatically:

```bash
.venv/bin/simagent agent circumcenter-in-triangle
.venv/bin/simagent web
```

Direct TypeScript entry points:

```bash
node dist/cli.js run --problem-id circumcenter-in-triangle --out-dir ../runs/pi-demo
node dist/service.js --runs-root ../runs
```

The control service supports start, status, events, stop, targeted comment,
branch, model listing, and shutdown. Branches replay a hash-verified Python
journal prefix and carry source run, step, journal sequence, and state hash as
provenance.
