#!/usr/bin/env node
import { resolve } from "node:path";

import { ModelRuntime } from "@earendil-works/pi-coding-agent";

import { createSimAgentRuntime } from "./runtime.js";

function parseOptions(argv: string[]): Map<string, string> {
  const result = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`expected --name value pairs, got ${argv.slice(index).join(" ")}`);
    }
    result.set(key.slice(2), value);
  }
  return result;
}

function required(options: Map<string, string>, name: string): string {
  const value = options.get(name);
  if (!value) throw new Error(`missing required --${name}`);
  return value;
}

async function resolveStandardModel(provider: string, modelId: string) {
  // No custom credential path: this is deliberately Pi's standard
  // ~/.pi/agent/auth.json + environment + models.json resolution.
  const modelRuntime = await ModelRuntime.create();
  const model = modelRuntime.getModel(provider, modelId);
  if (!model) throw new Error(`Pi model not found: ${provider}/${modelId}`);
  const auth = await modelRuntime.checkAuth(provider);
  return { modelRuntime, model, auth };
}

async function authCheck(argv: string[]): Promise<number> {
  const options = parseOptions(argv);
  const provider = required(options, "provider");
  const modelId = required(options, "model");
  const { model, auth } = await resolveStandardModel(provider, modelId);
  const result = {
    provider,
    model: modelId,
    configured: auth !== undefined,
    authType: auth?.type ?? null,
    authSource: auth?.source ?? null,
    input: model.input,
    vision: model.input.includes("image"),
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  return result.configured && result.vision ? 0 : 2;
}

async function smoke(argv: string[]): Promise<number> {
  const options = parseOptions(argv);
  const provider = required(options, "provider");
  const modelId = required(options, "model");
  const problemId = options.get("problem-id") ?? "circumcenter-in-triangle";
  const outDir = resolve(options.get("out-dir") ?? `runs/pi-p0-smoke-${Date.now()}`);
  const { modelRuntime, model, auth } = await resolveStandardModel(provider, modelId);
  if (!auth) {
    throw new Error(
      `no Pi authentication found for ${provider}; configure an API key or use Pi's /login first`,
    );
  }
  if (!model.input.includes("image")) {
    throw new Error(`${provider}/${modelId} is text-only; SimAgent smoke requires image input`);
  }

  const runtime = await createSimAgentRuntime({
    problemId,
    outDir,
    sessionDir: resolve(outDir, "pi-sessions"),
    modelRuntime,
    model,
    thinkingLevel: "medium",
  });
  runtime.session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      process.stdout.write(event.assistantMessageEvent.delta);
    }
  });
  try {
    await runtime.promptTask();
    process.stdout.write("\n");
    const finalized = await runtime.dispose();
    process.stdout.write(`kernel journal: ${finalized.journalPath}\n`);
    return 0;
  } catch (error) {
    if (runtime.session.isIdle) await runtime.dispose().catch(() => undefined);
    throw error;
  }
}

async function main(): Promise<number> {
  const [command, ...argv] = process.argv.slice(2);
  if (command === "auth-check") return authCheck(argv);
  if (command === "smoke") return smoke(argv);
  process.stderr.write(
    "usage:\n" +
      "  cli.js auth-check --provider NAME --model ID\n" +
      "  cli.js smoke --provider NAME --model ID [--problem-id ID] [--out-dir PATH]\n",
  );
  return 2;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
