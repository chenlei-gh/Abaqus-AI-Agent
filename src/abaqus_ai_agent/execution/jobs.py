from .client import AbaqusExecutor


def submit_job_script(job_name, wait=False):
    wait_code = "job.waitForCompletion()" if wait else ""
    return """job = mdb.jobs[%r]\njob.submit(consistencyChecking=OFF)\n%s\nprint(job.status)""" % (job_name, wait_code)


def submit_job(executor, job_name, wait=False):
    return executor.execute(submit_job_script(job_name, wait))


def job_status(executor, job_name):
    code = "job = mdb.jobs[%r]\nprint(job.status)" % job_name
    return executor.execute(code)
