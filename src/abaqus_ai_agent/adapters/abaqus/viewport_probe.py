# Run inside Abaqus/CAE. Read-only probe for the first
# image-to-geometry grounding experiment.

from .extract_geometry import extract_geometry, extract_viewport


def _first_viewport(session):
    names = list(session.viewports.keys())
    if not names:
        raise RuntimeError('no Abaqus viewport is available')
    return session.viewports[names[0]]


def snapshot(session):
    viewport = _first_viewport(session)
    result = {'viewport': extract_viewport(viewport), 'objects': []}
    displayed = viewport.displayedObject
    if displayed is None:
        return result

    instances = getattr(displayed, 'instances', None)
    if instances is not None:
        for name in instances.keys():
            instance = instances[name]
            result['objects'].append({
                'name': name,
                'entity_type': 'Instance',
                'geometry': extract_geometry(instance),
            })
    else:
        name = getattr(displayed, 'name', 'displayedObject')
        result['objects'].append({
            'name': name,
            'entity_type': 'Part',
            'geometry': extract_geometry(displayed),
        })
    return result
