# SimAgent P0 Pi runtime spike

This package is the P0 control-plane spike. It uses
`@earendil-works/pi-coding-agent` 0.81.1 in SDK full-control mode and keeps the
existing Python kernel as the only world/proof/verdict authority.

## Boundary

- **Pi:** provider/model/auth routing, the agent loop, events, steering, and
  conversation sessions/branches.
- **Python:** mutable world, search, exact certification, Lean checking,
  journal replay, and finalization.
- **Transport:** a private, strict LF-delimited JSONL subprocess protocol
  (`python -m simagent.kernel_transport`). Pi 0.81.1 has no built-in MCP
  client, and P0 does not retain MCP, so no MCP dependency or adapter is
  needed.

The SDK receives a no-discovery `ResourceLoader`, in-memory settings, an
explicit allowlist of kernel tools, and no active built-in coding tools.
Every kernel tool and Pi's global tool loop use sequential execution. Branch
checkpoints are created only at settled `turn_end` boundaries, after every
result in the tool batch has been persisted. `finish` is terminal in Python;
later siblings receive correlated error results and cannot mutate the world.

`look` is returned as Pi's `{ type: "image", data, mimeType }` tool-result
block. SimAgent rejects models whose `model.input` does not include
`"image"`; P0 deliberately has no silent text-only degradation because
pi-ai otherwise silently drops unsupported images.

## Requirements and deterministic checks

- Node `>=22.19.0` (validated with 22.23.1)
- the repository `.venv`
- exact dependencies and `package-lock.json` committed under `agent/`

```bash
cd agent
/home/dev/.local/node-v22.23.1-linux-x64/bin/npm ci --ignore-scripts
/home/dev/.local/node-v22.23.1-linux-x64/bin/npm run build
PI_OFFLINE=1 /home/dev/.local/node-v22.23.1-linux-x64/bin/npm test
```

The tests use Pi's faux provider, replace `fetch` with a failing stub, and do
not read real credentials or make API calls.

## Authentication check (non-interactive)

Build first, then inspect Pi's standard auth locations without printing any
credential value:

```bash
cd agent
node dist/cli.js auth-check \
  --provider anthropic \
  --model claude-sonnet-4-6
```

This uses `ModelRuntime.create()` with its standard resolution order
(runtime override, `~/.pi/agent/auth.json`, environment, model fallback). It
never starts an OAuth flow. Configure auth separately with normal Pi `/login`
or an API key.

## Optional real-model smoke

This is intentionally manual and uses an already-authenticated **vision**
model. It can incur provider charges and network traffic:

```bash
cd agent
node dist/cli.js smoke \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --problem-id circumcenter-in-triangle \
  --out-dir ../runs/pi-p0-manual-smoke
```

No automated test invokes this command, and it never performs interactive
OAuth login.
