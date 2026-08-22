# Validation

Models validate themselves declaratively via `__rules__`, checked automatically by `save()` (and therefore `create()` and `update()`).

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from zeython import Model, required, email, max_length

class User(Model):
    __tablename__ = "users"
    __rules__ = {
        "name": [required()],
        "email": [required(), email()],
        "bio": [max_length(500)],
    }

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    bio: Mapped[str] = mapped_column(String(500), nullable=True)
```

```python
await User.create(name="Ada", email="not-an-email")
# raises zeython.ValidationException({"email": ["Must be a valid email address."]})
```

`ValidationException` is already handled by the framework's default JSON error handler, so a failed validation in a controller becomes a `422` response with an `errors` object automatically — you don't need a `try`/`except` in most controllers:

```python
async def store(self, request):
    data = await request.json()
    user = await User.create(**data)   # raises -> 422 {"error": ..., "errors": {...}}
    return JSONResponse(user.to_dict(), status_code=201)
```

## Available rules

| Rule               | Behavior                                                        |
| ------------------ | --------------------------------------------------------------- |
| `required()`       | Value must not be `None` or `""`.                               |
| `min_length(n)`    | String length ≥ `n`. Passes on `None` (pair with `required()`). |
| `max_length(n)`    | String length ≤ `n`. Passes on `None`.                          |
| `email()`          | Basic `local@domain.tld` shape check.                           |
| `one_of((...))`    | Value must be one of the given choices. Passes on `None`.       |
| `matches(pattern)` | Value must match a regex. Passes on `None`.                     |

All rules except `required()` treat `None` as "not applicable" rather than a failure — combine with `required()` when a field is mandatory.

## Checking validity without raising

```python
errors = user.validate()   # {} if valid, else {"field": ["message", ...]}
if errors:
    ...
```

## Validating a plain dict

`user.validate()` needs a `Model` instance -- not always what you have. A query-string filter, a webhook payload, config loaded from somewhere else: `zeython.validation.validate(data, rules)` runs the same rule sets against any dict:

```python
from zeython.validation import validate, required, email

errors = validate(
    {"email": "not-an-email"},
    {"name": [required()], "email": [required(), email()]},
)
# {"name": ["This field is required."], "email": ["Must be a valid email address."]}

if errors:
    raise ValidationException(errors)
```

A missing key is treated as `None`, same as an unset field on a model instance. `Model.validate()` is this function applied to a model's own field values -- the two always agree on what the same rule set means.

## Custom rules

A rule is just `Callable[[Any], bool]` wrapped with a message:

```python
from zeython import Rule

def even(message="Must be even.") -> Rule:
    return Rule(lambda v: v is None or v % 2 == 0, message)
```
