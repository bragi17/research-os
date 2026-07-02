"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Activity,
  BadgeCheck,
  Beaker,
  Bot,
  CheckCircle2,
  CircleDot,
  Clock3,
  FileText,
  FolderTree,
  Loader2,
  Package,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  ScrollText,
  Search,
  Server,
  Terminal as TerminalIcon,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { FitAddon } from "@xterm/addon-fit";
import type { Terminal as XTermTerminal } from "@xterm/xterm";
import {
  closeTerminalSession,
  createCodingTask,
  createExperimentManifest,
  createExperimentPlan,
  createManuscriptPackage,
  createProductionProject,
  createRemoteHost,
  createSubmissionPackage,
  createTerminalSession,
  expandExperimentManifestJobs,
  generateClaimsFromResults,
  gateSubmissionPackage,
  getExperimentJobArtifacts,
  getExperimentJobLog,
  getModelSettings,
  getWorkspaceFile,
  getWorkspaceTree,
  listAgentRuntimes,
  listClaims,
  listCodeArtifacts,
  listCodingEvents,
  listCodingTasks,
  listExperimentJobs,
  listExperimentManifests,
  listExperimentPlans,
  listManuscriptPackages,
  listProductionProjects,
  listRemoteHosts,
  listSubmissionPackages,
  listTerminalSessions,
  productionTerminalWebSocketUrl,
  resizeTerminalSession,
  runCodingTask,
  runLocalExperimentJob,
  startManuscriptDrafting,
  type AgentRuntime,
  type ClaimLedger,
  type CodeArtifact,
  type CodingEvent,
  type CodingTask,
  type ExperimentJob,
  type ExperimentManifest,
  type ExperimentPlan,
  type JobLogTail,
  type ManuscriptPackage,
  type ProductionProject,
  type RemoteHost,
  type SubmissionPackage,
  type TerminalSession,
  type WorkspaceFile,
  type WorkspaceTree,
  type WorkspaceTreeEntry,
} from "@/lib/api";

type TabKey =
  | "plan"
  | "agent"
  | "terminal"
  | "logs"
  | "files"
  | "artifacts"
  | "claims"
  | "writing";

interface ExperimentWorkspaceProps {
  runId: string;
  topic: string;
}

interface WorkspaceState {
  projects: ProductionProject[];
  remoteHosts: RemoteHost[];
  runtimes: AgentRuntime[];
  tasks: CodingTask[];
  plans: ExperimentPlan[];
  events: CodingEvent[];
  artifacts: CodeArtifact[];
  manifests: ExperimentManifest[];
  jobs: ExperimentJob[];
  claims: ClaimLedger[];
  terminals: TerminalSession[];
  manuscripts: ManuscriptPackage[];
  submissions: SubmissionPackage[];
}

const EMPTY_STATE: WorkspaceState = {
  projects: [],
  remoteHosts: [],
  runtimes: [],
  tasks: [],
  plans: [],
  events: [],
  artifacts: [],
  manifests: [],
  jobs: [],
  claims: [],
  terminals: [],
  manuscripts: [],
  submissions: [],
};

const TABS: Array<{ key: TabKey; label: string; icon: LucideIcon }> = [
  { key: "plan", label: "Plan", icon: Beaker },
  { key: "agent", label: "Code Agent", icon: Bot },
  { key: "terminal", label: "Terminal", icon: TerminalIcon },
  { key: "logs", label: "Logs", icon: ScrollText },
  { key: "files", label: "Files", icon: FolderTree },
  { key: "artifacts", label: "Artifacts", icon: Package },
  { key: "claims", label: "Claims", icon: BadgeCheck },
  { key: "writing", label: "Writing", icon: PenLine },
];

const INPUT_CLASS =
  "min-h-8 w-full rounded-md border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 text-[12px] text-[var(--text-secondary)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] disabled:opacity-50";

const TEXTAREA_CLASS =
  "min-h-[72px] w-full resize-y rounded-md border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 py-2 text-[12px] leading-relaxed text-[var(--text-secondary)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] disabled:opacity-50";

const COMPACT_TEXTAREA_CLASS =
  "h-8 min-h-8 w-full resize-y rounded-md border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 py-1.5 text-[12px] leading-4 text-[var(--text-secondary)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] disabled:opacity-50";

const DEFAULT_EXPERIMENT_ROOT = "/data/research-os/experiments";

const REQUIRED_ACCEPTANCE_CRITERIA = {
  sanity_checks: ["The experiment command exits successfully."],
  minimum_artifacts: ["metrics.json", "report.md"],
  metric_thresholds: {},
  negative_controls: [],
  reproducibility_requirements: [
    "The manifest records an executable command and working directory.",
  ],
  claim_support_requirements: [
    "Claims cite generated metrics, logs, or artifacts.",
  ],
};

interface CreateDraftState {
  projectTitle: string;
  projectWorkspace: string;
  planTitle: string;
  planHypothesis: string;
  taskPrompt: string;
  taskProvider: string;
  manifestCmd: string;
  remoteMode: string;
  remoteHostId: string;
  remoteName: string;
  remoteHost: string;
  remotePort: string;
  remoteUsername: string;
  remoteKeyRef: string;
  remoteWorkdir: string;
  manuscriptTitle: string;
  venue: string;
  submissionDeadline: string;
}

const EMPTY_CREATE_DRAFT: CreateDraftState = {
  projectTitle: "",
  projectWorkspace: "",
  planTitle: "",
  planHypothesis: "",
  taskPrompt: "",
  taskProvider: "codex",
  manifestCmd: "",
  remoteMode: "local",
  remoteHostId: "",
  remoteName: "",
  remoteHost: "",
  remotePort: "22",
  remoteUsername: "",
  remoteKeyRef: "",
  remoteWorkdir: "",
  manuscriptTitle: "",
  venue: "",
  submissionDeadline: "",
};

function shortId(id?: string | null): string {
  return id ? id.slice(0, 8) : "none";
}

function formatDate(value?: string | null): string {
  if (!value) return "not set";
  try {
    return new Date(value).toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function jsonCount(value: unknown): string {
  if (Array.isArray(value))
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (value && typeof value === "object")
    return `${Object.keys(value).length} key${Object.keys(value).length === 1 ? "" : "s"}`;
  return "empty";
}

function projectMatchesRun(project: ProductionProject, runId: string): boolean {
  const sourceRunId = project.metadata_json?.source_run_id;
  const metadataRunId = project.metadata_json?.run_id;
  return sourceRunId === runId || metadataRunId === runId;
}

function slugify(value: string): string {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "experiment";
}

function buildExperimentWorkspacePath(root: string, topic: string, runId: string): string {
  const base = (root.trim() || DEFAULT_EXPERIMENT_ROOT).replace(/\/+$/g, "");
  return `${base}/${slugify(topic)}-${shortId(runId)}`;
}

function statusClass(status?: string | null): string {
  const value = (status || "").toLowerCase();
  if (
    [
      "completed",
      "passed",
      "supported",
      "accepted",
      "ready",
      "open",
      "reachable",
    ].includes(value)
  ) {
    return "border-[var(--accent-green)] text-[var(--accent-green)] bg-[var(--accent-green-soft)]";
  }
  if (
    [
      "running",
      "implementing",
      "sanity_running",
      "full_running",
      "drafting",
      "reviewing",
      "opening",
    ].includes(value)
  ) {
    return "border-[var(--accent)] text-[var(--accent)] bg-[var(--accent-soft)]";
  }
  if (
    [
      "failed",
      "timeout",
      "cancelled",
      "blocked",
      "unsupported",
      "contradicted",
      "closed",
      "unreachable",
    ].includes(value)
  ) {
    return "border-[var(--accent-red)] text-[var(--accent-red)] bg-[var(--accent-red-soft)]";
  }
  return "border-[var(--border-subtle)] text-[var(--text-muted)] bg-[var(--bg-secondary)]";
}

function StatusPill({ status }: { status?: string | null }) {
  return (
    <span
      className={`inline-flex max-w-full items-center rounded px-2 py-0.5 text-[10px] font-medium uppercase ${statusClass(status)}`}
    >
      <span className="truncate">{status || "unknown"}</span>
    </span>
  );
}

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border-subtle)] px-3 py-5 text-center text-[12px] text-[var(--text-muted)]">
      {label}
    </div>
  );
}

function Meta({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </div>
      <div
        className="truncate text-[12px] text-[var(--text-secondary)]"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {value ?? "none"}
      </div>
    </div>
  );
}

function ToolbarButton({
  children,
  disabled,
  onClick,
  title,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-[var(--border-subtle)] px-2.5 text-[12px] font-medium text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:pointer-events-none disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function CreateSection({
  title,
  detail,
  busy,
  disabled,
  onCreate,
  children,
}: {
  title: string;
  detail: string;
  busy: boolean;
  disabled?: boolean;
  onCreate: () => void;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 px-3 py-3 lg:grid-cols-[140px_minmax(0,1fr)_auto] lg:items-start">
      <div className="min-w-0">
        <div className="text-[12px] font-medium text-[var(--text-primary)]">
          {title}
        </div>
        <div className="mt-1 text-[11px] text-[var(--text-muted)]">
          {detail}
        </div>
      </div>
      <div className="min-w-0">{children}</div>
      <div className="flex lg:justify-end">
        <ToolbarButton
          title={`Create ${title.toLowerCase()}`}
          disabled={disabled || busy}
          onClick={onCreate}
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Create
        </ToolbarButton>
      </div>
    </div>
  );
}

export default function ExperimentWorkspace({
  runId,
  topic,
}: ExperimentWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("plan");
  const [state, setState] = useState<WorkspaceState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [createDraft, setCreateDraft] =
    useState<CreateDraftState>(EMPTY_CREATE_DRAFT);
  const [settingsWorkspaceRoot, setSettingsWorkspaceRoot] = useState(
    DEFAULT_EXPERIMENT_ROOT,
  );
  const [workspaceTree, setWorkspaceTree] = useState<WorkspaceTree | null>(
    null,
  );
  const [selectedFile, setSelectedFile] = useState<WorkspaceFile | null>(null);
  const [jobLogTail, setJobLogTail] = useState<JobLogTail | null>(null);
  const [jobArtifacts, setJobArtifacts] = useState<WorkspaceTree | null>(null);
  const [terminalStatus, setTerminalStatus] = useState<string>("idle");
  const [selectedLogJobId, setSelectedLogJobId] = useState<string | null>(null);
  const [logStream, setLogStream] = useState<"stdout" | "stderr">("stdout");
  const [logSearch, setLogSearch] = useState("");
  const [followLogs, setFollowLogs] = useState(false);
  const mountedRef = useRef(false);
  const loadSeqRef = useRef(0);
  const terminalSocketRef = useRef<WebSocket | null>(null);
  const terminalContainerRef = useRef<HTMLDivElement | null>(null);
  const xtermRef = useRef<XTermTerminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const terminalAttachSeqRef = useRef(0);

  const firstTask = state.tasks[0];
  const runProject =
    state.projects.find((project) => projectMatchesRun(project, runId)) ?? null;
  const selectedProjectId =
    firstTask?.project_id ||
    state.plans[0]?.project_id ||
    state.manifests[0]?.project_id ||
    runProject?.id ||
    null;
  const selectedPlanId =
    firstTask?.experiment_plan_id ||
    state.plans[0]?.id ||
    state.manifests[0]?.experiment_plan_id ||
    null;
  const activeProject =
    (selectedProjectId
      ? state.projects.find((project) => project.id === selectedProjectId)
      : null) ??
    runProject ??
    null;
  const selectedRemoteHost =
    state.remoteHosts.find((host) => host.id === createDraft.remoteHostId) ??
    state.remoteHosts[0] ??
    null;
  const activeManuscript = state.manuscripts[0] ?? null;
  const topicLabel = topic.trim() || "Research experiment";
  const defaultProjectTitle = topicLabel;
  const defaultWorkspacePath = useMemo(
    () => buildExperimentWorkspacePath(settingsWorkspaceRoot, topicLabel, runId),
    [runId, settingsWorkspaceRoot, topicLabel],
  );
  const latestTerminal = state.terminals[0] ?? null;
  const activeJobCount = state.jobs.filter((job) =>
    ["pending", "running", "stuck"].includes(job.status),
  ).length;

  const loadWorkspace = useCallback(async () => {
    if (!mountedRef.current) return;
    const loadId = ++loadSeqRef.current;
    setRefreshing(true);
    setErrors([]);

    const nextErrors: string[] = [];
    const read = async <T,>(
      label: string,
      request: () => Promise<T>,
      fallback: T,
    ): Promise<T> => {
      try {
        return await request();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        nextErrors.push(`${label}: ${message}`);
        return fallback;
      }
    };

    const [runtimes, tasks, projects, remoteHosts] = await Promise.all([
      read("agent runtimes", () => listAgentRuntimes(), [] as AgentRuntime[]),
      read(
        "coding tasks",
        () => listCodingTasks({ run_id: runId, limit: 20 }),
        [] as CodingTask[],
      ),
      read(
        "projects",
        () => listProductionProjects({ status: "active", limit: 50 }),
        [] as ProductionProject[],
      ),
      read(
        "remote hosts",
        () => listRemoteHosts({ limit: 50 }),
        [] as RemoteHost[],
      ),
    ]);

    const runProjectId = projects.find((project) =>
      projectMatchesRun(project, runId),
    )?.id;
    const taskProjectId = tasks[0]?.project_id || runProjectId;
    const rawPlans = await read(
      "experiment plans",
      () =>
        listExperimentPlans({
          ...(taskProjectId ? { project_id: taskProjectId } : {}),
          limit: 20,
        }),
      [] as ExperimentPlan[],
    );
    const plans = taskProjectId
      ? rawPlans
      : rawPlans.filter((plan) => plan.source_run_id === runId);

    const projectId = taskProjectId || plans[0]?.project_id;
    const planId =
      tasks.find((task) => task.experiment_plan_id)?.experiment_plan_id ||
      plans[0]?.id;
    const firstTaskId = tasks[0]?.id;

    const [events, artifacts, manifests, jobs, claims, terminals, manuscripts] =
      await Promise.all([
        firstTaskId
          ? read(
              "coding events",
              () => listCodingEvents(firstTaskId, { limit: 100 }),
              [] as CodingEvent[],
            )
          : Promise.resolve([] as CodingEvent[]),
        read(
          "code artifacts",
          () =>
            listCodeArtifacts({
              ...(projectId ? { project_id: projectId } : {}),
              ...(planId ? { experiment_plan_id: planId } : {}),
              limit: 20,
            }),
          [] as CodeArtifact[],
        ),
        read(
          "manifests",
          () =>
            listExperimentManifests({
              ...(projectId ? { project_id: projectId } : {}),
              ...(planId ? { experiment_plan_id: planId } : {}),
              limit: 20,
            }),
          [] as ExperimentManifest[],
        ),
        read(
          "jobs",
          () =>
            listExperimentJobs({
              ...(projectId ? { project_id: projectId } : {}),
              ...(planId ? { experiment_plan_id: planId } : {}),
              limit: 20,
            }),
          [] as ExperimentJob[],
        ),
        read(
          "claims",
          () =>
            listClaims({
              ...(projectId ? { project_id: projectId } : {}),
              ...(planId ? { experiment_plan_id: planId } : {}),
              limit: 20,
            }),
          [] as ClaimLedger[],
        ),
        read(
          "terminal sessions",
          () =>
            listTerminalSessions({
              run_id: runId,
              ...(projectId ? { project_id: projectId } : {}),
              limit: 20,
            }),
          [] as TerminalSession[],
        ),
        read(
          "manuscripts",
          () =>
            listManuscriptPackages({
              ...(projectId ? { project_id: projectId } : {}),
              limit: 20,
            }),
          [] as ManuscriptPackage[],
        ),
      ]);

    const submissions = manuscripts[0]?.id
      ? await read(
          "submissions",
          () =>
            listSubmissionPackages({
              manuscript_package_id: manuscripts[0].id,
              limit: 20,
            }),
          [] as SubmissionPackage[],
        )
      : [];

    const logJobId =
      selectedLogJobId && jobs.some((job) => job.id === selectedLogJobId)
        ? selectedLogJobId
        : jobs[0]?.id;
    const [nextWorkspaceTree, nextJobLogTail, nextJobArtifacts] =
      await Promise.all([
        projectId
          ? read(
              "workspace tree",
              () => getWorkspaceTree(projectId, { run_id: runId, path: "." }),
              null as WorkspaceTree | null,
            )
          : Promise.resolve(null),
        logJobId
          ? read(
              "job log",
              () => getExperimentJobLog(logJobId, logStream, 500),
              null as JobLogTail | null,
            )
          : Promise.resolve(null),
        jobs[0]
          ? read(
              "job artifacts",
              () => getExperimentJobArtifacts(jobs[0].id),
              null as WorkspaceTree | null,
            )
          : Promise.resolve(null),
      ]);

    if (!mountedRef.current || loadId !== loadSeqRef.current) return;
    setState({
      projects,
      remoteHosts,
      runtimes,
      tasks,
      plans,
      events,
      artifacts,
      manifests,
      jobs,
      claims,
      terminals,
      manuscripts,
      submissions,
    });
    setWorkspaceTree(nextWorkspaceTree);
    setJobLogTail(nextJobLogTail);
    setJobArtifacts(nextJobArtifacts);
    if (!selectedLogJobId && logJobId) setSelectedLogJobId(logJobId);
    setErrors(nextErrors);
    setLoading(false);
    setRefreshing(false);
  }, [runId, selectedLogJobId, logStream]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      terminalAttachSeqRef.current += 1;
      terminalSocketRef.current?.close();
      terminalSocketRef.current = null;
      xtermRef.current?.dispose();
      xtermRef.current = null;
      fitAddonRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getModelSettings()
      .then((settings) => {
        if (cancelled) return;
        const rootItem = settings.categories
          .find((category) => category.id === "storage")
          ?.items.find((item) => item.key === "RESEARCH_OS_WORKSPACE_ROOT");
        const root = rootItem?.value?.trim();
        if (root) setSettingsWorkspaceRoot(root);
      })
      .catch(() => {
        if (!cancelled) setSettingsWorkspaceRoot(DEFAULT_EXPERIMENT_ROOT);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (!followLogs || activeTab !== "logs") return;
    const interval = window.setInterval(() => {
      loadWorkspace();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [activeTab, followLogs, loadWorkspace]);

  const updateCreateDraft = (field: keyof CreateDraftState, value: string) => {
    setCreateDraft((draft) => ({ ...draft, [field]: value }));
  };

  const performWorkspaceAction = async (
    busyKey: string,
    action: () => Promise<string>,
  ) => {
    setActionBusy(busyKey);
    setActionMessage(null);
    try {
      const message = await action();
      if (!mountedRef.current) return;
      setActionMessage(message);
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const createProjectEntry = () =>
    performWorkspaceAction("create:project", async () => {
      const title = createDraft.projectTitle.trim() || defaultProjectTitle;
      const workspacePath =
        createDraft.projectWorkspace.trim() || defaultWorkspacePath;
      const project = await createProductionProject({
        title,
        description: `Experiment workspace for ${topicLabel}`,
        primary_topic: topicLabel,
        status: "active",
        default_library_pool_ids: [],
        default_workspace_path: workspacePath,
        metadata_json: {
          created_from: "experiment_workspace",
          source_run_id: runId,
          topic: topicLabel,
        },
      });
      return `Project created: ${shortId(project.id)}`;
    });

  const createPlanEntry = () =>
    performWorkspaceAction("create:plan", async () => {
      if (!selectedProjectId) throw new Error("Create a project first.");
      const title =
        createDraft.planTitle.trim() || `${topicLabel} experiment plan`;
      const hypothesis =
        createDraft.planHypothesis.trim() ||
        `A focused experiment can produce measurable evidence for ${topicLabel}.`;
      const plan = await createExperimentPlan({
        project_id: selectedProjectId,
        source_run_id: runId,
        title,
        hypothesis,
        method_plan_markdown:
          "1. Implement a reproducible experiment.\n2. Run sanity checks and collect metrics.\n3. Register artifacts for claim review.",
        implementation_plan_markdown:
          "Use the coding task to create scripts, configs, and a runnable manifest in the workspace.",
        datasets_json: { datasets: [] },
        baselines_json: { baselines: [] },
        metrics_json: { metrics: [] },
        ablation_plan_json: { ablations: [] },
        resource_plan_json: { local_first: true },
        expected_outputs_json: {
          artifacts: ["metrics.json", "report.md"],
        },
        acceptance_criteria_json: REQUIRED_ACCEPTANCE_CRITERIA,
        risk_register_json: { risks: [] },
        status: "draft",
      });
      return `Experiment plan created: ${shortId(plan.id)}`;
    });

  const createTaskEntry = () =>
    performWorkspaceAction("create:task", async () => {
      if (!selectedProjectId) throw new Error("Create a project first.");
      const title =
        activePlan?.title ||
        createDraft.planTitle.trim() ||
        `${topicLabel} coding task`;
      const prompt =
        createDraft.taskPrompt.trim() ||
        `Implement the experiment workspace for "${topicLabel}". Produce runnable code, a manifest-ready command, metrics output, and a short artifact summary. Keep changes scoped to the experiment project workspace.`;
      const task = await createCodingTask({
        project_id: selectedProjectId,
        run_id: runId,
        experiment_plan_id: selectedPlanId,
        provider: createDraft.taskProvider.trim() || "codex",
        workspace_path:
          firstTask?.workspace_path ||
          activeProject?.default_workspace_path ||
          createDraft.projectWorkspace.trim() ||
          defaultWorkspacePath,
        thread_name: title,
        system_prompt:
          "You are working inside the embedded Research OS experiment workspace. Produce reproducible experiment artifacts and keep edits scoped to the assigned workspace.",
        user_prompt: prompt,
        model: null,
        timeout_sec: 3600,
        semantic_inactivity_timeout_sec: 900,
        extra_args: [],
        custom_args: [],
        env: {},
        mcp_config: null,
        thinking_level: null,
        metadata_json: {
          created_from: "experiment_workspace",
          source_run_id: runId,
        },
      });
      return `Coding task created: ${shortId(task.id)}`;
    });

  const createRemoteHostEntry = () =>
    performWorkspaceAction("create:remote", async () => {
      const host = createDraft.remoteHost.trim();
      if (!host) throw new Error("Remote host is required.");
      const name =
        createDraft.remoteName.trim() ||
        `${slugify(topicLabel)}-${host.replace(/[^a-zA-Z0-9._-]+/g, "-")}`;
      const port = Number.parseInt(createDraft.remotePort || "22", 10);
      if (!Number.isFinite(port) || port < 1 || port > 65535) {
        throw new Error("Remote port must be between 1 and 65535.");
      }
      const remoteHost = await createRemoteHost({
        name,
        host,
        port,
        username: createDraft.remoteUsername.trim() || null,
        auth_type: createDraft.remoteKeyRef.trim() ? "key" : "agent",
        key_ref: createDraft.remoteKeyRef.trim() || null,
        default_workdir: createDraft.remoteWorkdir.trim() || null,
        default_env_json: {},
        capabilities_json: {
          created_from: "experiment_workspace",
          source_run_id: runId,
        },
        status: "unknown",
        last_checked_at: null,
      });
      setCreateDraft((draft) => ({
        ...draft,
        remoteMode: "ssh",
        remoteHostId: remoteHost.id,
      }));
      return `Remote host created: ${shortId(remoteHost.id)}`;
    });

  const createManifestEntry = () =>
    performWorkspaceAction("create:manifest", async () => {
      if (!selectedProjectId || !selectedPlanId) {
        throw new Error("Create a project and experiment plan first.");
      }
      const workspacePath =
        firstTask?.workspace_path ||
        activeProject?.default_workspace_path ||
        createDraft.projectWorkspace.trim() ||
        defaultWorkspacePath;
      const cmd = createDraft.manifestCmd.trim() || "python -m pytest";
      const useSsh = createDraft.remoteMode === "ssh";
      const remoteHost = useSsh ? selectedRemoteHost : null;
      if (useSsh && !remoteHost) {
        throw new Error("Create or select a remote SSH host first.");
      }
      const manifest = await createExperimentManifest({
        experiment_plan_id: selectedPlanId,
        project_id: selectedProjectId,
        manifest_version: "1",
        generated_by_coding_task_id: firstTask?.id || null,
        status: "accepted",
        manifest_json: {
          project: activeProject?.title || topicLabel,
          workspace: workspacePath,
          environment: {
            python: "3.11",
            install: [],
            env_vars: {},
          },
          resources: {
            local_first: !useSsh,
            gpu_required: useSsh,
            remote_host_id: remoteHost?.id || null,
            max_parallel: 1,
          },
          phases: [
            {
              name: "sanity",
              depends_on: [],
              jobs: [
                {
                  name: "sanity-run",
                  cmd,
                  cwd: ".",
                  expected_outputs: ["metrics.json", "report.md"],
                  timeout_sec: 1800,
                  retry: {
                    max_attempts: 1,
                    oom_retry: false,
                  },
                },
              ],
            },
          ],
        },
      });
      try {
        const jobs = await expandExperimentManifestJobs(manifest.id);
        return `Manifest created with ${jobs.length} job${
          jobs.length === 1 ? "" : "s"
        }`;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return `Manifest created; job expansion failed: ${message}`;
      }
    });

  const createManuscriptEntry = () =>
    performWorkspaceAction("create:manuscript", async () => {
      if (!selectedProjectId) throw new Error("Create a project first.");
      const title =
        createDraft.manuscriptTitle.trim() || `${topicLabel} manuscript`;
      const venue = createDraft.venue.trim();
      const manuscript = await createManuscriptPackage({
        project_id: selectedProjectId,
        title,
        venue_target: venue || null,
        paper_dir: `manuscripts/${slugify(title)}`,
        status: "outline",
        claim_ledger_snapshot_id: null,
        bib_snapshot_id: null,
        artifact_snapshot_id: null,
      });
      return `Manuscript created: ${shortId(manuscript.id)}`;
    });

  const createSubmissionEntry = () =>
    performWorkspaceAction("create:submission", async () => {
      if (!activeManuscript) throw new Error("Create a manuscript first.");
      const venue =
        createDraft.venue.trim() || activeManuscript.venue_target || "TBD";
      const submission = await createSubmissionPackage({
        manuscript_package_id: activeManuscript.id,
        venue,
        deadline: createDraft.submissionDeadline
          ? `${createDraft.submissionDeadline}T23:59:00Z`
          : null,
        submission_dir: `submissions/${slugify(venue)}-${shortId(
          activeManuscript.id,
        )}`,
        checklist_json: { items: [] },
        anonymity_report_json: {},
        compile_report_json: {},
        claim_audit_report_json: {},
        citation_audit_report_json: {},
        artifact_provenance_report_json: {},
        status: "preparing",
      });
      return `Submission created: ${shortId(submission.id)}`;
    });

  const runTask = async (task: CodingTask) => {
    setActionBusy(`task:${task.id}`);
    setActionMessage(null);
    try {
      const result = await runCodingTask(task.id);
      if (!mountedRef.current) return;
      setActionMessage(
        result.status === "completed"
          ? "Coding task completed"
          : result.failure_reason || result.status,
      );
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const runJob = async (job: ExperimentJob) => {
    setActionBusy(`job:${job.id}`);
    setActionMessage(null);
    try {
      await runLocalExperimentJob(job.id);
      if (!mountedRef.current) return;
      setActionMessage(`Local run finished for ${job.job_name}`);
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const ensureTerminal = useCallback(async (isCurrentAttach?: () => boolean) => {
    if (xtermRef.current) return xtermRef.current;
    if (!terminalContainerRef.current) return null;
    const [{ Terminal: XTerm }, { FitAddon: XTermFitAddon }] =
      await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
    if (!mountedRef.current || !terminalContainerRef.current || (isCurrentAttach && !isCurrentAttach())) {
      return null;
    }
    if (xtermRef.current) return xtermRef.current;
    const terminal = new XTerm({
      cursorBlink: true,
      convertEol: true,
      fontFamily: "var(--font-mono), monospace",
      fontSize: 12,
      lineHeight: 1.25,
      scrollback: 5000,
      theme: {
        background: "#2D2A26",
        foreground: "#F5F0E8",
        cursor: "#C4956A",
        selectionBackground: "#C4956A55",
      },
    });
    const fitAddon = new XTermFitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(terminalContainerRef.current);
    fitAddon.fit();
    terminal.onData((data) => {
      const socket = terminalSocketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "input", data }));
      }
    });
    xtermRef.current = terminal;
    fitAddonRef.current = fitAddon;
    return terminal;
  }, []);

  const attachTerminal = useCallback((session: TerminalSession) => {
    const attachSeq = terminalAttachSeqRef.current + 1;
    terminalAttachSeqRef.current = attachSeq;
    const previousSocket = terminalSocketRef.current;
    terminalSocketRef.current = null;
    previousSocket?.close();
    setTerminalStatus("connecting");
    void (async () => {
      const isCurrentAttach = () => mountedRef.current && terminalAttachSeqRef.current === attachSeq;
      const terminal = await ensureTerminal(isCurrentAttach);
      if (!mountedRef.current || terminalAttachSeqRef.current !== attachSeq || !terminal) return;
      terminal.reset();
      terminal.writeln(`research-os terminal ${shortId(session.id)}`);
      const socket = new WebSocket(productionTerminalWebSocketUrl(session.id));
      terminalSocketRef.current = socket;
      const isActiveSocket = () =>
        mountedRef.current &&
        terminalAttachSeqRef.current === attachSeq &&
        terminalSocketRef.current === socket;

      socket.onmessage = (event) => {
        if (!isActiveSocket()) return;
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            data?: string;
            status?: string;
            message?: string;
          };
          if (payload.type === "output" && payload.data) {
            terminal.write(payload.data);
          } else if (payload.type === "status") {
            setTerminalStatus(payload.status || "open");
            if (payload.status === "closed") terminal.writeln("\r\n[closed]");
          } else if (payload.type === "error") {
            setTerminalStatus("failed");
            terminal.writeln(`\r\n[error] ${payload.message || "terminal error"}`);
          }
        } catch {
          terminal.write(String(event.data));
        }
      };
      socket.onopen = () => {
        if (!isActiveSocket()) return;
        const token = localStorage.getItem("token");
        if (token) {
          socket.send(JSON.stringify({ type: "auth", token }));
        }
        fitAddonRef.current?.fit();
        setTerminalStatus("connecting");
      };
      socket.onclose = () => {
        if (!isActiveSocket()) return;
        setTerminalStatus("closed");
      };
      socket.onerror = () => {
        if (!isActiveSocket()) return;
        setTerminalStatus("failed");
      };
    })();
  }, [ensureTerminal]);

  const openTerminal = async () => {
    setActionBusy("terminal");
    setActionMessage(null);
    try {
      const session = await createTerminalSession({
        project_id: selectedProjectId || undefined,
        run_id: runId,
        cwd: firstTask?.workspace_path || undefined,
        shell: "bash",
        status: "opening",
      });
      if (!mountedRef.current) return;
      setActionMessage("Terminal session opened");
      attachTerminal(session);
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const closeTerminal = async (session: TerminalSession) => {
    setActionBusy(`terminal:${session.id}`);
    setActionMessage(null);
    try {
      terminalSocketRef.current?.send(JSON.stringify({ type: "close" }));
      terminalSocketRef.current?.close();
      await closeTerminalSession(session.id);
      if (!mountedRef.current) return;
      setActionMessage("Terminal session closed");
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const resizeTerminal = async (session: TerminalSession) => {
    setActionBusy(`terminal-resize:${session.id}`);
    setActionMessage(null);
    try {
      fitAddonRef.current?.fit();
      const rows = xtermRef.current?.rows || 24;
      const cols = xtermRef.current?.cols || 80;
      terminalSocketRef.current?.send(
        JSON.stringify({ type: "resize", rows, cols }),
      );
      await resizeTerminalSession(session.id, rows, cols);
      if (!mountedRef.current) return;
      setActionMessage(`Terminal resized to ${cols}x${rows}`);
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const openWorkspaceEntry = async (entry: WorkspaceTreeEntry) => {
    if (!selectedProjectId || entry.kind !== "file") return;
    setActionBusy(`file:${entry.path}`);
    setActionMessage(null);
    try {
      const file = await getWorkspaceFile(selectedProjectId, {
        run_id: runId,
        path: entry.path,
      });
      if (!mountedRef.current) return;
      setSelectedFile(file);
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const generateClaims = async () => {
    if (!selectedPlanId) return;
    setActionBusy("claims");
    setActionMessage(null);
    try {
      const result = await generateClaimsFromResults(
        selectedPlanId,
        selectedProjectId,
      );
      if (!mountedRef.current) return;
      setActionMessage(
        `Generated ${result.claims.length} claim${result.claims.length === 1 ? "" : "s"}`,
      );
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const startDrafting = async (manuscript: ManuscriptPackage) => {
    setActionBusy(`manuscript:${manuscript.id}`);
    setActionMessage(null);
    try {
      const updated = await startManuscriptDrafting(manuscript.id);
      if (!mountedRef.current) return;
      setActionMessage(`Manuscript status: ${updated.status}`);
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const gateSubmission = async (submission: SubmissionPackage) => {
    setActionBusy(`submission:${submission.id}`);
    setActionMessage(null);
    try {
      const updated = await gateSubmissionPackage(submission.id);
      if (!mountedRef.current) return;
      setActionMessage(`Submission status: ${updated.status}`);
      await loadWorkspace();
    } catch (error) {
      if (!mountedRef.current) return;
      setActionMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (mountedRef.current) setActionBusy(null);
    }
  };

  const activePlan = useMemo(() => {
    if (!selectedPlanId) return state.plans[0] ?? null;
    return (
      state.plans.find((plan) => plan.id === selectedPlanId) ??
      state.plans[0] ??
      null
    );
  }, [selectedPlanId, state.plans]);

  const selectedLogJob = useMemo(() => {
    if (!state.jobs.length) return null;
    return (
      state.jobs.find((job) => job.id === selectedLogJobId) ??
      state.jobs[0]
    );
  }, [selectedLogJobId, state.jobs]);

  const filteredLogContent = useMemo(() => {
    const content = jobLogTail?.content || "";
    const query = logSearch.trim().toLowerCase();
    if (!query) return content;
    return content
      .split("\n")
      .filter((line) => line.toLowerCase().includes(query))
      .join("\n");
  }, [jobLogTail?.content, logSearch]);

  const renderCreatePanel = () => (
    <div className="overflow-hidden rounded-md border border-[var(--border-subtle)]">
      <div className="flex flex-col gap-2 border-b border-[var(--border-subtle)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-[12px] font-medium text-[var(--text-primary)]">
            Setup
          </div>
          <div className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">
            Embedded creation flow for this run
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={selectedProjectId ? "project" : "no project"} />
          <StatusPill status={selectedPlanId ? "plan" : "no plan"} />
          <StatusPill status={selectedRemoteHost ? "ssh host" : "local"} />
          <StatusPill status={activeManuscript ? "manuscript" : "no paper"} />
        </div>
      </div>
      <div className="divide-y divide-[var(--border-subtle)]">
        <CreateSection
          title="Project"
          detail={selectedProjectId ? shortId(selectedProjectId) : "Required"}
          busy={actionBusy === "create:project"}
          onCreate={createProjectEntry}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              aria-label="Project title"
              value={createDraft.projectTitle}
              onChange={(event) =>
                updateCreateDraft("projectTitle", event.target.value)
              }
              placeholder={defaultProjectTitle}
              className={INPUT_CLASS}
            />
            <input
              aria-label="Workspace path"
              value={createDraft.projectWorkspace}
              onChange={(event) =>
                updateCreateDraft("projectWorkspace", event.target.value)
              }
              placeholder={activeProject?.default_workspace_path || defaultWorkspacePath}
              className={INPUT_CLASS}
            />
          </div>
        </CreateSection>

        <CreateSection
          title="Experiment plan"
          detail={selectedPlanId ? shortId(selectedPlanId) : "After project"}
          busy={actionBusy === "create:plan"}
          disabled={!selectedProjectId}
          onCreate={createPlanEntry}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              aria-label="Plan title"
              value={createDraft.planTitle}
              onChange={(event) =>
                updateCreateDraft("planTitle", event.target.value)
              }
              placeholder={`${topicLabel} experiment plan`}
              className={INPUT_CLASS}
              disabled={!selectedProjectId}
            />
            <input
              aria-label="Hypothesis"
              value={createDraft.planHypothesis}
              onChange={(event) =>
                updateCreateDraft("planHypothesis", event.target.value)
              }
              placeholder={`Measurable evidence for ${topicLabel}`}
              className={INPUT_CLASS}
              disabled={!selectedProjectId}
            />
          </div>
        </CreateSection>

        <CreateSection
          title="Coding task"
          detail={firstTask ? shortId(firstTask.id) : "After project"}
          busy={actionBusy === "create:task"}
          disabled={!selectedProjectId}
          onCreate={createTaskEntry}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[140px_minmax(0,1fr)]">
            <select
              aria-label="Coding provider"
              value={createDraft.taskProvider}
              onChange={(event) =>
                updateCreateDraft("taskProvider", event.target.value)
              }
              className={INPUT_CLASS}
              disabled={!selectedProjectId}
            >
              <option value="codex">codex</option>
              <option value="claude">claude</option>
              <option value="copilot">copilot</option>
              <option value="cursor">cursor</option>
              <option value="opencode">opencode</option>
            </select>
            <textarea
              aria-label="Coding task prompt"
              rows={1}
              value={createDraft.taskPrompt}
              onChange={(event) =>
                updateCreateDraft("taskPrompt", event.target.value)
              }
              placeholder={`Implement the experiment workspace for ${topicLabel}`}
              className={COMPACT_TEXTAREA_CLASS}
              disabled={!selectedProjectId}
            />
          </div>
        </CreateSection>

        <CreateSection
          title="Remote SSH"
          detail={selectedRemoteHost ? shortId(selectedRemoteHost.id) : "Optional"}
          busy={actionBusy === "create:remote"}
          onCreate={createRemoteHostEntry}
        >
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-[120px_minmax(0,1fr)]">
            <select
              aria-label="Execution mode"
              value={createDraft.remoteMode}
              onChange={(event) =>
                updateCreateDraft("remoteMode", event.target.value)
              }
              className={INPUT_CLASS}
            >
              <option value="local">local</option>
              <option value="ssh">ssh</option>
            </select>
            <select
              aria-label="Remote host"
              value={createDraft.remoteHostId}
              onChange={(event) =>
                updateCreateDraft("remoteHostId", event.target.value)
              }
              className={INPUT_CLASS}
            >
              <option value="">latest remote host</option>
              {state.remoteHosts.map((host) => (
                <option key={host.id} value={host.id}>
                  {host.name} ({host.host})
                </option>
              ))}
            </select>
          </div>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <input
              aria-label="Remote name"
              value={createDraft.remoteName}
              onChange={(event) =>
                updateCreateDraft("remoteName", event.target.value)
              }
              placeholder="gpu-box"
              className={INPUT_CLASS}
            />
            <input
              aria-label="Remote host address"
              value={createDraft.remoteHost}
              onChange={(event) =>
                updateCreateDraft("remoteHost", event.target.value)
              }
              placeholder="gpu.example.test"
              className={INPUT_CLASS}
            />
            <input
              aria-label="Remote username"
              value={createDraft.remoteUsername}
              onChange={(event) =>
                updateCreateDraft("remoteUsername", event.target.value)
              }
              placeholder="username"
              className={INPUT_CLASS}
            />
            <input
              aria-label="Remote port"
              inputMode="numeric"
              value={createDraft.remotePort}
              onChange={(event) =>
                updateCreateDraft("remotePort", event.target.value)
              }
              placeholder="22"
              className={INPUT_CLASS}
            />
            <input
              aria-label="SSH key path"
              value={createDraft.remoteKeyRef}
              onChange={(event) =>
                updateCreateDraft("remoteKeyRef", event.target.value)
              }
              placeholder="~/.ssh/id_rsa"
              className={INPUT_CLASS}
            />
            <input
              aria-label="Remote workdir"
              value={createDraft.remoteWorkdir}
              onChange={(event) =>
                updateCreateDraft("remoteWorkdir", event.target.value)
              }
              placeholder="/srv/research/project"
              className={`${INPUT_CLASS} sm:col-span-2 xl:col-span-3`}
            />
          </div>
        </CreateSection>

        <CreateSection
          title="Manifest"
          detail={state.manifests[0] ? shortId(state.manifests[0].id) : "After plan"}
          busy={actionBusy === "create:manifest"}
          disabled={!selectedProjectId || !selectedPlanId}
          onCreate={createManifestEntry}
        >
          <input
            aria-label="Manifest command"
            value={createDraft.manifestCmd}
            onChange={(event) =>
              updateCreateDraft("manifestCmd", event.target.value)
            }
            placeholder="python -m pytest"
            className={INPUT_CLASS}
            disabled={!selectedProjectId || !selectedPlanId}
          />
        </CreateSection>

        <CreateSection
          title="Manuscript"
          detail={activeManuscript ? shortId(activeManuscript.id) : "After project"}
          busy={actionBusy === "create:manuscript"}
          disabled={!selectedProjectId}
          onCreate={createManuscriptEntry}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              aria-label="Manuscript title"
              value={createDraft.manuscriptTitle}
              onChange={(event) =>
                updateCreateDraft("manuscriptTitle", event.target.value)
              }
              placeholder={`${topicLabel} manuscript`}
              className={INPUT_CLASS}
              disabled={!selectedProjectId}
            />
            <input
              aria-label="Target venue"
              value={createDraft.venue}
              onChange={(event) =>
                updateCreateDraft("venue", event.target.value)
              }
              placeholder="Target venue"
              className={INPUT_CLASS}
              disabled={!selectedProjectId}
            />
          </div>
        </CreateSection>

        <CreateSection
          title="Submission"
          detail={state.submissions[0] ? shortId(state.submissions[0].id) : "After manuscript"}
          busy={actionBusy === "create:submission"}
          disabled={!activeManuscript}
          onCreate={createSubmissionEntry}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              aria-label="Submission venue"
              value={createDraft.venue}
              onChange={(event) =>
                updateCreateDraft("venue", event.target.value)
              }
              placeholder={activeManuscript?.venue_target || "Venue"}
              className={INPUT_CLASS}
              disabled={!activeManuscript}
            />
            <input
              aria-label="Submission deadline"
              type="date"
              value={createDraft.submissionDeadline}
              onChange={(event) =>
                updateCreateDraft("submissionDeadline", event.target.value)
              }
              className={INPUT_CLASS}
              disabled={!activeManuscript}
            />
          </div>
        </CreateSection>
      </div>
    </div>
  );

  const renderPlan = () => (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <Meta label="Topic" value={topic} />
        <Meta label="Project" value={shortId(selectedProjectId)} />
        <Meta label="Plan" value={shortId(selectedPlanId)} />
        <Meta label="Active jobs" value={activeJobCount} />
      </div>
      {renderCreatePanel()}
      {activePlan ? (
        <div className="rounded-md border border-[var(--border-subtle)]">
          <div className="flex flex-col gap-2 border-b border-[var(--border-subtle)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                {activePlan.title}
              </div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                Updated {formatDate(activePlan.updated_at)}
              </div>
            </div>
            <StatusPill status={activePlan.status} />
          </div>
          <div className="grid grid-cols-1 gap-0 divide-y divide-[var(--border-subtle)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <div className="min-w-0 p-3">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Hypothesis
              </div>
              <p className="line-clamp-4 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                {activePlan.hypothesis}
              </p>
            </div>
            <div className="min-w-0 p-3">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Method
              </div>
              <p className="line-clamp-4 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                {activePlan.method_plan_markdown}
              </p>
            </div>
            <div className="min-w-0 p-3">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Acceptance
              </div>
              <p className="text-[12px] leading-relaxed text-[var(--text-secondary)]">
                {jsonCount(activePlan.acceptance_criteria_json)} criteria,{" "}
                {jsonCount(activePlan.expected_outputs_json)} outputs
              </p>
            </div>
          </div>
        </div>
      ) : (
        <EmptyRow label="No experiment plan is linked to this run yet." />
      )}
    </div>
  );

  const renderAgent = () => (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          <Server className="h-3.5 w-3.5" />
          Runtimes
        </div>
        {state.runtimes.length > 0 ? (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {state.runtimes.map((runtime) => (
              <div
                key={runtime.provider}
                className="rounded-md border border-[var(--border-subtle)] px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                    {runtime.provider}
                  </span>
                  <StatusPill status={runtime.status} />
                </div>
                <div
                  className="mt-1 truncate text-[11px] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {runtime.version ||
                    runtime.executable_path ||
                    runtime.failure_reason ||
                    "no details"}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyRow label="No local agent runtimes detected." />
        )}
      </div>
      <div>
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          <Bot className="h-3.5 w-3.5" />
          Coding tasks
        </div>
        {state.tasks.length > 0 ? (
          <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
            {state.tasks.map((task) => (
              <div
                key={task.id}
                className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                      {task.thread_name || task.provider}
                    </span>
                    <StatusPill status={task.status} />
                  </div>
                  <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                    {task.user_prompt}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:min-w-[300px]">
                  <Meta label="Model" value={task.model || task.provider} />
                  <Meta
                    label="Duration"
                    value={
                      task.duration_ms
                        ? `${Math.round(task.duration_ms / 1000)}s`
                        : "pending"
                    }
                  />
                  <div className="col-span-2 flex justify-end">
                    <ToolbarButton
                      title="Run coding task"
                      disabled={
                        actionBusy === `task:${task.id}` ||
                        task.status === "running"
                      }
                      onClick={() => runTask(task)}
                    >
                      {actionBusy === `task:${task.id}` ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                      Run
                    </ToolbarButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyRow label="No coding task has been created for this run yet." />
        )}
      </div>
    </div>
  );

  const renderTerminal = () => (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[12px] text-[var(--text-muted)]">
          Embedded run terminal
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ToolbarButton
            title="Create terminal session"
            disabled={actionBusy === "terminal"}
            onClick={openTerminal}
          >
            {actionBusy === "terminal" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Open
          </ToolbarButton>
          {latestTerminal && latestTerminal.status !== "closed" && (
            <ToolbarButton
              title="Attach terminal session"
              onClick={() => attachTerminal(latestTerminal)}
            >
              <TerminalIcon className="h-3.5 w-3.5" />
              Attach
            </ToolbarButton>
          )}
          {latestTerminal && latestTerminal.status !== "closed" && (
            <ToolbarButton
              title="Resize terminal"
              disabled={actionBusy === `terminal-resize:${latestTerminal.id}`}
              onClick={() => resizeTerminal(latestTerminal)}
            >
              {actionBusy === `terminal-resize:${latestTerminal.id}` ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Resize
            </ToolbarButton>
          )}
          {latestTerminal && latestTerminal.status !== "closed" && (
            <ToolbarButton
              title="Close terminal session"
              disabled={actionBusy === `terminal:${latestTerminal.id}`}
              onClick={() => closeTerminal(latestTerminal)}
            >
              <XCircle className="h-3.5 w-3.5" />
              Close
            </ToolbarButton>
          )}
        </div>
      </div>
      <div className="overflow-hidden rounded-md border border-[var(--border-subtle)] bg-[var(--bg-primary)]">
        <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <TerminalIcon className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
            <span
              className="truncate text-[12px] text-[var(--text-secondary)]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {latestTerminal?.shell || "bash"} @{" "}
              {latestTerminal?.cwd || firstTask?.workspace_path || "workspace"}
            </span>
          </div>
          <StatusPill status={latestTerminal?.status || "idle"} />
        </div>
        <div
          ref={terminalContainerRef}
          className="h-[320px] overflow-hidden bg-[#2D2A26] px-2 py-2"
        />
        <div className="flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] px-3 py-2">
          <span className="text-[11px] text-[var(--text-muted)]">
            {latestTerminal ? `PTY ${terminalStatus}` : "No terminal session"}
          </span>
          <span
            className="truncate text-[11px] text-[var(--text-muted)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {terminalSocketRef.current?.readyState === WebSocket.OPEN
              ? "websocket open"
              : "websocket idle"}
          </span>
        </div>
      </div>
      {state.terminals.length > 0 && (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {state.terminals.map((session) => (
            <div
              key={session.id}
              className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <div className="min-w-0">
                <div className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                  {shortId(session.id)} - {session.session_type}
                </div>
                <div
                  className="truncate text-[11px] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {session.cwd || "cwd not set"}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={session.status} />
                <span className="text-[11px] text-[var(--text-muted)]">
                  {formatDate(session.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderLogs = () => (
    <div className="space-y-3">
      {state.jobs.length > 0 && (
        <div className="overflow-hidden rounded-md border border-[var(--border-subtle)]">
          <div className="grid grid-cols-1 gap-2 border-b border-[var(--border-subtle)] px-3 py-2 lg:grid-cols-[minmax(0,1fr)_auto_auto_minmax(180px,260px)] lg:items-center">
            <select
              aria-label="Log job"
              value={selectedLogJob?.id || ""}
              onChange={(event) => setSelectedLogJobId(event.target.value)}
              className={INPUT_CLASS}
            >
              {state.jobs.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.phase_name} / {job.job_name} ({shortId(job.id)})
                </option>
              ))}
            </select>
            <div className="inline-flex overflow-hidden rounded-md border border-[var(--border-subtle)]">
              {(["stdout", "stderr"] as const).map((stream) => (
                <button
                  key={stream}
                  type="button"
                  onClick={() => setLogStream(stream)}
                  className={`h-8 px-2.5 text-[12px] font-medium ${
                    logStream === stream
                      ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                      : "text-[var(--text-muted)] hover:bg-[var(--bg-secondary)]"
                  }`}
                >
                  {stream}
                </button>
              ))}
            </div>
            <label className="inline-flex h-8 items-center gap-2 rounded-md border border-[var(--border-subtle)] px-2.5 text-[12px] text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={followLogs}
                onChange={(event) => setFollowLogs(event.target.checked)}
                className="h-3.5 w-3.5"
              />
              Follow
            </label>
            <div className="flex min-w-0 items-center gap-2 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-[var(--text-muted)]" />
              <input
                aria-label="Search logs"
                value={logSearch}
                onChange={(event) => setLogSearch(event.target.value)}
                className="h-8 min-w-0 flex-1 bg-transparent text-[12px] text-[var(--text-secondary)] outline-none placeholder:text-[var(--text-muted)]"
                placeholder="Search"
              />
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-3 py-2">
            <div
              className="truncate text-[12px] font-medium text-[var(--text-primary)]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {jobLogTail?.path || `${selectedLogJob?.job_name || "job"} ${logStream}`}
            </div>
            {jobLogTail && (
              <span className="text-[11px] text-[var(--text-muted)]">
                {jobLogTail.size} bytes{jobLogTail.truncated ? ", truncated" : ""}
              </span>
            )}
          </div>
          <pre
            className="max-h-[220px] overflow-y-auto whitespace-pre-wrap break-words bg-[var(--bg-primary)] px-3 py-2 text-[11px] leading-relaxed text-[var(--text-secondary)]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {filteredLogContent || "empty log"}
          </pre>
        </div>
      )}
      {state.events.length > 0 ? (
        <div className="max-h-[360px] divide-y divide-[var(--border-subtle)] overflow-y-auto rounded-md border border-[var(--border-subtle)]">
          {state.events.map((event) => (
            <div
              key={`${event.id}-${event.created_at}`}
              className="grid grid-cols-[auto_1fr] gap-3 px-3 py-2"
            >
              <CircleDot className="mt-1 h-3.5 w-3.5 text-[var(--accent)]" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-medium text-[var(--text-primary)]">
                    {event.event_type}
                  </span>
                  {event.level && <StatusPill status={event.level} />}
                  <span className="text-[11px] text-[var(--text-muted)]">
                    {formatDate(event.created_at)}
                  </span>
                </div>
                <div className="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-[var(--text-secondary)]">
                  {event.content ||
                    event.status_text ||
                    event.output_text ||
                    event.tool ||
                    "No message body"}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyRow label="No coding-agent log events are available." />
      )}
      {state.jobs.some((job) => job.stdout_log_path || job.stderr_log_path) && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {state.jobs
            .filter((job) => job.stdout_log_path || job.stderr_log_path)
            .map((job) => (
              <div
                key={job.id}
                className="rounded-md border border-[var(--border-subtle)] px-3 py-2"
              >
                <div className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                  {job.job_name}
                </div>
                <div
                  className="mt-1 truncate text-[11px] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {job.stdout_log_path || "stdout missing"}
                </div>
                <div
                  className="truncate text-[11px] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {job.stderr_log_path || "stderr missing"}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );

  const renderFiles = () => (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Meta
          label="Workspace"
          value={firstTask?.workspace_path || "not assigned"}
        />
        <Meta label="Manifest count" value={state.manifests.length} />
        <Meta label="Artifact count" value={state.artifacts.length} />
      </div>
      {workspaceTree && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="overflow-hidden rounded-md border border-[var(--border-subtle)]">
            <div className="border-b border-[var(--border-subtle)] px-3 py-2 text-[12px] font-medium text-[var(--text-primary)]">
              {workspaceTree.path || "."}
            </div>
            <div className="max-h-[280px] divide-y divide-[var(--border-subtle)] overflow-y-auto">
              {workspaceTree.entries.map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  onClick={() => openWorkspaceEntry(entry)}
                  disabled={
                    entry.kind !== "file" || actionBusy === `file:${entry.path}`
                  }
                  className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-2 px-3 py-2 text-left text-[12px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-secondary)] disabled:cursor-default disabled:hover:bg-transparent"
                >
                  {entry.kind === "directory" ? (
                    <FolderTree className="h-3.5 w-3.5 text-[var(--accent)]" />
                  ) : (
                    <FileText className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                  )}
                  <span
                    className="truncate"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {entry.path}
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {entry.kind}
                  </span>
                </button>
              ))}
              {workspaceTree.entries.length === 0 && (
                <div className="px-3 py-4 text-[12px] text-[var(--text-muted)]">
                  No files
                </div>
              )}
            </div>
          </div>
          <div className="overflow-hidden rounded-md border border-[var(--border-subtle)]">
            <div className="border-b border-[var(--border-subtle)] px-3 py-2 text-[12px] font-medium text-[var(--text-primary)]">
              {selectedFile?.path || "File preview"}
            </div>
            <pre
              className="max-h-[280px] overflow-y-auto whitespace-pre-wrap break-words px-3 py-2 text-[11px] leading-relaxed text-[var(--text-secondary)]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {selectedFile
                ? selectedFile.content
                : "Select a file from the workspace tree."}
            </pre>
          </div>
        </div>
      )}
      {jobArtifacts && jobArtifacts.entries.length > 0 && (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {jobArtifacts.entries.map((entry) => (
            <div
              key={entry.path}
              className="grid grid-cols-[auto_1fr_auto] items-center gap-2 px-3 py-2"
            >
              <Package className="h-3.5 w-3.5 text-[var(--accent)]" />
              <span
                className="truncate text-[12px] text-[var(--text-secondary)]"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {entry.path}
              </span>
              <span className="text-[10px] text-[var(--text-muted)]">
                {entry.kind}
              </span>
            </div>
          ))}
        </div>
      )}
      {state.manifests.length > 0 ? (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {state.manifests.map((manifest) => (
            <div
              key={manifest.id}
              className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                  Manifest {shortId(manifest.id)}
                </div>
                <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                  version {manifest.manifest_version},{" "}
                  {jsonCount(manifest.manifest_json)}
                </div>
              </div>
              <StatusPill status={manifest.status} />
            </div>
          ))}
        </div>
      ) : (
        <EmptyRow label="No experiment manifest files are registered." />
      )}
      {state.jobs.length > 0 && (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {state.jobs.map((job) => (
            <div
              key={job.id}
              className="grid grid-cols-1 gap-2 px-3 py-2 lg:grid-cols-[1fr_auto] lg:items-center"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                    {job.phase_name} / {job.job_name}
                  </span>
                  <StatusPill status={job.status} />
                </div>
                <div
                  className="mt-1 truncate text-[11px] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {job.cmd}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] text-[var(--text-muted)]">
                  {job.expected_outputs_json.length} outputs
                </span>
                <ToolbarButton
                  title="Run job"
                  disabled={actionBusy === `job:${job.id}`}
                  onClick={() => runJob(job)}
                >
                  {actionBusy === `job:${job.id}` ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Run
                </ToolbarButton>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderArtifacts = () => (
    <div className="space-y-3">
      {state.artifacts.length > 0 ? (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {state.artifacts.map((artifact) => (
            <div
              key={artifact.id}
              className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                  <span className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                    {artifact.path}
                  </span>
                </div>
                <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                  {artifact.summary || artifact.artifact_type}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={artifact.validation_status} />
                <span className="text-[11px] text-[var(--text-muted)]">
                  {formatDate(artifact.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyRow label="No code artifacts have been recorded." />
      )}
    </div>
  );

  const renderClaims = () => (
    <div className="space-y-3">
      <div className="flex justify-end">
        <ToolbarButton
          title="Generate claims from experiment results"
          disabled={!selectedPlanId || actionBusy === "claims"}
          onClick={generateClaims}
        >
          {actionBusy === "claims" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <BadgeCheck className="h-3.5 w-3.5" />
          )}
          Generate
        </ToolbarButton>
      </div>
      {state.claims.length > 0 ? (
        <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
          {state.claims.map((claim) => (
            <div
              key={claim.id}
              className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  {claim.status === "supported" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--accent-green)]" />
                  ) : (
                    <Clock3 className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                  )}
                  <span className="line-clamp-2 text-[13px] font-medium text-[var(--text-primary)]">
                    {claim.claim_text}
                  </span>
                </div>
                <div className="mt-1 line-clamp-2 text-[11px] text-[var(--text-muted)]">
                  {claim.evidence_summary || "Evidence summary pending"}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={claim.status} />
                <span className="text-[11px] text-[var(--text-muted)]">
                  {claim.support_level ?? "n/a"}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyRow label="No claim ledger entries are available." />
      )}
    </div>
  );

  const renderWriting = () => (
    <div className="space-y-4">
      <div>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Manuscripts
        </div>
        {state.manuscripts.length > 0 ? (
          <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
            {state.manuscripts.map((manuscript) => (
              <div
                key={manuscript.id}
                className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                    {manuscript.title}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                    {manuscript.venue_target ||
                      manuscript.paper_dir ||
                      "venue not selected"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={manuscript.status} />
                  <ToolbarButton
                    title="Start manuscript drafting gate"
                    disabled={actionBusy === `manuscript:${manuscript.id}`}
                    onClick={() => startDrafting(manuscript)}
                  >
                    {actionBusy === `manuscript:${manuscript.id}` ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <PenLine className="h-3.5 w-3.5" />
                    )}
                    Draft
                  </ToolbarButton>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyRow label="No manuscript package has been started." />
        )}
      </div>
      <div>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Submissions
        </div>
        {state.submissions.length > 0 ? (
          <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
            {state.submissions.map((submission) => (
              <div
                key={submission.id}
                className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                    {submission.venue}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
                    checklist {jsonCount(submission.checklist_json)}, compile{" "}
                    {jsonCount(submission.compile_report_json)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill status={submission.status} />
                  <ToolbarButton
                    title="Run submission gate"
                    disabled={actionBusy === `submission:${submission.id}`}
                    onClick={() => gateSubmission(submission)}
                  >
                    {actionBusy === `submission:${submission.id}` ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    )}
                    Gate
                  </ToolbarButton>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyRow label="No submission package has been prepared." />
        )}
      </div>
    </div>
  );

  const renderActiveTab = () => {
    if (activeTab === "plan") return renderPlan();
    if (activeTab === "agent") return renderAgent();
    if (activeTab === "terminal") return renderTerminal();
    if (activeTab === "logs") return renderLogs();
    if (activeTab === "files") return renderFiles();
    if (activeTab === "artifacts") return renderArtifacts();
    if (activeTab === "claims") return renderClaims();
    return renderWriting();
  };

  return (
    <div className="card-static overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-[var(--accent)]" />
            <h3 className="text-[13px] font-medium text-[var(--text-primary)]">
              Experiment Workspace
            </h3>
          </div>
          <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
            run {shortId(runId)} - project {shortId(selectedProjectId)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {actionMessage && (
            <span className="max-w-full truncate text-[11px] text-[var(--text-muted)]">
              {actionMessage}
            </span>
          )}
          <ToolbarButton
            title="Refresh workspace"
            disabled={refreshing}
            onClick={loadWorkspace}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
            />
            Refresh
          </ToolbarButton>
        </div>
      </div>

      <div className="overflow-x-auto border-b border-[var(--border-subtle)] px-2">
        <div className="flex min-w-max gap-1 py-2">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const selected = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium transition-colors ${
                  selected
                    ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "text-[var(--text-muted)] hover:bg-[var(--bg-secondary)] hover:text-[var(--text-primary)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-5 py-4">
        {loading ? (
          <div className="flex items-center gap-2 py-8 text-[12px] text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" />
            Loading experiment workspace...
          </div>
        ) : (
          renderActiveTab()
        )}
        {errors.length > 0 && (
          <div className="mt-4 rounded-md border border-[var(--accent-red)] bg-[var(--accent-red-soft)] px-3 py-2">
            <div className="mb-1 flex items-center gap-2 text-[12px] font-medium text-[var(--accent-red)]">
              <XCircle className="h-3.5 w-3.5" />
              Workspace data is partially unavailable
            </div>
            <div className="space-y-1">
              {errors.slice(0, 4).map((error) => (
                <div
                  key={error}
                  className="break-words text-[11px] text-[var(--text-secondary)]"
                >
                  {error}
                </div>
              ))}
              {errors.length > 4 && (
                <div className="text-[11px] text-[var(--text-muted)]">
                  {errors.length - 4} more endpoint errors
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
