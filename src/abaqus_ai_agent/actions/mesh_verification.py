"""Native Abaqus mesh-verification script rendering.

Kept separate from the general script renderer so the native result contract
is explicit and does not depend on printf-style interpolation of generated
Python source.
"""


def native_mesh_verification_script(model, parameters):
    part = parameters["part"]
    criterion = str(parameters.get("criterion", "ANALYSIS_CHECKS")).upper()
    allowed = (
        "ANALYSIS_CHECKS", "ANGULAR_DEVIATION", "ASPECT_RATIO",
        "GEOM_DEVIATION_FACTOR", "LARGE_ANGLE", "LONGEST_EDGE",
        "MAX_FREQUENCY", "SHAPE_FACTOR", "SHORTEST_EDGE", "SMALL_ANGLE",
        "STABLE_TIME_INCREMENT",
    )
    if criterion not in allowed:
        raise ValueError("unsupported Abaqus mesh verification criterion: %s" % criterion)
    args = ["criterion=%s" % criterion]
    if criterion != "ANALYSIS_CHECKS":
        if parameters.get("threshold") is None:
            raise ValueError("threshold is required for non-analysis mesh verification")
        args.append("threshold=%r" % parameters["threshold"])
    if parameters.get("elem_shape") is not None:
        args.append("elemShape=%s" % parameters["elem_shape"])
    if parameters.get("regions_expression") is not None:
        args.append("regions=%s" % parameters["regions_expression"])

    return """from abaqusConstants import *
model=mdb.models[%r]
part=model.parts[%r]
verification=part.verifyMeshQuality(%s)
failed=verification.get("failedElements", ())
warnings=verification.get("warningElements", ())
na=verification.get("naElements", ())
def labels(values):
    out=[]
    for element in values:
        try: out.append(int(element.label))
        except Exception: pass
    return out
print({"part":%r,"criterion":%r,"num_elements":verification.get("numElements"),
       "average":verification.get("average"),"worst":verification.get("worst"),
       "failed_element_labels":labels(failed),"warning_element_labels":labels(warnings),
       "na_element_labels":labels(na),"status":"fail" if failed else ("warning" if warnings else "pass"),
       "source":"abaqus_native_verify"})
""" % (model, part, ", ".join(args), part, criterion)
