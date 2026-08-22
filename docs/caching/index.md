# Caching

`zeython.cache` gives you a `Cache` bound in the container — an in-memory TTL cache by default — with `get`/`put`/`forget`/`has`/`flush`, plus `remember()` for the common "check the cache, else compute and store" pattern.

## The basics

```python
from zeython import Cache

async def index(self, request):
    cache: Cache = request.app.state.container.make(Cache)
    await cache.put("greeting", "hello", ttl=60)   # expires in 60 seconds
    await cache.get("greeting")                    # "hello"
    await cache.get("missing", "default")           # "default"
    await cache.has("greeting")                     # True
    await cache.forget("greeting")
```

`ttl` is in seconds; omit it (or pass `None`) for an entry that never expires on its own. There's no proactive sweep — an expired entry is evicted the next time it's read, not the moment it expires.

## `remember()`: the common case

Most caching is "check the cache; on a miss, compute the value and store it" — `remember()` is that in one call:

```python
posts = await cache.remember("posts:recent", 30, lambda: fetch_recent_posts())
```

The callback only runs on a miss. `zeython new` wires this into the generated `PostController.index` — the post list is cached for 30 seconds and invalidated (`cache.forget(...)`) whenever a post is created, so reads stay fast without serving stale data past a create:

```python
async def index(self, request):
    cache: Cache = request.app.state.container.make(Cache)

    async def fetch():
        posts = await Post.all(include=("author",))
        return [post.to_dict(include=("author",)) for post in posts]

    return JSONResponse(await cache.remember("posts:index", 30, fetch))
```

## The default cache is process-local

`InMemoryCache` lives in this process's memory — correct and fast for a single worker, and a real limitation once you run multiple worker processes or machines: each caches independently, so a `put` in one worker isn't visible to a request served by another. Same trade-off as `RateLimiter` and the default `Queue`. For a shared cache, implement `Cache` against a real backend (Redis is the usual choice) and bind it in place of the default:

```python
from zeython import Cache

app.container.singleton(Cache, lambda: MyRedisCache(redis_client))
```
