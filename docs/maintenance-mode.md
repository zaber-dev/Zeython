# Maintenance Mode

Take the whole app offline for a deploy or a risky migration without
stopping the process -- `zeython down` writes a flag file
(`storage/framework/down.json`); `zeython up` removes it. Mirrors
Laravel's `artisan down`/`up` closely, including the bypass mechanism for
checking the site yourself while it's "down" for everyone else.

## Setup

```python
# main.py
from zeython import Application, MaintenanceModeServiceProvider

app = Application()
# ... every other app.register(...) call ...
app.register(MaintenanceModeServiceProvider)  # keep this last -- see below
```

A generated project already has this registered, as the very last line in
`main.py` -- deliberately last, because the most recently registered
middleware wraps **outermost**, and maintenance mode needs to intercept a
request before anything else runs, including opening a database session.
That matters most exactly when this feature is useful: a migration in
progress, a database that's briefly unreachable. If you add your own
middleware-registering provider later, put it *above* this line, not
below it.

Its own `boot()` is a no-op unless the flag file exists, so it's safe to
always register -- the same reasoning `RequestIdServiceProvider` relies
on. With the app up, every request pays one `Path.exists()` call and
nothing else changes.

## Usage

```bash
zeython down
zeython down --message "Deploying, back in 5 minutes" --retry 300
zeython down --allow 1.2.3.4 --allow 5.6.7.8   # these IPs see the app normally
zeython up
```

While down, every other request gets:

```
HTTP/1.1 503 Service Unavailable
Retry-After: 300
Content-Type: application/json

{"message": "Deploying, back in 5 minutes", "status": 503}
```

`Retry-After` is only sent when `--retry` was given -- a client (or a
load balancer/CDN in front of the app) that respects it backs off for
that many seconds before trying again.

The flag file is read fresh on every request, not cached in memory --
`zeython up` takes effect on the very next request, no process restart
needed either way.

## Checking the site yourself while it's down

`zeython down` prints a bypass URL:

```
Application is now in maintenance mode.
  Bypass URL: /Xt3k9f...  (visiting it once sets a cookie for this browser)
```

Visit it once in a browser and every subsequent request from that browser
skips the 503 -- useful for smoke-testing a deploy against the real app
before flipping it back up for everyone else. Pass `--secret` to choose
your own bypass token instead of the generated one.

## Scope

Only HTTP requests are affected -- a WebSocket connection isn't checked
against maintenance mode. Only the process(es) that see the flag file are
affected: on a multi-instance deployment where each instance has its own
local filesystem, `zeython down` needs to run against each one (or the
flag file needs to live on shared storage) -- the same file-based
limitation Laravel's own `artisan down` has by default.

- `MAINTENANCE_STORE_PATH` -- default `storage/framework/down.json`,
  relative to the project root.
