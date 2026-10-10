"""Headless Abaqus Viewer ODB Visualization and Contour Rendering Engine.

Automates the generation and execution of headless off-screen postprocessing
scripts via `abaqus viewer -noGUI` to capture true finite element physical
field responses (e.g. von Mises stress concentrations, deformation displacement,
temperature gradients, contact sealing pressure) directly from authentic .odb
databases without needing interactive GUI windows or manual screenshotting.
"""

from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import zlib

try:
    from PIL import Image as _PILImage
    _HAS_PIL = True
except ImportError:
    _PILImage = None
    _HAS_PIL = False

from ..contracts.report import ReportFigure
from .batch import resolve_default_launcher


VALID_OUTPUT_POSITIONS: Set[str] = {
    "INTEGRATION_POINT",
    "NODAL",
    "ELEMENT_NODAL",
    "CENTROID",
    "ELEMENT_FACE",
}

VALID_PLOT_STATES: Set[str] = {
    "CONTOURS_ON_DEF",
    "CONTOURS_ON_UNDEF",
    "DEFORMED",
    "UNDEFORMED",
}

# 1x1 RGBA authentic standard PNG byte stream (IHDR width=1, height=1, valid chunk CRCs & IEND)
MINIMAL_VALID_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def verify_png_image_integrity(
    file_path_or_bytes: Union[str, Path, bytes],
) -> Tuple[int, int]:
    """Verify that input data represents an authentic, non-corrupt PNG with positive dimensions.

    Validates:
    - Standard 8-byte PNG magic signature (\\x89PNG\\r\\n\\x1a\\n).
    - Presence of initial IHDR chunk with positive width and height.
    - Integrity of all chunk headers, lengths, and CRC32 checksums.
    - Standard IEND termination chunk with valid CRC.
    - Complete raster decoding if Pillow is available.

    Returns (width, height) on success.
    Raises ValueError / FileNotFoundError / TypeError if invalid.
    """
    if isinstance(file_path_or_bytes, (str, Path)):
        p = Path(file_path_or_bytes)
        if not p.is_file():
            raise FileNotFoundError(f"Image file does not exist: {p}")
        data = p.read_bytes()
    elif isinstance(file_path_or_bytes, (bytes, bytearray)):
        data = bytes(file_path_or_bytes)
    else:
        raise TypeError(f"Expected file path or bytes, got {type(file_path_or_bytes)}")

    if len(data) < 33:
        raise ValueError(
            f"Truncated PNG image: data length is only {len(data)} bytes, expected >= 33 bytes"
        )

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(PNG_MAGIC):
        raise ValueError(
            f"Invalid PNG magic signature: {data[:8]!r}. File is not an authentic PNG image."
        )

    if not data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        raise ValueError("Corrupt or truncated PNG: missing standard IEND termination chunk or invalid CRC.")

    offset = 8
    chunks: List[bytes] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Corrupt PNG chunk structure: truncated chunk header")
        length, chunk_type = struct.unpack(">I4s", data[offset:offset + 8])
        offset += 8
        if offset + length + 4 > len(data):
            raise ValueError(f"Corrupt PNG chunk data: truncated {chunk_type.decode(errors='replace')} payload")
        chunk_data = data[offset:offset + length]
        offset += length
        expected_crc, = struct.unpack(">I", data[offset:offset + 4])
        offset += 4
        calc_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if calc_crc != expected_crc:
            raise ValueError(f"Corrupt PNG data: CRC32 mismatch in chunk {chunk_type.decode(errors='replace')}")
        if chunk_type == b"IHDR" and length != 13:
            raise ValueError(f"Invalid IHDR chunk length: {length}, expected 13")
        chunks.append(chunk_type)

    if not chunks or chunks[0] != b"IHDR":
        raise ValueError("Invalid PNG structure: first chunk is not IHDR")
    if chunks.count(b"IHDR") != 1:
        raise ValueError("Invalid PNG structure: duplicate IHDR chunk detected")
    if chunks[-1] != b"IEND":
        raise ValueError("Invalid PNG structure: last chunk is not IEND")
    if chunks.count(b"IEND") != 1:
        raise ValueError("Invalid PNG structure: multiple IEND chunks detected")

    width = int.from_bytes(data[16:20], byteorder="big")
    height = int.from_bytes(data[20:24], byteorder="big")
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Invalid PNG dimensions: width={width}, height={height}. Expected positive dimensions."
        )

    if not _HAS_PIL or _PILImage is None:
        raise RuntimeError("Official delivery requires Pillow for full PNG decoding")

    try:
        im = _PILImage.open(io.BytesIO(data))
        if im.format != "PNG":
            raise ValueError(f"Decoded image format is {im.format!r}, expected 'PNG'")
        im.load()
        dec_w, dec_h = im.size
        if dec_w != width or dec_h != height:
            raise ValueError(f"Raster dimension mismatch: IHDR ({width}x{height}) vs decoded ({dec_w}x{dec_h})")
    except Exception as exc:
        raise ValueError(f"Corrupt PNG image data: failed to decode raster payload: {exc}")

    return width, height


_PROCESS_RENDER_SIGNING_KEY: bytes = secrets.token_bytes(32)


def get_render_signing_key(
    require_persistent: bool = False,
    signing_key: Optional[bytes] = None,
) -> bytes:
    """Obtain process-isolated or environment-controlled HMAC secret key for authentic render evidence.

    Security Model & Lifecycle Contract:
    1. In-Process Pipeline (Ephemeral):
       When running inside a single active execution session, the pipeline generates and validates
       render evidence using `_PROCESS_RENDER_SIGNING_KEY` (a 256-bit CSPRNG key generated per Python process).
       This guarantees that within the run, artifacts cannot be forged or substituted by external callers.
    2. Cross-Process / Persistent Audit:
       When evidence must be verified across distinct processes, in CI audit steps, or during offline review,
       callers must configure the `ABAQUS_RENDER_SIGNING_SECRET` environment variable or provide an explicit
       `signing_key`. If `require_persistent=True` is specified and no persistent key is configured,
       this function fails closed with a RuntimeError rather than silently falling back to a process-local ephemeral key.
    """
    if signing_key is not None:
        return signing_key
    env_secret = os.environ.get("ABAQUS_RENDER_SIGNING_SECRET")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()
    if require_persistent:
        raise RuntimeError(
            "Persistent evidence verification requires 'ABAQUS_RENDER_SIGNING_SECRET' environment variable "
            "or an explicit signing_key to be provided. Ephemeral process key cannot be used for cross-process audit."
        )
    return _PROCESS_RENDER_SIGNING_KEY


@dataclass
class RenderExecutionEvidence:
    """Tamper-evident record binding a verified headless Abaqus Viewer rendering session."""

    session_nonce: str
    run_id: str
    odb_sha256: str
    timestamp_utc: str
    rendered_figures: List[Dict[str, Any]]
    session_signature: str
    exit_code: int = 0
    viewer_duration_sec: float = 0.0
    input_hash: str = ""
    viewer_script_sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_nonce": self.session_nonce,
            "run_id": self.run_id,
            "odb_sha256": self.odb_sha256,
            "timestamp_utc": self.timestamp_utc,
            "rendered_figures": self.rendered_figures,
            "session_signature": self.session_signature,
            "exit_code": self.exit_code,
            "viewer_duration_sec": self.viewer_duration_sec,
            "input_hash": self.input_hash,
            "viewer_script_sha256": self.viewer_script_sha256,
        }


def compute_evidence_canonical_payload(
    session_nonce: str,
    run_id: str,
    odb_sha256: str,
    rendered_figures: Sequence[Dict[str, Any]],
    exit_code: int = 0,
    input_hash: str = "",
    viewer_script_sha256: str = "",
) -> str:
    """Compute canonical, normalized JSON payload for HMAC signing across all session parameters."""
    norm_figs = []
    for rf in rendered_figures:
        if isinstance(rf, dict) and rf.get("filename"):
            norm_figs.append({
                "component": str(rf.get("component") or ""),
                "field": str(rf.get("field") or ""),
                "filename": str(Path(str(rf.get("filename"))).name),
                "frame": str(rf.get("frame") if rf.get("frame") is not None else (rf.get("frame_index") if rf.get("frame_index") is not None else "")),
                "image_sha256": str(rf.get("image_sha256") or ""),
                "output_position": str(rf.get("output_position") or ""),
                "region": str(rf.get("region") or ""),
                "step": str(rf.get("step") or rf.get("step_name") or ""),
            })
    norm_figs.sort(key=lambda x: x["filename"])
    payload = {
        "exit_code": int(exit_code),
        "figures": norm_figs,
        "input_hash": str(input_hash or ""),
        "odb_sha256": str(odb_sha256 or ""),
        "run_id": str(run_id or ""),
        "session_nonce": str(session_nonce or ""),
        "viewer_script_sha256": str(viewer_script_sha256 or ""),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def create_render_execution_evidence(
    session_nonce: str,
    run_id: str,
    odb_sha256: str,
    rendered_figures: Sequence[Dict[str, Any]],
    exit_code: int = 0,
    viewer_duration_sec: float = 0.0,
    input_hash: str = "",
    viewer_script_sha256: str = "",
    signing_key: Optional[bytes] = None,
    require_persistent_key: bool = False,
) -> RenderExecutionEvidence:
    """Construct authentic RenderExecutionEvidence with HMAC-SHA256 session signature."""
    import datetime

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    canonical_payload = compute_evidence_canonical_payload(
        session_nonce=session_nonce,
        run_id=run_id,
        odb_sha256=odb_sha256,
        rendered_figures=rendered_figures,
        exit_code=exit_code,
        input_hash=input_hash,
        viewer_script_sha256=viewer_script_sha256,
    )
    key = get_render_signing_key(require_persistent=require_persistent_key, signing_key=signing_key)
    sig = hmac.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return RenderExecutionEvidence(
        session_nonce=session_nonce,
        run_id=run_id,
        odb_sha256=odb_sha256,
        timestamp_utc=ts,
        rendered_figures=list(rendered_figures),
        session_signature=sig,
        exit_code=exit_code,
        viewer_duration_sec=viewer_duration_sec,
        input_hash=input_hash,
        viewer_script_sha256=viewer_script_sha256,
    )


def verify_render_execution_evidence(
    evidence: Union[RenderExecutionEvidence, Dict[str, Any]],
    expected_run_id: str,
    expected_odb_sha256: str,
    expected_input_hash: Optional[str] = None,
    signing_key: Optional[bytes] = None,
    require_persistent_key: bool = False,
) -> Tuple[bool, str]:
    """Verify that a RenderExecutionEvidence matches runtime context and has authentic HMAC signature."""
    if isinstance(evidence, RenderExecutionEvidence):
        data = evidence.to_dict()
    elif isinstance(evidence, dict):
        data = evidence
    else:
        return False, "Invalid evidence object type"

    nonce = data.get("session_nonce") or ""
    run_id = data.get("run_id") or ""
    odb_sha = data.get("odb_sha256") or ""
    figs = data.get("rendered_figures") or []
    sig = data.get("session_signature") or ""
    exit_code = data.get("exit_code", 0)
    ev_input_hash = data.get("input_hash") or ""
    viewer_script_sha = data.get("viewer_script_sha256") or ""

    if exit_code != 0:
        return False, f"Viewer process exited with non-zero exit code: {exit_code}"

    if not nonce or len(nonce) < 16:
        return False, "Evidence lacks valid session_nonce"
    if run_id != str(expected_run_id).strip():
        return False, f"Evidence run_id mismatch: {run_id!r} != {expected_run_id!r}"
    if odb_sha != str(expected_odb_sha256).strip():
        return False, f"Evidence odb_sha256 mismatch: {odb_sha!r} != {expected_odb_sha256!r}"
    if expected_input_hash is not None and str(expected_input_hash).strip():
        if not ev_input_hash:
            return False, "Evidence lacks required input_hash"
        if ev_input_hash != str(expected_input_hash).strip():
            return False, f"Evidence input_hash mismatch: {ev_input_hash!r} != {expected_input_hash!r}"
    elif ev_input_hash and expected_input_hash is not None:
        if ev_input_hash != str(expected_input_hash).strip():
            return False, f"Evidence input_hash mismatch: {ev_input_hash!r} != {expected_input_hash!r}"

    fig_names = [Path(str(rf.get("filename", ""))).name for rf in figs if isinstance(rf, dict) and rf.get("filename")]
    if len(fig_names) != len(set(fig_names)):
        return False, "Evidence rendered_figures contains duplicate filenames"

    canonical_payload = compute_evidence_canonical_payload(
        session_nonce=nonce,
        run_id=run_id,
        odb_sha256=odb_sha,
        rendered_figures=figs,
        exit_code=exit_code,
        input_hash=ev_input_hash,
        viewer_script_sha256=viewer_script_sha,
    )
    try:
        key = get_render_signing_key(require_persistent=require_persistent_key, signing_key=signing_key)
    except RuntimeError as exc:
        return False, str(exc)

    expected_sig = hmac.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, "Evidence session_signature mismatch or forged (invalid HMAC signature)"

    return True, "Valid"


def compute_viewer_session_token(
    session_nonce: str,
    run_id: str,
    odb_sha256: str,
    target_filename: str,
    image_sha256: str,
) -> str:
    """Cryptographically derive authentic viewer_session_token for an Abaqus Viewer render session.

    Binds the unpredictable session nonce, run_id, odb_sha256, target filename,
    and image content sha256. Prevents downstream forgery and ambient file adoption.
    """
    fname = Path(target_filename).name
    seed = f"VIEWER-SESSION:{session_nonce}:{run_id}:{odb_sha256}:{fname}:{image_sha256}"
    return f"VIEWER-TOKEN-{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


@dataclass
class ContourPlotRequest:
    """Specification for capturing an authentic finite element contour plot from an ODB."""

    output_filename: str
    variable_label: str = "S"
    component_or_invariant: Optional[str] = "Mises"
    output_position: str = "INTEGRATION_POINT"  # "INTEGRATION_POINT", "NODAL", "ELEMENT_NODAL"
    step_name: Optional[str] = None
    frame_index: int = -1
    plot_state: str = "CONTOURS_ON_DEF"  # "CONTOURS_ON_DEF", "CONTOURS_ON_UNDEF", "DEFORMED", "UNDEFORMED"
    view_orientation: str = "Iso"  # "Iso", "Front", "Back", "Top", "Bottom", "Left", "Right"
    deformation_scale_factor: Optional[float] = None  # None = AUTO, 1.0 = True scale
    caption: str = ""
    description: str = ""
    region: str = "WHOLE_MODEL"


def generate_headless_viewer_script(
    odb_path: Union[str, Path],
    requests: Sequence[ContourPlotRequest],
    output_dir: Optional[Union[str, Path]] = None,
) -> str:
    """Generate a clean, hardened Abaqus Viewer headless Python script.

    The script is designed to be executed via `abaqus viewer -noGUI <script.py>`
    and exports high-resolution PNG snapshots with off-screen rendering.
    """
    odb_str = Path(odb_path).as_posix()
    out_dir_str = Path(output_dir).as_posix() if output_dir else "."

    code_lines = [
        "# ===========================================================================",
        "# Auto-generated Headless Abaqus Viewer Postprocessing & Contour Script",
        "# Generated by abaqus_ai_agent for authentic CAE report generation",
        "# ===========================================================================",
        "import os",
        "import sys",
        "from abaqus import *",
        "from abaqusConstants import *",
        "import visualization",
        "",
        f"odb_path = r'{odb_str}'",
        f"out_dir = r'{out_dir_str}'",
        "if not os.path.exists(out_dir):",
        "    os.makedirs(out_dir)",
        "",
        "print('[HeadlessViewer] Opening ODB: %s' % odb_path)",
        "try:",
        "    odb = visualization.openOdb(path=odb_path, readOnly=True)",
        "except Exception as e:",
        "    print('[HeadlessViewer] ERROR: Failed to open ODB: %s' % e)",
        "    sys.exit(1)",
        "",
        "# Configure viewport and presentation options",
        "vp_name = session.currentViewportName",
        "vp = session.viewports[vp_name]",
        "vp.setValues(displayedObject=odb)",
        "",
        "# Publication-grade viewport settings: clean white background, shaded rendering",
        "session.printOptions.setValues(vpBackground=OFF)",
        "try:",
        "    vp.viewportAnnotationOptions.setValues(",
        "        triad=ON,",
        "        legend=ON,",
        "        title=OFF,",
        "        state=OFF,",
        "        annotations=OFF,",
        "    )",
        "    vp.odbDisplay.commonOptions.setValues(renderStyle=SHADED)",
        "except Exception as _vp_err:",
        "    print('[HeadlessViewer] WARNING: Viewport cosmetic annotations degraded: %s' % _vp_err)",
        "",
    ]

    seen_filenames: Set[str] = set()
    for idx, req in enumerate(requests):
        safe_fname = Path(req.output_filename).name
        if safe_fname in seen_filenames:
            raise ValueError(
                f"Duplicate target_filename detected in contour plot requests: {safe_fname!r}. "
                "Each visualization request must have a unique target_filename to prevent collision."
            )
        seen_filenames.add(safe_fname)
        target_path_expr = f"os.path.join(out_dir, {safe_fname!r})"

        pos_raw = (req.output_position or "INTEGRATION_POINT").strip().upper()
        if pos_raw not in VALID_OUTPUT_POSITIONS:
            raise ValueError(
                f"Invalid output_position {req.output_position!r} for request '{safe_fname}'. "
                f"Must be one of {sorted(VALID_OUTPUT_POSITIONS)}"
            )
        pos = pos_raw

        plot_state_raw = (req.plot_state or "CONTOURS_ON_DEF").strip().upper()
        if plot_state_raw not in VALID_PLOT_STATES:
            raise ValueError(
                f"Invalid plot_state {req.plot_state!r} for request '{safe_fname}'. "
                f"Must be one of {sorted(VALID_PLOT_STATES)}"
            )
        p_state = plot_state_raw

        code_lines += [
            f"# ---------------------------------------------------------------------------",
            f"# Request {idx + 1}: {req.variable_label} ({req.component_or_invariant or 'Scalar'}) -> {safe_fname}",
            f"# ---------------------------------------------------------------------------",
            "try:",
            f"    # 1. Step & Frame selection",
        ]

        if req.step_name:
            code_lines.append(f"    if {req.step_name!r} not in odb.steps:")
            code_lines.append(f"        raise KeyError('Requested step \"{req.step_name}\" not found in ODB steps: ' + str(list(odb.steps.keys())))")
            code_lines.append(f"    target_step = odb.steps[{req.step_name!r}]")
            code_lines.append(f"    target_frame = target_step.frames[{int(req.frame_index)}]")
            code_lines.append(f"    vp.odbDisplay.setFrame(step={req.step_name!r}, frame={int(req.frame_index)})")
        else:
            code_lines.append("    # Select final available step and frame")
            code_lines.append("    if len(odb.steps) == 0:")
            code_lines.append("        raise ValueError('Target ODB contains zero steps')")
            code_lines.append("    last_step_key = list(odb.steps.keys())[-1]")
            code_lines.append(f"    vp.odbDisplay.setFrame(step=last_step_key, frame={int(req.frame_index)})")

        code_lines += [
            "    # 2. Display mode (Contour on Deformed / Undeformed)",
            f"    vp.odbDisplay.display.setValues(plotState=({p_state},))",
        ]

        if req.region and req.region != "WHOLE_MODEL":
            code_lines += [
                f"    # Region set filtering: {req.region}",
                f"    reg_name = {req.region!r}",
                "    found_reg = None",
                "    if reg_name in odb.rootAssembly.elementSets:",
                "        found_reg = odb.rootAssembly.elementSets[reg_name]",
                "    elif reg_name in odb.rootAssembly.nodeSets:",
                "        found_reg = odb.rootAssembly.nodeSets[reg_name]",
                "    else:",
                "        for inst in odb.rootAssembly.instances.values():",
                "            if reg_name in inst.elementSets:",
                "                found_reg = inst.elementSets[reg_name]",
                "                break",
                "            elif reg_name in inst.nodeSets:",
                "                found_reg = inst.nodeSets[reg_name]",
                "                break",
                "    if found_reg is None:",
                "        raise KeyError('Requested region \"' + reg_name + '\" not found in ODB assembly or instance sets')",
                "    vp.odbDisplay.setValues(visibleDisplayGroups=(found_reg,))",
            ]

        # Deformation scale factor
        if req.deformation_scale_factor is not None:
            code_lines.append(
                f"    vp.odbDisplay.commonOptions.setValues(deformationScaling=USER_SPECIFIED, uniformScaleFactor={float(req.deformation_scale_factor)})"
            )
        else:
            code_lines.append(
                "    vp.odbDisplay.commonOptions.setValues(deformationScaling=AUTO)"
            )

        # Primary Variable setup
        v_label = req.variable_label
        inv = req.component_or_invariant

        code_lines.append(f"    # 3. Field variable configuration: {v_label}")
        if inv:
            inv_upper = inv.upper()
            inv_title = inv.title()
            code_lines += [
                "    try:",
                f"        vp.odbDisplay.setPrimaryVariable(",
                f"            variableLabel={v_label!r},",
                f"            outputPosition={pos},",
                f"            refinement=(INVARIANT, {inv_title!r})",
                "        )",
                "    except Exception:",
                "        try:",
                f"            vp.odbDisplay.setPrimaryVariable(",
                f"                variableLabel={v_label!r},",
                f"                outputPosition={pos},",
                f"                refinement=(INVARIANT, {inv_upper!r})",
                "            )",
                "        except Exception:",
                "            try:",
                f"                vp.odbDisplay.setPrimaryVariable(",
                f"                    variableLabel={v_label!r},",
                f"                    outputPosition={pos},",
                f"                    refinement=(INVARIANT, {inv!r})",
                "                )",
                "            except Exception:",
                "                try:",
                f"                    vp.odbDisplay.setPrimaryVariable(",
                f"                        variableLabel={v_label!r},",
                f"                        outputPosition={pos},",
                f"                        refinement=(COMPONENT, {inv!r})",
                "                    )",
                "                except Exception:",
                "                    try:",
                f"                        vp.odbDisplay.setPrimaryVariable(",
                f"                            variableLabel={v_label!r},",
                f"                            outputPosition={pos},",
                f"                            refinement=(COMPONENT, {inv_upper!r})",
                "                        )",
                "                    except Exception:",
                "                        try:",
                f"                            vp.odbDisplay.setPrimaryVariable(",
                f"                                variableLabel={v_label!r},",
                f"                                outputPosition={pos},",
                f"                                refinement=(COMPONENT, {inv_title!r})",
                "                            )",
                "                        except Exception:",
                f"                            raise ValueError('Failed to set primary variable \"{v_label}\" with invariant/component \"{inv}\"')",
            ]
        else:
            code_lines += [
                "    try:",
                f"        vp.odbDisplay.setPrimaryVariable(variableLabel={v_label!r}, outputPosition={pos})",
                "    except Exception as _pos_err:",
                f"        raise ValueError('Failed to set primary variable \"{v_label}\" at outputPosition {pos}: ' + str(_pos_err))",
            ]

        # View Orientation
        v_orient = req.view_orientation
        code_lines += [
            f"    # 4. Camera view orientation: {v_orient}",
            f"    if {v_orient!r} in session.views:",
            f"        vp.view.setValues(session.views[{v_orient!r}])",
            "    vp.view.fitView()",
            "",
            f"    # 5. Export authentic PNG",
            f"    out_img = {target_path_expr}",
            "    session.printToFile(fileName=out_img, format=PNG, canvasObjects=(vp,))",
            "    print('[HeadlessViewer] Successfully rendered: %s' % out_img)",
            "except Exception as err:",
            f"    print('[HeadlessViewer] ERROR: Failed to render {safe_fname}: %s' % err)",
            "    sys.exit(4)",
            "",
        ]

    code_lines += [
        "odb.close()",
        "print('[HeadlessViewer] Postprocessing completed successfully.')",
    ]

    return "\n".join(code_lines)


def render_odb_contours_headless(
    odb_path: Union[str, Path],
    requests: Sequence[ContourPlotRequest],
    output_dir: Union[str, Path],
    launcher: Optional[str] = None,
    timeout: int = 180,
) -> List[Path]:
    """Execute headless Abaqus Viewer in an isolated scratch sandbox to produce authentic contour images.

    Returns the list of verified, newly-generated PNG image Paths transferred to output_dir.
    Pre-existing files in output_dir are never certified or adopted if Viewer did not render them.
    """
    odb = Path(odb_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not requests:
        return []

    resolved_launcher = resolve_default_launcher(launcher or "abaqus")
    if not (os.path.exists(resolved_launcher) or any(os.access(p, os.X_OK) for p in [resolved_launcher])):
        # Fallback check on PATH
        if not shutil.which(resolved_launcher):
            raise RuntimeError(
                f"Abaqus launcher not found at {resolved_launcher}. "
                "Headless viewer rendering requires authentic Abaqus installation."
            )

    with tempfile.TemporaryDirectory(prefix="viewer_render_scratch_") as scratch_str:
        scratch_dir = Path(scratch_str).resolve()
        script_path = scratch_dir / "_headless_viewer_post.py"
        script_content = generate_headless_viewer_script(
            odb_path=odb,
            requests=requests,
            output_dir=scratch_dir,
        )
        script_path.write_text(script_content, encoding="utf-8")

        cmd = [str(resolved_launcher), "viewer", "-noGUI", str(script_path)]
        use_shell = (os.name == "nt")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(scratch_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=use_shell,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Headless Abaqus Viewer timed out after {timeout}s: {exc}")

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"Headless Abaqus Viewer failed with exit code {proc.returncode}: {err_msg}"
            )

        # Collect only freshly generated images from scratch sandbox and transfer to out_dir
        produced = []
        for req in requests:
            scratch_target = scratch_dir / Path(req.output_filename).name
            if scratch_target.exists() and scratch_target.stat().st_size > 0:
                verify_png_image_integrity(scratch_target)
                final_target = out_dir / scratch_target.name
                shutil.copy2(scratch_target, final_target)
                produced.append(final_target)

        if len(produced) != len(requests):
            missing_names = [
                Path(req.output_filename).name
                for req in requests
                if not (out_dir / Path(req.output_filename).name).exists()
            ]
            raise RuntimeError(
                f"Headless Abaqus Viewer failed to produce all requested figures: "
                f"expected {len(requests)}, got {len(produced)}. Missing: {missing_names}"
            )

        return produced


def render_authentic_visualizations(
    odb_path: Union[str, Path],
    specs: Sequence[Any],
    output_dir: Union[str, Path],
    launcher: Optional[str] = None,
    timeout: int = 180,
    run_id: Optional[str] = None,
    input_hash: Optional[str] = None,
    signing_key: Optional[bytes] = None,
    require_persistent_key: bool = False,
) -> List[ReportFigure]:
    """Authentically render and causally bind all requested CAE visualization specs.

    Fail-Closed Discipline:
    1. Validates that the target is a genuine binary ODB (never empty/mock).
    2. Translates each VisualizationSpec into a headless Abaqus Viewer contour request.
    3. Executes headless Abaqus Viewer.
    4. Ensures EVERY declared image is successfully produced on disk (> 0 bytes).
    5. Calculates authentic SHA-256 and causally binds run_id, input_hash, and odb_sha256 into the ReportFigure metadata.
    """
    import hashlib
    from .solver import is_authentic_binary_odb

    odb = Path(odb_path).resolve()
    if not odb.is_file():
        raise FileNotFoundError(f"Target ODB file does not exist: {odb}")
    if not is_authentic_binary_odb(odb):
        raise ValueError(
            f"Target file {odb} is not an authentic binary ODB. "
            "Headless viewer rendering strictly forbids synthetic or mock files."
        )

    h_odb = hashlib.sha256()
    with open(odb, "rb") as f:
        while chunk := f.read(65536):
            h_odb.update(chunk)
    odb_sha256 = h_odb.hexdigest()

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not specs:
        return []

    requests = []
    for spec in specs:
        v_orient = "Iso"
        vm = getattr(spec, "view_mode", "AUTO_FIT").upper()
        if "TOP" in vm:
            v_orient = "Top"
        elif "FRONT" in vm:
            v_orient = "Front"
        elif "SECTION" in vm or "ISOMETRIC" in vm:
            v_orient = "Iso"

        req = ContourPlotRequest(
            output_filename=spec.target_filename,
            variable_label=spec.field_name,
            component_or_invariant=spec.component,
            output_position=getattr(spec, "output_position", "INTEGRATION_POINT") or "INTEGRATION_POINT",
            step_name=spec.step_name,
            frame_index=spec.frame_index,
            view_orientation=v_orient,
            caption=getattr(spec, "caption_zh", "") or getattr(spec, "caption_en", ""),
            region=getattr(spec, "region", "WHOLE_MODEL") or "WHOLE_MODEL",
        )
        requests.append(req)

    produced_paths = render_odb_contours_headless(
        odb_path=odb,
        requests=requests,
        output_dir=out_dir,
        launcher=launcher,
        timeout=timeout,
    )
    produced_names = {p.name for p in produced_paths}

    figures: List[ReportFigure] = []
    session_nonce = secrets.token_hex(16)
    eff_run_id = str(run_id or "RUN").strip()

    for spec in specs:
        target_name = Path(spec.target_filename).name
        target_path = out_dir / target_name
        if target_name not in produced_names or not target_path.exists() or target_path.stat().st_size == 0:
            raise FileNotFoundError(
                f"Fail-Closed: Authentic CAE visualization '{spec.target_filename}' "
                f"failed to render from ODB {odb} in this viewer session. Placeholder images are strictly forbidden."
            )

        verify_png_image_integrity(target_path)

        h_img = hashlib.sha256()
        with open(target_path, "rb") as f:
            while chunk := f.read(65536):
                h_img.update(chunk)
        img_sha256 = h_img.hexdigest()

        fig = spec.to_report_figure(str(target_path))
        fig_meta = dict(fig.metadata or {})
        viewer_token = compute_viewer_session_token(
            session_nonce=session_nonce,
            run_id=eff_run_id,
            odb_sha256=odb_sha256,
            target_filename=target_name,
            image_sha256=img_sha256,
        )
        fig_meta["session_nonce"] = session_nonce
        fig_meta["viewer_session_token"] = viewer_token
        fig_meta["odb_path"] = str(odb)
        fig_meta["odb_sha256"] = odb_sha256
        fig_meta["image_sha256"] = img_sha256
        fig_meta["sha256"] = img_sha256
        if run_id:
            fig_meta["run_id"] = run_id
        if input_hash:
            fig_meta["input_hash"] = input_hash
        fig_meta["field"] = spec.field_name
        fig_meta["component"] = spec.component
        fig_meta["step"] = spec.step_name
        fig_meta["step_name"] = spec.step_name
        fig_meta["frame"] = spec.frame_index
        fig_meta["frame_index"] = spec.frame_index
        fig_meta["actual_frame"] = getattr(spec, "actual_frame_index", None)
        fig_meta["actual_frame_index"] = getattr(spec, "actual_frame_index", None)
        fig_meta["region"] = getattr(spec, "region", "WHOLE_MODEL") or "WHOLE_MODEL"
        fig_meta["output_position"] = getattr(spec, "output_position", "INTEGRATION_POINT") or "INTEGRATION_POINT"
        fig_meta["viewer_rendered"] = True

        bound_fig = ReportFigure(
            kind=fig.kind,
            path=fig.path,
            caption=fig.caption,
            source=fig.source,
            metadata=fig_meta,
        )
        figures.append(bound_fig)

    # Cryptographically bind session evidence across all generated figures
    script_str = generate_headless_viewer_script(
        odb_path=odb,
        requests=requests,
        output_dir=out_dir,
    )
    viewer_script_sha256 = hashlib.sha256(script_str.encode("utf-8")).hexdigest()

    rendered_summary = [
        {
            "filename": Path(f.path).name,
            "image_sha256": f.metadata.get("image_sha256"),
            "field": f.metadata.get("field"),
            "component": f.metadata.get("component"),
            "step": f.metadata.get("step"),
            "frame": f.metadata.get("frame"),
            "region": f.metadata.get("region"),
            "output_position": f.metadata.get("output_position"),
        }
        for f in figures
    ]
    render_evidence = create_render_execution_evidence(
        session_nonce=session_nonce,
        run_id=eff_run_id,
        odb_sha256=odb_sha256,
        rendered_figures=rendered_summary,
        input_hash=str(input_hash or ""),
        viewer_script_sha256=viewer_script_sha256,
        signing_key=signing_key,
        require_persistent_key=require_persistent_key,
    )
    for f in figures:
        f.metadata["render_execution_evidence"] = render_evidence.to_dict()

    return figures
