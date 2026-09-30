from .client import AbaqusExecutor


def capture_viewport_script(path, viewport_name=None, image_format="PNG"):
    if viewport_name is None:
        return """from abaqusConstants import PNG\nvp = session.viewports[session.currentViewportName]\nsession.printToFile(fileName=%r, format=PNG, canvasObjects=(vp,))\nprint(%r)""" % (path, path)
    return """from abaqusConstants import PNG\nvp = session.viewports[%r]\nsession.printToFile(fileName=%r, format=PNG, canvasObjects=(vp,))\nprint(%r)""" % (viewport_name, path, path)


def capture_viewport(executor, path, viewport_name=None):
    return executor.execute(capture_viewport_script(path, viewport_name))
