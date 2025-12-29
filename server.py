import asyncio
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

from aiohttp import web


PID_FILE = "./bot_worker.pid"
WORKER_CMD = ["python3", "main.py"]
WORKER_CWD = os.getcwd()  # 可改成 main.py 所在目录


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # 不发信号，仅检查
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 没权限但说明存在
        return True


def _read_pidfile() -> Optional[int]:
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        return pid
    except Exception:
        return None


def _write_pidfile(pid: int) -> None:
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))


def _remove_pidfile() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


@dataclass
class WorkerState:
    pid: Optional[int] = None
    started_at: Optional[float] = None
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None


class WorkerController:
    def __init__(self) -> None:
        self.state = WorkerState()
        self._lock = asyncio.Lock()

        # 尝试从 pidfile 恢复状态
        pid = _read_pidfile()
        if pid and _pid_is_running(pid):
            self.state.pid = pid
            # started_at 无法准确恢复（可选：写 metadata 文件）
        else:
            _remove_pidfile()

    def status(self) -> Dict[str, Any]:
        pid = self.state.pid
        running = bool(pid) and _pid_is_running(pid)
        if pid and not running:
            # pidfile 存在但进程没了
            self.state.pid = None
            _remove_pidfile()
        return {
            "ok": True,
            "running": running,
            "pid": pid if running else None,
            "started_at": self.state.started_at,
            "last_exit_code": self.state.last_exit_code,
            "last_error": self.state.last_error,
            "pidfile": os.path.abspath(PID_FILE),
            "cmd": WORKER_CMD,
        }

    async def start(self, *, enable: bool = True) -> Dict[str, Any]:
        async with self._lock:
            if not enable:
                return {"ok": True, **self.status(), "msg": "enable=false, not starting"}

            st = self.status()
            if st["running"]:
                return {"ok": True, **st, "msg": "already running"}

            try:
                # 启动子进程：独立进程组，方便 stop 时杀整组（包含子进程）
                p = subprocess.Popen(
                    WORKER_CMD,
                    cwd=WORKER_CWD,
                    stdout=None,  # 默认继承；也可改成文件
                    stderr=None,
                    preexec_fn=os.setsid,  # 新进程组（Linux）
                )
                self.state.pid = p.pid
                self.state.started_at = time.time()
                self.state.last_exit_code = None
                self.state.last_error = None
                _write_pidfile(p.pid)
                return {"ok": True, **self.status(), "msg": "started"}
            except Exception as e:
                self.state.last_error = repr(e)
                return {"ok": False, **self.status(), "msg": f"start failed: {e!r}"}

    async def stop(self, *, timeout_sec: float = 8.0) -> Dict[str, Any]:
        async with self._lock:
            st = self.status()
            if not st["running"]:
                return {"ok": True, **st, "msg": "already stopped"}

            pid = st["pid"]
            assert pid is not None

            try:
                # 给进程组发 SIGTERM
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                self.state.pid = None
                _remove_pidfile()
                return {"ok": True, **self.status(), "msg": "already exited"}
            except Exception as e:
                self.state.last_error = repr(e)
                return {"ok": False, **self.status(), "msg": f"stop failed: {e!r}"}

            # 等待退出
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if not _pid_is_running(pid):
                    self.state.pid = None
                    _remove_pidfile()
                    return {"ok": True, **self.status(), "msg": "stopped (SIGTERM)"}
                await asyncio.sleep(0.2)

            # 超时强杀
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

            await asyncio.sleep(0.2)
            self.state.pid = None
            _remove_pidfile()
            return {"ok": True, **self.status(), "msg": "killed (SIGKILL)"}


# ---------- HTTP Handlers ----------

async def handle_start(request: web.Request) -> web.Response:
    ctl: WorkerController = request.app["ctl"]

    # 允许 query 参数控制：/start?enable=true
    enable = request.query.get("enable", "true").lower() in ("1", "true", "yes", "on")

    # 也支持 JSON body：{"enable": true}
    if request.can_read_body and request.content_type == "application/json":
        try:
            body = await request.json()
            if "enable" in body:
                enable = bool(body["enable"])
        except Exception:
            pass

    res = await ctl.start(enable=enable)
    return web.json_response(res)

async def handle_stop(request: web.Request) -> web.Response:
    ctl: WorkerController = request.app["ctl"]

    timeout = request.query.get("timeout", None)
    timeout_sec = float(timeout) if timeout else 8.0

    res = await ctl.stop(timeout_sec=timeout_sec)
    return web.json_response(res)

async def handle_status(request: web.Request) -> web.Response:
    ctl: WorkerController = request.app["ctl"]
    return web.json_response(ctl.status())

def create_app() -> web.Application:
    app = web.Application()
    app["ctl"] = WorkerController()
    app.router.add_post("/start", handle_start)
    app.router.add_post("/stop", handle_stop)
    app.router.add_get("/status", handle_status)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=9689)
