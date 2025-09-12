import disnake
from disnake.ext import commands
from app.Controllers.Discord.greetUser import greet_user

class GreetSlash(commands.Cog):
    """
    A cog that contains a command to greet users.

    This cog defines a command that greets the user who invoked it. The greeting message is generated
    using the greet_user function from the greetUser controller.

    Attributes:
        bot (commands.Bot): The bot instance that the cog is attached to.
    """

    def __init__(self, bot):
        """
        Initializes the Greet cog.

        Args:
            bot (commands.Bot): The bot instance that the cog is attached to.
        """
        self.bot = bot

    @commands.slash_command(
        name="hello", 
        description="Greet the user"
    )
    async def hello(self, ctx):
        """
        Command to greet the user who invoked it using the Controller: app/Controllers/Discord/greetUser.py.

        This command uses the greet_user function to generate a greeting message for the user who invoked
        the command and sends it as a response in the Discord channel.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
        """
        greeting = greet_user(ctx.author.name)
        await ctx.send(greeting)

def setup(bot):
    bot.add_cog(GreetSlash(bot))