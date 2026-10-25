import ast
import io
import os
import re
from collections import defaultdict

SRC = r"D:\Vault\Abaqus\Abaqus-AI-Agent\src\abaqus_ai_agent"
ROOT = r"D:\Vault\Abaqus\Abaqus-AI-Agent"
TESTS = os.path.join(ROOT, "tests")
TOOLS = os.path.join(ROOT, "tools")
OUT = r"D:\Vault\Abaqus\_ast_verify_20261025.txt"

out = io.open(OUT, "w", encoding="utf-8")


def w(s=""):
    out.write(s + "\n")


def rel(p, base=SRC):
    return os.path.relpath(p, base).replace("\\", "/")


def py_files(root):
    res = []
    if not os.path.isdir(root):
        return res
    for dp, dn, fn in os.walk(root):
        if "__pycache__" in dp:
            continue
        for f in fn:
            if f.endswith(".py"):
                res.append(os.path.join(dp, f))
    return sorted(res)


src_files = py_files(SRC)
test_files = py_files(TESTS)
tool_files = py_files(TOOLS)

src_text = {}
for p in src_files:
    src_text[rel(p)] = io.open(p, "r", encoding="utf-8", errors="ignore").read()

test_text = {}
for p in test_files:
    test_text[rel(p, TESTS)] = io.open(p, "r", encoding="utf-8", errors="ignore").read()

tool_text = {}
for p in tool_files:
    tool_text[rel(p, TOOLS)] = io.open(p, "r", encoding="utf-8", errors="ignore").read()

w("=" * 78)
w("AST VERIFICATION PASS 2")
w("src=%d  tests=%d  tools=%d" % (len(src_files), len(test_files), len(tool_files)))
w("=" * 78)

# ---------- A. suspect symbols: precise 3-way split ----------
w("\n" + "=" * 78)
w("A. SYMBOL USAGE SPLIT: src-product / tests / tools")
w("=" * 78)
w("   'def' sites are excluded from the call-count; a symbol only used in")
w("   its own defining module is marked SELF-ONLY.")

SUSPECTS = [
    "execute_verified", "preview", "action_to_script",
    "audit_inp_mesh_quality", "parse_and_audit_inp_deck", "evaluate_mesh_quality_gate",
    "diagnose_contact", "evaluate_contact_checks", "contact_checks",
    "assess_meshability", "inspect_geometry_health", "plan_geometry_mesh",
    "evaluate_mesh_convergence", "evaluate_multi_level_mesh_convergence",
    "weighted_score", "enforce_image_context_policy", "validate_locator",
    "to_plain_data", "dumps",
    "calculate_adaptive_cpus", "calculate_adaptive_memory", "resolve_job_kwargs",
    "run_with_watchdog", "detect_runtime", "get_model_info",
    "read_model_snapshot", "extract_spatial_hotspots", "extract_history_curve",
    "calculate_derived_metrics",
]


def find_uses(sym, texts, base):
    """Return list of (relpath, line, is_def, is_import)."""
    hits = []
    pat = re.compile(r"\b%s\b" % re.escape(sym))
    for rp, t in texts.items():
        for m in pat.finditer(t):
            line = t[:m.start()].count("\n") + 1
            ls = t.rfind("\n", 0, m.start()) + 1
            le = t.find("\n", m.start())
            if le < 0:
                le = len(t)
            ctx = t[ls:le].strip()
            is_def = ctx.startswith("def ") or ctx.startswith("class ")
            is_imp = ctx.startswith("from ") or ctx.startswith("import ")
            hits.append((rp, line, is_def, is_imp, ctx[:90]))
    return hits


for sym in SUSPECTS:
    s_hits = find_uses(sym, src_text, SRC)
    t_hits = find_uses(sym, test_text, TESTS)
    o_hits = find_uses(sym, tool_text, TOOLS)

    s_calls = [h for h in s_hits if not h[2] and not h[3]]
    s_defs = [h for h in s_hits if h[2]]
    s_imps = [h for h in s_hits if h[3]]
    def_mods = set(h[0] for h in s_defs)

    external_calls = [h for h in s_calls if h[0] not in def_mods]

    w("\n  %s" % sym)
    w("    def site        : %s" % (", ".join("%s:L%d" % (h[0], h[1]) for h in s_defs) or "NONE"))
    w("    src imports     : %d" % len(s_imps))
    w("    src calls (all) : %d   outside def module: %d" % (len(s_calls), len(external_calls)))
    for h in external_calls[:10]:
        w("        SRC-CALL  %-46s L%-5d %s" % (h[0], h[1], h[4]))
    w("    tests           : %d" % len(t_hits))
    for h in t_hits[:6]:
        w("        TEST      %-46s L%-5d" % (h[0], h[1]))
    w("    tools           : %d" % len(o_hits))
    for h in o_hits[:6]:
        w("        TOOL      %-46s L%-5d" % (h[0], h[1]))

# ---------- B. action type -> full producer/consumer matrix ----------
w("\n" + "=" * 78)
w("B. ACTION TYPE MATRIX (factory / dispatch / consumer)")
w("=" * 78)

ACTION_NAMES = [
    "mesh_quality", "inspect_mesh", "generate_mesh", "seed_part",
    "element_type", "mesh_controls", "local_seed_size", "local_seed_number",
    "tie", "contact", "contact_property", "submit_job", "create_job",
]

for act in ACTION_NAMES:
    factory = []
    dispatch = []
    consumers = []
    for rp, t in src_text.items():
        # factory: _action("act"
        for m in re.finditer(r'_action\(\s*[\'"]%s[\'"]' % re.escape(act), t):
            line = t[:m.start()].count("\n") + 1
            factory.append((rp, line))
        # dispatch: if k == "act"
        for m in re.finditer(r'==\s*[\'"]%s[\'"]' % re.escape(act), t):
            line = t[:m.start()].count("\n") + 1
            dispatch.append((rp, line))
        # consumer: builders.<act>(  or  .action("<act>")
        for m in re.finditer(r'builders\.%s\s*\(' % re.escape(act), t):
            line = t[:m.start()].count("\n") + 1
            consumers.append((rp, line))
    w("\n  %s" % act)
    w("    factory(_action) : %s" % (", ".join("%s:L%d" % x for x in factory) or "NONE"))
    w("    dispatch(== str): %s" % (", ".join("%s:L%d" % x for x in dispatch) or "NONE"))
    w("    consumers        : %s" % (", ".join("%s:L%d" % x for x in consumers) or "NONE"))
    if not consumers:
        w("    >> NO PRODUCER: this action is never requested by planning code")

# ---------- C. package root false-positive check ----------
w("\n" + "=" * 78)
w("C. PACKAGE-ROOT ORPHAN RE-CHECK (was it a parser artifact?)")
w("=" * 78)
for pkg in ("context", "llm", "planning", "reporting", "validation",
            "perception", "telemetry", "visualization", "annotations",
            "editing", "materials", "adapters", "tools"):
    hits = []
    for rp, t in src_text.items():
        if rp == "%s/__init__.py" % pkg:
            continue
        for m in re.finditer(r"from\s+\.{1,3}%s[\.\s]|from\s+\.{1,3}%s\b|import\s+%s\b" % (pkg, pkg, pkg), t):
            line = t[:m.start()].count("\n") + 1
            hits.append((rp, line))
    status = "REAL-ORPHAN" if not hits else "USED(%d)" % len(hits)
    w("  %-16s %s" % (pkg, status))
    for h in hits[:4]:
        w("        %-46s L%d" % (h[0], h[1]))

# ---------- D. known-orphan confirmation ----------
w("\n" + "=" * 78)
w("D. CONFIRMED-ORPHAN MODULE RE-CHECK (any import anywhere?)")
w("=" * 78)
ORPHANS = [
    "adapters/abaqus/grounding_probe", "adapters/abaqus/viewport_probe",
    "adapters/abaqus/region_lifecycle", "adapters/abaqus/model_snapshot",
    "adapters/abaqus/locator_validation", "execution/b28_harness",
    "execution/convergence", "execution/convergence_loop",
    "grounding/serialization", "grounding/scoring",
    "mesh_audit", "mesh_gate", "contact_diagnostics",
    "contracts/benchmarks_catalog", "benchmark_catalog",
    "perception/image_context", "perception/benchmark_evaluator",
    "results/query_protocol", "actions/raw", "contracts/input",
]
for mod in ORPHANS:
    leaf = mod.rsplit("/", 1)[-1]
    imp_src = imp_test = imp_tool = 0
    for rp, t in src_text.items():
        if rp.startswith(mod) and "/" not in rp[len(mod):].lstrip("/"):
            continue
        pat = re.compile(r"(from\s+\.{1,3}[\w\.]*%s\b|import\s+[\w\.]*%s\b|abaqus_ai_agent\.%s\b)"
                         % (leaf, leaf, mod.replace("/", ".")))
        imp_src += len(pat.findall(t))
    for rp, t in test_text.items():
        if re.search(r"\b%s\b" % leaf, t):
            imp_test += 1
    for rp, t in tool_text.items():
        if re.search(r"\b%s\b" % leaf, t):
            imp_tool += 1
    verdict = "DEAD (no consumer at all)" if (imp_src == 0 and imp_test == 0 and imp_tool == 0) else \
              ("TEST-ONLY" if imp_src == 0 else ("PRODUCT-USED" if imp_src > 0 else "?"))
    w("  %-40s src=%d test=%d tool=%d   %s" % (mod, imp_src, imp_test, imp_tool, verdict))

# ---------- E. mesh_quality end-to-end trace ----------
w("\n" + "=" * 78)
w("E. mesh_quality END-TO-END TRACE")
w("=" * 78)
TRACE = [
    ("planning/compiler.py", r"mesh_quality|inspect_mesh|verifyMeshQuality"),
    ("actions/builders.py", r"mesh_quality"),
    ("actions/script.py", r"mesh_quality|verifyMeshQuality"),
    ("execution/analysis_run.py", r"mesh_quality"),
    ("acceptance.py", r"mesh_quality"),
    ("agent.py", r"mesh_gate|mesh_quality"),
    ("contracts/results.py", r"mesh_quality"),
    ("validation/preflight.py", r"mesh"),
]
for rp, pat in TRACE:
    t = src_text.get(rp)
    if t is None:
        w("\n  %s  -- FILE NOT FOUND" % rp)
        continue
    hits = []
    for m in re.finditer(pat, t):
        line = t[:m.start()].count("\n") + 1
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.start())
        if le < 0:
            le = len(t)
        hits.append((line, t[ls:le].strip()[:88]))
    w("\n  %s   hits=%d" % (rp, len(hits)))
    for line, ctx in hits[:12]:
        w("      L%-5d %s" % (line, ctx))
    if len(hits) > 12:
        w("      ... (+%d)" % (len(hits) - 12))

out.close()
print("ok")

