def inspect_odb(executor, path):
    if hasattr(executor, "inspect_odb"):
        return executor.inspect_odb(path)
    code = ("from odbAccess import openOdb\n"
            "odb=openOdb(path=%r, readOnly=True)\n"
            "result={'steps':list(odb.steps.keys()),'instances':list(odb.rootAssembly.instances.keys())}\n"
            "odb.close()\n"
            "print(result)") % path
    return executor.execute(code)


def extract_field(executor, path, step, field):
    code = ("from odbAccess import openOdb\n"
            "odb=openOdb(path=%r, readOnly=True)\n"
            "st=odb.steps[%r]\nfr=st.frames[-1]\n"
            "fo=fr.fieldOutputs[%r]\nresult=[]\n"
            "for v in fo.values:\n"
            "    result.append({'label':getattr(v,'nodeLabel',getattr(v,'elementLabel',None)),'data':v.data})\n"
            "odb.close()\nprint(result)") % (path, step, field)
    return executor.execute(code)


def summarize_numeric(values):
    nums = []
    for item in values or ():
        data = item.get("data") if isinstance(item, dict) else None
        if isinstance(data, (int, float)):
            nums.append(float(data))
        elif isinstance(data, (tuple, list)):
            nums.extend(float(x) for x in data if isinstance(x, (int, float)))
    if not nums:
        return {"count": 0, "minimum": None, "maximum": None, "average": None}
    return {"count": len(nums), "minimum": min(nums), "maximum": max(nums),
            "average": sum(nums) / len(nums)}
