def greet_user(name):
    """
    Controller function to greet a user in Discord.

    This function takes the name of a user and returns a greeting message. It can be used in a Discord bot
    to send personalized greetings to users.

    Args:
        name (str): The name of the user.

    Returns:
        str: A greeting message.
    """
    # Do some processing here
    return f"Hello, **{name}**!"

# Example usage of the greet_user function
# name = ctx.author.name    [for example: "Zaber"]
# greeting_message = greet_user(name)
# print(greeting_message)  # Output: Hello, **Zaber**!