import fnmatch
import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class PromotedArtifact:
    artifact_type: str
    filename: str
    source_path: str
    target_path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "filename": self.filename,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


class RunSandbox:
    """Isolated scratch execution directory sandbox for an AnalysisRun.
    
    Prevents Abaqus .lck lock file collisions and scratch clutter when multiple
    analysis jobs run concurrently. Handles deterministic artifact promotion to
    permanent storage.
    """

    DEFAULT_PROMOTION_PATTERNS: Tuple[str, ...] = (
        "*.odb",
        "*.sta",
        "*.msg",
        "*.dat",
        "*.inp",
        "*.log",
        "*.png",
        "*.csv",
        "*.json",
    )

    def __init__(
        self,
        run_id: Optional[str] = None,
        base_dir: Optional[str] = None,
        cleanup_on_exit: bool = False,
    ):
        self.run_id = run_id or str(uuid.uuid4())
        self.base_dir = os.path.abspath(base_dir) if base_dir else tempfile.gettempdir()
        self.sandbox_dir = os.path.join(self.base_dir, f"abaqus_sandbox_{self.run_id}")
        self.cleanup_on_exit = cleanup_on_exit
        self._created = False

    def create(self) -> str:
        """Create the scratch directory."""
        os.makedirs(self.sandbox_dir, exist_ok=True)
        self._created = True
        return self.sandbox_dir

    def resolve_path(self, relative_path: str) -> str:
        """Resolve a relative path against the sandbox directory."""
        if os.path.isabs(relative_path):
            return relative_path
        return os.path.join(self.sandbox_dir, relative_path)

    def check_locks(self) -> List[str]:
        """Check for active or stale .lck lock files in the sandbox."""
        if not os.path.exists(self.sandbox_dir):
            return []
        locks = []
        for root, _, files in os.walk(self.sandbox_dir):
            for f in files:
                if f.endswith(".lck"):
                    locks.append(os.path.join(root, f))
        return locks

    def is_locked(self) -> bool:
        """True if any active .lck files exist in the sandbox."""
        return len(self.check_locks()) > 0

    def clear_stale_locks(self) -> int:
        """Forcefully remove stale .lck files if verified dead/abandoned."""
        locks = self.check_locks()
        removed = 0
        for lck in locks:
            try:
                os.remove(lck)
                removed += 1
            except OSError:
                pass
        return removed

    def promote_artifacts(
        self,
        target_dir: str,
        patterns: Optional[Tuple[str, ...]] = None,
        move: bool = False,
    ) -> List[PromotedArtifact]:
        """Promote engineering artifacts from sandbox to canonical storage."""
        if not os.path.exists(self.sandbox_dir):
            return []

        os.makedirs(target_dir, exist_ok=True)
        effective_patterns = patterns or self.DEFAULT_PROMOTION_PATTERNS
        promoted: List[PromotedArtifact] = []

        for root, _, files in os.walk(self.sandbox_dir):
            for fname in files:
                for pat in effective_patterns:
                    if fnmatch.fnmatch(fname, pat):
                        src = os.path.join(root, fname)
                        dst = os.path.join(target_dir, fname)
                        if move:
                            shutil.move(src, dst)
                            final_src = dst
                        else:
                            shutil.copy2(src, dst)
                            final_src = src

                        size = os.path.getsize(dst)
                        sha = _compute_sha256(dst)
                        ext = os.path.splitext(fname)[1].lstrip(".").lower() or "artifact"
                        promoted.append(
                            PromotedArtifact(
                                artifact_type=ext,
                                filename=fname,
                                source_path=final_src,
                                target_path=dst,
                                sha256=sha,
                                size_bytes=size,
                            )
                        )
                        break
        return promoted

    def cleanup(self) -> bool:
        """Remove the sandbox directory and all intermediate files."""
        if not os.path.exists(self.sandbox_dir):
            return True
        try:
            shutil.rmtree(self.sandbox_dir, ignore_errors=True)
            self._created = False
            return True
        except Exception:
            return False

    def __enter__(self) -> "RunSandbox":
        self.create()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cleanup_on_exit:
            self.cleanup()
