import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Bookmark,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Download,
  File,
  Folder,
  Grid3X3,
  HardDrive,
  Hash,
  History,
  Image,
  KeyRound,
  Layers3,
  Loader2,
  LogOut,
  Moon,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  TerminalSquare,
  Trash2,
  Upload,
  UserPlus,
  UserCircle,
  UserRound,
  WifiOff,
  X,
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
type ViewKey = "tasks" | "creators" | "files" | "logs" | "settings" | "accounts";

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

type BatchTaskResponse = {
  tasks: Task[];
  created_count: number;
};

type Creator = {
  id: number;
  username: string;
  full_name: string | null;
  avatar_url: string | null;
  biography: string | null;
  is_private: boolean;
  is_verified: boolean;
  followers: number | null;
  followees: number | null;
  mediacount: number | null;
  status: "pending" | "ready" | "error";
  error: string | null;
  created_at: string;
  updated_at: string;
  refreshed_at: string | null;
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

type MediaItem = {
  path: string;
  name: string;
  size: number;
  modified_at: string;
  media_type: "image" | "video";
  mime_type: string;
};

type AccountStatus = {
  is_connected: boolean;
  username: string | null;
  session_file: string | null;
  updated_at: string | null;
  pending_two_factor: boolean;
  message: string | null;
};

type AccountRecord = {
  username: string;
  session_file: string;
  is_connected: boolean;
  is_default: boolean;
  updated_at: string | null;
  last_used_at: string | null;
  last_test_status: "unknown" | "valid" | "invalid" | null;
  cooldown_until: string | null;
  failure_count: number;
  last_error: string | null;
  message: string | null;
};

type AccountListResponse = {
  accounts: AccountRecord[];
  default_username: string | null;
  available_count: number;
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
  stability_guard_enabled: boolean;
  account_min_interval_seconds: number;
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

const targetItems: Array<{ value: TargetType; label: string; icon: ReactNode }> = [
  { value: "profile", label: "个人主页", icon: <UserCircle size={22} aria-hidden="true" /> },
  { value: "hashtag", label: "话题", icon: <Hash size={22} aria-hidden="true" /> },
  { value: "shortcode", label: "帖子", icon: <Grid3X3 size={22} aria-hidden="true" /> },
  { value: "feed", label: "动态", icon: <Layers3 size={22} aria-hidden="true" /> },
  { value: "stories", label: "快拍", icon: <History size={22} aria-hidden="true" /> },
  { value: "saved", label: "已保存", icon: <Bookmark size={22} aria-hidden="true" /> }
];

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

function mergeTasks(tasks: Task[], nextTasks: Task[]): Task[] {
  return nextTasks.reduce((current, task) => mergeTask(current, task), tasks);
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
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatCompactNumber(value: number | null): string {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
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

function parentPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

export function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [accounts, setAccounts] = useState<AccountListResponse | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [filePath, setFilePath] = useState("");
  const [view, setView] = useState<ViewKey>("tasks");
  const [isNewTaskOpen, setNewTaskOpen] = useState(false);
  const [isAccountModalOpen, setAccountModalOpen] = useState(false);
  const [targetType, setTargetType] = useState<TargetType>("profile");
  const [targetsText, setTargetsText] = useState("");
  const [creatorUsername, setCreatorUsername] = useState("");
  const [options, setOptions] = useState<DownloadOptions>(defaultOptions);
  const [cookies, setCookies] = useState("");
  const [cookieUsername, setCookieUsername] = useState("");
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [sessionUsername, setSessionUsername] = useState("");
  const [sessionFile, setSessionFile] = useState<File | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<AppSettings | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [eventState, setEventState] = useState<"connecting" | "connected" | "offline">("connecting");
  const [taskMedia, setTaskMedia] = useState<MediaItem[]>([]);
  const [fileMedia, setFileMedia] = useState<MediaItem[]>([]);
  const [previewMedia, setPreviewMedia] = useState<MediaItem | null>(null);
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<number[]>([]);
  const [selectedTaskIds, setSelectedTaskIds] = useState<number[]>([]);
  const filePathRef = useRef(filePath);

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
  const themePreference = settingsDraft?.theme ?? settings?.theme ?? "light";
  const selectedCreators = useMemo(
    () => creators.filter((creator) => selectedCreatorIds.includes(creator.id)),
    [creators, selectedCreatorIds]
  );

  useEffect(() => {
    const root = document.documentElement;
    const systemQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const resolvedTheme = themePreference === "system" ? (systemQuery.matches ? "dark" : "light") : themePreference;
      root.dataset.theme = resolvedTheme;
      root.dataset.themePreference = themePreference;
      root.style.colorScheme = resolvedTheme;
    };

    applyTheme();
    if (themePreference !== "system") return;

    systemQuery.addEventListener("change", applyTheme);
    return () => systemQuery.removeEventListener("change", applyTheme);
  }, [themePreference]);

  useEffect(() => {
    filePathRef.current = filePath;
  }, [filePath]);

  const refreshTasks = useCallback(async () => {
    const data = await api<Task[]>("/api/tasks");
    setTasks(data);
    setSelectedTaskId((current) => current ?? data[0]?.id ?? null);
  }, []);

  const refreshCreators = useCallback(async () => {
    const data = await api<Creator[]>("/api/creators");
    setCreators(data);
  }, []);

  const refreshFiles = useCallback(async (path = filePath) => {
    const data = await api<FileItem[]>(`/api/files?path=${encodeURIComponent(path)}`);
    setFiles(data);
    setFilePath(path);
  }, [filePath]);

  const refreshFileMedia = useCallback(async (path = filePath) => {
    const data = await api<MediaItem[]>(`/api/media?path=${encodeURIComponent(path)}&limit=60`);
    setFileMedia(data);
  }, [filePath]);

  const refreshTaskMedia = useCallback(async (taskId = selectedTask?.id) => {
    if (!taskId) {
      setTaskMedia([]);
      return;
    }
    const data = await api<MediaItem[]>(`/api/media?task_id=${taskId}&limit=60`);
    setTaskMedia(data);
  }, [selectedTask?.id]);

  const refreshStatus = useCallback(async () => {
    const [nextAccount, nextAccounts, nextHealth, nextSettings, nextSystem] = await Promise.all([
      api<AccountStatus>("/api/account"),
      api<AccountListResponse>("/api/accounts"),
      api<HealthStatus>("/api/health"),
      api<AppSettings>("/api/settings"),
      api<SystemInfo>("/api/system")
    ]);
    setAccount(nextAccount);
    setAccounts(nextAccounts);
    setHealth(nextHealth);
    setSettings(nextSettings);
    setSettingsDraft(nextSettings);
    setSystem(nextSystem);
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshTasks(), refreshCreators(), refreshFiles(), refreshFileMedia(), refreshTaskMedia(), refreshStatus()]);
  }, [refreshCreators, refreshFileMedia, refreshFiles, refreshStatus, refreshTaskMedia, refreshTasks]);

  const loadTaskEvents = useCallback(async (taskId: number) => {
    const data = await api<{ task: Task; events: TaskEvent[] }>(`/api/tasks/${taskId}`);
    setTasks((current) => mergeTask(current, data.task));
    setEvents((current) => data.events.reduce((next, event) => mergeEvent(next, event), current));
  }, []);

  useEffect(() => {
    Promise.all([refreshTasks(), refreshCreators(), refreshFiles(""), refreshFileMedia(""), refreshStatus()]).catch((exc: unknown) =>
      setError(exc instanceof Error ? exc.message : "无法加载控制台数据")
    );
  }, [refreshCreators, refreshFileMedia, refreshFiles, refreshStatus, refreshTasks]);

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
        window.setTimeout(() => {
          refreshTaskMedia(data.type === "task" ? data.payload.id : data.type === "event" ? data.payload.task_id : undefined).catch(() => undefined);
          refreshFileMedia(filePathRef.current).catch(() => undefined);
        }, 800);
      } catch {
        setEventState("offline");
      }
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    if (selectedTask) {
      loadTaskEvents(selectedTask.id).catch(() => undefined);
      refreshTaskMedia(selectedTask.id).catch(() => undefined);
    } else {
      setTaskMedia([]);
    }
  }, [loadTaskEvents, refreshTaskMedia, selectedTask?.id]);

  async function runAction<T>(name: string, action: () => Promise<T>): Promise<T | null> {
    setBusyAction(name);
    setError(null);
    try {
      return await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "操作失败");
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
    const payload = { target_type: targetType, targets, options };
    const created = await runAction("create", () =>
      targets.length > 1
        ? api<BatchTaskResponse>("/api/tasks/batch", {
            method: "POST",
            body: JSON.stringify(payload)
          })
        : api<Task>("/api/tasks", {
            method: "POST",
            body: JSON.stringify(payload)
          }).then((task) => ({ tasks: [task], created_count: 1 }))
    );
    if (created) {
      setTasks((current) => mergeTasks(current, created.tasks));
      setSelectedTaskId(created.tasks[0]?.id ?? null);
      setNewTaskOpen(false);
      setView("tasks");
      setSelectedCreatorIds([]);
      if (!loginTargetTypes.has(targetType)) setTargetsText("");
    }
  }

  async function taskCommand(taskId: number, command: "cancel" | "retry") {
    const task = await runAction(`${command}-${taskId}`, () =>
      api<Task>(`/api/tasks/${taskId}/${command}`, { method: "POST" })
    );
    if (task) setTasks((current) => mergeTask(current, task));
  }

  async function bulkTaskCommand(command: "cancel" | "retry") {
    const eligible = tasks.filter((task) => {
      if (!selectedTaskIds.includes(task.id)) return false;
      return command === "cancel"
        ? task.status === "queued" || task.status === "running"
        : task.status === "failed" || task.status === "cancelled" || task.status === "completed";
    });
    if (eligible.length === 0) {
      setError(command === "cancel" ? "请选择排队中或运行中的任务。" : "请选择可重试的任务。");
      return;
    }
    const updated = await runAction(`bulk-${command}`, async () =>
      Promise.all(eligible.map((task) => api<Task>(`/api/tasks/${task.id}/${command}`, { method: "POST" })))
    );
    if (updated) {
      setTasks((current) => mergeTasks(current, updated));
      setSelectedTaskIds((current) => current.filter((id) => !updated.some((task) => task.id === id)));
    }
  }

  function toggleTaskSelection(taskId: number, checked: boolean) {
    setSelectedTaskIds((current) => checked ? [...new Set([...current, taskId])] : current.filter((id) => id !== taskId));
  }

  function toggleCreatorSelection(creatorId: number, checked: boolean) {
    setSelectedCreatorIds((current) => checked ? [...new Set([...current, creatorId])] : current.filter((id) => id !== creatorId));
  }

  function startSelectedCreatorDownload() {
    if (selectedCreators.length === 0) {
      setError("请选择要下载的博主。");
      return;
    }
    setTargetType("profile");
    setTargetsText(selectedCreators.map((creator) => creator.username).join("\n"));
    setNewTaskOpen(true);
  }

  async function addCreator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const username = creatorUsername.trim();
    if (!username) {
      setError("请输入博主用户名。");
      return;
    }
    const creator = await runAction("creator-add", () =>
      api<Creator>("/api/creators", {
        method: "POST",
        body: JSON.stringify({ username })
      })
    );
    if (creator) {
      setCreators((current) => [creator, ...current.filter((item) => item.id !== creator.id)]);
      setCreatorUsername("");
    }
  }

  async function refreshCreator(creatorId: number) {
    const creator = await runAction(`creator-refresh-${creatorId}`, () =>
      api<Creator>(`/api/creators/${creatorId}/refresh`, { method: "POST" })
    );
    if (creator) {
      setCreators((current) => current.map((item) => (item.id === creator.id ? creator : item)));
    }
  }

  async function deleteCreator(creatorId: number) {
    const deleted = await runAction(`creator-delete-${creatorId}`, () =>
      api<{ ok: boolean }>(`/api/creators/${creatorId}`, { method: "DELETE" })
    );
    if (deleted?.ok) {
      setCreators((current) => current.filter((item) => item.id !== creatorId));
    }
  }

  async function importCookies(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const status = await runAction("cookies", () =>
      api<AccountStatus>("/api/account/cookies", {
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

  async function testSession() {
    const status = await runAction("test-session", () => api<AccountStatus>("/api/session/test", { method: "POST" }));
    if (status) {
      setAccount(status);
      await refreshStatus();
    }
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

  async function testAccount(username: string) {
    const status = await runAction(`test-account-${username}`, () =>
      api<AccountStatus>(`/api/accounts/${encodeURIComponent(username)}/test`, { method: "POST" })
    );
    if (status) {
      setAccount(status.username === account?.username ? status : account);
      await refreshStatus();
    }
  }

  async function setDefaultAccount(username: string) {
    const next = await runAction(`default-account-${username}`, () =>
      api<AccountListResponse>(`/api/accounts/${encodeURIComponent(username)}/default`, { method: "POST" })
    );
    if (next) {
      setAccounts(next);
      await refreshStatus();
    }
  }

  async function deleteAccount(username: string) {
    const next = await runAction(`delete-account-${username}`, () =>
      api<AccountListResponse>(`/api/accounts/${encodeURIComponent(username)}`, { method: "DELETE" })
    );
    if (next) {
      setAccounts(next);
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
      await Promise.all([refreshStatus(), refreshFiles(""), refreshFileMedia("")]);
    }
  }

  function updateOption<K extends keyof DownloadOptions>(key: K, value: DownloadOptions[K]) {
    setOptions((current) => ({ ...current, [key]: value }));
  }

  return (
    <AppShell
      view={view}
      setView={setView}
      onNewTask={() => setNewTaskOpen(true)}
      onRefresh={() => refreshAll().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "刷新失败"))}
      eventState={eventState}
      account={account}
      health={health}
      onNewAccount={() => setAccountModalOpen(true)}
    >
      {error && (
        <div className="notice-error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {view === "tasks" && (
        <TaskListView
          tasks={tasks}
          selectedTask={selectedTask}
          selectedEvents={selectedEvents}
          account={account}
          accounts={accounts}
          health={health}
          system={system}
          eventState={eventState}
          busyAction={busyAction}
          selectedTaskIds={selectedTaskIds}
          onToggleTaskSelection={toggleTaskSelection}
          onSelectAllTasks={() => setSelectedTaskIds(tasks.map((task) => task.id))}
          onClearTaskSelection={() => setSelectedTaskIds([])}
          onBulkTaskCommand={bulkTaskCommand}
          media={taskMedia}
          onOpenMedia={setPreviewMedia}
          onRefreshMedia={() => refreshTaskMedia().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "预览刷新失败"))}
          setSelectedTaskId={setSelectedTaskId}
          onTaskCommand={taskCommand}
          onNewTask={() => setNewTaskOpen(true)}
        />
      )}

      {view === "creators" && (
        <CreatorsView
          creators={creators}
          creatorUsername={creatorUsername}
          setCreatorUsername={setCreatorUsername}
          busyAction={busyAction}
          selectedCreatorIds={selectedCreatorIds}
          onToggleCreatorSelection={toggleCreatorSelection}
          onSelectAllCreators={() => setSelectedCreatorIds(creators.map((creator) => creator.id))}
          onClearCreatorSelection={() => setSelectedCreatorIds([])}
          onDownloadSelected={startSelectedCreatorDownload}
          onAdd={addCreator}
          onRefresh={refreshCreator}
          onDelete={deleteCreator}
        />
      )}

      {view === "files" && (
        <FilesView
          files={files}
          filePath={filePath}
          media={fileMedia}
          onOpen={(path) =>
            Promise.all([refreshFiles(path), refreshFileMedia(path)]).catch((exc: unknown) =>
              setError(exc instanceof Error ? exc.message : "文件加载失败")
            )
          }
          onOpenMedia={setPreviewMedia}
          onRefresh={() =>
            Promise.all([refreshFiles(), refreshFileMedia()]).catch((exc: unknown) =>
              setError(exc instanceof Error ? exc.message : "文件刷新失败")
            )
          }
        />
      )}

      {view === "logs" && (
        <LogsView
          tasks={tasks}
          selectedTask={selectedTask}
          selectedEvents={selectedEvents}
          setSelectedTaskId={setSelectedTaskId}
          eventState={eventState}
        />
      )}

      {view === "settings" && (
        <SettingsView
          health={health}
          settings={settings}
          settingsDraft={settingsDraft}
          system={system}
          setSettingsDraft={setSettingsDraft}
          onSaveSettings={saveSettings}
          busyAction={busyAction}
        />
      )}

      {view === "accounts" && (
        <AccountsView
          account={account}
          accounts={accounts}
          settingsDraft={settingsDraft}
          setSettingsDraft={setSettingsDraft}
          onSaveSettings={saveSettings}
          onTestSession={testSession}
          onClearSession={clearSession}
          onTestAccount={testAccount}
          onSetDefaultAccount={setDefaultAccount}
          onDeleteAccount={deleteAccount}
          loginUsername={loginUsername}
          setLoginUsername={setLoginUsername}
          loginPassword={loginPassword}
          setLoginPassword={setLoginPassword}
          twoFactorCode={twoFactorCode}
          setTwoFactorCode={setTwoFactorCode}
          sessionUsername={sessionUsername}
          setSessionUsername={setSessionUsername}
          setSessionFile={setSessionFile}
          cookies={cookies}
          setCookies={setCookies}
          cookieUsername={cookieUsername}
          setCookieUsername={setCookieUsername}
          onLogin={loginAccount}
          onTwoFactor={submitTwoFactor}
          onSessionFile={importSessionFile}
          onImportCookies={importCookies}
          busyAction={busyAction}
        />
      )}

      {isNewTaskOpen && (
        <NewTaskModal
          targetType={targetType}
          setTargetType={setTargetType}
          targetsText={targetsText}
          setTargetsText={setTargetsText}
          options={options}
          updateOption={updateOption}
          requiresLogin={requiresLogin}
          availableAccounts={accounts?.available_count ?? 0}
          busy={busyAction === "create"}
          onSubmit={createTask}
          onClose={() => setNewTaskOpen(false)}
        />
      )}
      {isAccountModalOpen && (
        <AccountModal
          account={account}
          loginUsername={loginUsername}
          setLoginUsername={setLoginUsername}
          loginPassword={loginPassword}
          setLoginPassword={setLoginPassword}
          twoFactorCode={twoFactorCode}
          setTwoFactorCode={setTwoFactorCode}
          sessionUsername={sessionUsername}
          setSessionUsername={setSessionUsername}
          setSessionFile={setSessionFile}
          cookies={cookies}
          setCookies={setCookies}
          cookieUsername={cookieUsername}
          setCookieUsername={setCookieUsername}
          onLogin={loginAccount}
          onTwoFactor={submitTwoFactor}
          onSessionFile={importSessionFile}
          onImportCookies={importCookies}
          busyAction={busyAction}
          onClose={() => setAccountModalOpen(false)}
        />
      )}
      {previewMedia && <PreviewModal media={previewMedia} onClose={() => setPreviewMedia(null)} />}
    </AppShell>
  );
}

function AppShell({
  view,
  setView,
  onNewTask,
  onRefresh,
  eventState,
  account,
  health,
  onNewAccount,
  children
}: {
  view: ViewKey;
  setView: (value: ViewKey) => void;
  onNewTask: () => void;
  onRefresh: () => void;
  eventState: "connecting" | "connected" | "offline";
  account: AccountStatus | null;
  health: HealthStatus | null;
  onNewAccount: () => void;
  children: ReactNode;
}) {
  const title =
    view === "tasks"
      ? "任务列表"
      : view === "creators"
        ? "博主管理"
        : view === "files"
          ? "文件中心"
          : view === "logs"
            ? "日志详情"
            : view === "accounts"
              ? "账号池管理"
              : "配置中心";
  const subtitle =
    view === "tasks"
      ? "管理 Instagram 下载队列、状态和重试。"
      : view === "creators"
        ? "维护常用博主资料，并自动显示头像。"
        : view === "files"
          ? "浏览下载目录并获取已完成文件。"
          : view === "logs"
            ? "查看任务运行轨迹和错误详情。"
            : view === "accounts"
              ? "维护可轮换账号，并添加或更新 Session。"
              : "调整运行参数、账号 Session 与界面偏好。";

  return (
    <div className="app-frame">
      <Sidebar view={view} setView={setView} account={account} />
      <main className="main-surface">
        <header className="topbar">
          <div>
            <p className="page-kicker">INSTAFLOW PRO</p>
            <h1 className="page-title">{title}</h1>
            <p className="page-subtitle">{subtitle}</p>
          </div>
          <div className="topbar-actions">
            <div className={`mini-state ${eventState === "connected" ? "ok" : "warn"}`}>
              {eventState === "connected" ? <Server size={16} /> : <WifiOff size={16} />}
              <span>{eventState === "connected" ? "实时连接" : "连接离线"}</span>
            </div>
            <div className={`mini-state ${health?.ok ? "ok" : "warn"}`}>
              {health?.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <span>{health?.ok ? "系统正常" : "需检查"}</span>
            </div>
            <button className="icon-action" type="button" onClick={onRefresh} aria-label="刷新">
              <RefreshCw size={18} aria-hidden="true" />
            </button>
            <button className="primary-action" type="button" onClick={view === "accounts" ? onNewAccount : onNewTask}>
              {view === "accounts" ? <UserPlus size={18} aria-hidden="true" /> : <Plus size={18} aria-hidden="true" />}
              {view === "accounts" ? "新增账号" : "新建任务"}
            </button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

function Sidebar({
  view,
  setView,
  account
}: {
  view: ViewKey;
  setView: (value: ViewKey) => void;
  account: AccountStatus | null;
}) {
  const navItems: Array<{ value: ViewKey; label: string; icon: ReactNode }> = [
    { value: "tasks", label: "任务列表", icon: <Archive size={20} aria-hidden="true" /> },
    { value: "creators", label: "博主管理", icon: <UserRound size={20} aria-hidden="true" /> },
    { value: "accounts", label: "账号池", icon: <ShieldCheck size={20} aria-hidden="true" /> },
    { value: "files", label: "文件中心", icon: <Folder size={20} aria-hidden="true" /> },
    { value: "logs", label: "日志详情", icon: <TerminalSquare size={20} aria-hidden="true" /> },
    { value: "settings", label: "系统设置", icon: <Settings size={20} aria-hidden="true" /> }
  ];

  return (
    <aside className="sidebar-shell">
      <div className="brand-block">
        <h2>InstaFlow Pro</h2>
        <span>高级用户模式</span>
      </div>
      <nav className="side-nav" aria-label="控制台导航">
        {navItems.map((item) => (
          <button
            className={`side-nav-item ${view === item.value ? "active" : ""}`}
            type="button"
            key={item.value}
            onClick={() => setView(item.value)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-account">
        <div className={account?.is_connected ? "account-dot ok" : "account-dot"} />
        <div>
          <strong>{account?.is_connected ? `@${account.username ?? "session"}` : "未连接账号"}</strong>
          <span>{account?.is_connected ? "Session 可用于私密内容" : "公开内容仍可下载"}</span>
        </div>
      </div>
    </aside>
  );
}

function TaskListView({
  tasks,
  selectedTask,
  selectedEvents,
  account,
  accounts,
  health,
  system,
  eventState,
  busyAction,
  selectedTaskIds,
  onToggleTaskSelection,
  onSelectAllTasks,
  onClearTaskSelection,
  onBulkTaskCommand,
  media,
  onOpenMedia,
  onRefreshMedia,
  setSelectedTaskId,
  onTaskCommand,
  onNewTask
}: {
  tasks: Task[];
  selectedTask: Task | null;
  selectedEvents: TaskEvent[];
  account: AccountStatus | null;
  accounts: AccountListResponse | null;
  health: HealthStatus | null;
  system: SystemInfo | null;
  eventState: "connecting" | "connected" | "offline";
  busyAction: string | null;
  selectedTaskIds: number[];
  onToggleTaskSelection: (taskId: number, checked: boolean) => void;
  onSelectAllTasks: () => void;
  onClearTaskSelection: () => void;
  onBulkTaskCommand: (command: "cancel" | "retry") => void;
  media: MediaItem[];
  onOpenMedia: (media: MediaItem) => void;
  onRefreshMedia: () => void;
  setSelectedTaskId: (value: number) => void;
  onTaskCommand: (taskId: number, command: "cancel" | "retry") => void;
  onNewTask: () => void;
}) {
  const completed = tasks.filter((task) => task.status === "completed").length;
  const running = tasks.filter((task) => task.status === "running").length;
  const selectedCount = selectedTaskIds.length;
  const cancellableCount = tasks.filter((task) => selectedTaskIds.includes(task.id) && (task.status === "queued" || task.status === "running")).length;
  const retryableStatuses: TaskStatus[] = ["failed", "cancelled", "completed"];
  const retryableCount = tasks.filter((task) => selectedTaskIds.includes(task.id) && retryableStatuses.includes(task.status)).length;

  return (
    <div className="view-stack">
      <section className="summary-grid" aria-label="系统状态">
        <SummaryCard icon={<Play size={20} />} label="运行中任务" value={`${running}`} detail={`${health?.queued_tasks ?? 0} 个排队等待`} />
        <SummaryCard icon={<CheckCircle2 size={20} />} label="已完成" value={`${completed}`} detail={`共 ${tasks.length} 个最近任务`} />
        <SummaryCard
          icon={<ShieldCheck size={20} />}
          label="账号池"
          value={`${accounts?.available_count ?? 0} 可用`}
          detail={account?.is_connected ? `默认 @${account.username ?? "session"}` : "任务会自动轮换"}
        />
        <SummaryCard
          icon={eventState === "connected" ? <Server size={20} /> : <WifiOff size={20} />}
          label="下载引擎"
          value={system?.engine_version ?? "等待后端"}
          detail={system ? `存储 ${formatBytes(system.storage_used)}` : "正在读取状态"}
        />
      </section>

      <section className="content-grid">
        <div className="settings-card task-board">
          <div className="section-heading">
            <div>
              <p className="section-kicker">DOWNLOAD QUEUE</p>
              <h2>任务列表</h2>
            </div>
            <button className="secondary-action" type="button" onClick={onNewTask}>
              <Plus size={17} aria-hidden="true" />
              创建
            </button>
          </div>
          {tasks.length > 0 && (
            <div className="bulk-toolbar">
              <span>{selectedCount > 0 ? `已选 ${selectedCount} 个任务` : "选择任务后可批量操作"}</span>
              <div>
                <button className="secondary-action compact" type="button" onClick={onSelectAllTasks}>
                  <Check size={15} aria-hidden="true" />
                  全选
                </button>
                <button className="secondary-action compact" type="button" onClick={onClearTaskSelection} disabled={selectedCount === 0}>
                  <X size={15} aria-hidden="true" />
                  清空
                </button>
                <button className="secondary-action compact" type="button" onClick={() => onBulkTaskCommand("cancel")} disabled={cancellableCount === 0 || busyAction === "bulk-cancel"}>
                  {busyAction === "bulk-cancel" ? <Loader2 className="spin" size={15} /> : <PauseCircle size={15} aria-hidden="true" />}
                  取消
                </button>
                <button className="secondary-action compact" type="button" onClick={() => onBulkTaskCommand("retry")} disabled={retryableCount === 0 || busyAction === "bulk-retry"}>
                  {busyAction === "bulk-retry" ? <Loader2 className="spin" size={15} /> : <RotateCcw size={15} aria-hidden="true" />}
                  重试
                </button>
              </div>
            </div>
          )}
          <div className="task-table custom-scrollbar">
            {tasks.length === 0 ? (
              <EmptyState icon={<Archive size={28} />} title="还没有任务" detail="点击新建任务开始下载。" />
            ) : (
              tasks.map((task) => (
                <article
                  className={`task-card ${selectedTask?.id === task.id ? "selected" : ""}`}
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
                  <span className="row-check" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedTaskIds.includes(task.id)}
                      onChange={(event) => onToggleTaskSelection(task.id, event.target.checked)}
                      aria-label={`选择任务 ${task.id}`}
                    />
                  </span>
                  <span className="task-id">#{task.id}</span>
                  <TaskStatusLabel status={task.status} />
                  <span className="task-target">{targetLabels[task.target_type]} · {task.targets.join(", ")}</span>
                  <time>{formatTime(task.created_at)}</time>
                  <span className="task-actions">
                    {task.status === "running" && (
                      <span
                        className="inline-command"
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          onTaskCommand(task.id, "cancel");
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            event.stopPropagation();
                            onTaskCommand(task.id, "cancel");
                          }
                        }}
                      >
                        {busyAction === `cancel-${task.id}` ? <Loader2 className="spin" size={15} /> : <PauseCircle size={15} />}
                        取消
                      </span>
                    )}
                    {(task.status === "failed" || task.status === "cancelled") && (
                      <span
                        className="inline-command"
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          onTaskCommand(task.id, "retry");
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            event.stopPropagation();
                            onTaskCommand(task.id, "retry");
                          }
                        }}
                      >
                        {busyAction === `retry-${task.id}` ? <Loader2 className="spin" size={15} /> : <RotateCcw size={15} />}
                        重试
                      </span>
                    )}
                  </span>
                </article>
              ))
            )}
          </div>
        </div>

        <aside className="settings-card detail-panel">
          <div className="section-heading compact">
            <div>
              <p className="section-kicker">DETAILS</p>
              <h2>{selectedTask ? `任务 #${selectedTask.id}` : "任务详情"}</h2>
            </div>
            {selectedTask?.error_code && <TaskError task={selectedTask} />}
          </div>
          {selectedTask ? (
            <>
              <div className="detail-list">
                <DetailLine label="目标类型" value={targetLabels[selectedTask.target_type]} />
                <DetailLine label="目标" value={selectedTask.targets.join(", ")} />
                <DetailLine label="创建时间" value={formatTime(selectedTask.created_at)} />
                <DetailLine label="尝试次数" value={`${selectedTask.attempt_count}`} />
                <DetailLine label="最大下载" value={selectedTask.options.max_count ? `${selectedTask.options.max_count}` : "不限"} />
              </div>
              <div className="recent-log custom-scrollbar">
                {selectedEvents.slice(-5).map((event) => (
                  <div className={`mini-log ${event.level}`} key={event.id}>
                    <time>{formatTime(event.created_at)}</time>
                    <p>{event.message}</p>
                  </div>
                ))}
                {selectedEvents.length === 0 && <p className="muted-line">暂无日志。</p>}
              </div>
              <MediaPanel
                title="实时预览"
                subtitle="显示此任务目录下最近生成的图片和视频。"
                media={media}
                onOpen={onOpenMedia}
                onRefresh={onRefreshMedia}
              />
            </>
          ) : (
            <EmptyState icon={<Search size={28} />} title="请选择任务" detail="任务运行后会在这里显示详情。" />
          )}
        </aside>
      </section>
    </div>
  );
}

function CreatorsView({
  creators,
  creatorUsername,
  setCreatorUsername,
  busyAction,
  selectedCreatorIds,
  onToggleCreatorSelection,
  onSelectAllCreators,
  onClearCreatorSelection,
  onDownloadSelected,
  onAdd,
  onRefresh,
  onDelete
}: {
  creators: Creator[];
  creatorUsername: string;
  setCreatorUsername: (value: string) => void;
  busyAction: string | null;
  selectedCreatorIds: number[];
  onToggleCreatorSelection: (creatorId: number, checked: boolean) => void;
  onSelectAllCreators: () => void;
  onClearCreatorSelection: () => void;
  onDownloadSelected: () => void;
  onAdd: (event: FormEvent<HTMLFormElement>) => void;
  onRefresh: (creatorId: number) => void;
  onDelete: (creatorId: number) => void;
}) {
  const readyCount = creators.filter((creator) => creator.status === "ready").length;
  const privateCount = creators.filter((creator) => creator.is_private).length;
  const selectedCount = selectedCreatorIds.length;

  return (
    <div className="view-stack">
      <section className="summary-grid" aria-label="博主管理概览">
        <SummaryCard icon={<UserRound size={20} />} label="已管理博主" value={`${creators.length}`} detail={`${readyCount} 个资料可用`} />
        <SummaryCard icon={<ShieldCheck size={20} />} label="私密账号" value={`${privateCount}`} detail="可能需要登录后刷新" />
        <SummaryCard
          icon={<AlertTriangle size={20} />}
          label="刷新失败"
          value={`${creators.filter((creator) => creator.status === "error").length}`}
          detail="保留上一次可用资料"
        />
        <SummaryCard icon={<Image size={20} />} label="头像缓存" value={`${creators.filter((creator) => creator.avatar_url).length}`} detail="来自博主公开资料" />
      </section>

      <section className="settings-card creator-toolbar">
        <div className="section-heading compact">
          <div>
            <p className="section-kicker">CREATORS</p>
            <h2>添加博主</h2>
            <span>输入 Instagram 用户名，系统会自动拉取头像和基础资料。</span>
          </div>
          {creators.length > 0 && (
            <div className="bulk-actions">
              <span>{selectedCount > 0 ? `已选 ${selectedCount} 个博主` : "可批量创建下载任务"}</span>
              <button className="secondary-action compact" type="button" onClick={onSelectAllCreators}>
                <Check size={15} aria-hidden="true" />
                全选
              </button>
              <button className="secondary-action compact" type="button" onClick={onClearCreatorSelection} disabled={selectedCount === 0}>
                <X size={15} aria-hidden="true" />
                清空
              </button>
              <button className="primary-action compact" type="button" onClick={onDownloadSelected} disabled={selectedCount === 0}>
                <Download size={15} aria-hidden="true" />
                下载选中
              </button>
            </div>
          )}
        </div>
        <form className="creator-form" onSubmit={onAdd}>
          <label className="field-line">
            <span>博主用户名</span>
            <input
              type="text"
              value={creatorUsername}
              onChange={(event) => setCreatorUsername(event.target.value)}
              placeholder="profile_name 或 @profile_name"
              autoComplete="off"
            />
          </label>
          <button className="primary-action fit" type="submit" disabled={busyAction === "creator-add" || !creatorUsername.trim()}>
            {busyAction === "creator-add" ? <Loader2 className="spin" size={18} /> : <Plus size={18} aria-hidden="true" />}
            添加
          </button>
        </form>
      </section>

      <section className="creator-grid" aria-label="博主列表">
        {creators.length === 0 ? (
          <div className="settings-card">
            <EmptyState icon={<UserRound size={28} />} title="还没有博主" detail="添加用户名后会在这里显示头像和资料。" />
          </div>
        ) : (
          creators.map((creator) => (
            <article className={`creator-card ${creator.status} ${selectedCreatorIds.includes(creator.id) ? "selected" : ""}`} key={creator.id}>
              <label className="creator-select">
                <input
                  type="checkbox"
                  checked={selectedCreatorIds.includes(creator.id)}
                  onChange={(event) => onToggleCreatorSelection(creator.id, event.target.checked)}
                />
                <span>选择 @{creator.username}</span>
              </label>
              <div className="creator-main">
                <Avatar creator={creator} />
                <div className="creator-identity">
                  <div className="creator-title-row">
                    <strong>@{creator.username}</strong>
                    {creator.is_verified && <span className="creator-pill ok">已认证</span>}
                    {creator.is_private && <span className="creator-pill warn">私密</span>}
                    {creator.status === "error" && <span className="creator-pill error">刷新失败</span>}
                  </div>
                  <span>{creator.full_name || "未获取全名"}</span>
                  <p>{creator.biography || creator.error || "暂无简介。"}</p>
                </div>
              </div>
              <div className="creator-stats">
                <DetailLine label="粉丝" value={formatCompactNumber(creator.followers)} />
                <DetailLine label="关注" value={formatCompactNumber(creator.followees)} />
                <DetailLine label="帖子" value={formatCompactNumber(creator.mediacount)} />
                <DetailLine label="刷新" value={formatTime(creator.refreshed_at)} />
              </div>
              {creator.error && (
                <div className="creator-error" role="status">
                  <AlertTriangle size={16} aria-hidden="true" />
                  <span>{creator.error}</span>
                </div>
              )}
              <div className="creator-actions">
                <button
                  className="secondary-action"
                  type="button"
                  disabled={busyAction === `creator-refresh-${creator.id}`}
                  onClick={() => onRefresh(creator.id)}
                >
                  {busyAction === `creator-refresh-${creator.id}` ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} aria-hidden="true" />}
                  刷新
                </button>
                <button
                  className="secondary-action danger"
                  type="button"
                  disabled={busyAction === `creator-delete-${creator.id}`}
                  onClick={() => onDelete(creator.id)}
                >
                  {busyAction === `creator-delete-${creator.id}` ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} aria-hidden="true" />}
                  删除
                </button>
              </div>
            </article>
          ))
        )}
      </section>
    </div>
  );
}

function FilesView({
  files,
  filePath,
  media,
  onOpen,
  onOpenMedia,
  onRefresh
}: {
  files: FileItem[];
  filePath: string;
  media: MediaItem[];
  onOpen: (path: string) => void;
  onOpenMedia: (media: MediaItem) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="content-grid file-center-grid">
      <section className="settings-card full-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">FILE CENTER</p>
            <h2>文件中心</h2>
            <span>{filePath || "下载根目录"}</span>
          </div>
          <button className="secondary-action" type="button" onClick={onRefresh}>
            <RefreshCw size={17} aria-hidden="true" />
            刷新
          </button>
        </div>
        <FilePath path={filePath} onOpen={onOpen} />
        <div className="file-table custom-scrollbar">
          {filePath && (
            <button className="file-row file-button" type="button" onClick={() => onOpen(parentPath(filePath))}>
              <Folder size={19} aria-hidden="true" />
              <span>..</span>
              <small>上级目录</small>
              <span />
            </button>
          )}
          {files.length === 0 ? (
            <EmptyState icon={<Folder size={28} />} title="此文件夹暂无文件" detail="任务完成后可在这里下载结果。" />
          ) : (
            files.map((item) => (
              <div className="file-row" key={item.path}>
                {item.is_dir ? <Folder size={19} aria-hidden="true" /> : <File size={19} aria-hidden="true" />}
                {item.is_dir ? (
                  <button className="file-name" type="button" onClick={() => onOpen(item.path)}>
                    {item.name}
                  </button>
                ) : (
                  <span title={item.name}>{item.name}</span>
                )}
                <small>{item.is_dir ? "文件夹" : formatBytes(item.size)}</small>
                {!item.is_dir && (
                  <a className="download-link" href={`/api/files/download?path=${encodeURIComponent(item.path)}`} aria-label={`下载 ${item.name}`}>
                    <Download size={16} aria-hidden="true" />
                  </a>
                )}
              </div>
            ))
          )}
        </div>
      </section>
      <MediaPanel
        title="当前目录预览"
        subtitle="递归显示当前目录下最近 60 个媒体文件。"
        media={media}
        onOpen={onOpenMedia}
        onRefresh={onRefresh}
      />
    </div>
  );
}

function MediaPanel({
  title,
  subtitle,
  media,
  onOpen,
  onRefresh
}: {
  title: string;
  subtitle: string;
  media: MediaItem[];
  onOpen: (media: MediaItem) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="settings-card media-panel">
      <div className="section-heading compact">
        <div>
          <p className="section-kicker">MEDIA PREVIEW</p>
          <h2>{title}</h2>
          <span>{subtitle}</span>
        </div>
        <button className="icon-action" type="button" onClick={onRefresh} aria-label="刷新预览">
          <RefreshCw size={17} aria-hidden="true" />
        </button>
      </div>
      <div className="media-grid custom-scrollbar">
        {media.length === 0 ? (
          <EmptyState icon={<Image size={28} />} title="暂无可预览媒体" detail="采集到图片或视频后会显示在这里。" />
        ) : (
          media.map((item) => (
            <button className="media-card" type="button" key={item.path} onClick={() => onOpen(item)}>
              <span className="media-thumb">
                {item.media_type === "image" ? (
                  <img src={`/api/media/view?path=${encodeURIComponent(item.path)}`} alt={item.name} loading="lazy" />
                ) : (
                  <video src={`/api/media/view?path=${encodeURIComponent(item.path)}`} muted preload="metadata" />
                )}
                <span className="media-type">{item.media_type === "image" ? "图片" : "视频"}</span>
              </span>
              <span className="media-meta">
                <strong title={item.name}>{item.name}</strong>
                <small>{formatBytes(item.size)} · {formatTime(item.modified_at)}</small>
              </span>
            </button>
          ))
        )}
      </div>
    </section>
  );
}

function PreviewModal({ media, onClose }: { media: MediaItem; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const source = `/api/media/view?path=${encodeURIComponent(media.path)}`;

  return (
    <div className="preview-backdrop" role="presentation" onClick={onClose}>
      <div className="preview-dialog" role="dialog" aria-modal="true" aria-label={media.name} onClick={(event) => event.stopPropagation()}>
        <div className="preview-header">
          <div>
            <strong title={media.name}>{media.name}</strong>
            <span>{media.media_type === "image" ? "图片" : "视频"} · {formatBytes(media.size)}</span>
          </div>
          <div className="preview-actions">
            <a className="secondary-action" href={`/api/files/download?path=${encodeURIComponent(media.path)}`}>
              <Download size={16} aria-hidden="true" />
              下载
            </a>
            <button className="modal-close" type="button" onClick={onClose} aria-label="关闭预览">
              <X size={22} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="preview-stage">
          {media.media_type === "image" ? (
            <img src={source} alt={media.name} />
          ) : (
            <video src={source} controls autoPlay />
          )}
        </div>
      </div>
    </div>
  );
}

function LogsView({
  tasks,
  selectedTask,
  selectedEvents,
  setSelectedTaskId,
  eventState
}: {
  tasks: Task[];
  selectedTask: Task | null;
  selectedEvents: TaskEvent[];
  setSelectedTaskId: (value: number) => void;
  eventState: "connecting" | "connected" | "offline";
}) {
  return (
    <section className="content-grid logs-grid">
      <div className="settings-card log-selector">
        <div className="section-heading compact">
          <div>
            <p className="section-kicker">TASKS</p>
            <h2>选择任务</h2>
          </div>
          <div className={`mini-state ${eventState === "connected" ? "ok" : "warn"}`}>
            {eventState === "connected" ? <Server size={15} /> : <WifiOff size={15} />}
            <span>{eventState === "connected" ? "实时" : "离线"}</span>
          </div>
        </div>
        <div className="task-picker custom-scrollbar">
          {tasks.map((task) => (
            <button
              className={`picker-row ${selectedTask?.id === task.id ? "active" : ""}`}
              type="button"
              key={task.id}
              onClick={() => setSelectedTaskId(task.id)}
            >
              <span>#{task.id}</span>
              <TaskStatusLabel status={task.status} />
              <small>{task.targets.join(", ")}</small>
            </button>
          ))}
          {tasks.length === 0 && <EmptyState icon={<TerminalSquare size={28} />} title="暂无任务" detail="创建任务后会产生运行日志。" />}
        </div>
      </div>
      <div className="settings-card log-panel-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">ACTIVITY LOG</p>
            <h2>{selectedTask ? `任务 #${selectedTask.id} 日志` : "日志详情"}</h2>
            <span>{selectedTask ? `${targetLabels[selectedTask.target_type]} · ${statusLabels[selectedTask.status]}` : "请选择任务"}</span>
          </div>
          {selectedTask?.error_code && <TaskError task={selectedTask} />}
        </div>
        <div className="log-console custom-scrollbar">
          {selectedEvents.length === 0 ? (
            <p className="console-empty">所选任务暂无事件。</p>
          ) : (
            selectedEvents.map((event) => (
              <div className={`console-line ${event.level}`} key={event.id}>
                <time>{formatTime(event.created_at)}</time>
                <span>{event.level}</span>
                <p>{event.message}</p>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function SettingsView({
  health,
  settings,
  settingsDraft,
  system,
  setSettingsDraft,
  onSaveSettings,
  busyAction
}: {
  health: HealthStatus | null;
  settings: AppSettings | null;
  settingsDraft: AppSettings | null;
  system: SystemInfo | null;
  setSettingsDraft: (value: AppSettings) => void;
  onSaveSettings: (event: FormEvent<HTMLFormElement>) => void;
  busyAction: string | null;
}) {
  if (!settings || !settingsDraft) {
    return (
      <section className="settings-card full-card">
        <EmptyState icon={<Settings size={28} />} title="正在加载配置" detail="稍等片刻，系统正在读取设置。" />
      </section>
    );
  }

  const diskPercent = Math.min(100, Math.round((system?.storage_used ?? 0) / Math.max((system?.storage_used ?? 0) + (health?.free_disk_bytes ?? 1), 1) * 100));

  return (
    <div className="settings-layout">
      <section className="settings-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">DOWNLOAD</p>
            <h2>下载设置</h2>
          </div>
          <HardDrive size={22} aria-hidden="true" />
        </div>
        <form className="settings-form" onSubmit={onSaveSettings}>
          <label className="field-line">
            <span>并发任务数</span>
            <input
              type="number"
              min={1}
              max={5}
              value={settingsDraft.max_concurrent_tasks}
              onChange={(event) => setSettingsDraft({ ...settingsDraft, max_concurrent_tasks: Number(event.target.value) })}
            />
          </label>
          <label className="field-line">
            <span>默认最大下载数</span>
            <input
              type="number"
              min={1}
              value={settingsDraft.default_max_count ?? ""}
              onChange={(event) =>
                setSettingsDraft({ ...settingsDraft, default_max_count: event.target.value ? Number(event.target.value) : null })
              }
            />
          </label>
          <label className="field-line wide">
            <span>保存路径</span>
            <input
              type="text"
              value={settingsDraft.download_root}
              onChange={(event) => setSettingsDraft({ ...settingsDraft, download_root: event.target.value })}
            />
          </label>
          <button className="primary-action fit" type="submit" disabled={busyAction === "settings"}>
            {busyAction === "settings" ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
            保存设置
          </button>
        </form>
      </section>

      <section className="settings-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">INTERFACE</p>
            <h2>界面设置</h2>
          </div>
          <SlidersHorizontal size={22} aria-hidden="true" />
        </div>
        <div className="theme-switcher" role="group" aria-label="主题选择">
          <ThemeButton icon={<Sun size={17} />} label="浅色" active={settingsDraft.theme === "light"} onClick={() => setSettingsDraft({ ...settingsDraft, theme: "light" })} />
          <ThemeButton icon={<Moon size={17} />} label="深色" active={settingsDraft.theme === "dark"} onClick={() => setSettingsDraft({ ...settingsDraft, theme: "dark" })} />
          <ThemeButton icon={<Sparkles size={17} />} label="跟随系统" active={settingsDraft.theme === "system"} onClick={() => setSettingsDraft({ ...settingsDraft, theme: "system" })} />
        </div>
        <div className="toggle-list">
          <SwitchLine
            label="显示调试日志"
            detail="日志页显示更详细的运行信息。"
            checked={settingsDraft.show_debug_logs}
            onChange={(value) => setSettingsDraft({ ...settingsDraft, show_debug_logs: value })}
          />
          <SwitchLine
            label="桌面通知"
            detail="任务完成或失败时提醒。"
            checked={settingsDraft.desktop_notifications}
            onChange={(value) => setSettingsDraft({ ...settingsDraft, desktop_notifications: value })}
          />
        </div>
      </section>

      <section className="settings-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">SYSTEM</p>
            <h2>系统信息</h2>
          </div>
          <Server size={22} aria-hidden="true" />
        </div>
        <div className="system-list">
          <DetailLine label="下载引擎" value={system?.engine_version ?? "-"} />
          <DetailLine label="数据库" value={formatBytes(system?.database_size ?? 0)} />
          <DetailLine label="数据目录" value={system?.data_root ?? "-"} />
          <DetailLine label="运行中任务" value={`${system?.running_tasks ?? 0}`} />
          <DetailLine label="总任务数" value={`${system?.total_tasks ?? 0}`} />
        </div>
        <div className="disk-card">
          <div>
            <strong>磁盘占用</strong>
            <span>{formatBytes(system?.storage_used ?? 0)} / 可用 {formatBytes(health?.free_disk_bytes ?? 0)}</span>
          </div>
          <div className="disk-track">
            <span style={{ width: `${diskPercent}%` }} />
          </div>
        </div>
        <div className="health-list">
          <HealthRow ok={health?.database_writable ?? false} label="数据库可写" />
          <HealthRow ok={health?.download_root_writable ?? false} label="下载目录可写" />
          <HealthRow ok={!health?.cooling_down} label={health?.cooling_down ? `冷却至 ${formatTime(health.cooldown_until)}` : "无冷却"} />
        </div>
      </section>
    </div>
  );
}

function AccountsView({
  account,
  accounts,
  settingsDraft,
  setSettingsDraft,
  onSaveSettings,
  onTestSession,
  onClearSession,
  onTestAccount,
  onSetDefaultAccount,
  onDeleteAccount,
  loginUsername,
  setLoginUsername,
  loginPassword,
  setLoginPassword,
  twoFactorCode,
  setTwoFactorCode,
  sessionUsername,
  setSessionUsername,
  setSessionFile,
  cookies,
  setCookies,
  cookieUsername,
  setCookieUsername,
  onLogin,
  onTwoFactor,
  onSessionFile,
  onImportCookies,
  busyAction
}: {
  account: AccountStatus | null;
  accounts: AccountListResponse | null;
  settingsDraft: AppSettings | null;
  setSettingsDraft: (value: AppSettings) => void;
  onSaveSettings: (event: FormEvent<HTMLFormElement>) => void;
  onTestSession: () => void;
  onClearSession: () => void;
  onTestAccount: (username: string) => void;
  onSetDefaultAccount: (username: string) => void;
  onDeleteAccount: (username: string) => void;
  loginUsername: string;
  setLoginUsername: (value: string) => void;
  loginPassword: string;
  setLoginPassword: (value: string) => void;
  twoFactorCode: string;
  setTwoFactorCode: (value: string) => void;
  sessionUsername: string;
  setSessionUsername: (value: string) => void;
  setSessionFile: (value: File | null) => void;
  cookies: string;
  setCookies: (value: string) => void;
  cookieUsername: string;
  setCookieUsername: (value: string) => void;
  onLogin: (event: FormEvent<HTMLFormElement>) => void;
  onTwoFactor: (event: FormEvent<HTMLFormElement>) => void;
  onSessionFile: (event: FormEvent<HTMLFormElement>) => void;
  onImportCookies: (event: FormEvent<HTMLFormElement>) => void;
  busyAction: string | null;
}) {
  const records = accounts?.accounts ?? [];
  const coolingCount = records.filter(isAccountCoolingDown).length;
  const invalidCount = records.filter((record) => record.last_test_status === "invalid" || !record.is_connected).length;

  return (
    <div className="account-manager">
      <section className="summary-grid" aria-label="账号池概览">
        <SummaryCard icon={<ShieldCheck size={20} />} label="可用账号" value={`${accounts?.available_count ?? 0}`} detail={`共 ${records.length} 个账号`} />
        <SummaryCard icon={<Clock3 size={20} />} label="冷却中" value={`${coolingCount}`} detail="到期后自动恢复轮换" />
        <SummaryCard icon={<AlertTriangle size={20} />} label="异常账号" value={`${invalidCount}`} detail="建议测试或重新导入" />
        <SummaryCard icon={<UserRound size={20} />} label="默认账号" value={accounts?.default_username ? `@${accounts.default_username}` : "未设置"} detail="优先用于手动操作" />
      </section>

      <section className="settings-card account-stability-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">STABILITY GUARD</p>
            <h2>稳定采集设置</h2>
            <span>控制账号使用间隔，并自动跳过冷却中的账号。</span>
          </div>
          <ShieldCheck size={22} aria-hidden="true" />
        </div>
        {settingsDraft ? (
          <form className="stability-form" onSubmit={onSaveSettings}>
            <SwitchLine
              label="稳定采集模式"
              detail="任务启动前会检查账号冷却和最小使用间隔。"
              checked={settingsDraft.stability_guard_enabled}
              onChange={(value) => setSettingsDraft({ ...settingsDraft, stability_guard_enabled: value })}
            />
            <label className="field-line">
              <span>账号最小间隔（秒）</span>
              <input
                type="number"
                min={0}
                max={3600}
                value={settingsDraft.account_min_interval_seconds}
                disabled={!settingsDraft.stability_guard_enabled}
                onChange={(event) =>
                  setSettingsDraft({ ...settingsDraft, account_min_interval_seconds: Number(event.target.value) })
                }
              />
            </label>
            <button className="primary-action fit" type="submit" disabled={busyAction === "settings"}>
              {busyAction === "settings" ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
              保存设置
            </button>
          </form>
        ) : (
          <p className="muted-line">正在加载稳定采集设置。</p>
        )}
      </section>

      <section className="settings-card account-form-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">ADD ACCOUNT</p>
            <h2>新增或更新账号</h2>
            <span>使用网页登录、Session 文件或 Cookie 文本导入账号到账号池。</span>
          </div>
          <KeyRound size={22} aria-hidden="true" />
        </div>
        <div className="account-forms">
          <form className="compact-form" onSubmit={account?.pending_two_factor ? onTwoFactor : onLogin}>
            <label>
              用户名
              <input type="text" value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} />
            </label>
            <label>
              密码
              <input type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
            </label>
            <button
              className="primary-action fit"
              type="submit"
              disabled={busyAction === "login" || (!account?.pending_two_factor && (!loginUsername.trim() || !loginPassword))}
            >
              {busyAction === "login" ? <Loader2 className="spin" size={18} /> : <KeyRound size={18} />}
              {account?.pending_two_factor ? "继续验证" : "网页登录"}
            </button>
            {(account?.pending_two_factor || twoFactorCode) && (
              <>
                <label className="wide">
                  两步验证码
                  <input type="text" value={twoFactorCode} onChange={(event) => setTwoFactorCode(event.target.value)} />
                </label>
                <button className="secondary-action fit" type="submit" disabled={busyAction === "2fa" || !twoFactorCode.trim()}>
                  <ShieldCheck size={16} aria-hidden="true" />
                  提交验证码
                </button>
              </>
            )}
          </form>

          <form className="compact-form single" onSubmit={onSessionFile}>
            <label>
              Session 用户名
              <input type="text" value={sessionUsername} onChange={(event) => setSessionUsername(event.target.value)} />
            </label>
            <label>
              Session 文件
              <input type="file" onChange={(event) => setSessionFile(event.target.files?.[0] ?? null)} />
            </label>
            <button className="secondary-action fit" type="submit" disabled={busyAction === "session-file" || !sessionUsername.trim()}>
              <Upload size={16} aria-hidden="true" />
              导入 Session
            </button>
          </form>

          <form className="compact-form cookie-form" onSubmit={onImportCookies}>
            <label>
              Cookie 用户名
              <input type="text" value={cookieUsername} onChange={(event) => setCookieUsername(event.target.value)} placeholder="可选" />
            </label>
            <label className="wide">
              Cookie JSON 或 Netscape 文本
              <textarea rows={4} value={cookies} onChange={(event) => setCookies(event.target.value)} placeholder="sessionid=...; csrftoken=..." />
            </label>
            <button className="secondary-action fit" type="submit" disabled={busyAction === "cookies" || !cookies.trim()}>
              {busyAction === "cookies" ? <Loader2 className="spin" size={16} /> : <Upload size={16} aria-hidden="true" />}
              导入 Cookies
            </button>
          </form>
        </div>
      </section>

      <section className="settings-card account-table-card">
        <div className="section-heading">
          <div>
            <p className="section-kicker">ACCOUNT DETAILS</p>
            <h2>账号详细情况</h2>
            <span>{account?.message ?? "账号越多，批量任务越容易分散请求压力。"}</span>
          </div>
        </div>
        <AccountPool
          accounts={accounts}
          busyAction={busyAction}
          onTestSession={onTestSession}
          onClearSession={onClearSession}
          onTestAccount={onTestAccount}
          onSetDefaultAccount={onSetDefaultAccount}
          onDeleteAccount={onDeleteAccount}
        />
      </section>

    </div>
  );
}

function AccountPool({
  accounts,
  busyAction,
  onTestSession,
  onClearSession,
  onTestAccount,
  onSetDefaultAccount,
  onDeleteAccount
}: {
  accounts: AccountListResponse | null;
  busyAction: string | null;
  onTestSession: () => void;
  onClearSession: () => void;
  onTestAccount: (username: string) => void;
  onSetDefaultAccount: (username: string) => void;
  onDeleteAccount: (username: string) => void;
}) {
  const records = accounts?.accounts ?? [];
  if (records.length === 0) {
    return (
      <div className="account-empty">
        <UserRound size={28} aria-hidden="true" />
        <div>
          <strong>账号池为空</strong>
          <span>点击右上角新增账号，使用登录、Cookie 或 Session 文件逐个添加。</span>
        </div>
      </div>
    );
  }

  return (
    <div className="account-pool">
      <div className="account-pool-summary">
        <span>{accounts?.available_count ?? 0} / {records.length} 可用</span>
        <div className="account-actions">
          <button className="secondary-action" type="button" disabled={busyAction === "test-session"} onClick={onTestSession}>
            <RefreshCw size={16} aria-hidden="true" />
            测试默认
          </button>
          <button className="secondary-action danger" type="button" disabled={busyAction === "clear-session"} onClick={onClearSession}>
            <LogOut size={16} aria-hidden="true" />
            删除默认
          </button>
        </div>
      </div>
      <div className="account-table-wrap custom-scrollbar">
        <div className="account-table-header" aria-hidden="true">
          <span>账号</span>
          <span>轮换状态</span>
          <span>Session 测试</span>
          <span>最近使用</span>
          <span>冷却截止</span>
          <span>失败</span>
          <span>最近错误</span>
          <span>操作</span>
        </div>
        <div className="account-list">
        {records.map((record) => (
          <article className={`account-row ${record.is_default ? "default" : ""}`} key={record.username}>
            <div className="account-cell account-row-main" data-label="账号">
              <div className={record.is_connected ? "account-dot ok" : "account-dot"} />
              <div>
                <strong>@{record.username}</strong>
                {record.is_default && <span>默认账号</span>}
              </div>
            </div>
            <div className="account-cell" data-label="轮换状态">
              <span className={`test-state ${accountAvailabilityClass(record)}`}>{accountAvailabilityLabel(record)}</span>
            </div>
            <div className="account-cell" data-label="Session 测试">
              <span className={`test-state ${record.last_test_status ?? "unknown"}`}>{accountTestLabel(record.last_test_status)}</span>
            </div>
            <div className="account-cell" data-label="最近使用">
              <small>{formatTime(record.last_used_at)}</small>
            </div>
            <div className="account-cell" data-label="冷却截止">
              <small>{formatTime(record.cooldown_until)}</small>
            </div>
            <div className="account-cell" data-label="失败">
              <span className={record.failure_count > 0 ? "test-state warn" : "muted-line"}>{record.failure_count}</span>
            </div>
            <div className="account-cell account-error" data-label="最近错误" title={record.last_error ?? undefined}>
              {record.last_error ?? "-"}
            </div>
            <div className="account-cell account-row-actions" data-label="操作">
              <button
                className="secondary-action"
                type="button"
                disabled={busyAction === `test-account-${record.username}`}
                onClick={() => onTestAccount(record.username)}
              >
                <RefreshCw size={15} aria-hidden="true" />
                测试
              </button>
              <button
                className="secondary-action"
                type="button"
                disabled={record.is_default || busyAction === `default-account-${record.username}`}
                onClick={() => onSetDefaultAccount(record.username)}
              >
                <Check size={15} aria-hidden="true" />
                默认
              </button>
              <button
                className="secondary-action danger"
                type="button"
                disabled={busyAction === `delete-account-${record.username}`}
                onClick={() => onDeleteAccount(record.username)}
              >
                <X size={15} aria-hidden="true" />
                删除
              </button>
            </div>
          </article>
        ))}
        </div>
      </div>
    </div>
  );
}

function accountTestLabel(value: AccountRecord["last_test_status"]): string {
  if (value === "valid") return "有效";
  if (value === "invalid") return "失效";
  return "未测试";
}

function accountAvailabilityLabel(record: AccountRecord): string {
  if (record.last_test_status === "invalid") return "账号已失效";
  if (!record.is_connected) return "Session 文件缺失";
  if (record.cooldown_until && new Date(record.cooldown_until).getTime() > Date.now()) return "冷却中";
  return "可参与轮换";
}

function accountAvailabilityClass(record: AccountRecord): string {
  if (record.last_test_status === "invalid" || !record.is_connected) return "invalid";
  if (isAccountCoolingDown(record)) return "warn";
  return "valid";
}

function isAccountCoolingDown(record: AccountRecord): boolean {
  return Boolean(record.cooldown_until && new Date(record.cooldown_until).getTime() > Date.now());
}

function NewTaskModal({
  targetType,
  setTargetType,
  targetsText,
  setTargetsText,
  options,
  updateOption,
  requiresLogin,
  availableAccounts,
  busy,
  onSubmit,
  onClose
}: {
  targetType: TargetType;
  setTargetType: (value: TargetType) => void;
  targetsText: string;
  setTargetsText: (value: string) => void;
  options: DownloadOptions;
  updateOption: <K extends keyof DownloadOptions>(key: K, value: DownloadOptions[K]) => void;
  requiresLogin: boolean;
  availableAccounts: number;
  busy: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
}) {
  const targetHelp = loginTargetTypes.has(targetType)
    ? "此目标类型使用账号池自动轮换，无需输入公开用户名。"
    : "可输入一个或多个目标，用换行或逗号分隔。";

  return (
    <div className="modal-backdrop" role="presentation">
      <div className="dashboard-blur" aria-hidden="true">
        <div className="mock-sidebar" />
        <div className="mock-main">
          <span />
          <span />
          <span />
        </div>
      </div>
      <div className="task-modal" role="dialog" aria-modal="true" aria-labelledby="new-task-title">
        <div className="modal-header">
          <h2 id="new-task-title">创建新下载任务</h2>
          <button className="modal-close" type="button" onClick={onClose} aria-label="关闭">
            <X size={22} aria-hidden="true" />
          </button>
        </div>
        <form className="modal-body custom-scrollbar" onSubmit={onSubmit}>
          <section>
            <label className="modal-label">目标类型</label>
            <div className="target-grid">
              {targetItems.map((item) => (
                <button
                  className={`target-option ${targetType === item.value ? "active" : ""}`}
                  type="button"
                  key={item.value}
                  onClick={() => setTargetType(item.value)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="modal-section">
            <label className="modal-label" htmlFor="targets">
              目标内容
            </label>
            <textarea
              id="targets"
              rows={4}
              value={targetsText}
              disabled={loginTargetTypes.has(targetType)}
              onChange={(event) => setTargetsText(event.target.value)}
              placeholder={loginTargetTypes.has(targetType) ? targetLabels[targetType] : "profile_one\n#hashtag\nshortcode"}
            />
            <p className="field-help">{targetHelp}</p>
          </section>

          {requiresLogin && availableAccounts < 1 && (
            <div className="modal-warning" role="alert">
              <AlertTriangle size={18} aria-hidden="true" />
              此任务需要先在配置中心连接 Instagram 账号。
            </div>
          )}
          {availableAccounts > 0 && (
            <div className="modal-hint">
              <ShieldCheck size={17} aria-hidden="true" />
              当前账号池有 {availableAccounts} 个可用账号，任务启动时会自动选择最近未使用的账号。
            </div>
          )}

          <section className="modal-section">
            <label className="modal-label">下载内容</label>
            <div className="content-grid-options">
              <CheckTile icon={<Image size={18} />} label="图片" checked={options.download_pictures} onChange={(value) => updateOption("download_pictures", value)} />
              <CheckTile icon={<Play size={18} />} label="视频" checked={options.download_videos} onChange={(value) => updateOption("download_videos", value)} />
              <CheckTile icon={<UserCircle size={18} />} label="头像" checked={options.download_profile_pic} onChange={(value) => updateOption("download_profile_pic", value)} />
              <CheckTile icon={<History size={18} />} label="快拍" checked={options.download_stories} onChange={(value) => updateOption("download_stories", value)} />
              <CheckTile icon={<Sparkles size={18} />} label="精选" checked={options.download_highlights} onChange={(value) => updateOption("download_highlights", value)} />
              <CheckTile icon={<Hash size={18} />} label="标记" checked={options.download_tagged} onChange={(value) => updateOption("download_tagged", value)} />
              <CheckTile icon={<Grid3X3 size={18} />} label="Reels" checked={options.download_reels} onChange={(value) => updateOption("download_reels", value)} />
              <CheckTile icon={<File size={18} />} label="元数据" checked={options.save_metadata} onChange={(value) => updateOption("save_metadata", value)} />
            </div>
          </section>

          <details className="soft-details modal-details">
            <summary>
              <SlidersHorizontal size={17} aria-hidden="true" />
              高级选项
              <ChevronRight size={16} aria-hidden="true" />
            </summary>
            <div className="advanced-grid">
              <label>
                最大下载数
                <input
                  type="number"
                  min={1}
                  value={options.max_count ?? ""}
                  onChange={(event) => updateOption("max_count", event.target.value ? Number(event.target.value) : null)}
                />
              </label>
              <SwitchLine label="快速更新" detail="跳过已存在内容。" checked={options.fast_update} onChange={(value) => updateOption("fast_update", value)} />
              <SwitchLine label="压缩 JSON" detail="保存更小的元数据文件。" checked={options.compress_json} onChange={(value) => updateOption("compress_json", value)} />
              <SwitchLine label="清理路径" detail="移除文件名中的非法字符。" checked={options.sanitize_paths} onChange={(value) => updateOption("sanitize_paths", value)} />
              <SwitchLine label="视频缩略图" detail="保存视频预览图。" checked={options.download_video_thumbnails} onChange={(value) => updateOption("download_video_thumbnails", value)} />
              <SwitchLine label="评论" detail="下载帖子评论。" checked={options.download_comments} onChange={(value) => updateOption("download_comments", value)} />
              <SwitchLine label="地理位置" detail="保存位置数据。" checked={options.download_geotags} onChange={(value) => updateOption("download_geotags", value)} />
              <SwitchLine label="IGTV" detail="包含 IGTV 内容。" checked={options.download_igtv} onChange={(value) => updateOption("download_igtv", value)} />
            </div>
          </details>

          <div className="modal-footer">
            <button className="secondary-action" type="button" onClick={onClose}>
              取消
            </button>
            <button className="primary-action" type="submit" disabled={busy || (requiresLogin && availableAccounts < 1)}>
              {busy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              开始下载
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SummaryCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <article className="summary-card">
      <div className="summary-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
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
    <span className={`status-label ${status}`}>
      {icon}
      {statusLabels[status]}
    </span>
  );
}

function TaskError({ task }: { task: Task }) {
  return (
    <div className="error-badge" title={task.error ?? undefined}>
      <AlertTriangle size={16} aria-hidden="true" />
      {task.error_code}
    </div>
  );
}

function Avatar({ creator }: { creator: Creator }) {
  const [failed, setFailed] = useState(false);
  const showImage = creator.avatar_url && !failed;
  return (
    <div className="creator-avatar">
      {showImage ? (
        <img src={creator.avatar_url ?? ""} alt={`${creator.username} 头像`} loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <UserCircle size={42} aria-hidden="true" />
      )}
    </div>
  );
}

function FilePath({ path, onOpen }: { path: string; onOpen: (path: string) => void }) {
  const parts = path.split("/").filter(Boolean);
  let current = "";
  return (
    <div className="breadcrumb" aria-label="文件路径">
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

function CheckTile({ icon, label, checked, onChange }: { icon: ReactNode; label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className={`check-tile ${checked ? "checked" : ""}`}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {icon}
      <span>{label}</span>
      <Check size={15} aria-hidden="true" />
    </label>
  );
}

function ThemeButton({ icon, label, active, onClick }: { icon: ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button className={`theme-button ${active ? "active" : ""}`} type="button" onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function SwitchLine({
  label,
  detail,
  checked,
  onChange
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="switch-line">
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
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

function DetailLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-line">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function EmptyState({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="empty-state">
      {icon}
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}
