"""
Legacy boot.py - DEPRECATED

This file is deprecated and maintained only for backward compatibility.
Please use the new modular system in config/application.py

For migration instructions, see README.md

The new system provides:
- Better separation of concerns
- Configurable services
- Improved error handling
- Cleaner architecture
- Service status monitoring

Legacy usage:
python config/boot.py

New usage:
python config/application.py
"""

import os
import sys
import warnings
from pathlib import Path

# Issue deprecation warning
warnings.warn(
    "config/boot.py is deprecated. Please use config/application.py for the new modular system. "
    "See README.md for migration instructions.",
    DeprecationWarning,
    stacklevel=2
)

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("WARNING: Using deprecated boot.py")
print("Please switch to the new modular system:")
print("  python config/application.py")
print("See README.md for migration instructions.")
print("=" * 60)

# Import and run the new application system
try:
    from config.application import main
    main()
except ImportError as e:
    print(f"Failed to import new application system: {e}")
    print("Falling back to legacy implementation...")
    
    # Fallback to legacy implementation if needed
    import threading
    from flask import Flask
    import glob
    from database.db import engine, Base
    
    # Create the database tables
    Base.metadata.create_all(bind=engine)
    
    # Check if the Flask app and Discord bot are enabled
    flask_enabled = os.environ.get('FLASK_HOST')
    discord_enabled = os.environ.get('DISCORD_TOKEN')
    
    # Flask app setup
    if flask_enabled:
        print("Flask app enabled (legacy mode)")
        app = Flask(__name__, template_folder='../resources/views')
        with app.app_context():
            import routes.web
            from routes.api import api
            app.register_blueprint(api)
    
        def run_flask():
            app.run(host=os.environ.get('FLASK_HOST'), port=os.environ.get('FLASK_PORT'))
    
    # Discord bot setup
    if discord_enabled:
        try:
            import disnake as discord
            from disnake.ext import commands
            
            print("Discord bot enabled (legacy mode)")
            intents = discord.Intents.all()
            bot = commands.Bot(command_prefix=os.environ.get('DISCORD_PREFIX','!'), intents=intents)
            
            @bot.event
            async def on_ready():
                print(f'Logged in as {bot.user}')
    
            def load_cogs(bot):
                cog_directories = ['app/Commands/Context', 'app/Commands/Slash'] 
                for directory in cog_directories:
                    for filename in glob.glob(f'{directory}/*.py'):
                        if filename.endswith('.py'):
                            cog = filename.replace('/', '.').replace('\\', '.').replace('.py', '')
                            try:
                                bot.load_extension(cog)
                                print(f'Loaded cog: {cog}')
                            except Exception as e:
                                print(f'Failed to load cog {cog}: {e}')
    
            def run_discord_bot():
                try:
                    print("Starting Discord bot...")
                    load_cogs(bot)
                    bot.run(os.environ.get('DISCORD_TOKEN'))
                except Exception as e:
                    print(f"Error starting Discord bot: {e}")
        except ImportError:
            print("Discord dependencies not available, skipping Discord service")
            discord_enabled = False
    
    # Main execution
    if __name__ == "__main__":
        threads = []
        
        if flask_enabled:
            flask_thread = threading.Thread(target=run_flask)
            flask_thread.start()
            threads.append(flask_thread)
            
        if discord_enabled:
            discord_thread = threading.Thread(target=run_discord_bot)
            discord_thread.start()
            threads.append(discord_thread)
        
        # Join threads to the main thread
        for thread in threads:
            thread.join()