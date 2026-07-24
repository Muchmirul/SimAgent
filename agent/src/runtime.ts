import { resolve } from "node:path";

import type { Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  createExtensionRuntime,
  ModelRuntime,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";

import {
  KernelClient,
  type KernelClientOptions,
  type KernelDescription,
  type KernelFinalizeResult,
} from "./kernel-client.js";
import { createKernelTools, isKernelToolDetails, KERNEL_TOOL_NAMES } from "./tools.js";

const BUILTIN_TOOL_NAMES = ["read", "bash", "edit", "write", "grep", "find", "ls"] as const;

export class VisionCapabilityError extends Error {
  constructor(model: Model<any>) {
    super(
      `SimAgent requires a vision model; ${model.provider}/${model.id} advertises input=` +
        JSON.stringify(model.input),
    );
    this.name = "VisionCapabilityError";
  }
}

export function assertVisionModel(model: Model<any>): void {
  if (!model.input.includes("image")) throw new VisionCapabilityError(model);
}

/** Resource loader with no discovery and no filesystem-backed customization. */
export function createIsolatedResourceLoader(systemPrompt: string): ResourceLoader {
  const extensions = {
    extensions: [],
    errors: [],
    runtime: createExtensionRuntime(),
  };
  return {
    getExtensions: () => extensions,
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => systemPrompt,
    getAppendSystemPrompt: () => [],
    extendResources: () => {},
    reload: async () => {},
  };
}

export interface BranchCheckpoint {
  id: string;
  piEntryId: string;
  kernelJournalSeq: number;
  kernelStateHash: string;
  settled: true;
  safe: boolean;
}

export interface CreateSimAgentRuntimeOptions {
  problemId: string;
  outDir: string;
  cwd?: string;
  sessionDir?: string;
  sessionManager?: SessionManager;
  modelRuntime?: ModelRuntime;
  model?: Model<any>;
  thinkingLevel?: "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
  pythonPath?: string;
  repoRoot?: string;
  /** Internal/public for deterministic prefix-replay tests and branch creation. */
  replayJournal?: string;
  replayThrough?: number;
}

async function selectModel(runtime: ModelRuntime, requested?: Model<any>): Promise<Model<any>> {
  if (requested) {
    assertVisionModel(requested);
    const auth = await runtime.checkAuth(requested.provider);
    if (auth === undefined) {
      throw new Error(`no standard Pi authentication is configured for ${requested.provider}`);
    }
    return requested;
  }
  const available = await runtime.getAvailable();
  const vision = available.find((candidate) => candidate.input.includes("image"));
  if (!vision) throw new Error("no authenticated Pi vision model is available");
  return vision;
}

function deterministicSettings(): SettingsManager {
  return SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: { enabled: false },
    steeringMode: "one-at-a-time",
    followUpMode: "one-at-a-time",
    images: { blockImages: false, autoResize: false },
    enableInstallTelemetry: false,
  });
}

/**
 * Pi control plane paired with one Python kernel subprocess.
 *
 * Checkpoints are emitted only at ``turn_end``, after Pi has emitted and
 * persisted every tool result in the assistant's batch. Branching while the
 * session is streaming, from a terminal state, or from an unknown checkpoint
 * is rejected.
 */
export class SimAgentRuntime {
  readonly session: AgentSession;
  readonly kernel: KernelClient;
  readonly modelRuntime: ModelRuntime;
  readonly model: Model<any>;
  readonly description: KernelDescription;
  readonly resourceLoader: ResourceLoader;

  private checkpoints: BranchCheckpoint[] = [];
  private checkpointSequence = 0;
  private readonly unsubscribe: () => void;
  private disposed = false;

  constructor(
    session: AgentSession,
    kernel: KernelClient,
    modelRuntime: ModelRuntime,
    model: Model<any>,
    resourceLoader: ResourceLoader,
  ) {
    this.session = session;
    this.kernel = kernel;
    this.modelRuntime = modelRuntime;
    this.model = model;
    this.description = kernel.description;
    this.resourceLoader = resourceLoader;
    this.unsubscribe = session.subscribe((event) => {
      if (event.type === "turn_end") this.recordCheckpoint();
    });
  }

  private recordCheckpoint(): void {
    const piEntryId = this.session.sessionManager.getLeafId();
    if (!piEntryId) return;
    const previous = this.checkpoints.at(-1);
    if (
      previous?.piEntryId === piEntryId &&
      previous.kernelJournalSeq === this.kernel.tip.journalSeq
    ) {
      return;
    }
    this.checkpoints.push({
      id: `checkpoint-${++this.checkpointSequence}`,
      piEntryId,
      kernelJournalSeq: this.kernel.tip.journalSeq,
      kernelStateHash: this.kernel.tip.stateHash,
      settled: true,
      safe: !this.kernel.tip.finished,
    });
  }

  getCheckpoints(): readonly BranchCheckpoint[] {
    return this.checkpoints.map((checkpoint) => ({ ...checkpoint }));
  }

  latestCheckpoint(): BranchCheckpoint {
    const checkpoint = this.checkpoints.at(-1);
    if (!checkpoint) throw new Error("session has no settled branch checkpoint");
    return { ...checkpoint };
  }

  async prompt(text: string): Promise<void> {
    await this.session.prompt(text, { expandPromptTemplates: false });
  }

  async promptTask(): Promise<void> {
    await this.prompt(this.description.taskPrompt);
  }

  async branch(checkpoint: BranchCheckpoint, outDir: string): Promise<SimAgentRuntime> {
    if (!this.session.isIdle) throw new Error("branching is allowed only after the current Pi run settles");
    const known = this.checkpoints.find((candidate) => candidate.id === checkpoint.id);
    if (!known) throw new Error(`unknown branch checkpoint ${checkpoint.id}`);
    if (
      known.piEntryId !== checkpoint.piEntryId ||
      known.kernelJournalSeq !== checkpoint.kernelJournalSeq ||
      known.kernelStateHash !== checkpoint.kernelStateHash
    ) {
      throw new Error("branch checkpoint metadata does not match this session");
    }
    if (!known.safe) throw new Error("cannot branch a terminal kernel checkpoint");
    if (!this.session.sessionManager.isPersisted()) {
      throw new Error("Pi session persistence is required for branch creation");
    }
    const sourceSessionFile = this.session.sessionFile;
    if (!sourceSessionFile) throw new Error("persisted Pi session has no session file");
    // SessionManager.createBranchedSession() replaces the manager it is called
    // on. Use a detached manager so the live source session remains untouched.
    const detachedSource = SessionManager.open(sourceSessionFile);
    const branchFile = detachedSource.createBranchedSession(known.piEntryId);
    if (!branchFile) throw new Error("Pi did not create a branched session file");
    const branchModel = this.session.model;
    if (!branchModel) throw new Error("source Pi session has no active model");
    assertVisionModel(branchModel);

    const branched = await createSimAgentRuntime({
      problemId: this.description.specId,
      outDir,
      cwd: this.session.sessionManager.getCwd(),
      sessionManager: SessionManager.open(branchFile),
      modelRuntime: this.modelRuntime,
      model: branchModel,
      thinkingLevel: this.session.thinkingLevel,
      repoRoot: this.kernel.repoRoot,
      pythonPath: this.kernel.pythonPath,
      replayJournal: this.kernel.tip.journalPath,
      replayThrough: known.kernelJournalSeq,
    });
    if (branched.kernel.tip.stateHash !== known.kernelStateHash) {
      await branched.dispose();
      throw new Error("branched kernel state does not match the source checkpoint");
    }
    return branched;
  }

  async dispose(): Promise<KernelFinalizeResult> {
    if (this.disposed) throw new Error("SimAgent runtime is already disposed");
    if (!this.session.isIdle) throw new Error("cannot dispose while Pi is streaming");
    this.disposed = true;
    this.unsubscribe();
    this.session.dispose();
    try {
      return await this.kernel.close();
    } catch (error) {
      await this.kernel.terminate();
      throw error;
    }
  }
}

export async function createSimAgentRuntime(
  options: CreateSimAgentRuntimeOptions,
): Promise<SimAgentRuntime> {
  const cwd = resolve(options.cwd ?? options.repoRoot ?? process.cwd());
  // Default construction deliberately uses Pi's standard auth/models locations.
  const modelRuntime = options.modelRuntime ?? (await ModelRuntime.create());
  const model = await selectModel(modelRuntime, options.model);

  const kernelOptions: KernelClientOptions = {
    problemId: options.problemId,
    outDir: options.outDir,
  };
  if (options.pythonPath !== undefined) kernelOptions.pythonPath = options.pythonPath;
  if (options.repoRoot !== undefined) kernelOptions.repoRoot = options.repoRoot;
  if (options.replayJournal !== undefined) kernelOptions.replayJournal = options.replayJournal;
  if (options.replayThrough !== undefined) kernelOptions.replayThrough = options.replayThrough;
  const kernel = await KernelClient.start(kernelOptions);

  try {
    const resourceLoader = createIsolatedResourceLoader(kernel.description.systemPrompt);
    const settingsManager = deterministicSettings();
    const sessionManager =
      options.sessionManager ??
      (options.sessionDir === undefined
        ? SessionManager.create(cwd)
        : SessionManager.create(cwd, resolve(options.sessionDir)));
    const customTools = createKernelTools(kernel);
    const { session } = await createAgentSession({
      cwd,
      model,
      thinkingLevel: options.thinkingLevel ?? "off",
      modelRuntime,
      resourceLoader,
      customTools,
      tools: [...KERNEL_TOOL_NAMES],
      excludeTools: [...BUILTIN_TOOL_NAMES],
      sessionManager,
      settingsManager,
    });

    // Pi 0.81.1 defaults to parallel execution. The kernel owns one mutable
    // world, so force both the global loop and every individual tool to be
    // sequential (the latter is set in createKernelTools()).
    session.agent.toolExecution = "sequential";

    // Tool implementations return kernel error metadata instead of throwing so
    // image/text blocks and terminal hints survive. Convert that metadata into
    // Pi's canonical isError flag in the post-tool hook.
    const inheritedAfterToolCall = session.agent.afterToolCall;
    session.agent.afterToolCall = async (context, signal) => {
      const inherited = await inheritedAfterToolCall?.(context, signal);
      const details = inherited?.details ?? context.result.details;
      if (!isKernelToolDetails(details)) return inherited;
      return {
        ...inherited,
        details,
        isError: details.kernel.isError || inherited?.isError === true,
        terminate: details.kernel.finished || inherited?.terminate === true,
      };
    };

    const active = session.getActiveToolNames();
    const accidental = active.filter((name) => !KERNEL_TOOL_NAMES.includes(name));
    if (accidental.length > 0 || active.length !== KERNEL_TOOL_NAMES.length) {
      session.dispose();
      throw new Error(`Pi exposed an unexpected tool set: ${active.join(", ")}`);
    }
    return new SimAgentRuntime(session, kernel, modelRuntime, model, resourceLoader);
  } catch (error) {
    await kernel.terminate();
    throw error;
  }
}
