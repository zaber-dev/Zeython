# Database

Zeython uses SQLAlchemy for ORM and a database abstraction in `database/db.py`.

## Setup
- Engine and session are initialized in `database/db.py`
- Tables are created in `config/application.py` during startup

## Transactions
- Use session from `database.db`
- Prefer service layer for business logic and transaction management
