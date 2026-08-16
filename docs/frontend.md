# Frontend & CSS

Zeython is a backend framework — it renders HTML via Jinja2
(`resources/views/`, see [Views](views.md)) and leaves the frontend build
tooling up to you. It doesn't bundle a JS framework, a Vite pipeline, or a
Node.js dependency of any kind. What it does ship an opinion on is CSS,
because "unstyled HTML" is a bad first impression for a new project.

## Tailwind out of the box (dev only)

The generated `resources/views/welcome.html` loads Tailwind's **Play CDN**:

```html
<script src="https://cdn.tailwindcss.com"></script>
```

This gives every new project real, non-ugly styling with zero setup — no
`npm install`, no build step, no Node.js requirement at all. Use utility
classes in any `.html` template and they just work.

**This is not a production setup.** The Play CDN compiles every utility
class in the browser, on every page load, with nothing purged — Tailwind's
own docs are explicit that it's for prototyping, not deployment. Before you
ship, replace it with a compiled build.

## Moving to a compiled build

You do not need Node.js to compile Tailwind — the standalone CLI is a
single executable with no runtime dependency:

```bash
# macOS/Linux, see https://tailwindcss.com/blog/standalone-cli for other platforms
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
chmod +x tailwindcss-linux-x64
mv tailwindcss-linux-x64 tailwindcss

./tailwindcss -i resources/css/app.css -o public/css/app.css --minify
```

Then swap the CDN `<script>` tag for a stylesheet link:

```html
<link rel="stylesheet" href="/css/app.css" />
```

and serve `public/` the same way `StorageServiceProvider` serves uploads —
mount it with Starlette's `StaticFiles`:

```python
from starlette.staticfiles import StaticFiles

app.router.mount("/css", StaticFiles(directory="public/css"))
```

If your team already has a Node-based frontend build (Vite, esbuild,
whatever), there's nothing Zeython-specific about wiring it in: build to a
directory, mount that directory the same way.

## If you don't want Tailwind at all

Delete the `<script>` tag and write plain CSS, or drop in any other
framework — nothing else in Zeython depends on it. The Play CDN is a
starting point, not a requirement.
