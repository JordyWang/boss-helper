"""本地可视化操作界面。

界面使用 Python 标准库提供的本地 HTTP 服务，不引入前端框架或额外依赖。
浏览器只负责展示和发起请求；真正的设备操作仍然复用会话列表页、聊天页、
运行归档和 ``.run.lock``。HTTP 服务使用单线程服务器，另外在服务层保留
进程内锁，避免同一进程/浏览器误发请求时并行控制设备。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlparse

from .artifacts import RunArtifacts, RunInProgressError
from .capture import record_observation, save_conversation
from .config import AppConfig, load_config
from .logger import close_logger, setup_logger
from .operations import OperationContext, run_operation
from .pages.chat import ChatPage
from .pages.conversations import ConversationListPage
from .records import Recorder
from .state import State


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Boss Helper · 操作台</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --panel: #ffffff;
      --ink: #182230;
      --muted: #6b7788;
      --line: #e4eaf2;
      --brand: #1769e0;
      --brand-dark: #0f4fae;
      --ok: #087443;
      --warn: #a45a00;
      --danger: #b42318;
      --shadow: 0 10px 30px rgba(33, 55, 85, .08);
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
    header { background: linear-gradient(120deg, #135dcc, #2388e8); color: #fff;
      padding: 22px 34px; display: flex; align-items: center; justify-content: space-between; }
    header h1 { margin: 0; font-size: 22px; letter-spacing: .3px; }
    header p { margin: 4px 0 0; opacity: .82; }
    .badge { border: 1px solid rgba(255,255,255,.38); border-radius: 99px;
      padding: 5px 12px; font-size: 12px; background: rgba(255,255,255,.12); }
    main { max-width: 1280px; margin: 24px auto; padding: 0 20px 50px; }
    .toolbar, .panel { background: var(--panel); border: 1px solid var(--line);
      border-radius: 14px; box-shadow: var(--shadow); }
    .toolbar { padding: 16px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    button, input { font: inherit; }
    button { border: 0; border-radius: 8px; padding: 9px 14px; cursor: pointer;
      background: var(--brand); color: #fff; transition: background .15s, transform .05s; }
    button:hover { background: var(--brand-dark); }
    button:active { transform: translateY(1px); }
    button.secondary { background: #eef4fc; color: #1d4f91; }
    button.secondary:hover { background: #dceafd; }
    button.danger { background: #b42318; }
    button.danger:hover { background: #8f1d14; }
    button:disabled { opacity: .55; cursor: wait; }
    button.small { padding: 6px 10px; font-size: 12px; }
    input { border: 1px solid #ccd6e4; border-radius: 8px; padding: 9px 11px;
      min-width: 280px; color: var(--ink); background: #fff; }
    input.number { min-width: 72px; width: 72px; }
    .hint { color: var(--muted); margin-left: auto; }
    .status { margin: 14px 0; padding: 10px 14px; border-radius: 9px; background: #edf5ff;
      color: #24558f; border: 1px solid #d2e5ff; min-height: 42px; }
    .status.error { background: #fff1f0; color: var(--danger); border-color: #ffd4d0; }
    .status.ok { background: #ecfdf3; color: var(--ok); border-color: #b7ebcc; }
    .overview { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px; margin-bottom: 14px; }
    .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
      box-shadow: var(--shadow); padding: 14px 16px; }
    .metric-label { color: var(--muted); font-size: 12px; }
    .metric-value { font-size: 20px; font-weight: 700; margin-top: 2px; word-break: break-all; }
    .action-title { font-weight: 700; margin-right: 4px; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 18px; }
    .panel-title { display: flex; justify-content: space-between; align-items: center;
      padding: 16px 18px; border-bottom: 1px solid var(--line); }
    .panel-title h2 { font-size: 16px; margin: 0; }
    .count { color: var(--muted); font-size: 12px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--muted); font-size: 12px; font-weight: 600; background: #fbfcfe; }
    tr:last-child td { border-bottom: 0; }
    tr:hover td { background: #fbfdff; }
    .person { font-weight: 650; }
    .sub { color: var(--muted); font-size: 12px; margin-top: 2px; }
    code { font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #32577e; word-break: break-all; }
    .empty { padding: 42px 20px; color: var(--muted); text-align: center; }
    .archive { max-height: 520px; overflow: auto; padding: 12px 16px; }
    .message { padding: 9px 0; border-bottom: 1px solid var(--line); }
    .message:last-child { border-bottom: 0; }
    .message-meta { color: var(--muted); font-size: 11px; margin-bottom: 2px; }
    .message-action { color: #8a5a00; background: #fff8e8; border-radius: 5px; padding: 2px 6px; }
    .run-path { padding: 12px 16px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); word-break: break-all; }
    @media (max-width: 1100px) { .overview { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .overview { grid-template-columns: repeat(2, 1fr); } .hint { width: 100%; margin-left: 0; } }
  </style>
</head>
<body>
  <header>
    <div><h1>Boss Helper · 可视化操作台</h1><p>设备检查、批量沟通、会话查看与本地归档</p></div>
    <span class="badge">串行执行 · 本机界面</span>
  </header>
  <main>
    <section class="overview">
      <div class="metric"><div class="metric-label">今日已沟通</div><div id="todayMetric" class="metric-value">—</div></div>
      <div class="metric"><div class="metric-label">单次默认上限</div><div id="runMetric" class="metric-value">—</div></div>
      <div class="metric"><div class="metric-label">APK 版本</div><div id="versionMetric" class="metric-value">—</div></div>
      <div class="metric"><div class="metric-label">设备状态</div><div id="deviceMetric" class="metric-value">未检查</div></div>
      <div class="metric"><div class="metric-label">SQLite 已采集</div><div id="storageMetric" class="metric-value">—</div></div>
    </section>
    <section class="toolbar" style="margin-bottom:14px">
      <span class="action-title">运行操作</span>
      <button id="health" class="secondary">检查设备</button>
      <button id="capture" class="secondary">保存截图与 Dump</button>
      <input id="applyLimit" class="number" type="number" min="1" max="100" value="1" aria-label="沟通数量">
      <button id="runBatch" class="danger">批量沟通</button>
      <span class="hint">批量沟通会产生真实操作，点击后还会二次确认</span>
    </section>
    <section class="toolbar">
      <span class="action-title">会话管理</span>
      <button id="refresh">刷新会话列表</button>
      <input id="targetId" placeholder="粘贴会话 ID，按 ID 保存" aria-label="会话 ID">
      <button id="archiveSelected">保存指定会话</button>
      <input id="count" class="number" type="number" min="1" placeholder="数量" aria-label="数量">
      <button id="archiveCount" class="secondary">保存前 N 个</button>
      <span class="hint">默认只列出当前可见会话，不会自动点开全部聊天</span>
    </section>
    <div id="status" class="status">正在准备界面…</div>
    <section class="grid">
      <div class="panel">
        <div class="panel-title"><h2>当前会话</h2><span id="countLabel" class="count">0 条</span></div>
        <div class="table-wrap"><table>
          <thead><tr><th>联系人</th><th>公司 / 职位</th><th>最近消息</th><th>会话 ID</th><th></th></tr></thead>
          <tbody id="conversationRows"><tr><td colspan="5" class="empty">点击“刷新会话列表”读取</td></tr></tbody>
        </table></div>
      </div>
      <aside class="panel">
        <div class="panel-title"><h2>最近归档</h2><span class="count">本次操作</span></div>
        <div id="archive" class="archive"><div class="empty">保存会话后在这里查看消息</div></div>
        <div id="runPath" class="run-path">暂无运行记录</div>
      </aside>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    function setStatus(text, kind='') { $('status').textContent = text; $('status').className = 'status ' + kind; }
    function setBusy(busy) { document.querySelectorAll('button').forEach((button) => button.disabled = busy); }
    function idOf(row) { return row.conversation_id || row.local_id || ''; }
    function renderRows(rows) {
      $('countLabel').textContent = `${rows.length} 条`;
      if (!rows.length) { $('conversationRows').innerHTML = '<tr><td colspan="5" class="empty">当前没有可见会话</td></tr>'; return; }
      $('conversationRows').innerHTML = rows.map((row) => {
        const id = idOf(row);
        return `<tr><td><div class="person">${esc(row.name || '未知联系人')}</div><div class="sub">${esc(row.time || '')}</div></td>` +
          `<td>${esc(row.company || '-')}<div class="sub">${esc(row.job_title || '-')}</div></td>` +
          `<td>${esc(row.preview || '-')}<div class="sub">${esc(row.salary || '')}</div></td>` +
          `<td><code>${esc(id)}</code></td>` +
          `<td><button class="small" data-id="${esc(id)}">保存</button></td></tr>`;
      }).join('');
      document.querySelectorAll('[data-id]').forEach((button) => button.addEventListener('click', () => archive(button.dataset.id)));
    }
    function renderArchive(payload) {
      const messages = payload.messages || [];
      $('runPath').textContent = payload.log_path ? `运行日志：${payload.log_path}` : '暂无运行记录';
      if (!messages.length) { $('archive').innerHTML = '<div class="empty">会话已保存，但当前没有可见消息</div>'; return; }
      $('archive').innerHTML = `<div class="sub" style="margin-bottom:8px">ID：<code>${esc(payload.conversation_id || '-')}</code></div>` +
        messages.map((message) => `<div class="message"><div class="message-meta">${esc(message.sender || 'system')} · ${esc(message.kind || 'text')} ${esc(message.timestamp || '')}</div>` +
          `<div class="${message.kind === 'action' ? 'message-action' : ''}">${esc(message.text || '')}</div></div>`).join('');
    }
    async function request(url, options={}) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `请求失败（${response.status}）`);
      return data;
    }
    async function refresh() {
      setStatus('正在读取消息列表…'); setBusy(true);
      try { const data = await request('/api/conversations'); renderRows(data.entries || []); setStatus(`已读取 ${data.entries.length} 个当前可见会话（未打开聊天）`, 'ok'); }
      catch (error) { setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    async function archive(conversationId) {
      if (!conversationId) { setStatus('没有可用的会话 ID', 'error'); return; }
      setStatus('正在打开并保存指定会话…'); setBusy(true);
      try { const data = await request('/api/conversations/archive', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({conversation_id:conversationId})}); renderArchive(data); setStatus('会话已保存', 'ok'); }
      catch (error) { setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    async function archiveCount() {
      const value = Number.parseInt($('count').value, 10);
      if (!value || value < 1) { setStatus('请输入大于 0 的会话数量', 'error'); return; }
      setStatus(`正在保存前 ${value} 个会话…`); setBusy(true);
      try { const data = await request('/api/conversations/archive', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({count:value})}); renderArchive(data); setStatus(`已完成 ${data.saved_count || 0} 个会话归档`, 'ok'); }
      catch (error) { setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    async function dashboard() {
      try { const data = await request('/api/dashboard'); $('todayMetric').textContent = `${data.applied_today} / ${data.daily_limit}`; $('runMetric').textContent = data.run_limit; $('versionMetric').textContent = data.version.version_name || '未记录'; const s = data.storage || {}; $('storageMetric').textContent = `会话 ${s.conversations || 0} · 消息 ${s.messages || 0}`; }
      catch (error) { setStatus(error.message, 'error'); }
    }
    async function health() {
      setStatus('正在检查设备…'); setBusy(true);
      try { const data = await request('/api/health'); const d = data.device || {}; $('deviceMetric').textContent = d.model || '已连接'; setStatus(`设备正常：Android ${d.android_version || '-'}，${d.window_size || '-'}`, 'ok'); $('runPath').textContent = `运行日志：${data.log_path}`; }
      catch (error) { $('deviceMetric').textContent = '异常'; setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    async function capture() {
      setStatus('正在保存当前截图与 UI Dump…'); setBusy(true);
      try { const data = await request('/api/capture', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); $('runPath').textContent = `截图：${data.screenshot_path} · Dump：${data.dump_path}`; setStatus('截图与 UI Dump 已保存', 'ok'); }
      catch (error) { setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    async function runBatch() {
      const limit = Number.parseInt($('applyLimit').value, 10);
      if (!limit || limit < 1 || limit > 100) { setStatus('沟通数量必须在 1 到 100 之间', 'error'); return; }
      if (!window.confirm(`将真实建立最多 ${limit} 个沟通。确认继续吗？`)) return;
      setStatus(`正在执行批量沟通（上限 ${limit}）…请勿关闭页面`); setBusy(true);
      try { const data = await request('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({limit, confirmation:'COMMUNICATE'})}); $('runPath').textContent = `运行日志：${data.log_path}`; setStatus(`执行完成：本次建立沟通 ${data.applied || 0} 个，今日累计 ${data.applied_today || 0} 个`, 'ok'); await dashboard(); }
      catch (error) { setStatus(error.message, 'error'); }
      finally { setBusy(false); }
    }
    $('refresh').addEventListener('click', refresh);
    $('archiveSelected').addEventListener('click', () => archive($('targetId').value.trim()));
    $('archiveCount').addEventListener('click', archiveCount);
    $('health').addEventListener('click', health);
    $('capture').addEventListener('click', capture);
    $('runBatch').addEventListener('click', runBatch);
    dashboard();
    refresh();
  </script>
</body>
</html>
"""


class WebOperationError(RuntimeError):
    """可安全显示给本地界面的业务错误。"""


@dataclass
class WebSettings:
    config_path: str = "config.yaml"
    logs_dir: str = "logs"


class ConversationWebService:
    """把浏览器请求转换为一次次串行的设备操作。"""

    def __init__(
        self,
        settings: Optional[WebSettings] = None,
        *,
        device_factory: Optional[Callable[[str, logging.Logger], Any]] = None,
        list_page_factory: Callable[..., ConversationListPage] = ConversationListPage,
        chat_page_factory: Callable[..., ChatPage] = ChatPage,
    ):
        self.settings = settings or WebSettings()
        self._device_factory = device_factory
        self._list_page_factory = list_page_factory
        self._chat_page_factory = chat_page_factory
        self._lock = threading.Lock()
        self._active_recorder: Optional[Recorder] = None

    @staticmethod
    def _default_device_factory(serial: str, log: logging.Logger) -> Any:
        from .device import connect

        return connect(serial, log)

    def _run(
        self,
        callback: Callable[
            [AppConfig, Any, logging.Logger, RunArtifacts], Dict[str, Any]
        ],
        *,
        ensure_application: bool = True,
    ) -> Dict[str, Any]:
        """取得进程内锁、运行归档和设备锁后执行一个动作。"""
        with self._lock:
            artifacts: Optional[RunArtifacts] = None
            recorder: Optional[Recorder] = None
            logger_ready = False
            result: Dict[str, Any] = {}
            run_status = "completed"
            try:
                artifacts = RunArtifacts.create(self.settings.logs_dir)
                log = setup_logger(artifacts=artifacts)
                logger_ready = True
                cfg = load_config(self.settings.config_path)
                if cfg.safety.records_db:
                    recorder = Recorder(
                        cfg.safety.records_db,
                        run_id=artifacts.run_id,
                        source="web",
                        log_path=str(artifacts.log_path),
                    )
                    self._active_recorder = recorder
                    log.info("运行数据 SQLite: %s", cfg.safety.records_db)
                factory = self._device_factory or self._default_device_factory
                device = factory(cfg.serial, log)
                from .device import ensure_app, record_app_version, version_values_changed

                baseline = None
                try:
                    baseline_value = json.loads(
                        Path(cfg.safety.app_version_path).read_text(encoding="utf-8")
                    )
                    if isinstance(baseline_value, dict):
                        baseline = baseline_value
                except (OSError, ValueError, TypeError):
                    pass
                version = record_app_version(
                    device, cfg.package, cfg.safety.app_version_path, log
                )
                if version and version_values_changed(baseline, version):
                    record_observation(
                        recorder,
                        "apk_version",
                        str(version.get("package", cfg.package) or cfg.package),
                        version,
                        run_id=artifacts.run_id,
                        log=log,
                    )
                if ensure_application:
                    ensure_app(device, cfg.package, log)
                result = callback(cfg, device, log, artifacts) or {}
                result["ok"] = bool(result.get("ok", True))
                if not result["ok"]:
                    run_status = "error"
                result["run_id"] = artifacts.run_id
                result["log_path"] = str(artifacts.log_path)
                return result
            except RunInProgressError as exc:
                run_status = "error"
                return {"ok": False, "busy": True, "error": str(exc)}
            except Exception as exc:
                run_status = "error"
                result = {
                    "ok": False,
                    "error": str(exc) or exc.__class__.__name__,
                }
                if artifacts is not None:
                    result["run_id"] = artifacts.run_id
                    result["log_path"] = str(artifacts.log_path)
                return result
            finally:
                # close_logger 会关闭文件 handler 并释放其关联的 RunArtifacts；
                # 没有成功安装 logger 时，再由显式 close 兜底。
                if recorder is not None:
                    recorder.close(status=run_status)
                self._active_recorder = None
                if logger_ready:
                    close_logger()
                if artifacts is not None and getattr(
                    artifacts, "_run_lock_handle", None
                ) is not None:
                    artifacts.close()

    def list_conversations(self) -> Dict[str, Any]:
        def action(
            cfg: AppConfig,
            device: Any,
            log: logging.Logger,
            artifacts: RunArtifacts,
        ) -> Dict[str, Any]:
            page = self._list_page_factory(device, cfg.timing, log, artifacts)
            if not page.open_list():
                raise WebOperationError("无法打开 Boss 消息列表")
            visible = page.visible()
            for entry in visible:
                save_conversation(
                    self._active_recorder,
                    entry,
                    run_id=artifacts.run_id,
                    source="list",
                    include_messages=False,
                    log=log,
                )
            entries = [entry.as_dict() for entry in visible]
            return {"entries": entries, "opened": False}

        return self._run(action)

    def dashboard(self) -> Dict[str, Any]:
        """读取本地状态，不连接设备也不取得设备运行锁。"""
        try:
            cfg = load_config(self.settings.config_path)
            state = State(cfg.safety.state_path, read_only=True)
            storage: Dict[str, Any] = {
                "path": cfg.safety.records_db,
                "runs": 0,
                "records": 0,
                "jobs": 0,
                "conversations": 0,
                "messages": 0,
                "observations": 0,
            }
            # dashboard 是只读接口，不通过 Recorder 打开可写连接；这样即使
            # 用户只查看页面，也不会创建/修改 SQLite 文件。
            if cfg.safety.records_db and Path(cfg.safety.records_db).exists():
                try:
                    conn = sqlite3.connect(
                        f"file:{Path(cfg.safety.records_db).resolve()}?mode=ro",
                        uri=True,
                        timeout=1.0,
                    )
                    try:
                        for table in (
                            "runs",
                            "records",
                            "jobs",
                            "conversations",
                            "messages",
                            "observations",
                        ):
                            try:
                                storage[table] = int(
                                    conn.execute(
                                        f"SELECT COUNT(*) FROM {table}"
                                    ).fetchone()[0]
                                )
                            except sqlite3.Error:
                                # 旧数据库可能尚未完成迁移，单表缺失不影响
                                # 页面其余状态显示。
                                storage[table] = 0
                    finally:
                        conn.close()
                except (OSError, sqlite3.Error):
                    pass
            version: Dict[str, Any] = {}
            try:
                value = json.loads(
                    Path(cfg.safety.app_version_path).read_text(encoding="utf-8")
                )
                if isinstance(value, dict):
                    version = value
            except (OSError, ValueError, TypeError):
                pass
            return {
                "ok": True,
                "applied_today": state.applied_today,
                "daily_limit": cfg.limits.max_apply_per_day,
                "run_limit": cfg.limits.max_apply_per_run,
                "package": cfg.package,
                "version": version,
                "storage": storage,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}

    def device_health(self) -> Dict[str, Any]:
        def action(
            cfg: AppConfig,
            device: Any,
            log: logging.Logger,
            artifacts: RunArtifacts,
        ) -> Dict[str, Any]:
            from .device import health

            info = health(device, cfg.package)
            record_observation(
                self._active_recorder,
                "device_health",
                str(info.get("package", "") or ""),
                info,
                run_id=artifacts.run_id,
                log=log,
            )
            log.info(
                "可视化界面设备检查: package=%s android=%s model=%s",
                info.get("package", "?"),
                info.get("android_version", "?"),
                info.get("model", "?"),
            )
            return {"device": info}

        return self._run(action, ensure_application=False)

    def run_batch(self, limit: Any, confirmation: str = "") -> Dict[str, Any]:
        """执行明确确认过的批量沟通。"""
        if confirmation != "COMMUNICATE":
            return {"ok": False, "error": "批量沟通需要明确确认"}
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return {"ok": False, "error": "沟通数量必须是整数"}
        if not 1 <= limit <= 100:
            return {"ok": False, "error": "沟通数量必须在 1 到 100 之间"}

        def action(
            cfg: AppConfig,
            device: Any,
            log: logging.Logger,
            artifacts: RunArtifacts,
        ) -> Dict[str, Any]:
            from .engine import ApplyEngine

            cfg.limits.max_apply_per_run = limit
            # 浏览器已经显式二次确认，不能在无终端的 Web 进程中调用 input()。
            cfg.safety.confirm_before_apply = False
            state = State(cfg.safety.state_path)
            engine = ApplyEngine(
                device,
                cfg,
                state,
                log,
                artifacts=artifacts,
                recorder=self._active_recorder,
            )
            applied = engine.run()
            return {
                "applied": applied,
                "summary": asdict(engine.last_summary),
                "applied_today": state.applied_today,
            }

        return self._run(action)

    def capture_screen(self) -> Dict[str, Any]:
        """保存当前设备截图和 UI dump，供界面快速诊断。"""
        def action(
            cfg: AppConfig,
            device: Any,
            log: logging.Logger,
            artifacts: RunArtifacts,
        ) -> Dict[str, Any]:
            dump_path = artifacts.save_dump(device, "dump.xml")
            screenshot_path = artifacts.save_screenshot(device, "screenshot.png")
            record_observation(
                self._active_recorder,
                "capture",
                artifacts.run_id,
                {"dump_path": dump_path, "screenshot_path": screenshot_path},
                run_id=artifacts.run_id,
                log=log,
            )
            log.info("界面诊断已保存: %s, %s", dump_path, screenshot_path)
            return {"dump_path": dump_path, "screenshot_path": screenshot_path}

        return self._run(action)

    @staticmethod
    def _archive_payloads(directory: Path) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(value, dict) and "messages" in value:
                value["archive_path"] = str(path)
                payloads.append(value)
        return payloads

    def archive_conversations(
        self,
        conversation_id: str = "",
        count: Optional[int] = None,
        max_scrolls: int = 8,
    ) -> Dict[str, Any]:
        conversation_id = str(conversation_id or "").strip()

        if not conversation_id and count is None:
            return {"ok": False, "error": "请选择会话或填写归档数量"}
        if count is not None:
            try:
                count = int(count)
            except (TypeError, ValueError):
                return {"ok": False, "error": "会话数量必须是整数"}
            if count < 1:
                return {"ok": False, "error": "会话数量必须大于 0"}
        try:
            max_scrolls = max(0, int(max_scrolls))
        except (TypeError, ValueError):
            return {"ok": False, "error": "最大滚动次数必须是整数"}

        def action(
            cfg: AppConfig,
            device: Any,
            log: logging.Logger,
            artifacts: RunArtifacts,
        ) -> Dict[str, Any]:
            listing = self._list_page_factory(device, cfg.timing, log, artifacts)
            chat = self._chat_page_factory(device, cfg.timing, log, artifacts)
            args = SimpleNamespace(
                op="conversations",
                conversation_id=conversation_id,
                list_only=False,
                count=count,
                max_scrolls=max_scrolls,
                name="",
            )
            ctx = OperationContext(
                args=args,
                cfg=cfg,
                log=log,
                device=device,
                chat=chat,
                conversations=listing,
                artifacts=artifacts,
                recorder=self._active_recorder,
            )
            code = run_operation(ctx)
            payloads = self._archive_payloads(artifacts.directory)
            result: Dict[str, Any] = {
                "code": code,
                "saved_count": len(payloads),
                "archives": payloads,
            }
            if payloads:
                result.update(payloads[-1])
            if code != 0:
                result["ok"] = False
                result["error"] = "未找到目标会话，或会话归档失败"
            return result

        return self._run(action)

    def archives(self, limit: int = 20) -> Dict[str, Any]:
        """读取最近归档；纯文件读取，不连接设备。"""
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 20
        rows: List[Dict[str, Any]] = []
        base = Path(self.settings.logs_dir)
        for path in sorted(base.glob("*/*_conversation*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            rows.append(
                {
                    "conversation_id": payload.get("conversation_id", ""),
                    "message_count": len(payload.get("messages") or []),
                    "path": str(path),
                }
            )
            if len(rows) >= limit:
                break
        return {"ok": True, "archives": rows}


class _RequestHandler(BaseHTTPRequestHandler):
    """将 HTTP 路由绑定到单个服务实例。"""

    service: ConversationWebService

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
        # 浏览器请求不污染运行日志；设备操作日志由 setup_logger 记录。
        return

    def _send(
        self,
        payload: Any,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        if isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._send({"ok": False, "error": message}, status=status)

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            self._send(INDEX_HTML, content_type="text/html; charset=utf-8")
            return
        if route == "/api/conversations":
            result = self.service.list_conversations()
            status = 409 if result.get("busy") else (200 if result.get("ok") else 500)
            self._send(result, status=status)
            return
        if route == "/api/dashboard":
            result = self.service.dashboard()
            self._send(result, status=200 if result.get("ok") else 500)
            return
        if route == "/api/health":
            result = self.service.device_health()
            status = 409 if result.get("busy") else (200 if result.get("ok") else 500)
            self._send(result, status=status)
            return
        if route == "/api/archives":
            self._send(self.service.archives())
            return
        self._error("找不到页面", status=404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 64 * 1024:
                raise ValueError("请求体过大")
            raw = self.rfile.read(max(0, size))
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, Mapping):
                raise ValueError("请求必须是 JSON 对象")
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            self._error(f"请求参数错误: {exc}")
            return
        if route == "/api/conversations/archive":
            result = self.service.archive_conversations(
                conversation_id=str(
                    body.get("conversation_id", body.get("id", "")) or ""
                ),
                count=body.get("count"),
                max_scrolls=body.get("max_scrolls", 8),
            )
        elif route == "/api/run":
            result = self.service.run_batch(
                body.get("limit"), str(body.get("confirmation", ""))
            )
        elif route == "/api/capture":
            result = self.service.capture_screen()
        else:
            self._error("不支持的操作", status=404)
            return
        status = 409 if result.get("busy") else (200 if result.get("ok") else 400)
        self._send(result, status=status)


class _SingleRequestHTTPServer(HTTPServer):
    allow_reuse_address = True


def make_handler(service: ConversationWebService):
    """为测试或自定义服务器创建绑定服务的 handler 类。"""
    return type("ConversationRequestHandler", (_RequestHandler,), {"service": service})


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    config_path: str = "config.yaml",
    logs_dir: str = "logs",
    open_browser: bool = True,
) -> None:
    """启动本地 Web UI，直到 Ctrl-C。"""
    if not 0 < int(port) < 65536:
        raise RuntimeError("端口必须在 1 到 65535 之间")
    service = ConversationWebService(
        WebSettings(config_path=config_path, logs_dir=logs_dir)
    )
    try:
        server = _SingleRequestHTTPServer((host, int(port)), make_handler(service))
    except OSError as exc:
        raise RuntimeError(f"无法监听 {host}:{port}: {exc}") from exc
    address = server.server_address
    url = f"http://{address[0]}:{address[1]}/"
    print(f"Boss Helper 可视化界面: {url}")
    print("按 Ctrl-C 停止服务；设备操作仍会严格串行执行。")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n正在停止可视化界面…")
    finally:
        server.server_close()


__all__ = [
    "ConversationWebService",
    "INDEX_HTML",
    "WebOperationError",
    "WebSettings",
    "make_handler",
    "serve",
]
