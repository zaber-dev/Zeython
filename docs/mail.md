# Mail

`zeython.mail` gives you a `Mailer` interface, a `Message` to send, and two
backends: `LogMailer` (the default — writes to your logs instead of
sending, so a fresh project needs zero mail configuration) and `SmtpMailer`
(stdlib `smtplib`, no third-party dependency).

## Sending

```python
from zeython import Mailer, Message

async def handle_something(mailer: Mailer):
    await mailer.send(Message(
        to="ada@example.com",
        subject="Welcome!",
        body="Hi Ada, welcome aboard.",
        html="<p>Hi Ada, <b>welcome</b> aboard.</p>",   # optional
    ))
```

`Message.to` accepts a single address or a list.

## Setup

```python
# main.py
from zeython import Application, MailServiceProvider

app = Application()
app.register(MailServiceProvider)
```

## Sending from a background job

This is the common case — see [Background Jobs](queues.md). A job's
`handle()` can declare `mailer: Mailer` as a parameter and have it resolved
automatically, the same autowiring the rest of the framework uses:

```python
# app/Jobs/send_welcome_email_job.py
from dataclasses import dataclass
from zeython import Job, Mailer, Message

@dataclass
class SendWelcomeEmailJob(Job):
    to_email: str
    name: str

    async def handle(self, mailer: Mailer) -> None:
        await mailer.send(Message(
            to=self.to_email,
            subject="Welcome!",
            body=f"Hi {self.name}, welcome aboard.",
        ))
```

```python
await dispatch(request, SendWelcomeEmailJob(to_email=user.email, name=user.name))
```

This works with any job, not just mail — a job's `handle()` can request
*any* type bound in the container (a `Database`, your own service), not
only `Mailer`. See [Background Jobs](queues.md#defining-a-job).

## Configuration

| `.env` key | Default | Meaning |
|---|---|---|
| `MAIL_DRIVER` | `log` | `log` (writes to logs) or `smtp` (really sends). |
| `MAIL_HOST` | `localhost` | SMTP server. |
| `MAIL_PORT` | `587` | SMTP port. |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | *(unset)* | SMTP auth; skipped if either is unset. |
| `MAIL_ENCRYPTION` | `tls` | `tls` (STARTTLS) or `none`. |
| `MAIL_FROM_ADDRESS` | `no-reply@example.com` | Default `From:`, overridable per-`Message`. |

## Development

Leave `MAIL_DRIVER=log` (the default) during development — every email
shows up in your app's own logs (`zeython.mail`, at `INFO`) instead of
actually being sent, so you can develop and test mail-sending flows without
SMTP credentials or a risk of spamming real addresses.

## Writing your own backend

Subclass `Mailer` and implement `async def send(self, message: Message) ->
None`, then bind it in place of `MailServiceProvider`'s default:

```python
app.container.singleton(Mailer, lambda: MyTransactionalEmailApiMailer(api_key=...))
```
