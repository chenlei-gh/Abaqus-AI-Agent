def get_model_info(executor):
    """Read-only model inventory through the executor."""
    code = ("import json\n"
            "result={}\n"
            "result['models']=list(mdb.models.keys())\n"
            "result['jobs']=list(mdb.jobs.keys())\n"
            "print(json.dumps(result))")
    return executor.execute(code)


def capture_viewport(executor, path="abaqus_viewport.png"):
    if hasattr(executor, "capture_viewport"):
        return executor.capture_viewport(path)
    return executor.execute(
        "session.printToFile(fileName=%r, format=PNG, "
        "canvasObjects=(session.viewports[session.currentViewportName],))" % path)
