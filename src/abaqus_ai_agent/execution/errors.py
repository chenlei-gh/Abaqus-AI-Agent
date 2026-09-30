class AbaqusExecutionError(RuntimeError):
    def __init__(self, message, *, payload=None):
        super().__init__(message)
        self.payload = payload


class AbaqusConnectionError(AbaqusExecutionError):
    pass
