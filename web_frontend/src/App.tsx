import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  File,
  Folder,
  FolderOpen,
  HardDrive,
  KeyRound,
  Loader2,
  LogOut,
  PauseCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  Settings,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  Upload,
  UserRound,
  WifiOff,
  XCircle
} from "lucide-react";

type TaskStatus = "queued" | "running" | "cancelled" | "failed" | "completed";
type ErrorCode =
  | "network"
  | "timeout"
  | "rate_limit"
  | "login_required"
  | "login_expired"
  | "not_found"
  | "private_no_access"
  | "disk_error"
  | "cancelled"
  | "unknown";
type TargetType = "profile" | "hashtag" | "shortcode" | "feed" | "stories" | "saved";
type EventLevel = "info" | "error" | "status" | "session" | "retry" | "rate_limit" | "health";

type DownloadOptions = {
  download_pictures: boolean;
  download_videos: boolean;
  download_video_thumbnails: boolean;
  download_profile_pic: boolean;
  download_posts: boolean;
  download_stories: boolean;
  download_highlights: boolean;
  download_tagged: boolean;
  download_reels: boolean;
  download_igtv: boolean;
  download_comments: boolean;
  download_geotags: boolean;
  save_metadata: boolean;
  compress_json: boolean;
  fast_update: boolean;
  max_count: number | null;
  sanitize_paths: boolean;
};

type Task = {
  id: number;
  status: TaskStatus;
  target_type: TargetType;
  targets: string[];
  options: DownloadOptions;
  error: string | null;
  error_code: ErrorCode | null;
  attempt_count: number;
  next_retry_at: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

type TaskEvent = {
  id: number;
  task_id: number;
  level: EventLevel;
  message: string;
  created_at: string;
};

type FileItem = {
  path: string;
  name: string;
  size: number;
  modified_at: string;
  is_dir: boolean;
};

type AccountStatus = {
  is_connected: boolean;
  username: string | null;
  session_file: string | null;
  updated_at: string | null;
  pending_two_factor: boolean;
  message: string | null;
};

type HealthStatus = {
  ok: boolean;
  database_writable: boolean;
  download_root_writable: boolean;
  free_disk_bytes: number;
  session: AccountStatus;
  running_tasks: number;
  queued_tasks: number;
  cooling_down: boolean;
  cooldown_until: string | null;
  message: string | null;
};

type AppSettings = {
  max_concurrent_tasks: number;
  download_root: string;
  default_max_count: number | null;
  show_debug_logs: boolean;
  desktop_notifications: boolean;
  theme: "light" | "dark" | "system";
};

type SystemInfo = {
  engine_version: string;
  database_size: number;
  storage_used: number;
  data_root: string;
  download_root: string;
  max_concurrent_tasks: number;
  running_tasks: number;
  total_tasks: number;
};

type EventMessage =
  | { type: "task"; payload: Task }
  | { type: "event"; payload: TaskEvent }
  | { type: "health"; payload: Record<string, unknown> };

const defaultOptions: DownloadOptions = {
  download_pictures: true,
  download_videos: true,
  download_video_thumbnails: true,
  download_profile_pic: true,
  download_posts: true,
  download_stories: false,
  download_highlights: false,
  download_tagged: false,
  download_reels: false,
  download_igtv: false,
  download_comments: false,
  download_geotags: false,
  save_metadata: true,
  compress_json: true,
  fast_update: false,
  max_count: 1000,
  sanitize_paths: true
};

const targetLabels: Record<TargetType, string> = {
  profile: "个人主页",
  hashtag: "话题",
  shortcode: "帖子",
  feed: "动态",
  stories: "快拍",
  saved: "已保存"
};

const statusLabels: Record<TaskStatus, string> = {
  queued: "排队中",
  running: "运行中",
  cancelled: "已取消",
  failed: "失败",
  completed: "已完成"
};

const loginTargetTypes = new Set<TargetType>(["feed", "stories", "saved"]);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...init?.headers },
    ...init
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json() as Promise<T>;
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg || item.type || "Validation error").join(", ");
  } catch {
    // Fall through to status text.
  }
  return response.statusText || `Request failed with ${response.status}`;
}

function mergeTask(tasks: Task[], task: Task): Task[] {
  const exists = tasks.some((item) => item.id === task.id);
  const next = exists ? tasks.map((item) => (item.id === task.id ? task : item)) : [task, ...tasks];
  return next.sort((a, b) => b.id - a.id);
}

function mergeEvent(events: TaskEvent[], event: TaskEvent): TaskEvent[] {
  if (events.some((item) => item.id === event.id)) return events;
  return [...events, event].sort((a, b) => a.id - b.id).slice(-500);
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function splitTargets(value: string, targetType: TargetType): string[] {
  const targets = value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (targets.length > 0) return targets;
  if (loginTargetTypes.has(targetType)) return [targetType];
  return [];
}

export function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [filePath, setFilePath] = useState("");
  const [targetType, setTargetType] = useState<TargetType>("profile");
  const [targetsText, setTargetsText] = useState("");
  const [options, setOptions] = useState<DownloadOptions>(defaultOptions);
  const [cookies, setCookies] = useState("");
  const [cookieUsername, setCookieUsername] = useState("");
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [sessionUsername, setSessionUsername] = useState("");
  const [sessionFile, setSessionFile] = useState<File | null>(null);
  const [browserName, setBrowserName] = useState("edge");
  const [settingsDraft, setSettingsDraft] = useState<AppSettings | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [eventState, setEventState] = useState<"connecting" | "connected" | "offline">("connecting");

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0] ?? null,
    [selectedTaskId, tasks]
  );
  const selectedEvents = useMemo(
    () => events.filter((event) => !selectedTask || event.task_id === selectedTask.id),
    [events, selectedTask]
  );
  const requiresLogin =
    loginTargetTypes.has(targetType) || options.download_stories || options.download_highlights || options.download_geotags;

  const refreshTasks = useCallback(async () => {
    const data = await api<Task[]>("/api/tasks");
    setTasks(data);
    setSelectedTaskId((current) => current ?? data[0]?.id ?? null);
  }, []);

  const refreshFiles = useCallback(async (path = filePath) => {
    const data = await api<FileItem[]>(`/api/files?path=${encodeURIComponent(path)}`);
    setFiles(data);
    setFilePath(path);
  }, [filePath]);

  const refreshStatus = useCallback(async () => {
    const [nextAccount, nextHealth, nextSettings, nextSystem] = await Promise.all([
      api<AccountStatus>("/api/session/status"),
      api<HealthStatus>("/api/health"),
      api<AppSettings>("/api/settings"),
      api<SystemInfo>("/api/system")
    ]);
    setAccount(nextAccount);
    setHealth(nextHealth);
    setSettings(nextSettings);
    setSettingsDraft(nextSettings);
    setSystem(nextSystem);
  }, []);

  const loadTaskEvents = useCallback(async (taskId: number) => {
    const data = await api<{ task: Task; events: TaskEvent[] }>(`/api/tasks/${taskId}`);
    setTasks((current) => mergeTask(current, data.task));
    setEvents((current) => data.events.reduce((next, event) => mergeEvent(next, event), current));
  }, []);

  useEffect(() => {
    Promise.all([refreshTasks(), refreshFiles(""), refreshStatus()]).catch((exc: unknown) =>
      setError(exc instanceof Error ? exc.message : "Unable to load dashboard data")
    );
  }, [refreshFiles, refreshStatus, refreshTasks]);

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => setEventState("connected");
    source.onerror = () => setEventState("offline");
    source.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as EventMessage;
        if (data.type === "task") {
          setTasks((current) => mergeTask(current, data.payload));
        }
        if (data.type === "event") {
          setEvents((current) => mergeEvent(current, data.payload));
        }
      } catch {
        setEventState("offline");
      }
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    if (selectedTask) {
      loadTaskEvents(selectedTask.id).catch(() => undefined);
    }
  }, [loadTaskEvents, selectedTask?.id]);

  async function runAction<T>(name: string, action: () => Promise<T>): Promise<T | null> {
    setBusyAction(name);
    setError(null);
    try {
      return await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Action failed");
      return null;
    } finally {
      setBusyAction(null);
    }
  }

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targets = splitTargets(targetsText, targetType);
    if (targets.length === 0) {
      setError("请输入至少一个目标。");
      return;
    }
    const created = await runAction("create", () =>
      api<Task>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({ target_type: targetType, targets, options })
      })
    );
    if (created) {
      setTasks((current) => mergeTask(current, created));
      setSelectedTaskId(created.id);
      if (!loginTargetTypes.has(targetType)) setTargetsText("");
    }
  }

  async function taskCommand(taskId: number, command: "cancel" | "retry") {
    const task = await runAction(`${command}-${taskId}`, () =>
      api<Task>(`/api/tasks/${taskId}/${command}`, { method: "POST" })
    );
    if (task) setTasks((current) => mergeTask(current, task));
  }

  async function importCookies(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const status = await runAction("cookies", () =>
      api<AccountStatus>("/api/session/import-cookies", {
        method: "POST",
        body: JSON.stringify({ username: cookieUsername.trim() || null, cookies })
      })
    );
    if (status) {
      setAccount(status);
      setCookies("");
      await refreshStatus();
    }
  }

  async function loginAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const status = await runAction("login", () =>
      api<AccountStatus>("/api/account/login", {
        method: "POST",
        body: JSON.stringify({ username: loginUsername.trim(), password: loginPassword })
      })
    );
    if (status) {
      setAccount(status);
      setLoginPassword("");
      await refreshStatus();
    }
  }

  async function submitTwoFactor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const status = await runAction("2fa", () =>
      api<AccountStatus>("/api/account/2fa", {
        method: "POST",
        body: JSON.stringify({ username: loginUsername.trim() || account?.username, code: twoFactorCode.trim() })
      })
    );
    if (status) {
      setAccount(status);
      setTwoFactorCode("");
      await refreshStatus();
    }
  }

  async function importSessionFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionFile) {
      setError("请选择 Session 文件。");
      return;
    }
    const body = new FormData();
    body.append("username", sessionUsername.trim());
    body.append("file", sessionFile);
    const status = await runAction("session-file", () =>
      api<AccountStatus>("/api/account/session-file", {
        method: "POST",
        body
      })
    );
    if (status) {
      setAccount(status);
      setSessionFile(null);
      await refreshStatus();
    }
  }

  async function importBrowserCookies() {
    const status = await runAction("browser-cookies", () =>
      api<AccountStatus>("/api/session/import-browser", {
        method: "POST",
        body: JSON.stringify({ browser: browserName })
      })
    );
    if (status) {
      setAccount(status);
      await refreshStatus();
    }
  }

  async function testSession() {
    const status = await runAction("test-session", () => api<AccountStatus>("/api/session/test", { method: "POST" }));
    if (status) setAccount(status);
  }

  async function clearSession() {
    const status = await runAction("clear-session", () =>
      api<AccountStatus>("/api/account/session", { method: "DELETE" })
    );
    if (status) {
      setAccount(status);
      await refreshStatus();
    }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settingsDraft) return;
    const updated = await runAction("settings", () =>
      api<AppSettings>("/api/settings", {
        method: "PATCH",
        body: JSON.stringify(settingsDraft)
      })
    );
    if (updated) {
      setSettings(updated);
      setSettingsDraft(updated);
      await Promise.all([refreshStatus(), refreshFiles("")]);
    }
  }

  function updateOption<K extends keyof DownloadOptions>(key: K, value: DownloadOptions[K]) {
    setOptions((current) => ({ ...current, [key]: value }));
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <FolderOpen size={32} aria-hidden="true" />
          <div>
            <strong>InstaFlow Pro</strong>
            <span>高级用户模式</span>
          </div>
        </div>
        <nav aria-label="控制台导航">
          <a href="#tasks">
            <Play size={18} aria-hidden="true" />
            任务列表
          </a>
          <a href="#logs">
            <TerminalSquare size={18} aria-hidden="true" />
            日志详情
          </a>
          <a href="#files">
            <Folder size={18} aria-hidden="true" />
            文件中心
          </a>
          <a href="#account">
            <UserRound size={18} aria-hidden="true" />
            账号
          </a>
          <a href="#settings">
            <Settings size={18} aria-hidden="true" />
            设置
          </a>
        </nav>
      </aside>

      <main className="workspace">
        <header className="toolbar">
          <div>
            <h1>任务列表</h1>
            <p>提交下载任务，监控队列状态和自动重试。</p>
          </div>
          <button
            className="secondary"
            type="button"
            onClick={() => Promise.all([refreshTasks(), refreshFiles(), refreshStatus()]).catch(() => undefined)}
          >
            <RefreshCw size={18} aria-hidden="true" />
            刷新
          </button>
        </header>

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <section className="status-strip" aria-label="System status">
          <StatusPill
            ok={health?.ok ?? false}
            icon={health?.ok ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
            label={health?.ok ? "Healthy" : "Needs attention"}
            detail={health?.message ?? `${health?.queued_tasks ?? 0} queued, ${health?.running_tasks ?? 0} running`}
          />
          <StatusPill
            ok={account?.is_connected ?? false}
            icon={<ShieldCheck size={18} />}
            label={account?.is_connected ? account.username ?? "Connected" : "No session"}
            detail={account?.message ?? (requiresLogin ? "Current form needs login" : "Public jobs available")}
          />
          <StatusPill
            ok={eventState === "connected"}
            icon={eventState === "connected" ? <Server size={18} /> : <WifiOff size={18} />}
            label={eventState === "connected" ? "Live updates" : "Realtime offline"}
            detail={system ? `${system.engine_version} · ${formatBytes(system.storage_used)} stored` : "Waiting for backend"}
          />
        </section>

        <section className="grid" id="tasks">
          <TaskForm
            targetType={targetType}
            setTargetType={setTargetType}
            targetsText={targetsText}
            setTargetsText={setTargetsText}
            options={options}
            updateOption={updateOption}
            onSubmit={createTask}
            requiresLogin={requiresLogin}
            accountConnected={account?.is_connected ?? false}
            busy={busyAction === "create"}
          />

          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Tasks</h2>
                <span>{tasks.length} recent jobs</span>
              </div>
            </div>
            <div className="task-list custom-scrollbar">
              {tasks.length === 0 ? (
                <p className="empty">No tasks yet.</p>
              ) : (
                tasks.map((task) => (
                  <div
                    className={`task-row ${selectedTask?.id === task.id ? "selected" : ""}`}
                    key={task.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedTaskId(task.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedTaskId(task.id);
                      }
                    }}
                  >
                    <span>#{task.id}</span>
                    <TaskStatusLabel status={task.status} />
                    <span title={task.targets.join(", ")}>{task.targets.join(", ")}</span>
                    <span>{targetLabels[task.target_type]}</span>
                    <span className="row-actions" onClick={(evt) => evt.stopPropagation()}>
                      {task.status === "running" || task.status === "queued" ? (
                        <button
                          className="text-button"
                          type="button"
                          disabled={busyAction === `cancel-${task.id}`}
                          onClick={() => taskCommand(task.id, "cancel")}
                        >
                          <PauseCircle size={16} aria-hidden="true" />
                          Cancel
                        </button>
                      ) : (
                        <button
                          className="text-button"
                          type="button"
                          disabled={busyAction === `retry-${task.id}`}
                          onClick={() => taskCommand(task.id, "retry")}
                        >
                          <RotateCcw size={16} aria-hidden="true" />
                          Retry
                        </button>
                      )}
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        </section>

        <section className="bottom-grid">
          <section className="panel" id="logs">
            <div className="panel-heading">
              <div>
                <h2>Task log</h2>
                <span>{selectedTask ? `#${selectedTask.id} · ${statusLabels[selectedTask.status]}` : "Select a task"}</span>
              </div>
              {selectedTask?.error_code && <TaskError task={selectedTask} />}
            </div>
            <div className="log-box custom-scrollbar">
              {selectedEvents.length === 0 ? (
                <p className="empty">No events for the selected task.</p>
              ) : (
                selectedEvents.map((event) => (
                  <div className={`log ${event.level}`} key={event.id}>
                    <time dateTime={event.created_at}>{formatTime(event.created_at)}</time>
                    <span>{event.level}</span>
                    <p>{event.message}</p>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="panel" id="files">
            <div className="panel-heading">
              <div>
                <h2>Files</h2>
                <span>{filePath || "download root"}</span>
              </div>
              <button className="secondary" type="button" onClick={() => refreshFiles()}>
                <RefreshCw size={16} aria-hidden="true" />
                Refresh
              </button>
            </div>
            <FilePath path={filePath} onOpen={(path) => refreshFiles(path).catch(() => undefined)} />
            <div className="file-list custom-scrollbar">
              {filePath && (
                <button className="file-row file-button" type="button" onClick={() => refreshFiles(parentPath(filePath))}>
                  <Folder size={18} aria-hidden="true" />
                  <span>..</span>
                  <small>Parent</small>
                  <span />
                </button>
              )}
              {files.length === 0 ? (
                <p className="empty">No files in this folder.</p>
              ) : (
                files.map((item) => (
                  <div className="file-row" key={item.path}>
                    {item.is_dir ? <Folder size={18} aria-hidden="true" /> : <File size={18} aria-hidden="true" />}
                    {item.is_dir ? (
                      <button className="file-name" type="button" onClick={() => refreshFiles(item.path)}>
                        {item.name}
                      </button>
                    ) : (
                      <span title={item.name}>{item.name}</span>
                    )}
                    <small>{item.is_dir ? "Folder" : formatBytes(item.size)}</small>
                    {!item.is_dir && (
                      <a href={`/api/files/download?path=${encodeURIComponent(item.path)}`} aria-label={`Download ${item.name}`}>
                        <Download size={16} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </section>

        <section className="bottom-grid">
          <AccountPanel
            account={account}
            cookies={cookies}
            setCookies={setCookies}
            username={cookieUsername}
            setUsername={setCookieUsername}
            onImport={importCookies}
            onTest={testSession}
            onClear={clearSession}
            busyAction={busyAction}
          />
          <SettingsPanel
            health={health}
            settings={settings}
            draft={settingsDraft}
            setDraft={setSettingsDraft}
            onSubmit={saveSettings}
            busy={busyAction === "settings"}
          />
        </section>
      </main>
    </div>
  );
}

function StatusPill({ ok, icon, label, detail }: { ok: boolean; icon: React.ReactNode; label: string; detail: string }) {
  return (
    <div className={`status-pill ${ok ? "ok" : "warn"}`}>
      {icon}
      <div>
        <strong>{label}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function TaskForm({
  targetType,
  setTargetType,
  targetsText,
  setTargetsText,
  options,
  updateOption,
  onSubmit,
  requiresLogin,
  accountConnected,
  busy
}: {
  targetType: TargetType;
  setTargetType: (value: TargetType) => void;
  targetsText: string;
  setTargetsText: (value: string) => void;
  options: DownloadOptions;
  updateOption: <K extends keyof DownloadOptions>(key: K, value: DownloadOptions[K]) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  requiresLogin: boolean;
  accountConnected: boolean;
  busy: boolean;
}) {
  const targetHelp = loginTargetTypes.has(targetType)
    ? "This target type uses the authenticated session and does not need a public username."
    : "Enter one or more targets, separated by new lines or commas.";

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>New task</h2>
          <span>Public targets work without a session.</span>
        </div>
      </div>
      <form className="task-form" onSubmit={onSubmit}>
        <label>
          Target type
          <select value={targetType} onChange={(event) => setTargetType(event.target.value as TargetType)}>
            {Object.entries(targetLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Targets
          <textarea
            rows={4}
            value={targetsText}
            disabled={loginTargetTypes.has(targetType)}
            onChange={(event) => setTargetsText(event.target.value)}
            placeholder={loginTargetTypes.has(targetType) ? targetType : "profile_one\n#hashtag\nshortcode"}
          />
          <small>{targetHelp}</small>
        </label>
        {requiresLogin && !accountConnected && (
          <div className="error" role="alert">
            This task needs a connected Instagram session.
          </div>
        )}
        <label>
          Max count
          <input
            type="number"
            min={1}
            value={options.max_count ?? ""}
            onChange={(event) => updateOption("max_count", event.target.value ? Number(event.target.value) : null)}
          />
        </label>
        <div className="option-grid">
          <Toggle label="Pictures" checked={options.download_pictures} onChange={(value) => updateOption("download_pictures", value)} />
          <Toggle label="Videos" checked={options.download_videos} onChange={(value) => updateOption("download_videos", value)} />
          <Toggle label="Metadata" checked={options.save_metadata} onChange={(value) => updateOption("save_metadata", value)} />
          <Toggle label="Fast update" checked={options.fast_update} onChange={(value) => updateOption("fast_update", value)} />
          <Toggle label="Stories" checked={options.download_stories} onChange={(value) => updateOption("download_stories", value)} />
          <Toggle label="Highlights" checked={options.download_highlights} onChange={(value) => updateOption("download_highlights", value)} />
          <Toggle label="Tagged" checked={options.download_tagged} onChange={(value) => updateOption("download_tagged", value)} />
          <Toggle label="Reels" checked={options.download_reels} onChange={(value) => updateOption("download_reels", value)} />
          <Toggle label="Comments" checked={options.download_comments} onChange={(value) => updateOption("download_comments", value)} />
          <Toggle label="Geotags" checked={options.download_geotags} onChange={(value) => updateOption("download_geotags", value)} />
        </div>
        <button className="primary" type="submit" disabled={busy || (requiresLogin && !accountConnected)}>
          {busy ? <Loader2 className="spin" size={18} aria-hidden="true" /> : <Play size={18} aria-hidden="true" />}
          Queue task
        </button>
      </form>
    </section>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}

function TaskStatusLabel({ status }: { status: TaskStatus }) {
  const icon =
    status === "running" ? (
      <Loader2 className="spin" size={15} aria-hidden="true" />
    ) : status === "completed" ? (
      <CheckCircle2 size={15} aria-hidden="true" />
    ) : status === "failed" ? (
      <XCircle size={15} aria-hidden="true" />
    ) : status === "cancelled" ? (
      <PauseCircle size={15} aria-hidden="true" />
    ) : (
      <Clock3 size={15} aria-hidden="true" />
    );
  return (
    <span className={`status ${status}`}>
      {icon}
      {statusLabels[status]}
    </span>
  );
}

function TaskError({ task }: { task: Task }) {
  return (
    <div className="status failed" title={task.error ?? undefined}>
      <AlertTriangle size={16} aria-hidden="true" />
      {task.error_code}
    </div>
  );
}

function FilePath({ path, onOpen }: { path: string; onOpen: (path: string) => void }) {
  const parts = path.split("/").filter(Boolean);
  let current = "";
  return (
    <div className="breadcrumb" aria-label="File path">
      <button type="button" onClick={() => onOpen("")}>
        root
      </button>
      {parts.map((part) => {
        current = current ? `${current}/${part}` : part;
        return (
          <button type="button" key={current} onClick={() => onOpen(current)}>
            {part}
          </button>
        );
      })}
    </div>
  );
}

function parentPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

function AccountPanel({
  account,
  cookies,
  setCookies,
  username,
  setUsername,
  onImport,
  onTest,
  onClear,
  busyAction
}: {
  account: AccountStatus | null;
  cookies: string;
  setCookies: (value: string) => void;
  username: string;
  setUsername: (value: string) => void;
  onImport: (event: FormEvent<HTMLFormElement>) => void;
  onTest: () => void;
  onClear: () => void;
  busyAction: string | null;
}) {
  return (
    <section className="panel" id="account">
      <div className="panel-heading">
        <div>
          <h2>Account session</h2>
          <span>{account?.is_connected ? `Connected as ${account.username ?? "session"}` : "No active session"}</span>
        </div>
        <div className={`health-row ${account?.is_connected ? "ok" : "warn"}`}>
          <UserRound size={16} aria-hidden="true" />
          {account?.is_connected ? "Connected" : "Disconnected"}
        </div>
      </div>
      <form className="task-form" onSubmit={onImport}>
        <label>
          Username
          <input type="text" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Optional" />
        </label>
        <label>
          Cookies
          <textarea
            rows={5}
            value={cookies}
            onChange={(event) => setCookies(event.target.value)}
            placeholder="sessionid=...; csrftoken=..."
          />
        </label>
        <div className="button-row">
          <button className="primary" type="submit" disabled={busyAction === "cookies" || !cookies.trim()}>
            {busyAction === "cookies" ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
            Import
          </button>
          <button className="secondary" type="button" disabled={busyAction === "test-session"} onClick={onTest}>
            <RefreshCw size={18} aria-hidden="true" />
            Test
          </button>
          <button className="secondary" type="button" disabled={busyAction === "clear-session"} onClick={onClear}>
            <LogOut size={18} aria-hidden="true" />
            Clear
          </button>
        </div>
      </form>
    </section>
  );
}

function SettingsPanel({
  health,
  settings,
  draft,
  setDraft,
  onSubmit,
  busy
}: {
  health: HealthStatus | null;
  settings: AppSettings | null;
  draft: AppSettings | null;
  setDraft: (value: AppSettings) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  busy: boolean;
}) {
  if (!draft || !settings) {
    return (
      <section className="panel" id="settings">
        <p className="empty">Loading settings.</p>
      </section>
    );
  }
  return (
    <section className="panel" id="settings">
      <div className="panel-heading">
        <div>
          <h2>Settings & health</h2>
          <span>Runtime settings apply immediately.</span>
        </div>
        <HardDrive size={20} aria-hidden="true" />
      </div>
      <form className="task-form" onSubmit={onSubmit}>
        <label>
          Download root
          <input
            type="text"
            value={draft.download_root}
            onChange={(event) => setDraft({ ...draft, download_root: event.target.value })}
          />
        </label>
        <div className="option-grid">
          <label>
            Max workers
            <input
              type="number"
              min={1}
              max={5}
              value={draft.max_concurrent_tasks}
              onChange={(event) => setDraft({ ...draft, max_concurrent_tasks: Number(event.target.value) })}
            />
          </label>
          <label>
            Default max count
            <input
              type="number"
              min={1}
              value={draft.default_max_count ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, default_max_count: event.target.value ? Number(event.target.value) : null })
              }
            />
          </label>
        </div>
        <div className="health-list">
          <HealthRow ok={health?.database_writable ?? false} label="Database writable" />
          <HealthRow ok={health?.download_root_writable ?? false} label="Download root writable" />
          <HealthRow ok={!health?.cooling_down} label={health?.cooling_down ? `Cooldown until ${formatTime(health.cooldown_until)}` : "No cooldown"} />
          <div className="metric">
            <span>Free disk</span>
            <strong>{formatBytes(health?.free_disk_bytes ?? 0)}</strong>
          </div>
        </div>
        <button className="primary" type="submit" disabled={busy}>
          {busy ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
          Save settings
        </button>
      </form>
    </section>
  );
}

function HealthRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={`health-row ${ok ? "ok" : "warn"}`}>
      {ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
      {label}
    </div>
  );
}
