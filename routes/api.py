"""
This file defines the API routes for the RankBot application.
The API routes are prefixed with '/api/v1'.

To add more API routes, follow these steps:
1. Import the necessary modules or functions.
2. Use the `api` blueprint to define the route.
3. Specify the route path and methods.
4. Define the route function with any required parameters.
5. Implement the logic for the route.
6. Return the desired response.

Example:
@api.route('/new_route', methods=['GET'])
def new_route():
    # Implement the logic for the new route
    return 'This is the response for the new route.'
"""

from flask import Blueprint
api = Blueprint('api', __name__, url_prefix='/api/v1') # Define the API blueprint

@api.route('/hello/<name>', methods=['GET'])
def api_hello(name):
    return f"Hello, {name}!"