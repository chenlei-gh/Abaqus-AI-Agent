from dataclasses import dataclass
from typing import Optional, Tuple


DEFAULT_ARTIFACT_SUFFIXES = (
    ".inp", ".odb", ".sta", ".msg", ".dat", ".log", ".cae", ".com", ".prt", ".sim"
)


@dataclass(frozen=True)
class JobArtifact:
    job_name: str
    suffix: str
    path: str
    exists: bool
    size: Optional[int] = None
    modified_time: Optional[float] = None


@dataclass(frozen=True)
class JobArtifacts:
    job_name: str
    workdir: str
    items: Tuple[JobArtifact, ...] = ()

    def by_suffix(self, suffix):
        return tuple(x for x in self.items if x.suffix == suffix)

    @property
    def existing(self):
        return tuple(x for x in self.items if x.exists)

    def missing(self, required=(".odb",)):
        return tuple(x for x in self.items if x.suffix in required and not x.exists)


def inspect_job_artifacts(executor, job_name, workdir=None, suffixes=DEFAULT_ARTIFACT_SUFFIXES):
    workdir = workdir or "."
    code = """import os, json
job=%r
workdir=os.path.abspath(%r)
suffixes=%r
items=[]
for suffix in suffixes:
    path=os.path.join(workdir, job+suffix)
    if os.path.exists(path):
        st=os.stat(path)
        items.append({'suffix':suffix,'path':path,'exists':True,
                      'size':st.st_size,'modified_time':st.st_mtime})
    else:
        items.append({'suffix':suffix,'path':path,'exists':False,
                      'size':None,'modified_time':None})
print(json.dumps({'job_name':job,'workdir':workdir,'items':items}))
""" % (job_name, workdir, tuple(suffixes))
    raw = executor.execute(code)
    if isinstance(raw, dict):
        payload = raw
    else:
        payload = {"job_name": job_name, "workdir": workdir, "items": []}
        if isinstance(raw, str):
            try:
                import json
                payload = json.loads(raw.strip().splitlines()[-1])
            except Exception:
                pass
    return JobArtifacts(
        payload.get("job_name", job_name),
        payload.get("workdir", workdir),
        tuple(JobArtifact(
            job_name, x.get("suffix", ""), x.get("path", ""),
            bool(x.get("exists")), x.get("size"), x.get("modified_time"))
            for x in payload.get("items", ())))
