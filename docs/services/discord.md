# Discord Service (Optional)

Registers and runs a Discord bot service when `DISCORD_TOKEN` is configured.

## Enable
- `DISCORD_TOKEN` enables the service
- `DISCORD_PREFIX` sets command prefix (default: !)

## Access bot
```python
from app.Core.service_manager import service_manager
discord = service_manager.get_service('discord')
bot = discord.get_bot() if discord else None
```
