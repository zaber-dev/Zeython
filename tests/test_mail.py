import logging
from unittest.mock import MagicMock, patch

from zeython.application import Application
from zeython.config import Config
from zeython.mail import LogMailer, Mailer, MailServiceProvider, Message, SmtpMailer

# -- Message --------------------------------------------------------------------------


def test_recipients_wraps_a_single_address() -> None:
    message = Message(to="ada@example.com", subject="Hi", body="Hello")
    assert message.recipients() == ["ada@example.com"]


def test_recipients_passes_through_a_list() -> None:
    message = Message(to=["ada@example.com", "grace@example.com"], subject="Hi", body="Hello")
    assert message.recipients() == ["ada@example.com", "grace@example.com"]


# -- LogMailer --------------------------------------------------------------------------


async def test_log_mailer_logs_the_message(caplog) -> None:
    mailer = LogMailer()
    message = Message(to="ada@example.com", subject="Welcome", body="Hello Ada")

    with caplog.at_level(logging.INFO, logger="zeython.mail"):
        await mailer.send(message)

    assert "ada@example.com" in caplog.text
    assert "Welcome" in caplog.text
    assert "Hello Ada" in caplog.text


# -- SmtpMailer ---------------------------------------------------------------------------


async def test_smtp_mailer_sends_over_smtp_with_tls_and_auth() -> None:
    mailer = SmtpMailer(
        host="smtp.example.com",
        port=587,
        username="user",
        password="secret",
        use_tls=True,
        default_from="no-reply@example.com",
    )
    message = Message(to="ada@example.com", subject="Welcome", body="Hello Ada")

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client

    with patch("smtplib.SMTP", return_value=mock_client) as mock_smtp:
        await mailer.send(message)

    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    mock_client.starttls.assert_called_once()
    mock_client.login.assert_called_once_with("user", "secret")
    assert mock_client.send_message.call_count == 1

    sent_email = mock_client.send_message.call_args[0][0]
    assert sent_email["Subject"] == "Welcome"
    assert sent_email["From"] == "no-reply@example.com"
    assert sent_email["To"] == "ada@example.com"


async def test_smtp_mailer_skips_login_without_credentials() -> None:
    mailer = SmtpMailer(
        host="localhost", port=25, username=None, password=None, use_tls=False, default_from="a@b.com"
    )
    message = Message(to="ada@example.com", subject="Hi", body="Hello")

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client

    with patch("smtplib.SMTP", return_value=mock_client):
        await mailer.send(message)

    mock_client.starttls.assert_not_called()
    mock_client.login.assert_not_called()


async def test_smtp_mailer_message_from_overrides_default() -> None:
    mailer = SmtpMailer(
        host="localhost", port=25, username=None, password=None, use_tls=False, default_from="default@example.com"
    )
    message = Message(to="ada@example.com", subject="Hi", body="Hello", from_address="custom@example.com")

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client

    with patch("smtplib.SMTP", return_value=mock_client):
        await mailer.send(message)

    sent_email = mock_client.send_message.call_args[0][0]
    assert sent_email["From"] == "custom@example.com"


# -- MailServiceProvider ---------------------------------------------------------------------


def test_default_driver_binds_log_mailer(tmp_path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(MailServiceProvider)

    assert isinstance(app.container.make(Mailer), LogMailer)


def test_smtp_driver_binds_smtp_mailer_with_config(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "MAIL_DRIVER=smtp\nMAIL_HOST=smtp.example.com\nMAIL_PORT=2525\n"
        "MAIL_USERNAME=user\nMAIL_PASSWORD=secret\nMAIL_ENCRYPTION=none\n"
        "MAIL_FROM_ADDRESS=hello@example.com\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(MailServiceProvider)

    mailer = app.container.make(Mailer)
    assert isinstance(mailer, SmtpMailer)
    assert mailer.host == "smtp.example.com"
    assert mailer.port == 2525
    assert mailer.username == "user"
    assert mailer.use_tls is False
    assert mailer.default_from == "hello@example.com"
