def greet_user(name):
    """
    Controller function to greet a user.

    This function is called when the user visits the /example route. It processes the user's name
    and returns a greeting message in HTML format.

    Args:
        name (str): The name of the user.

    Returns:
        str: An HTML string with a greeting message.
    """
    # Do some processing here
    return f"<h1>Hello, {name}!</h1>"

# Example usage of the greet_user function
# name = "Zaber"
# greeting_message = greet_user(name)
# print(greeting_message)  # Output: <h1>Hello, Zaber!</h1>