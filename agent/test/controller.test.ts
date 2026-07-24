import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
  fauxToolCall,
  InMemoryCredentialStore,
  type Context,
} from "@earendil-works/pi-ai";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";

import { createSimAgentRuntime, RunController } from "../src/index.js";

async function waitTerminal(controller: RunController, run: string): Promise<void> {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    if (["done", "failed", "stopped"].includes(controller.status(run).status)) return;
    await new Promise((resolveWait) => setTimeout(resolveWait, 25));
  }
  throw new Error(`run ${run} did not settle`);
}

describe.sequential("P6 run controller", () => {
  it("starts a pi session and branches from an exact settled prefix with provenance", async () => {
    const root = await mkdtemp(join(tmpdir(), "simagent-p6-controller-"));
    const faux = fauxProvider({
      provider: "simagent-controller-faux",
      models: [{ id: "scripted", input: ["text", "image"] }],
    });
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(),
      modelsPath: null,
    });
    modelRuntime.registerNativeProvider(faux.provider);
    const model = modelRuntime.getModel(faux.provider.id, "scripted");
    if (!model) throw new Error("faux model missing");
    const controller = new RunController({
      runsRoot: root,
      modelRuntime,
      runtimeFactory: async (options) =>
        createSimAgentRuntime({ ...options, modelRuntime, model }),
    });
    try {
      faux.setResponses([
        fauxAssistantMessage(
          fauxToolCall(
            "set_var",
            { name: "T", values: [-1, 0, 1, 0, 0, 0.2] },
            { id: "controller-source-set" },
          ),
          { stopReason: "toolUse" },
        ),
        fauxAssistantMessage(fauxText("source settled")),
      ]);
      const source = (await controller.start({ problemId: "circumcenter-in-triangle" })).run;
      await waitTerminal(controller, source);
      const sourceStatus = controller.status(source);
      expect(sourceStatus.status).toBe("done");
      expect(sourceStatus.checkpoints.some((checkpoint) => checkpoint.kernelTraceStep === 1)).toBe(true);

      let branchContext: Context | undefined;
      faux.setResponses([
        (context) => {
          branchContext = JSON.parse(JSON.stringify(context)) as Context;
          return fauxAssistantMessage(fauxToolCall("certify", {}, { id: "controller-branch-certify" }), {
            stopReason: "toolUse",
          });
        },
        fauxAssistantMessage(
          fauxToolCall("finish", { summary: "branch certified" }, { id: "controller-branch-finish" }),
          { stopReason: "toolUse" },
        ),
      ]);
      const branch = (
        await controller.branch(source, {
          step: 1,
          comment: "Recheck this exact wide triangle.",
          target: { step: 1, kind: "cell" },
        })
      ).run;
      await waitTerminal(controller, branch);
      expect(controller.status(branch).status).toBe("done");
      const proof = JSON.parse(await readFile(join(root, branch, "proof.json"), "utf8")) as Record<string, unknown>;
      expect(proof.statement_review).toBe("bundled-trusted");
      const trace = (await readFile(join(root, branch, "trace.jsonl"), "utf8"))
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as Record<string, unknown>);
      const provenance = trace.find((entry) => entry.kind === "provenance");
      const comment = trace.find((entry) => entry.kind === "user_comment");
      expect(provenance?.source).toMatchObject({ run: source, step: 1 });
      expect(comment?.text).toBe("Recheck this exact wide triangle.");
      expect(JSON.stringify(branchContext?.messages)).toContain("Recheck this exact wide triangle.");
      expect(controller.events(branch).events.some((event) => event.type === "branched")).toBe(true);

      faux.setResponses([
        fauxAssistantMessage(
          fauxToolCall("finish", { summary: "must not run" }, { id: "inexact-branch-finish" }),
          { stopReason: "toolUse" },
        ),
      ]);
      await expect(controller.branch(source, { step: 2 })).rejects.toThrow(
        /no exact safe pi checkpoint/,
      );
    } finally {
      await controller.shutdown();
      await rm(root, { recursive: true, force: true });
    }
  }, 60_000);
});
