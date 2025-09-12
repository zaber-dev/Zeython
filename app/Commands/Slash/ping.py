from disnake import OptionType, OptionChoice
from disnake.ext import commands

class PingSlash(commands.Cog):
    """
    A cog that contains a slash command to check the bot's latency.

    This cog defines a slash command named 'ping' that responds with the bot's latency
    when invoked. The latency is calculated and returned in milliseconds.
    
    Attributes:
        bot (commands.Bot): The bot instance that the cog is attached to.
    """

    def __init__(self, bot):
        """
        Initializes the PingSlash cog.

        Args:
            bot (commands.Bot): The bot instance that the cog is attached to.
        """
        self.bot = bot

    @commands.slash_command(
        name="ping",
        description="Check the bot's latency",
    )
    async def ping(self, ctx):
        """
        Command to check the bot's latency.

        This command calculates the bot's latency and sends it as a response in the Discord channel.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
        """
        await ctx.send(f"Pong! Latency: {round(self.bot.latency * 1000)}ms")

def setup(bot):
    bot.add_cog(PingSlash(bot))