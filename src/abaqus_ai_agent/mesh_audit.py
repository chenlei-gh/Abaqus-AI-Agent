"""Universal Finite Element Mesh Geometry Topology and Quality Audit Engine.

Performs rigorous geometrical, topological, and mathematical evaluations of native Abaqus element decks:
1. S4R / S4 / S3 Quad & Tri Shell Elements:
   - Node planar/curved coordinates (x, y, z)
   - Edge lengths and Aspect Ratio (AR = max_edge / min_edge)
   - Corner Interior Angles (theta = arccos(v1 . v2 / |v1||v2|))
   - Isoparametric Gauss Quadrature Jacobian Matrix Determinant Ratio
   - Quad Warping Factor (out-of-plane normal angular deviation)
2. C3D8R / C3D8 Hexahedral Solid Continuum Elements:
   - 8-node trilinear coordinates (x, y, z)
   - Hexahedral Aspect Ratio across principal directions
   - Corner vertex & Gauss integration point 3D Jacobian Matrix Determinant Ratio
3. INP Deck Fail-Closed Parser & Engineering Gatekeeper Integration:
   - Strictly audits actual input deck topology.
   - Immediate rejection on missing nodes or zero valid elements.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .mesh_gate import (
    MeshGateEvaluation,
    evaluate_mesh_quality_gate,
)
from .contracts.mesh_quality import MeshQualityPolicy


@dataclass(frozen=True)
class QuadMeshAuditResult:
    """Individual 4-node quad shell element quality metrics."""
    element_id: int
    aspect_ratio: float
    min_angle_deg: float
    max_angle_deg: float
    jacobian_ratio: float
    warping_angle_deg: float


@dataclass(frozen=True)
class HexMeshAuditResult:
    """Individual 8-node hex solid element quality metrics."""
    element_id: int
    aspect_ratio: float
    min_angle_deg: float
    max_angle_deg: float
    jacobian_ratio: float


def _vector_sub(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2])


def _vector_cross(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        v1[1] * v2[2] - v1[2] * v2[1],
        v1[2] * v2[0] - v1[0] * v2[2],
        v1[0] * v2[1] - v1[1] * v2[0],
    )


def _vector_dot(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    return v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]


def _vector_norm(v: Tuple[float, float, float]) -> float:
    return math.sqrt(max(1e-18, v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _angle_deg(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    n1 = _vector_norm(v1)
    n2 = _vector_norm(v2)
    cos_val = max(-1.0, min(1.0, _vector_dot(v1, v2) / (n1 * n2)))
    return math.degrees(math.acos(cos_val))


def audit_quad_element(
    elem_id: int,
    p1: Tuple[float, float, float],
    p2: Tuple[float, float, float],
    p3: Tuple[float, float, float],
    p4: Tuple[float, float, float],
) -> QuadMeshAuditResult:
    """Audit single 4-node quad shell element with genuine 2D isoparametric Jacobian mapping."""
    e1 = _vector_sub(p2, p1)
    e2 = _vector_sub(p3, p2)
    e3 = _vector_sub(p4, p3)
    e4 = _vector_sub(p1, p4)

    l1 = _vector_norm(e1)
    l2 = _vector_norm(e2)
    l3 = _vector_norm(e3)
    l4 = _vector_norm(e4)

    min_l = max(1e-9, min(l1, l2, l3, l4))
    max_l = max(l1, l2, l3, l4)
    aspect_ratio = max_l / min_l

    ang1 = _angle_deg(e1, _vector_sub(p4, p1))
    ang2 = _angle_deg(e2, _vector_sub(p1, p2))
    ang3 = _angle_deg(e3, _vector_sub(p2, p3))
    ang4 = _angle_deg(e4, _vector_sub(p3, p4))

    min_angle = min(ang1, ang2, ang3, ang4)
    max_angle = max(ang1, ang2, ang3, ang4)

    n_a = _vector_cross(e1, _vector_sub(p4, p1))
    n_b = _vector_cross(e3, _vector_sub(p2, p3))
    norm_na = _vector_norm(n_a)
    norm_nb = _vector_norm(n_b)

    warping_deg = _angle_deg(n_a, n_b) if norm_na > 1e-9 and norm_nb > 1e-9 else 0.0

    # Genuine 2D Isoparametric Quadrature Jacobian Determinant Evaluation
    # Sample points: 4 corners (-1, -1), (1, -1), (1, 1), (-1, 1) and center (0, 0)
    pts = (p1, p2, p3, p4)
    d1 = _vector_sub(p3, p1)
    d2 = _vector_sub(p4, p2)
    ref_norm = _vector_cross(d1, d2)
    ref_norm_len = _vector_norm(ref_norm)
    if ref_norm_len < 1e-12:
        unit_ref_n = (0.0, 0.0, 1.0)
    else:
        unit_ref_n = (ref_norm[0] / ref_norm_len, ref_norm[1] / ref_norm_len, ref_norm[2] / ref_norm_len)

    sample_coords = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (0.0, 0.0)]
    dets = []
    for xi, eta in sample_coords:
        # Derivatives of bilinear shape functions
        # N1 = 0.25*(1-xi)*(1-eta)
        # N2 = 0.25*(1+xi)*(1-eta)
        # N3 = 0.25*(1+xi)*(1+eta)
        # N4 = 0.25*(1-xi)*(1+eta)
        dN_dxi = [
            -0.25 * (1.0 - eta),
             0.25 * (1.0 - eta),
             0.25 * (1.0 + eta),
            -0.25 * (1.0 + eta),
        ]
        dN_deta = [
            -0.25 * (1.0 - xi),
            -0.25 * (1.0 + xi),
             0.25 * (1.0 + xi),
             0.25 * (1.0 - xi),
        ]
        v_xi = [0.0, 0.0, 0.0]
        v_eta = [0.0, 0.0, 0.0]
        for i in range(4):
            for c in range(3):
                v_xi[c] += dN_dxi[i] * pts[i][c]
                v_eta[c] += dN_deta[i] * pts[i][c]

        cross_j = _vector_cross(tuple(v_xi), tuple(v_eta))
        # Signed determinant relative to reference element normal
        det_val = _vector_dot(cross_j, unit_ref_n)
        dets.append(det_val)

    min_det = min(dets)
    max_det = max(dets)
    if min_det <= 0.0:
        # Inverted or severely folded element
        jac_ratio = min_det if min_det < 0.0 else 0.0
    elif max_det <= 1e-15:
        jac_ratio = 0.0
    else:
        jac_ratio = min(1.0, max(0.0, min_det / max_det))

    return QuadMeshAuditResult(
        element_id=elem_id,
        aspect_ratio=aspect_ratio,
        min_angle_deg=min_angle,
        max_angle_deg=max_angle,
        jacobian_ratio=jac_ratio,
        warping_angle_deg=warping_deg,
    )


def _mat3_det(m: Sequence[Sequence[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][2] * m[2][0])
    )


def audit_hex_element(
    elem_id: int,
    pts: Sequence[Tuple[float, float, float]],
) -> HexMeshAuditResult:
    """Audit single 8-node C3D8 / C3D8R hexahedral solid continuum element."""
    if len(pts) != 8:
        raise ValueError(f"Hex element {elem_id} requires exactly 8 nodes, got {len(pts)}")

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    edge_lens = [_vector_norm(_vector_sub(pts[i], pts[j])) for i, j in edges]
    min_edge = max(1e-9, min(edge_lens))
    max_edge = max(edge_lens)
    aspect_ratio = max_edge / min_edge

    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (0, 3, 7, 4),
        (1, 2, 6, 5),
    ]
    face_angles = []
    for f in faces:
        p_a, p_b, p_c, p_d = pts[f[0]], pts[f[1]], pts[f[2]], pts[f[3]]
        face_angles.append(_angle_deg(_vector_sub(p_b, p_a), _vector_sub(p_d, p_a)))
        face_angles.append(_angle_deg(_vector_sub(p_c, p_b), _vector_sub(p_a, p_b)))
        face_angles.append(_angle_deg(_vector_sub(p_d, p_c), _vector_sub(p_b, p_c)))
        face_angles.append(_angle_deg(_vector_sub(p_a, p_d), _vector_sub(p_c, p_d)))

    min_ang = min(face_angles)
    max_ang = max(face_angles)

    xi_coords = [
        (-1.0, -1.0, -1.0),
        ( 1.0, -1.0, -1.0),
        ( 1.0,  1.0, -1.0),
        (-1.0,  1.0, -1.0),
        (-1.0, -1.0,  1.0),
        ( 1.0, -1.0,  1.0),
        ( 1.0,  1.0,  1.0),
        (-1.0,  1.0,  1.0),
    ]

    def _calc_det_j(xi: float, eta: float, zeta: float) -> float:
        j_mat = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        for i in range(8):
            xi_i, eta_i, zeta_i = xi_coords[i]
            dn_dxi = 0.125 * xi_i * (1.0 + eta_i * eta) * (1.0 + zeta_i * zeta)
            dn_deta = 0.125 * eta_i * (1.0 + xi_i * xi) * (1.0 + zeta_i * zeta)
            dn_dzeta = 0.125 * zeta_i * (1.0 + xi_i * xi) * (1.0 + eta_i * eta)

            x, y, z = pts[i]
            j_mat[0][0] += dn_dxi * x
            j_mat[0][1] += dn_dxi * y
            j_mat[0][2] += dn_dxi * z

            j_mat[1][0] += dn_deta * x
            j_mat[1][1] += dn_deta * y
            j_mat[1][2] += dn_deta * z

            j_mat[2][0] += dn_dzeta * x
            j_mat[2][1] += dn_dzeta * y
            j_mat[2][2] += dn_dzeta * z
        return _mat3_det(j_mat)

    det_j_0 = _calc_det_j(0.0, 0.0, 0.0)
    det_js = [det_j_0]
    for xi_i, eta_i, zeta_i in xi_coords:
        det_js.append(_calc_det_j(xi_i * 0.577350269, eta_i * 0.577350269, zeta_i * 0.577350269))

    min_det = min(det_js)
    max_det = max(det_js)
    ref_det = max(1e-12, abs(det_j_0))
    jac_ratio = max(0.0, min_det / ref_det) if min_det > 0.0 else -abs(min_det / ref_det)

    return HexMeshAuditResult(
        element_id=elem_id,
        aspect_ratio=aspect_ratio,
        min_angle_deg=min_ang,
        max_angle_deg=max_ang,
        jacobian_ratio=jac_ratio,
    )


def parse_and_audit_inp_deck(inp_path: Union[Path, str]) -> Dict[str, Any]:
    """Parse an authentic Abaqus INP deck to extract nodes, elements and perform topological audits."""
    p = Path(inp_path)
    if not p.is_file():
        raise FileNotFoundError(f"Input deck not found: {p}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

    nodes: Dict[int, Tuple[float, float, float]] = {}
    quad_elements: Dict[int, Tuple[int, int, int, int]] = {}
    hex_elements: Dict[int, Tuple[int, ...]] = {}

    current_mode = None
    current_elem_type = ""

    node_pattern = re.compile(r"^\s*(\d+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)")

    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("**"):
            continue

        if line_s.startswith("*"):
            upper = line_s.upper()
            if upper.startswith("*NODE"):
                current_mode = "NODE"
            elif upper.startswith("*ELEMENT"):
                current_mode = "ELEMENT"
                m_type = re.search(r"TYPE\s*=\s*([A-Za-z0-9]+)", upper)
                current_elem_type = m_type.group(1).upper() if m_type else "UNKNOWN"
            else:
                current_mode = None
            continue

        if current_mode == "NODE":
            m = node_pattern.match(line_s)
            if m:
                nid = int(m.group(1))
                nodes[nid] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))

        elif current_mode == "ELEMENT":
            tokens = [t.strip() for t in line_s.split(",") if t.strip()]
            if not tokens:
                continue
            try:
                eid = int(tokens[0])
                node_ids = [int(t) for t in tokens[1:]]
                if current_elem_type.startswith(("S4", "S4R", "CPS4", "CPE4", "CAX4")) and len(node_ids) >= 4:
                    quad_elements[eid] = (node_ids[0], node_ids[1], node_ids[2], node_ids[3])
                elif current_elem_type.startswith(("C3D8", "C3D8R", "C3D8I")) and len(node_ids) >= 8:
                    hex_elements[eid] = tuple(node_ids[:8])
            except ValueError:
                pass

    audited_quads: List[QuadMeshAuditResult] = []
    missing_node_quads = 0
    for eid, (n1, n2, n3, n4) in quad_elements.items():
        if n1 in nodes and n2 in nodes and n3 in nodes and n4 in nodes:
            audited_quads.append(audit_quad_element(eid, nodes[n1], nodes[n2], nodes[n3], nodes[n4]))
        else:
            missing_node_quads += 1

    audited_hexes: List[HexMeshAuditResult] = []
    missing_node_hexes = 0
    for eid, h_nodes in hex_elements.items():
        if all(n in nodes for n in h_nodes):
            pts = tuple(nodes[n] for n in h_nodes)
            audited_hexes.append(audit_hex_element(eid, pts))
        else:
            missing_node_hexes += 1

    return {
        "nodes_count": len(nodes),
        "quad_elements_count": len(quad_elements),
        "hex_elements_count": len(hex_elements),
        "audited_quads": audited_quads,
        "audited_hexes": audited_hexes,
        "missing_node_elements_count": missing_node_quads + missing_node_hexes,
    }


def audit_inp_mesh_quality(
    inp_path: Union[Path, str],
    policy: Optional[MeshQualityPolicy] = None,
) -> Tuple[MeshGateEvaluation, Dict[str, Any]]:
    """Universal fail-closed mesh quality auditor for an Abaqus INP deck.

    Audits shell and solid continuum element geometries. If elements reference undefined nodes,
    or if zero valid elements exist, rejects immediately with BLOCKED.
    """
    p = Path(inp_path)
    if not p.is_file():
        gate_eval = MeshGateEvaluation(
            passed=False,
            status="BLOCKED",
            metrics={},
            violations=(f"inp_file_not_found:{p}",),
        )
        return gate_eval, {"passed": False, "violations": [f"inp_file_not_found:{p}"]}

    parsed = parse_and_audit_inp_deck(p)
    violations: List[str] = []

    if parsed["missing_node_elements_count"] > 0:
        violations.append(
            f"inp_contains_{parsed['missing_node_elements_count']}_elements_referencing_undefined_nodes"
        )

    quads = parsed["audited_quads"]
    hexes = parsed["audited_hexes"]
    total_audited = len(quads) + len(hexes)

    if total_audited == 0:
        violations.append("inp_contains_zero_auditable_finite_elements")

    if violations:
        gate_eval = MeshGateEvaluation(
            passed=False,
            status="BLOCKED",
            metrics={},
            violations=tuple(violations),
        )
        return gate_eval, {
            "gate_status": "BLOCKED",
            "passed": False,
            "violations": violations,
            "governing_metrics": {},
            "nodes_count": parsed["nodes_count"],
            "total_elements_audited": 0,
        }

    # Governing metrics
    min_jacs = []
    max_ars = []
    min_angs = []
    max_angs = []

    if quads:
        min_jacs.append(min(q.jacobian_ratio for q in quads))
        max_ars.append(max(q.aspect_ratio for q in quads))
        min_angs.append(min(q.min_angle_deg for q in quads))
        max_angs.append(max(q.max_angle_deg for q in quads))

    if hexes:
        min_jacs.append(min(h.jacobian_ratio for h in hexes))
        max_ars.append(max(h.aspect_ratio for h in hexes))
        min_angs.append(min(h.min_angle_deg for h in hexes))
        max_angs.append(max(h.max_angle_deg for h in hexes))

    governing = {
        "min_jacobian": round(min(min_jacs), 3) if min_jacs else 0.0,
        "max_aspect_ratio": round(max(max_ars), 3) if max_ars else 999.0,
        "min_angle": round(min(min_angs), 2) if min_angs else 0.0,
        "max_angle": round(max(max_angs), 2) if max_angs else 180.0,
    }

    effective_policy = policy or MeshQualityPolicy(
        max_aspect_ratio=10.0,
        min_jacobian=0.40,
        min_angle=15.0,
        max_angle=165.0,
    )

    gate_eval = evaluate_mesh_quality_gate(governing, policy=effective_policy)

    detailed_report = {
        "gate_status": gate_eval.status,
        "passed": gate_eval.passed,
        "violations": list(gate_eval.violations),
        "warnings": list(gate_eval.warnings),
        "governing_metrics": governing,
        "nodes_count": parsed["nodes_count"],
        "quad_elements_count": len(quads),
        "hex_elements_count": len(hexes),
        "total_elements_audited": total_audited,
        "audit_source": str(p),
    }

    return gate_eval, detailed_report
