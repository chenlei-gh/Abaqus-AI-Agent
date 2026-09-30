class AbaqusExecutionError(RuntimeError):
    def __init__(self, message, *, payload=None, category="execution", traceback=None,
                 source_line=None, code_excerpt=None, context=None, recovery_hint=None):
        super().__init__(message)
        self.payload = payload
        self.category = category
        self.traceback = traceback
        self.source_line = source_line
        self.code_excerpt = code_excerpt
        self.context = context or {}
        self.recovery_hint = recovery_hint

    def diagnostic(self):
        return {"category": self.category, "message": str(self), "traceback": self.traceback,
                "source_line": self.source_line, "code_excerpt": self.code_excerpt,
                "context": self.context, "recovery_hint": self.recovery_hint}


class AbaqusConnectionError(AbaqusExecutionError):
    def __init__(self, message, *, payload=None, **kwargs):
        super().__init__(message, payload=payload, category="connection", **kwargs)


def classify_execution_error(message, payload=None):
    low = str(message or "").lower()
    markers = (("syntax", "syntax"), ("license", "license"), ("timeout", "timeout"),
               ("attributeerror", "abaqus_api"), ("typeerror", "abaqus_api"),
               ("keyerror", "object_missing"), ("indexerror", "object_missing"),
               ("region", "region_invalid"), ("set not found", "region_invalid"),
               ("solver", "solver"), ("odb", "odb"))
    for marker, category in markers:
        if marker in low:
            return category
    return "execution"
