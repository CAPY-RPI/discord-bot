import pytest

from capy_discord.errors import CapyError, UserFriendlyError


def test_capy_error_inheritance():
    assert issubclass(CapyError, Exception)


def test_user_friendly_error_inheritance():
    assert issubclass(UserFriendlyError, CapyError)


def test_capy_error_message():
    msg = "test error"
    with pytest.raises(CapyError) as exc_info:
        raise CapyError(msg)
    assert str(exc_info.value) == msg


def test_user_friendly_error_attributes():
    internal_msg = "internal error log"
    user_msg = "User-facing message"

    with pytest.raises(UserFriendlyError) as exc_info:
        raise UserFriendlyError(internal_msg, user_msg)

    assert str(exc_info.value) == internal_msg
    assert exc_info.value.user_message == user_msg
