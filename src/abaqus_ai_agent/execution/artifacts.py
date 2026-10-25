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


def inspect_job_diagnostics(executor, job_name, workdir=None, tail_lines=80):
    """Read bounded tails plus full-file terminal markers from solver artifacts.

    The tail remains the human-readable diagnostic payload. Completion, non-
    completion and error markers are evaluated over the whole file so an early
    ``***ERROR`` cannot be hidden by a later completion marker.
    """
    workdir = workdir or "."
    code = """import os, json
job=%r
workdir=os.path.abspath(%r)
tail=%d
result={}
for suffix in ('.msg', '.sta', '.dat', '.log'):
    path=os.path.join(workdir, job+suffix)
    if not os.path.exists(path):
        continue
    try:
        with open(path, 'rb') as fh:
            lines = [l.decode('latin-1', 'replace') for l in fh.readlines()]
        text=''.join(lines)
        upper=text.upper()
        entry={
            'path':path,
            'tail':''.join(lines[-tail:]),
            'has_completed':any('THE ANALYSIS HAS COMPLETED SUCCESSFULLY' in l.upper() for l in lines),
            'has_not_completed':any('THE ANALYSIS HAS NOT BEEN COMPLETED' in l.upper() for l in lines),
            'has_error':any('***ERROR' in l.upper() or '***FATAL' in l.upper() for l in lines),
            'error_sample':next((l.strip() for l in lines if '***ERROR' in l.upper() or '***FATAL' in l.upper()), ''),
            'step_time':None,
            'total_time':None,
            'coverage_time':None,
            'coverage_time_source':'unavailable',
            'time_step_count':0,
            'time_ambiguous':False,
        }
        if suffix == '.sta':
            import re
            clean=text.replace('D','E').replace('d','e')
            number=r'([-+]?[0-9]*[.]?[0-9]+(?:[eE][-+]?[0-9]+)?)'
            labeled_step=[float(x) for x in re.findall(r'(?im)[ 	]*STEP[ 	]+TIME[ 	]*[:=]?[ 	]*'+number, clean)]
            labeled_total=[float(x) for x in re.findall(r'(?im)[ 	]*TOTAL[ 	]+TIME[ 	]*[:=]?[ 	]*'+number, clean)]
            tabular_step=[]; tabular_total=[]; seen_steps=set()
            for line in clean.splitlines():
                tokens=line.split()
                if len(tokens) < 5:
                    continue
                try:
                    step_no=int(tokens[0]); int(tokens[1]); int(tokens[2])
                    step_t=float(tokens[3]); total_t=float(tokens[4])
                except Exception:
                    continue
                seen_steps.add(step_no)
                tabular_step.append(step_t)
                tabular_total.append(total_t)
            step_values=labeled_step or tabular_step
            total_values=labeled_total or tabular_total
            entry['time_step_count']=len(seen_steps)
            if step_values:
                entry['step_time']=step_values[-1]
                entry['coverage_time']=step_values[-1]
                entry['coverage_time_source']='.sta:STEP TIME last value'
            if total_values:
                entry['total_time']=total_values[-1]
            if not step_values and total_values:
                if entry['time_step_count'] > 1:
                    entry['time_ambiguous']=True
                else:
                    entry['coverage_time']=total_values[-1]
                    entry['coverage_time_source']='.sta:TOTAL TIME (single-step fallback)'
        result[suffix]=entry
    except Exception as exc:
        result[suffix]={'path':path, 'error':str(exc)}
print(json.dumps(result))
""" % (job_name, workdir, int(tail_lines))
    raw = executor.execute(code)
    if isinstance(raw, dict):
        return raw
    try:
        import json
        return json.loads(str(raw).strip().splitlines()[-1])
    except Exception:
        return {"raw": str(raw)}
