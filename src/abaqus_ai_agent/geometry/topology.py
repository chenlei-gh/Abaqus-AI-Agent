"""Canonical Topology Normalization subsystem for Track GA-1.3A.

Builds normalized, deterministic topological relationships across the full
B-Rep hierarchy: Solid -> Shell -> Face (outer/inner loops) -> Edge -> Vertex.
Provides bidirectional adjacency indices (edge-to-faces, vertex-to-edges,
face-to-face adjacency via shared edges, connected components) with strict
idempotence and zero duplicate CAD kernel dependency.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .model import CadFace, CadLoop, GeometryModel


@dataclass(frozen=True)
class NormalizedTopology:
    """Immutable, deterministic topological graph and adjacency mapping for GA-1.3A.

    Acts as the canonical topological representation consumed by downstream
    feature recognition (GA-1.3B) and adaptive meshing partition strategies (GA-1.4).
    """
    model_id: str
    solid_to_shells: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    shell_to_faces: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    face_to_edges: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    face_to_outer_loop: Dict[str, Optional[CadLoop]] = field(default_factory=dict)
    face_to_inner_loops: Dict[str, Tuple[CadLoop, ...]] = field(default_factory=dict)
    edge_to_vertices: Dict[str, Tuple[Optional[str], Optional[str]]] = field(default_factory=dict)
    edge_to_adjacent_faces: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    vertex_to_incident_edges: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    face_adjacency: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    connected_components: Tuple[Tuple[str, ...], ...] = ()

    @property
    def boundary_edges(self) -> Tuple[str, ...]:
        """Edges belonging to an open sheet boundary (referenced by exactly 1 face)."""
        return tuple(
            eid for eid, faces in sorted(self.edge_to_adjacent_faces.items())
            if len(faces) == 1
        )

    @property
    def manifold_shared_edges(self) -> Tuple[str, ...]:
        """Proper 2-manifold internal edges (referenced by exactly 2 incident faces)."""
        return tuple(
            eid for eid, faces in sorted(self.edge_to_adjacent_faces.items())
            if len(faces) == 2
        )

    @property
    def non_manifold_edges(self) -> Tuple[str, ...]:
        """Non-manifold edges (referenced by > 2 incident faces)."""
        return tuple(
            eid for eid, faces in sorted(self.edge_to_adjacent_faces.items())
            if len(faces) > 2
        )

    @property
    def dangling_edges(self) -> Tuple[str, ...]:
        """Dangling wireframe edges not bound to any boundary face."""
        return tuple(
            eid for eid, faces in sorted(self.edge_to_adjacent_faces.items())
            if len(faces) == 0
        )

    def get_outer_loop(self, face_id: str) -> Optional[CadLoop]:
        """Get the outer bounding loop of a face if resolved."""
        return self.face_to_outer_loop.get(face_id)

    def get_inner_loops(self, face_id: str) -> Tuple[CadLoop, ...]:
        """Get inner hole/void loops of a face."""
        return self.face_to_inner_loops.get(face_id, ())

    def get_adjacent_faces(self, face_id: str) -> Tuple[str, ...]:
        """Get neighboring faces topologically connected via shared edges."""
        return self.face_adjacency.get(face_id, ())

    def get_shared_edges(self, face_id_1: str, face_id_2: str) -> Tuple[str, ...]:
        """Get common edges shared between two faces."""
        edges1 = set(self.face_to_edges.get(face_id_1, ()))
        edges2 = set(self.face_to_edges.get(face_id_2, ()))
        return tuple(sorted(edges1.intersection(edges2)))

    def is_watertight_shell(self, shell_id: str) -> bool:
        """Check if all edges of a given shell are strictly 2-manifold (zero open boundary)."""
        face_ids = set(self.shell_to_faces.get(shell_id, ()))
        if not face_ids:
            return False

        # Count incident faces within this shell
        shell_edge_counts: Dict[str, int] = {}
        for fid in face_ids:
            for eid in self.face_to_edges.get(fid, ()):
                shell_edge_counts[eid] = shell_edge_counts.get(eid, 0) + 1

        # Every edge must be shared by exactly 2 faces within the shell
        for eid, count in shell_edge_counts.items():
            if count != 2:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize normalized topology summary for provenance auditing."""
        return {
            "model_id": self.model_id,
            "counts": {
                "solids": len(self.solid_to_shells),
                "shells": len(self.shell_to_faces),
                "faces": len(self.face_to_edges),
                "edges": len(self.edge_to_adjacent_faces),
                "vertices": len(self.vertex_to_incident_edges),
                "boundary_edges": len(self.boundary_edges),
                "manifold_edges": len(self.manifold_shared_edges),
                "non_manifold_edges": len(self.non_manifold_edges),
                "dangling_edges": len(self.dangling_edges),
                "connected_components": len(self.connected_components),
            },
            "connected_components": [list(c) for c in self.connected_components],
        }


def normalize_topology(model: GeometryModel) -> NormalizedTopology:
    """Construct deterministic NormalizedTopology relationships from GeometryModel.

    Guarantees:
    - Complete bidirectional adjacency graph (Face <-> Edge <-> Vertex)
    - Full loop structure (outer loop + inner hole loops)
    - Connected component resolution
    - Deterministic, lexicographically sorted indexing (100% idempotent)
    """
    solid_to_shells: Dict[str, Tuple[str, ...]] = {}
    for solid in sorted(model.solids, key=lambda s: s.id):
        solid_to_shells[solid.id] = tuple(sorted(solid.shell_ids))

    shell_to_faces: Dict[str, Tuple[str, ...]] = {}
    for shell in sorted(model.shells, key=lambda sh: sh.id):
        shell_to_faces[shell.id] = tuple(sorted(shell.face_ids))

    face_to_edges: Dict[str, Tuple[str, ...]] = {}
    face_to_outer: Dict[str, Optional[CadLoop]] = {}
    face_to_inner: Dict[str, Tuple[CadLoop, ...]] = {}

    edge_to_faces_map: Dict[str, List[str]] = {edge.id: [] for edge in model.edges}

    for face in sorted(model.faces, key=lambda f: f.id):
        # Extract outer loop
        outer_edges: List[str] = []
        if face.outer_loop:
            face_to_outer[face.id] = face.outer_loop
            outer_edges.extend(face.outer_loop.edge_ids)
        else:
            face_to_outer[face.id] = None

        # Extract inner loops
        face_to_inner[face.id] = tuple(sorted(face.inner_loops, key=lambda l: l.id))
        inner_edges: List[str] = []
        for in_loop in face.inner_loops:
            inner_edges.extend(in_loop.edge_ids)

        # Consolidated edge list
        if outer_edges or inner_edges:
            combined_edges = tuple(sorted(set(outer_edges + inner_edges)))
        else:
            combined_edges = tuple(sorted(set(face.edge_ids)))

        face_to_edges[face.id] = combined_edges

        # Register incident edges
        for eid in combined_edges:
            if eid not in edge_to_faces_map:
                edge_to_faces_map[eid] = []
            edge_to_faces_map[eid].append(face.id)

    edge_to_vertices: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    vertex_to_edges_map: Dict[str, List[str]] = {v.id: [] for v in model.vertices}

    for edge in sorted(model.edges, key=lambda e: e.id):
        v_start = edge.start_vertex_id
        v_end = edge.end_vertex_id
        edge_to_vertices[edge.id] = (v_start, v_end)

        if v_start:
            if v_start not in vertex_to_edges_map:
                vertex_to_edges_map[v_start] = []
            vertex_to_edges_map[v_start].append(edge.id)
        if v_end and v_end != v_start:
            if v_end not in vertex_to_edges_map:
                vertex_to_edges_map[v_end] = []
            vertex_to_edges_map[v_end].append(edge.id)

    # Sort adjacency lists for deterministic stability
    edge_to_adjacent_faces = {
        eid: tuple(sorted(faces))
        for eid, faces in sorted(edge_to_faces_map.items())
    }
    vertex_to_incident_edges = {
        vid: tuple(sorted(edges))
        for vid, edges in sorted(vertex_to_edges_map.items())
    }

    # Compute face-to-face adjacency via shared edges
    face_adj_map: Dict[str, Set[str]] = {face.id: set() for face in model.faces}
    for eid, incident_faces in edge_to_adjacent_faces.items():
        if len(incident_faces) >= 2:
            for i in range(len(incident_faces)):
                for j in range(i + 1, len(incident_faces)):
                    f1, f2 = incident_faces[i], incident_faces[j]
                    face_adj_map[f1].add(f2)
                    face_adj_map[f2].add(f1)

    face_adjacency = {
        fid: tuple(sorted(neighbors))
        for fid, neighbors in sorted(face_adj_map.items())
    }

    # Compute connected components among faces using BFS
    visited: Set[str] = set()
    components: List[Tuple[str, ...]] = []

    for fid in sorted(face_adj_map.keys()):
        if fid not in visited:
            comp: List[str] = []
            queue = deque([fid])
            visited.add(fid)
            while queue:
                curr = queue.popleft()
                comp.append(curr)
                for neighbor in face_adjacency.get(curr, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(tuple(sorted(comp)))

    components_tuple = tuple(sorted(components, key=lambda c: (len(c), c[0] if c else "")))

    return NormalizedTopology(
        model_id=model.model_id,
        solid_to_shells=solid_to_shells,
        shell_to_faces=shell_to_faces,
        face_to_edges=face_to_edges,
        face_to_outer_loop=face_to_outer,
        face_to_inner_loops=face_to_inner,
        edge_to_vertices=edge_to_vertices,
        edge_to_adjacent_faces=edge_to_adjacent_faces,
        vertex_to_incident_edges=vertex_to_incident_edges,
        face_adjacency=face_adjacency,
        connected_components=components_tuple,
    )
