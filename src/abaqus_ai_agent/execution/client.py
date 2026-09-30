import json
import socket
from abc import ABC, abstractmethod

from .errors import AbaqusConnectionError, AbaqusExecutionError


class AbaqusExecutor(ABC):
    """Stable execution boundary. Implementations may use socket/file IPC."""

    @abstractmethod
    def execute(self, code, timeout=120):
        raise NotImplementedError

    def ping(self):
        return self.execute("print('ABAQUS_AI_AGENT_PING')")


class BridgeExecutor(AbaqusExecutor):
    """JSON-over-TCP executor compatible with the live Abaqus bridge contract.

    The wire request is deliberately small: {type: 'execute', code: ...}.
    Response shapes are normalized without assuming a particular MCP client.
    """
    def __init__(self, host="127.0.0.1", port=48152, timeout=120):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)

    def _request(self, payload, timeout=None):
        timeout = self.timeout if timeout is None else float(timeout)
        raw = (json.dumps(payload, separators=(",", ":")) + "\\n").encode("utf-8")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            raise AbaqusConnectionError("cannot connect to Abaqus bridge: %s" % exc) from exc
        try:
            sock.settimeout(timeout)
            sock.sendall(raw)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\\n" in chunk:
                    break
        except OSError as exc:
            raise AbaqusConnectionError("Abaqus bridge I/O failed: %s" % exc) from exc
        finally:
            sock.close()
        data = b"".join(chunks).strip()
        if not data:
            raise AbaqusExecutionError("Abaqus bridge returned an empty response")
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as exc:
            raise AbaqusExecutionError("Abaqus bridge returned invalid JSON: %r" % data[:200]) from exc

    def execute(self, code, timeout=120):
        result = self._request({"type": "execute", "code": code}, timeout)
        if isinstance(result, dict) and result.get("ok") is False:
            raise AbaqusExecutionError(result.get("error", "Abaqus execution failed"), payload=result)
        return result

    def ping(self):
        return self._request({"type": "ping"}, self.timeout)


class InProcessExecutor(AbaqusExecutor):
    """Testing adapter; executes code through an injected callable."""
    def __init__(self, runner):
        self.runner = runner

    def execute(self, code, timeout=120):
        return self.runner(code)
