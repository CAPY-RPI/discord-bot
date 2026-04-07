class CapyError(Exception):
    """Base exception class for all Capy Discord errors."""

    pass


class UserFriendlyError(CapyError):
    """An exception that can be safely displayed to the user.

    Attributes:
        user_message (str): The message to display to the user.
    """

    def __init__(self, message: str, user_message: str) -> None:
        """Initialize the error.

        Args:
            message: Internal log message.
            user_message: User-facing message.
        """
        super().__init__(message)
        self.user_message = user_message
