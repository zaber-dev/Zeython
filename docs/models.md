# Models

Enhanced models provide validation, caching, audit trails, soft deletes, and JSON serialization.

## Base model
- EnhancedBaseModel with validation hooks
- model_cache for read caching
- Audit fields (created_at/by, updated_at/by)
- Soft delete with restore

## Users
- Create and authenticate users
- External IDs (discord, github, etc.)
- Profile data key-value store

## Balance
- Currency-specific balances
- Transaction controls

See MVC_ENHANCEMENTS.md for deep dives and examples.
