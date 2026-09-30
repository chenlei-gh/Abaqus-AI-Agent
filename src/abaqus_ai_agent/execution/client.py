import json
import socket
import uuid
from abc import ABC, abstractmethod

from .errors import AbaqusConnectionError, AbaqusExecutionError, classify_execution_error, recovery_hint


class AbaqusExecutor(ABC):
    @abstractmethod
    def execute(self, code, timeout=120):
        raise NotImplementedError

    def ping(self):
        return self.execute("print('ABAQUS_AI_AGENT_PING')")

    def inspect_model(self):
        from .inspection import get_model_info
        return get_model_info(self)

    def capture_viewport(self, path="abaqus_viewport.png"):
        from .inspection import capture_viewport
        return capture_viewport(self)

    def inspect_odb(self, path):
        from .odb import inspect_odb
        return inspect_odb(self)

    def snapshot(self):
        from .snapshot import read_model_snapshot
        return read_model_snapshot(self)

    def runtime_info(self):
        from .runtime import detect_runtime
        return detect_runtime(self)

    def viewport_state(self):
        from .inspection import viewport_state
        return viewport_state(self)

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        # Native fallback: block until Abaqus reports job completion.
        return self.execute("mdb.jobs[%r].waitForCompletion(); print(mdb.jobs[%r].status)" % (name, name), timeout=timeout)


class BridgeExecutor(AbaqusExecutor):
    """Line-delimited JSON client for a compatible local Abaqus bridge."""
    def __init__(self, host="127.0.0.1", port=48152, timeout=120):
        self.host, self.port, self.timeout = host, int(port), float(timeout)

    def _request(self, method, params=None, timeout=None):
        timeout = self.timeout if timeout is None else float(timeout)
        request_id = str(uuid.uuid4())
        params = dict(params or {})
        params.setdefault("timeout", timeout)
        params.setdefault("executionId", request_id)
        payload = {"id": request_id, "method": method, "params": params}
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            sock.settimeout(timeout + 10.0)
        except OSError as exc:
            raise AbaqusConnectionError("cannot connect to Abaqus bridge: %s" % exc) from exc
        try:
            sock.sendall(raw)
            chunks, total = [], 0
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise AbaqusConnectionError("bridge closed before a complete response")
                pos = chunk.find(b"\n")
                if pos >= 0:
                    chunks.append(chunk[:pos]); total += pos; break
                chunks.append(chunk); total += len(chunk)
                if total > 16 * 1024 * 1024:
                    raise AbaqusExecutionError("bridge response exceeded 16 MiB")
            response = json.loads(b"".join(chunks).decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise AbaqusExecutionError("Abaqus bridge protocol failure: %s" % exc) from exc
        finally:
            sock.close()
        if response.get("id") != request_id:
            raise AbaqusExecutionError("Abaqus bridge returned a mismatched response id", payload=response)
        if not response.get("ok", False):
            error = response.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            details = error if isinstance(error, dict) else {}
            raise AbaqusExecutionError(
                message or "Abaqus bridge execution failed",
                payload=response,
                category=classify_execution_error(message, response),
                traceback=details.get("traceback"),
                source_line=details.get("source_line"),
                code_excerpt=details.get("code_excerpt"),
                context=details.get("context"),
                recovery_hint=details.get("recovery_hint") or recovery_hint(classify_execution_error(message, response)),
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise AbaqusExecutionError("Abaqus bridge returned an invalid result envelope", payload=response)
        return result

    def execute(self, code, timeout=120):
        return self._request("execute", {"code": code}, timeout)

    def ping(self):
        return self._request("ping", {}, self.timeout)

    def inspect_model(self):
        return self._request("model_info", {}, self.timeout)

    def capture_viewport(self, path="abaqus_viewport.png"):
        return self._request("capture_viewport", {"path": path}, self.timeout)

    def inspect_odb(self, path):
        return self._request("inspect_odb", {"path": path}, self.timeout)

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        return self._request("monitor_job_status", {
            "jobName": name, "timeout": timeout, "pollInterval": poll_seconds
        }, timeout)


class InProcessExecutor(AbaqusExecutor):
    def __init__(self, runner):
        self.runner = runner

    def execute(self, code, timeout=120):
        return self.runner(code)
