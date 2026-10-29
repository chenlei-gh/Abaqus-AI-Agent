"""CAD-linked local incremental remeshing for failed tetrahedra.

The input is ``_abqai_quality_failed``, the failed elements from the previous
quality check. The fragment maps them to CAD cells, changes one documented
local scheme, deletes only that native-mesh region, and calls
``generateMesh(regions=...)``.

Deleting the only cell and regenerating it with the same part seed reproduced
the same mesh on the machine. Official edge seeds override part seeds, so a
later attempt must change the scheme before deletion. Attempts 2 and 3 seed
the edges of geometric faces that contain the current failed elements at
``part_size / 2**(attempt-1)``. Attempt 3 also adds face-adjacent cells that
are not already in the region. A single-cell part cannot expand, so attempt 3
stays on the current failed-host faces and uses the finer local edge seed.

Attempts 4 and 5 do not keep dividing that seed. Attempt 4 redistributes the
already chosen local size toward both ends of the failed-host edges with
``seedEdgeByBias(biasMethod=DOUBLE, endEdges=...)``. Official bias seeding has
no curvature controls, and ``endEdges`` places the smallest elements at the
edge ends without guessing which geometric vertex is which. Attempt 5 leaves
the edge seeds unchanged and sets ``sizeGrowth=MAXIMUM`` only on the located
cells. Official size growth changes the interior transition of the default
tetrahedron mesher; it is not another edge-size divisor. The fragment never
changes the global part seed, selects ``algorithm=NON_DEFAULT``, or calls
whole-part ``deleteMesh()``.

An edge seed or bias that cannot be read back, an identical previous scheme,
or a mesh fingerprint that does not change, is not a successful remesh.
"""

MAX_LOCAL_REMESH_ATTEMPT = 5


def local_remesh_script(part_expr, attempt, previous_hosts="_abqai_local_host_indices"):
    """Emit one located local incremental-remesh attempt.

    ``attempt`` is 2 through 5. Attempts 2 and 3 change the local edge size.
    Attempt 3 also tries to add cells adjacent to the previous region.
    Attempts 4 and 5 keep the current failed-host region and change node
    distribution or interior growth instead of dividing the seed again.
    The caller owns quality checks before and after this fragment.
    """
    if attempt not in (2, 3, 4, 5):
        raise ValueError("local remesh attempt must be 2, 3, 4, or 5")
    if not str(part_expr).strip():
        raise ValueError("local remesh requires a part expression")
    expansion = ""
    if attempt == 3:
        expansion = (
            "for _abqai_index in {previous}:\n"
            "    if _abqai_index not in _abqai_local_region_indices:\n"
            "        _abqai_local_region_indices.append(_abqai_index)\n"
            "for _abqai_index in tuple(_abqai_local_region_indices):\n"
            "    for _abqai_neighbor in ({part}.cells[_abqai_index].getAdjacentCells() or ()):\n"
            "        if int(_abqai_neighbor.index) not in _abqai_local_region_indices:\n"
            "            _abqai_local_region_indices.append(int(_abqai_neighbor.index))\n"
            "_abqai_local_region_expanded = not (set(_abqai_local_region_indices) <= set({previous}))\n"
        ).format(part=part_expr, previous=previous_hosts)
    if attempt in (2, 3):
        scheme = (
            "_abqai_local_scheme = 'host_edge_seed'\n"
            "_abqai_local_seed_divisor = float(2 ** ({attempt} - 1))\n"
            "_abqai_local_seed_scope = 'host_faces'\n"
            "if {attempt} > 2 and globals().get('_abqai_local_region_expanded', False):\n"
            "    _abqai_local_scheme = 'expanded_edge_seed'\n"
            "    _abqai_local_seed_scope = 'expanded_cells'\n"
            "elif {attempt} > 2:\n"
            "    _abqai_local_scheme = 'finer_edge_seed'\n"
            "    _abqai_local_seed_scope = 'failed_host_faces_finer'\n"
        ).format(attempt=attempt)
        action = (
            "_abqai_local_seed_size = _abqai_local_base_seed / _abqai_local_seed_divisor\n"
            "if not _abqai_local_seed_size or _abqai_local_seed_size <= 0.0:\n"
            "    raise RuntimeError('tet_local_seed_size_unresolved')\n"
            "{part}.seedEdgeBySize(edges=_abqai_local_seed_edges, size=_abqai_local_seed_size, deviationFactor=0.1, minSizeFactor=0.1, constraint=FINER)\n"
            "_abqai_local_seed_readback = []\n"
            "for _abqai_edge in _abqai_local_seed_edges:\n"
            "    _abqai_observed = {part}.getEdgeSeeds(edge=_abqai_edge, attribute=EDGE_SEEDING_METHOD)\n"
            "    if _abqai_observed is None:\n"
            "        raise RuntimeError('tet_local_edge_seed_not_applied')\n"
            "    _abqai_local_seed_readback.append(str(_abqai_observed))\n"
            "if len(_abqai_local_seed_readback) != len(_abqai_local_seed_edges):\n"
            "    raise RuntimeError('tet_local_edge_seed_readback_incomplete')\n"
        ).format(part=part_expr)
    elif attempt == 4:
        scheme = (
            "_abqai_local_scheme = 'edge_end_bias'\n"
            "_abqai_local_seed_scope = 'failed_host_edge_ends'\n"
            "_abqai_local_seed_divisor = globals().get('_abqai_local_seed_divisor')\n"
        )
        action = (
            "if 'DOUBLE' not in globals() or 'BIASED' not in globals() or 'BIAS_METHOD' not in globals():\n"
            "    from abaqusConstants import DOUBLE, BIASED, BIAS_METHOD, BIAS_MIN_SIZE, BIAS_MAX_SIZE\n"
            "_abqai_local_bias_min = globals().get('_abqai_local_seed_size')\n"
            "if not _abqai_local_bias_min or float(_abqai_local_bias_min) <= 0.0:\n"
            "    _abqai_local_bias_min = _abqai_local_base_seed / 2.0\n"
            "_abqai_local_bias_max = _abqai_local_base_seed\n"
            "if not _abqai_local_bias_max or float(_abqai_local_bias_min) >= float(_abqai_local_bias_max):\n"
            "    raise RuntimeError('tet_local_bias_size_pair_invalid')\n"
            "_abqai_local_seed_size = float(_abqai_local_bias_min)\n"
            "{part}.seedEdgeByBias(biasMethod=DOUBLE, endEdges=_abqai_local_seed_edges, minSize=float(_abqai_local_bias_min), maxSize=float(_abqai_local_bias_max), constraint=FINER)\n"
            "_abqai_local_seed_readback = []\n"
            "for _abqai_edge in _abqai_local_seed_edges:\n"
            "    _abqai_method = {part}.getEdgeSeeds(edge=_abqai_edge, attribute=EDGE_SEEDING_METHOD)\n"
            "    _abqai_bias = {part}.getEdgeSeeds(edge=_abqai_edge, attribute=BIAS_METHOD)\n"
            "    _abqai_min_read = {part}.getEdgeSeeds(edge=_abqai_edge, attribute=BIAS_MIN_SIZE)\n"
            "    _abqai_max_read = {part}.getEdgeSeeds(edge=_abqai_edge, attribute=BIAS_MAX_SIZE)\n"
            "    if str(_abqai_method) != str(BIASED) or str(_abqai_bias) != str(DOUBLE):\n"
            "        raise RuntimeError('tet_local_edge_bias_not_applied')\n"
            "    if not _abqai_min_read or not _abqai_max_read or float(_abqai_min_read) <= 0.0 or float(_abqai_max_read) <= 0.0:\n"
            "        raise RuntimeError('tet_local_edge_bias_readback_incomplete')\n"
            "    _abqai_local_seed_readback.append((str(_abqai_method), str(_abqai_bias)))\n"
            "if len(_abqai_local_seed_readback) != len(_abqai_local_seed_edges):\n"
            "    raise RuntimeError('tet_local_edge_bias_readback_incomplete')\n"
        ).format(part=part_expr)
    else:
        scheme = (
            "_abqai_local_scheme = 'interior_growth_maximum'\n"
            "_abqai_local_seed_scope = 'located_cells_growth'\n"
            "_abqai_local_seed_divisor = globals().get('_abqai_local_seed_divisor')\n"
        )
        action = (
            "if 'MAXIMUM' not in globals() or 'ELEM_SHAPE' not in globals() or 'TECHNIQUE' not in globals():\n"
            "    from abaqusConstants import MAXIMUM, ELEM_SHAPE, TECHNIQUE\n"
            "{part}.setMeshControls(regions=_abqai_local_cells, elemShape=TET, technique=FREE, sizeGrowth=MAXIMUM)\n"
            "_abqai_local_growth_readback = []\n"
            "for _abqai_index in _abqai_local_region_indices:\n"
            "    _abqai_cell = {part}.cells[_abqai_index]\n"
            "    _abqai_shape = {part}.getMeshControl(region=_abqai_cell, attribute=ELEM_SHAPE)\n"
            "    _abqai_technique = {part}.getMeshControl(region=_abqai_cell, attribute=TECHNIQUE)\n"
            "    if str(_abqai_shape) != str(TET) or str(_abqai_technique) != str(FREE):\n"
            "        raise RuntimeError('tet_local_growth_controls_not_applied')\n"
            "    _abqai_local_growth_readback.append((str(_abqai_shape), str(_abqai_technique)))\n"
            "if len(_abqai_local_growth_readback) != len(_abqai_local_region_indices):\n"
            "    raise RuntimeError('tet_local_growth_controls_not_applied')\n"
        ).format(part=part_expr)
    return (
        "_abqai_local_attempt = {attempt}\n"
        "_abqai_local_status = 'not_attempted'\n"
        "_abqai_previous_scheme = globals().get('_abqai_local_scheme')\n"
        "_abqai_previous_seed_divisor = globals().get('_abqai_local_seed_divisor')\n"
        "_abqai_previous_seed_edges = globals().get('_abqai_local_seed_edge_count')\n"
        "_abqai_previous_region = list(globals().get('_abqai_local_region_indices', ()) or ())\n"
        "_abqai_local_failed_labels = set(\n"
        "    int(_abqai_element.label) for _abqai_element in _abqai_quality_failed)\n"
        "if not _abqai_local_failed_labels:\n"
        "    raise RuntimeError('tet_local_quality_failure_has_no_locatable_elements')\n"
        "_abqai_local_current_hosts = []\n"
        "_abqai_local_found_labels = set()\n"
        "for _abqai_cell in {part}.cells:\n"
        "    for _abqai_element in (_abqai_cell.getElements() or ()):\n"
        "        _abqai_label = int(_abqai_element.label)\n"
        "        if _abqai_label in _abqai_local_failed_labels:\n"
        "            if int(_abqai_cell.index) not in _abqai_local_current_hosts:\n"
        "                _abqai_local_current_hosts.append(int(_abqai_cell.index))\n"
        "            _abqai_local_found_labels.add(_abqai_label)\n"
        "_abqai_local_unresolved = sorted(\n"
        "    _abqai_local_failed_labels - _abqai_local_found_labels)\n"
        "if _abqai_local_unresolved:\n"
        "    raise RuntimeError('tet_local_host_cell_unresolved: CAD-associated cells were not found for failed element labels ' + "
        "str(_abqai_local_unresolved) + '; arbitrary 3D orphan-mesh local remeshing is unsupported')\n"
        "_abqai_local_region_indices = list(_abqai_local_current_hosts)\n"
        "{expansion}"
        "_abqai_local_points = []\n"
        "for _abqai_index in _abqai_local_region_indices:\n"
        "    _abqai_point = {part}.cells[_abqai_index].pointOn\n"
        "    if len(_abqai_point) == 1 and isinstance(_abqai_point[0], (tuple, list)):\n"
        "        _abqai_point = _abqai_point[0]\n"
        "    _abqai_local_points.append(tuple(float(_abqai_value) for _abqai_value in _abqai_point))\n"
        "_abqai_local_cells = {part}.cells.findAt(tuple(_abqai_local_points), printWarning=False)\n"
        "if not _abqai_local_cells:\n"
        "    raise RuntimeError('tet_local_region_empty')\n"
        "_abqai_local_host_faces = []\n"
        "_abqai_local_seen_faces = set()\n"
        "for _abqai_face in {part}.faces:\n"
        "    _abqai_face_hit = False\n"
        "    for _abqai_element in (_abqai_face.getElements() or ()):\n"
        "        if int(_abqai_element.label) in _abqai_local_failed_labels:\n"
        "            _abqai_face_hit = True\n"
        "            break\n"
        "    if _abqai_face_hit and id(_abqai_face) not in _abqai_local_seen_faces:\n"
        "        _abqai_local_seen_faces.add(id(_abqai_face))\n"
        "        _abqai_local_host_faces.append(_abqai_face)\n"
        "_abqai_local_base_seed = None\n"
        "for _abqai_seed_attr in ('SIZE', 'DEFAULT_SIZE'):\n"
        "    try:\n"
        "        _abqai_local_base_seed = float({part}.getPartSeeds(attribute=globals()[_abqai_seed_attr]))\n"
        "    except Exception:\n"
        "        _abqai_local_base_seed = None\n"
        "    if _abqai_local_base_seed and _abqai_local_base_seed > 0.0:\n"
        "        break\n"
        "if not _abqai_local_base_seed or _abqai_local_base_seed <= 0.0:\n"
        "    raise RuntimeError('tet_local_seed_size_unresolved')\n"
        "{scheme}"
        "if not _abqai_local_host_faces:\n"
        "    raise RuntimeError('tet_local_host_faces_unresolved: failed labels ' + str(sorted(_abqai_local_failed_labels)))\n"
        "_abqai_local_seed_edges = []\n"
        "_abqai_local_seen_edges = set()\n"
        "for _abqai_face in _abqai_local_host_faces:\n"
        "    for _abqai_edge_index in (_abqai_face.getEdges() or ()):\n"
        "        _abqai_edge_index = int(_abqai_edge_index)\n"
        "        if _abqai_edge_index not in _abqai_local_seen_edges:\n"
        "            _abqai_local_seen_edges.add(_abqai_edge_index)\n"
        "            _abqai_local_seed_edges.append({part}.edges[_abqai_edge_index])\n"
        "if not _abqai_local_seed_edges:\n"
        "    raise RuntimeError('tet_local_seed_edges_unresolved')\n"
        "if {attempt} > 2:\n"
        "    _abqai_same_region = list(_abqai_previous_region) == list(_abqai_local_region_indices)\n"
        "    _abqai_same_scheme = _abqai_previous_scheme == _abqai_local_scheme\n"
        "    _abqai_same_seed = (\n"
        "        _abqai_previous_seed_edges is not None and _abqai_previous_seed_divisor is not None and\n"
        "        len(_abqai_local_seed_edges) == int(_abqai_previous_seed_edges) and\n"
        "        float(_abqai_previous_seed_divisor) == float(_abqai_local_seed_divisor))\n"
        "    if _abqai_same_region and _abqai_same_scheme and (_abqai_local_scheme != 'finer_edge_seed' or _abqai_same_seed):\n"
        "        raise RuntimeError('tet_local_scheme_not_different: attempt=' + str({attempt}))\n"
        "_abqai_local_before = (len({part}.elements), len({part}.nodes))\n"
        "try:\n"
        "{action}"
        "    {part}.deleteMesh(regions=_abqai_local_cells)\n"
        "    {part}.generateMesh(regions=_abqai_local_cells)\n"
        "except BaseException as _abqai_local_exc:\n"
        "    raise RuntimeError('tet_local_incremental_remesh_failed:{attempt}: region=' + "
        "str(_abqai_local_region_indices) + ' scope=' + _abqai_local_seed_scope + ': ' + str(_abqai_local_exc))\n"
        "_abqai_local_after = (len({part}.elements), len({part}.nodes))\n"
        "_abqai_local_region_elements = 0\n"
        "for _abqai_index in _abqai_local_region_indices:\n"
        "    _abqai_local_region_elements += len({part}.cells[_abqai_index].getElements() or ())\n"
        "if _abqai_local_region_elements <= 0:\n"
        "    raise RuntimeError('tet_local_region_unmeshed_after_remesh:' + str(_abqai_local_region_indices))\n"
        "_abqai_local_mesh_changed = _abqai_local_before != _abqai_local_after\n"
        "_abqai_local_host_indices = list(_abqai_local_region_indices)\n"
        "_abqai_local_seed_edge_count = len(_abqai_local_seed_edges)\n"
        "_abqai_local_status = 'applied_' + _abqai_local_seed_scope\n"
    ).format(
        part=part_expr,
        attempt=attempt,
        expansion=expansion,
        scheme=scheme,
        action="".join("    " + line + "\n" for line in action.splitlines()),
    )
