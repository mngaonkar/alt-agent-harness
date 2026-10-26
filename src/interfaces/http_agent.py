"""SHAP v0.1 HTTP server. Wraps Session like repl.py does.

Imports only Session (and Turn) — same contract as repl.py. The agent loop,
tools, and config are never touched directly.

Endpoints:
  GET  /agent-card              public
  POST /tasks                   Bearer auth
  GET  /tasks/{task_id}         Bearer auth
  GET  /tasks/{task_id}/events  Bearer auth   poll: events collected so far
  GET  /tasks/{task_id}/events/stream  Bearer auth   SSE: live event stream
  GET  /artifacts/{task_id}/{name}  Bearer auth

v0.1: sequential execution, no cancel, URL-only artifacts from a locally
mounted shared filesystem, fixed Bearer token.
"""

import json
import mimetypes
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

from agent.session import Session, Turn


# ---------------------------------------------------------------------------
# Task record & runner
# ---------------------------------------------------------------------------

class TaskRecord:
    """State for one delegated task."""

    def __init__(self, task_id, task_type, input_data):
        self.task_id = task_id
        self.task_type = task_type
        self.input = input_data
        self.status = "accepted"  # accepted | working | completed | failed
        self.result = None
        self.events = []
        self.created_at = time.time()
        self.completed_at = None


class TaskRunner:
    """Sequential task runner: single worker thread, FIFO queue.

    One task runs to completion before the next starts. No parallel execution.
    """

    def __init__(self, session, shared_fs_path, base_url):
        self.session = session
        self.shared_fs_path = Path(shared_fs_path)
        self.base_url = base_url
        self.queue = queue.Queue()
        self.tasks = {}  # task_id -> TaskRecord
        self._current = None  # TaskRecord currently being executed
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        # Subscribe once; events are routed to the currently-running task.
        self.session.subscribe(self._on_event)

    def _on_event(self, kind, text):
        if self._current is not None:
            self._current.events.append(
                {"kind": kind, "text": text, "ts": time.time()}
            )

    def submit(self, task_id, task_type, input_data):
        record = TaskRecord(task_id, task_type, input_data)
        self.tasks[task_id] = record
        self.queue.put(record)
        return record

    def _run(self):
        while True:
            record = self.queue.get()
            self._execute(record)

    def _execute(self, record):
        record.status = "working"
        self._current = record
        try:
            output_dir = self.shared_fs_path / "output" / record.task_id
            output_dir.mkdir(parents=True, exist_ok=True)

            text = self._build_prompt(record)
            # Per-task isolation: clear conversation history.
            self.session.reset()
            turn = self.session.submit(text)

            text_result = turn.text if turn.kind in ("reply", "status") else ""
            artifacts = self._scan_artifacts(output_dir, record.task_id)

            if artifacts and text_result:
                result_type = "text_and_artifact"
            elif artifacts:
                result_type = "artifact"
            else:
                result_type = "text"

            record.result = {
                "type": result_type,
                "text": text_result or None,
                "artifact": artifacts[0] if len(artifacts) == 1 else None,
                "artifacts": artifacts if len(artifacts) > 1 else None,
            }
            record.status = "completed"
        except Exception as exc:
            record.result = {
                "type": "text",
                "text": "Error: %s" % exc,
                "artifact": None,
            }
            record.status = "failed"
        finally:
            record.completed_at = time.time()
            self._current = None

    def _build_prompt(self, record):
        """Compose the prompt, injecting the output directory for artifacts."""
        input_data = record.input
        text = input_data.get("text", "")
        output_dir = self.shared_fs_path / "output" / record.task_id
        prompt = text
        prompt += "\n\nWrite any output files to: %s/" % output_dir
        return prompt

    def _scan_artifacts(self, output_dir, task_id):
        """Scan the task's output directory for produced files."""
        artifacts = []
        if not output_dir.exists():
            return artifacts
        for f in sorted(output_dir.iterdir()):
            if f.is_file():
                mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                artifacts.append({
                    "id": "%s/%s" % (task_id, f.name),
                    "mime_type": mime,
                    "name": f.name,
                    "url": "%s/artifacts/%s/%s" % (self.base_url, task_id, f.name),
                    "bytes": f.stat().st_size,
                })
        return artifacts


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class SHAPHandler(BaseHTTPRequestHandler):
    # Set by run() before the server starts.
    runner = None
    agent_card = None
    token = ""
    require_auth = True
    base_url = ""

    def log_message(self, fmt, *args):
        print("[http] %s" % (fmt % args))

    # -- helpers ----------------------------------------------------------

    def _send_json(self, status, body):
        data = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status, code, message, details=None):
        self._send_json(status, {
            "error": {"code": code, "message": message, "details": details or {}},
        })

    def _check_auth(self):
        if not self.require_auth:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == "Bearer " + self.token:
            return True
        self._send_error(401, "unauthorized", "Missing or invalid Bearer token.")
        return False

    def _stream_events(self, record):
        """Stream the task's events as Server-Sent Events.

        Sends each event as it arrives, then a final 'done' event once the
        task reaches a terminal state, then closes the connection.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.write(b": stream open\n\n")
        self.wfile.flush()

        sent = 0
        try:
            while True:
                events = list(record.events)
                for ev in events[sent:]:
                    payload = json.dumps(
                        {"kind": ev["kind"], "text": ev["text"], "ts": ev["ts"]})
                    self.wfile.write(("data: %s\n\n" % payload).encode())
                sent = len(events)
                self.wfile.flush()

                if record.status in ("completed", "failed"):
                    self.wfile.write(
                        ("data: %s\n\n" % json.dumps(
                            {"kind": "done", "status": record.status})).encode())
                    self.wfile.flush()
                    break
                time.sleep(0.2)
        except OSError:
            pass  # client disconnected

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/agent-card":
            self._send_json(200, self.agent_card)
            return

        if path.startswith("/tasks/"):
            if not self._check_auth():
                return
            rest = unquote(path[len("/tasks/"):])
            if rest.endswith("/events/stream"):
                task_id = rest[: -len("/events/stream")]
                record = self.runner.tasks.get(task_id)
                if record is None:
                    self._send_error(404, "not_found", "No task with id %s" % task_id)
                    return
                self._stream_events(record)
                return
            if rest.endswith("/events"):
                task_id = rest[: -len("/events")]
                record = self.runner.tasks.get(task_id)
                if record is None:
                    self._send_error(404, "not_found", "No task with id %s" % task_id)
                    return
                self._send_json(200, {
                    "task_id": record.task_id,
                    "status": record.status,
                    "events": record.events,
                })
                return
            task_id = rest
            record = self.runner.tasks.get(task_id)
            if record is None:
                self._send_error(404, "not_found", "No task with id %s" % task_id)
                return
            self._send_json(200, {
                "task_id": record.task_id,
                "status": record.status,
                "result": record.result,
                "events_url": "%s/tasks/%s/events" % (self.base_url, task_id),
                "stream_url": "%s/tasks/%s/events/stream" % (self.base_url, task_id),
            })
            return

        if path.startswith("/artifacts/"):
            if not self._check_auth():
                return
            parts = unquote(path[len("/artifacts/"):]).split("/", 1)
            if len(parts) != 2:
                self._send_error(404, "not_found", "Invalid artifact path.")
                return
            task_id, filename = parts
            record = self.runner.tasks.get(task_id)
            if record is None:
                self._send_error(404, "not_found", "No task with id %s" % task_id)
                return
            file_path = self.runner.shared_fs_path / "output" / task_id / filename
            if not file_path.is_file():
                self._send_error(404, "not_found", "Artifact not found.")
                return
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._send_error(404, "not_found", "Unknown endpoint.")

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/tasks":
            if not self._check_auth():
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                self._send_error(400, "invalid_request", "Malformed JSON body.")
                return
            task_id = data.get("task_id") or str(uuid.uuid4())
            task_type = data.get("type", "general")
            input_data = data.get("input", {})
            self.runner.submit(task_id, task_type, input_data)
            self._send_json(202, {
                "task_id": task_id,
                "status": "accepted",
                "status_url": "%s/tasks/%s" % (self.base_url, task_id),
                "events_url": "%s/tasks/%s/events" % (self.base_url, task_id),
                "stream_url": "%s/tasks/%s/events/stream" % (self.base_url, task_id),
                "result": None,
            })
            return

        self._send_error(404, "not_found", "Unknown endpoint.")


# ---------------------------------------------------------------------------
# Agent card
# ---------------------------------------------------------------------------

def build_agent_card(session, base_url):
    cfg = session.cfg
    return {
        "name": cfg.get("agent_name", "alt-agent"),
        "version": "0.1.0",
        "description": cfg.get(
            "agent_description",
            "General-purpose AI agent with tool and skill support.",
        ),
        "url": base_url,
        "capabilities": {
            "tasks": ["general"],
            "result_types": ["text", "artifact"],
            "artifact_types": ["application/octet-stream"],
            "max_artifact_bytes": 10485760,
            "events": ["tool", "error", "status"],
            "event_stream": "sse",
        },
        "auth": {"type": "bearer"},
        "contact": cfg.get("agent_contact", ""),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _local_ip():
    """Best-effort local LAN IP (the address other hosts would use)."""
    import socket
    for target in ("8.8.8.8", "1.1.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            continue
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def run(session: Session):
    """Start the SHAP HTTP server. Blocks until Ctrl-C."""
    cfg = session.cfg
    shared_fs_path = cfg.get("shared_fs_path", "/mnt/shared")
    token = cfg.get("agent_token", "")
    bind_host = cfg.get("serve_host", "0.0.0.0")
    port = int(cfg.get("serve_port", 8765))
    # When binding to 0.0.0.0 (all interfaces), advertise the machine's real
    # IP in URLs so remote clients can reach them. The server still binds to
    # 0.0.0.0; only the advertised host differs.
    if bind_host in ("0.0.0.0", "::"):
        host = _local_ip()
    else:
        host = bind_host
    base_url = "http://%s:%d" % (host, port)

    # Loopback binds may omit the token.
    require_auth = host not in ("127.0.0.1", "localhost", "::1")
    if not token:
        if require_auth:
            token = uuid.uuid4().hex
            print("[http] WARNING: no agent_token in config; generated ephemeral token: %s" % token)
        else:
            token = "shap-dev"

    runner = TaskRunner(session, shared_fs_path, base_url)
    card = build_agent_card(session, base_url)

    SHAPHandler.runner = runner
    SHAPHandler.agent_card = card
    SHAPHandler.token = token
    SHAPHandler.require_auth = require_auth
    SHAPHandler.base_url = base_url

    server = ThreadingHTTPServer((bind_host, port), SHAPHandler)
    print("[http] SHAP server on %s" % base_url)
    print("[http]   auth:        %s" % ("required" if require_auth else "loopback-exempt"))
    print("[http]   shared_fs:   %s" % shared_fs_path)
    print("[http]   token:       %s" % ("set" if token else "(none)"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[http] shutting down")
    finally:
        server.server_close()
