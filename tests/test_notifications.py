"""Tests for zeython.notifications -- multi-channel (mail/database/broadcast)
notifications, mirroring Laravel's Notification system.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.mail import LogMailer, Mailer, Message
from zeython.notifications import (
    Notification,
    NotificationManager,
    NotificationServiceProvider,
    mark_as_read,
    notify,
    unread_notifications,
)
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client
from zeython.websockets import WebSocketHub, WebSocketHubServiceProvider


class NotifUser(Model):
    __tablename__ = "notif_test_users"
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))


class NotifRecord(Model):
    __tablename__ = "notif_test_records"
    notifiable_id: Mapped[int] = mapped_column(Integer, ForeignKey("notif_test_users.id"))
    type: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatabaseOnlyNotification(Notification):
    def via(self, notifiable: Any) -> list[str]:
        return ["database"]

    def to_database(self, notifiable: Any) -> dict:
        return {"message": f"hi {notifiable.name}"}


class MailOnlyNotification(Notification):
    def via(self, notifiable: Any) -> list[str]:
        return ["mail"]

    def to_mail(self, notifiable: Any) -> Message:
        return Message(to=notifiable.email, subject="Hello", body="Hi there")


class BroadcastOnlyNotification(Notification):
    def via(self, notifiable: Any) -> list[str]:
        return ["broadcast"]

    def to_database(self, notifiable: Any) -> dict:
        return {"message": "broadcast payload"}


class UnknownChannelNotification(Notification):
    def via(self, notifiable: Any) -> list[str]:
        return ["carrier-pigeon"]


class MailThenDatabaseNotification(Notification):
    def via(self, notifiable: Any) -> list[str]:
        return ["mail", "database"]

    def to_mail(self, notifiable: Any) -> Message:
        return Message(to=notifiable.email, subject="x", body="x")

    def to_database(self, notifiable: Any) -> dict:
        return {"message": "still delivered"}


class _RaisingMailer(Mailer):
    async def send(self, message: Message) -> None:
        raise RuntimeError("SMTP is down")


async def _make_app(
    tmp_path: Path, *, record_model: type[Model] | None = NotifRecord, mailer: Mailer | None = None, hub: bool = False
) -> tuple[Application, int]:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n")

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(NotificationServiceProvider(app, record_model=record_model))
    if hub:
        app.register(WebSocketHubServiceProvider)

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    mailer = mailer or LogMailer()
    app.container.singleton(Mailer, lambda: mailer)

    async with database.session():
        user = await NotifUser.create(email="ada@example.com", name="Ada")
        user_id = user.id

    return app, user_id


# -- Channels, via a real request round-trip ---------------------------------------------------


async def test_database_channel_writes_a_record(tmp_path: Path) -> None:
    app, user_id = await _make_app(tmp_path)

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, DatabaseOnlyNotification())
        return JSONResponse({"ok": True})

    @app.get("/check")
    async def check(request):
        rows = await NotifRecord.find_by(notifiable_id=user_id)
        return JSONResponse([r.data for r in rows])

    async with client(app) as http:
        await http.post("/notify")
        response = await http.get("/check")
        assert response.json() == [{"message": "hi Ada"}]


async def test_mail_channel_sends_through_the_bound_mailer(tmp_path: Path) -> None:
    sent: list[Message] = []

    class _CapturingMailer(Mailer):
        async def send(self, message: Message) -> None:
            sent.append(message)

    app, user_id = await _make_app(tmp_path, mailer=_CapturingMailer())

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, MailOnlyNotification())
        return JSONResponse({"ok": True})

    async with client(app) as http:
        await http.post("/notify")

    assert len(sent) == 1
    assert sent[0].to == "ada@example.com"
    assert sent[0].subject == "Hello"


async def test_broadcast_channel_uses_the_bound_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, user_id = await _make_app(tmp_path, hub=True)
    captured: list[Any] = []

    async def fake_broadcast(self, message, *, exclude=None):
        captured.append(message)

    monkeypatch.setattr(WebSocketHub, "broadcast", fake_broadcast)

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, BroadcastOnlyNotification())
        return JSONResponse({"ok": True})

    async with client(app) as http:
        await http.post("/notify")

    assert len(captured) == 1
    assert captured[0]["type"] == "BroadcastOnlyNotification"
    assert captured[0]["data"] == {"message": "broadcast payload"}


def test_to_broadcast_defaults_to_the_to_database_payload() -> None:
    class _Notifiable:
        name = "Ada"

    notification = DatabaseOnlyNotification()
    notifiable = _Notifiable()
    assert notification.to_broadcast(notifiable) == notification.to_database(notifiable)


# -- Error handling ------------------------------------------------------------------------


async def test_database_channel_without_a_record_model_raises_a_clear_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app, user_id = await _make_app(tmp_path, record_model=None)

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, DatabaseOnlyNotification())
        return JSONResponse({"ok": True})

    with caplog.at_level("ERROR"):
        async with client(app) as http:
            response = await http.post("/notify")
            assert response.status_code == 200  # the channel error is logged, not raised to the client

    assert "record_model" in caplog.text


async def test_broadcast_channel_without_a_hub_registered_raises_a_clear_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app, user_id = await _make_app(tmp_path, hub=False)

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, BroadcastOnlyNotification())
        return JSONResponse({"ok": True})

    with caplog.at_level("ERROR"):
        async with client(app) as http:
            await http.post("/notify")

    assert "WebSocketHubServiceProvider" in caplog.text


async def test_unknown_channel_logs_a_warning_and_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app, user_id = await _make_app(tmp_path)

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, UnknownChannelNotification())
        return JSONResponse({"ok": True})

    with caplog.at_level("WARNING"):
        async with client(app) as http:
            response = await http.post("/notify")
            assert response.status_code == 200

    assert "carrier-pigeon" in caplog.text


async def test_a_failing_channel_does_not_block_another(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app, user_id = await _make_app(tmp_path, mailer=_RaisingMailer())

    @app.post("/notify")
    async def fire(request):
        user = await NotifUser.find(user_id)
        await notify(request, user, MailThenDatabaseNotification())
        return JSONResponse({"ok": True})

    with caplog.at_level("ERROR"):
        async with client(app) as http:
            await http.post("/notify")

    async with app.container.make(Database).session():
        rows = await NotifRecord.find_by(notifiable_id=user_id)
    assert [r.data for r in rows] == [{"message": "still delivered"}]
    assert "SMTP is down" in caplog.text or "mail" in caplog.text.lower()


# -- unread_notifications / mark_as_read -------------------------------------------------------


async def test_unread_notifications_excludes_read_ones_newest_first(tmp_path: Path) -> None:
    app, user_id = await _make_app(tmp_path)

    async with app.container.make(Database).session():
        user = await NotifUser.find(user_id)
        first = await NotifRecord.create(notifiable_id=user.id, type="A", data={})
        second = await NotifRecord.create(notifiable_id=user.id, type="B", data={})
        await mark_as_read(first)

        unread = await unread_notifications(user, NotifRecord)
        assert [row.id for row in unread] == [second.id]


async def test_mark_as_read_stamps_read_at(tmp_path: Path) -> None:
    app, user_id = await _make_app(tmp_path)

    async with app.container.make(Database).session():
        user = await NotifUser.find(user_id)
        record = await NotifRecord.create(notifiable_id=user.id, type="A", data={})
        assert record.read_at is None

        updated = await mark_as_read(record)
        assert updated.read_at is not None


# -- Direct resolution outside a request (mirrors dispatch()/emit()) ---------------------------


async def test_notification_manager_resolved_directly_outside_a_request(tmp_path: Path) -> None:
    app, user_id = await _make_app(tmp_path)

    async with app.container.make(Database).session():
        user = await NotifUser.find(user_id)
        manager = app.container.make(NotificationManager)
        await manager.notify(user, DatabaseOnlyNotification())

        rows = await NotifRecord.find_by(notifiable_id=user.id)
        assert [r.data for r in rows] == [{"message": "hi Ada"}]


# -- Notification base class defaults ------------------------------------------------------


def test_via_defaults_to_the_database_channel() -> None:
    assert Notification().via(object()) == ["database"]


async def test_to_mail_not_overridden_raises_notimplementederror() -> None:
    with pytest.raises(NotImplementedError):
        Notification().to_mail(object())


async def test_to_database_not_overridden_raises_notimplementederror() -> None:
    with pytest.raises(NotImplementedError):
        Notification().to_database(object())
