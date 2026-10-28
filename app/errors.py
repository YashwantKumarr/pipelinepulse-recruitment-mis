class AppError(Exception):
    """Expected, client-facing error. Messages must never echo resume or candidate content."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
