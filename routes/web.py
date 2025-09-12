from flask import current_app as app, render_template
from app.Controllers.Flask.greetUser import greet_user

@app.route('/')
def home():
    """
    Render the home page.

    This route renders the index.html template when the user visits the root URL.

    Returns:
        str: The rendered HTML of the home page.
    """
    return render_template('index.html')

@app.route('/<name>')
def api_hello(name):
    """
    Greet the user with the provided name using the Controller: app/Controllers/Discord/greetUser.py.

    This route calls the greet_user function to generate a greeting message for the user
    with the given name and returns it as a response.

    Args:
        name (str): The name of the user.

    Returns:
        str: A greeting message for the user.
    """
    return greet_user(name)