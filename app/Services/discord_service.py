"""
Optional Discord Service implementation.

This service is only loaded if Discord/Disnake dependencies are available.
It provides Discord bot functionality as a modular service that can be
enabled/disabled through configuration.
"""

import os
import sys
import glob
from typing import Dict, Any

try:
    import disnake as discord
    from disnake.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None
    commands = None

from app.Core.service import ThreadedService


class DiscordService(ThreadedService):
    """
    Discord bot service implementation.
    
    Provides Discord bot functionality as a modular service that can be
    configured and managed independently of other services.
    """
    
    def __init__(self, name: str = "discord", config: Dict[str, Any] = None):
        """
        Initialize the Discord service.
        
        Args:
            name (str): Service name
            config (Dict[str, Any]): Service configuration
        """
        if not DISCORD_AVAILABLE:
            raise ImportError("Discord dependencies (disnake) are not installed")
        
        super().__init__(name, config)
        self.bot = None
        self._setup_bot()
    
    def _setup_bot(self):
        """Set up the Discord bot."""
        try:
            # Configure bot with intents
            intents = discord.Intents.all()
            prefix = self.config.get('prefix', '!')
            
            self.bot = commands.Bot(
                command_prefix=prefix,
                intents=intents
            )
            
            # Setup event handlers
            self._setup_event_handlers()
            
            self.logger.info("Discord bot initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Discord bot: {e}")
            raise
    
    def _setup_event_handlers(self):
        """Set up Discord bot event handlers."""
        @self.bot.event
        async def on_ready():
            self.logger.info(f'Discord bot logged in as {self.bot.user}')
        
        # Add other event handlers as needed
    
    def _load_cogs(self):
        """Load Discord command cogs."""
        try:
            # Add project root to path for imports
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..')
            )
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            
            # Load cogs from Commands directories
            cog_directories = ['app/Commands/Context', 'app/Commands/Slash']
            
            for directory in cog_directories:
                cog_path = os.path.join(project_root, directory)
                if not os.path.exists(cog_path):
                    continue
                
                for filename in glob.glob(f'{cog_path}/*.py'):
                    if filename.endswith('.py') and not filename.endswith('__init__.py'):
                        # Convert file path to module name
                        relative_path = os.path.relpath(filename, project_root)
                        cog_name = relative_path.replace(os.sep, '.').replace('.py', '')
                        
                        try:
                            self.bot.load_extension(cog_name)
                            self.logger.info(f'Loaded Discord cog: {cog_name}')
                        except Exception as e:
                            self.logger.error(f'Failed to load cog {cog_name}: {e}')
            
        except Exception as e:
            self.logger.error(f"Failed to load Discord cogs: {e}")
    
    def is_enabled(self) -> bool:
        """
        Check if the Discord service is enabled.
        
        Returns:
            bool: True if Discord token is configured, False otherwise
        """
        return bool(self.config.get('token') or self.config.get('enabled', False))
    
    def _run(self):
        """Run the Discord bot."""
        if not self.bot:
            self.logger.error("Discord bot not initialized")
            return
        
        try:
            token = self.config.get('token')
            if not token:
                self.logger.error("Discord token not configured")
                return
            
            self.logger.info("Starting Discord bot...")
            
            # Load cogs before starting
            self._load_cogs()
            
            # Start the bot
            self.bot.run(token)
            
        except Exception as e:
            self.logger.error(f"Discord bot error: {e}")
        finally:
            self.is_running = False
    
    def get_bot(self):
        """
        Get the Discord bot instance.
        
        Returns:
            The Discord bot instance
        """
        return self.bot
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the Discord service.
        
        Returns:
            Dict[str, Any]: Service status including Discord-specific information
        """
        status = super().get_status()
        status.update({
            'prefix': self.config.get('prefix', '!'),
            'token_configured': bool(self.config.get('token')),
            'bot_initialized': self.bot is not None,
            'dependencies_available': DISCORD_AVAILABLE
        })
        
        if self.bot and hasattr(self.bot, 'user') and self.bot.user:
            status.update({
                'bot_username': str(self.bot.user),
                'bot_id': self.bot.user.id
            })
        
        return status