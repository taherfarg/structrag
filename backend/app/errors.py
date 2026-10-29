class AppError(Exception):
    """An error the API reports as {"error": {"code", "message", "details"}}."""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} not found")
