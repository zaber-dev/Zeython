import disnake
from disnake.ext import commands

class Ping(commands.Cog):
    """
    A cog that contains a command to check the bot's latency.

    This cog defines a command named 'ping' that responds with the bot's latency
    when invoked. The latency is calculated and returned in milliseconds.
    
    Attributes:
        bot (commands.Bot): The bot instance that the cog is attached to.
    """

    def __init__(self, bot):
        """
        Initializes the Ping cog.

        Args:
            bot (commands.Bot): The bot instance that the cog is attached to.
        """
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        """
        Command to check the bot's latency.

        This command calculates the bot's latency and sends it as a response in the Discord channel.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
        """
        latency = round(self.bot.latency * 1000)  # Calculate bot's latency in milliseconds
        await ctx.send(f'Pong! Latency: {latency}ms')

def setup(bot):
    bot.add_cog(Ping(bot))