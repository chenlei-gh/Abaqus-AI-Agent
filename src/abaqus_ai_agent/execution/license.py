import os
import re
import time
import uuid
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class LicenseHealthStatus:
    healthy: bool
    server: str
    available_tokens: int
    total_tokens: int
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "server": self.server,
            "available_tokens": self.available_tokens,
            "total_tokens": self.total_tokens,
            "details": dict(self.details),
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class LicenseHandle:
    handle_id: str
    feature: str
    tokens: int
    provider_name: str
    granted_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handle_id": self.handle_id,
            "feature": self.feature,
            "tokens": self.tokens,
            "provider_name": self.provider_name,
            "granted_at": self.granted_at,
            "metadata": dict(self.metadata),
        }


class _LicenseContext:
    def __init__(self, provider: "LicenseProvider", feature: str, tokens: int, timeout: float):
        self.provider = provider
        self.feature = feature
        self.tokens = tokens
        self.timeout = timeout
        self.handle: Optional[LicenseHandle] = None

    def __enter__(self) -> LicenseHandle:
        self.handle = self.provider.reserve(feature=self.feature, tokens=self.tokens, timeout=self.timeout)
        if self.handle is None:
            raise TimeoutError(
                f"Failed to acquire {self.tokens} tokens for feature '{self.feature}' "
                f"from {self.provider.__class__.__name__} within {self.timeout}s timeout"
            )
        return self.handle

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle is not None:
            self.provider.release(self.handle)
            self.handle = None


class LicenseProvider(ABC):
    """Abstract vendor-neutral license management provider.
    
    Prevents hardcoding licensing CLI commands (lmutil, dslsstat) in high-level orchestration.
    """

    @abstractmethod
    def available_tokens(self, feature: str = "standard") -> int:
        """Query currently available unallocated tokens for a given feature."""
        pass

    @abstractmethod
    def reserve(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> Optional[LicenseHandle]:
        """Attempt to reserve tokens, waiting up to `timeout` seconds. Returns None on exhaustion/timeout."""
        pass

    @abstractmethod
    def release(self, handle: LicenseHandle) -> bool:
        """Release previously reserved license tokens back to the provider."""
        pass

    @abstractmethod
    def health(self) -> LicenseHealthStatus:
        """Check connection health and aggregate status of the license server."""
        pass

    def acquire(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> _LicenseContext:
        """Context manager for scoped token reservation and automatic release."""
        return _LicenseContext(self, feature, tokens, timeout)


class MockLicenseProvider(LicenseProvider):
    """Thread-safe in-memory mock license provider for testing and deterministic simulation."""

    def __init__(self, initial_tokens: Optional[Dict[str, int]] = None, healthy: bool = True, server: str = "mock://licenseserver"):
        self.server = server
        self._healthy = healthy
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._total_tokens: Dict[str, int] = dict(initial_tokens or {"standard": 5, "explicit": 5, "cae": 2})
        self._allocated_tokens: Dict[str, int] = {k: 0 for k in self._total_tokens}
        self._active_handles: Dict[str, LicenseHandle] = {}

    def set_healthy(self, healthy: bool) -> None:
        with self._lock:
            self._healthy = healthy

    def set_total_tokens(self, feature: str, total: int) -> None:
        with self._cond:
            self._total_tokens[feature] = max(0, total)
            if feature not in self._allocated_tokens:
                self._allocated_tokens[feature] = 0
            self._cond.notify_all()

    def available_tokens(self, feature: str = "standard") -> int:
        with self._lock:
            if not self._healthy:
                return 0
            total = self._total_tokens.get(feature, 0)
            allocated = self._allocated_tokens.get(feature, 0)
            return max(0, total - allocated)

    def reserve(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> Optional[LicenseHandle]:
        start_time = time.time()
        with self._cond:
            while True:
                if not self._healthy:
                    return None
                total = self._total_tokens.get(feature, 0)
                allocated = self._allocated_tokens.get(feature, 0)
                available = total - allocated
                if available >= tokens:
                    self._allocated_tokens[feature] = allocated + tokens
                    handle = LicenseHandle(
                        handle_id=str(uuid.uuid4()),
                        feature=feature,
                        tokens=tokens,
                        provider_name=self.__class__.__name__,
                        granted_at=time.time(),
                        metadata={"mock": True, "server": self.server},
                    )
                    self._active_handles[handle.handle_id] = handle
                    return handle

                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=min(remaining, 0.1))

    def release(self, handle: LicenseHandle) -> bool:
        with self._cond:
            if handle.handle_id not in self._active_handles:
                return False
            del self._active_handles[handle.handle_id]
            current = self._allocated_tokens.get(handle.feature, 0)
            self._allocated_tokens[handle.feature] = max(0, current - handle.tokens)
            self._cond.notify_all()
            return True

    def health(self) -> LicenseHealthStatus:
        with self._lock:
            total_sum = sum(self._total_tokens.values())
            alloc_sum = sum(self._allocated_tokens.values())
            avail_sum = max(0, total_sum - alloc_sum) if self._healthy else 0
            return LicenseHealthStatus(
                healthy=self._healthy,
                server=self.server,
                available_tokens=avail_sum,
                total_tokens=total_sum,
                details={
                    "total_by_feature": dict(self._total_tokens),
                    "allocated_by_feature": dict(self._allocated_tokens),
                    "active_handles_count": len(self._active_handles),
                },
            )


class LocalLicenseProvider(LicenseProvider):
    """Transparent placeholder provider for single-machine environments without external license servers."""

    def __init__(self, unlimited_tokens: int = 9999):
        self.unlimited_tokens = unlimited_tokens
        self._active_handles: Dict[str, LicenseHandle] = {}
        self._lock = threading.Lock()

    def available_tokens(self, feature: str = "standard") -> int:
        return self.unlimited_tokens

    def reserve(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> Optional[LicenseHandle]:
        with self._lock:
            handle = LicenseHandle(
                handle_id=str(uuid.uuid4()),
                feature=feature,
                tokens=tokens,
                provider_name="LocalLicenseProvider",
                granted_at=time.time(),
                metadata={"local": True},
            )
            self._active_handles[handle.handle_id] = handle
            return handle

    def release(self, handle: LicenseHandle) -> bool:
        with self._lock:
            return self._active_handles.pop(handle.handle_id, None) is not None

    def health(self) -> LicenseHealthStatus:
        return LicenseHealthStatus(
            healthy=True,
            server="local://standalone",
            available_tokens=self.unlimited_tokens,
            total_tokens=self.unlimited_tokens,
            details={"mode": "unmetered_local"},
        )


class FlexNetAdapter(LicenseProvider):
    """Production adapter for FlexNet Publisher (lmutil lmstat)."""

    def __init__(
        self,
        server: str,
        lmutil_path: str = "lmutil",
        timeout: float = 10.0,
        command_runner: Optional[Callable[[list], Dict[str, Any]]] = None,
    ):
        self.server = server
        self.lmutil_path = lmutil_path
        self.timeout = timeout
        self._runner = command_runner or self._default_runner
        self._lock = threading.Lock()
        self._reserved_handles: Dict[str, LicenseHandle] = {}

    def _default_runner(self, cmd: list) -> Dict[str, Any]:
        import subprocess
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            return {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        except Exception as exc:
            return {"exit_code": -1, "stdout": "", "stderr": str(exc)}

    def parse_lmstat_output(self, stdout: str, feature: str) -> Dict[str, int]:
        """Parse `Users of <feature>: (Total of X licenses issued; Total of Y licenses in use)`."""
        pattern = re.compile(
            rf"Users of {re.escape(feature)}:\s*\(Total of (\d+) licenses? issued;\s*Total of (\d+) licenses? in use\)",
            re.IGNORECASE,
        )
        match = pattern.search(stdout)
        if match:
            total = int(match.group(1))
            in_use = int(match.group(2))
            available = max(0, total - in_use)
            return {"total": total, "in_use": in_use, "available": available}
        return {"total": 0, "in_use": 0, "available": 0}

    def available_tokens(self, feature: str = "standard") -> int:
        cmd = [self.lmutil_path, "lmstat", "-c", self.server, "-f", feature]
        res = self._runner(cmd)
        if res.get("exit_code") != 0:
            return 0
        stats = self.parse_lmstat_output(res.get("stdout", ""), feature)
        with self._lock:
            local_reserved = sum(h.tokens for h in self._reserved_handles.values() if h.feature == feature)
        return max(0, stats["available"] - local_reserved)

    def reserve(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> Optional[LicenseHandle]:
        start_time = time.time()
        while True:
            avail = self.available_tokens(feature)
            if avail >= tokens:
                with self._lock:
                    handle = LicenseHandle(
                        handle_id=str(uuid.uuid4()),
                        feature=feature,
                        tokens=tokens,
                        provider_name=self.__class__.__name__,
                        granted_at=time.time(),
                        metadata={"server": self.server},
                    )
                    self._reserved_handles[handle.handle_id] = handle
                    return handle

            if (time.time() - start_time) >= timeout:
                return None
            time.sleep(min(0.2, max(0.05, timeout / 5.0)))

    def release(self, handle: LicenseHandle) -> bool:
        with self._lock:
            return self._reserved_handles.pop(handle.handle_id, None) is not None

    def health(self) -> LicenseHealthStatus:
        cmd = [self.lmutil_path, "lmstat", "-c", self.server]
        res = self._runner(cmd)
        healthy = res.get("exit_code") == 0
        stdout = res.get("stdout", "")
        # Aggregate totals if possible
        pattern = re.compile(r"\(Total of (\d+) licenses? issued;\s*Total of (\d+) licenses? in use\)", re.IGNORECASE)
        total_sum = 0
        used_sum = 0
        for m in pattern.finditer(stdout):
            total_sum += int(m.group(1))
            used_sum += int(m.group(2))
        return LicenseHealthStatus(
            healthy=healthy,
            server=self.server,
            available_tokens=max(0, total_sum - used_sum) if healthy else 0,
            total_tokens=total_sum if healthy else 0,
            details={"raw_output_snippet": stdout[:200], "exit_code": res.get("exit_code")},
        )


class DSLSAdapter(LicenseProvider):
    """Production adapter for Dassault Systèmes License Server (dslsstat)."""

    def __init__(
        self,
        server: str,
        dslsstat_path: str = "dslsstat",
        timeout: float = 10.0,
        command_runner: Optional[Callable[[list], Dict[str, Any]]] = None,
    ):
        self.server = server
        self.dslsstat_path = dslsstat_path
        self.timeout = timeout
        self._runner = command_runner or self._default_runner
        self._lock = threading.Lock()
        self._reserved_handles: Dict[str, LicenseHandle] = {}

    def _default_runner(self, cmd: list) -> Dict[str, Any]:
        import subprocess
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            return {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        except Exception as exc:
            return {"exit_code": -1, "stdout": "", "stderr": str(exc)}

    def parse_dslsstat_output(self, stdout: str, feature: str) -> Dict[str, int]:
        pattern = re.compile(
            rf"{re.escape(feature)}\s+(\d+)\s+(\d+)\s+(\d+)",
            re.IGNORECASE,
        )
        match = pattern.search(stdout)
        if match:
            total = int(match.group(1))
            in_use = int(match.group(2))
            free = int(match.group(3))
            return {"total": total, "in_use": in_use, "available": free}
        return {"total": 0, "in_use": 0, "available": 0}

    def available_tokens(self, feature: str = "standard") -> int:
        cmd = [self.dslsstat_path, "-s", self.server, "-f", feature]
        res = self._runner(cmd)
        if res.get("exit_code") != 0:
            return 0
        stats = self.parse_dslsstat_output(res.get("stdout", ""), feature)
        with self._lock:
            local_reserved = sum(h.tokens for h in self._reserved_handles.values() if h.feature == feature)
        return max(0, stats["available"] - local_reserved)

    def reserve(self, feature: str = "standard", tokens: int = 1, timeout: float = 0.0) -> Optional[LicenseHandle]:
        start_time = time.time()
        while True:
            avail = self.available_tokens(feature)
            if avail >= tokens:
                with self._lock:
                    handle = LicenseHandle(
                        handle_id=str(uuid.uuid4()),
                        feature=feature,
                        tokens=tokens,
                        provider_name=self.__class__.__name__,
                        granted_at=time.time(),
                        metadata={"server": self.server},
                    )
                    self._reserved_handles[handle.handle_id] = handle
                    return handle
            if (time.time() - start_time) >= timeout:
                return None
            time.sleep(min(0.2, max(0.05, timeout / 5.0)))

    def release(self, handle: LicenseHandle) -> bool:
        with self._lock:
            return self._reserved_handles.pop(handle.handle_id, None) is not None

    def health(self) -> LicenseHealthStatus:
        cmd = [self.dslsstat_path, "-s", self.server, "-health"]
        res = self._runner(cmd)
        healthy = res.get("exit_code") == 0
        return LicenseHealthStatus(
            healthy=healthy,
            server=self.server,
            available_tokens=0,
            total_tokens=0,
            details={"exit_code": res.get("exit_code")},
        )
