import requests

# Define the function to send a webhook
def send_webhook(url, data):
    """
    Send a webhook to the specified URL with the given data.

    Args:
        url (str): The webhook URL.
        data (dict): The data to send in the webhook.

    Returns:
        Response: The response from the webhook request.
    """
    response = requests.post(url, json=data)
    return response

# Define the function to process a webhook
def process_webhook(data):
    """
    Process the incoming webhook data.

    This function processes the incoming webhook data and returns a response.

    Args:
        data (dict): The webhook data.

    Returns:
        str: A response message.
    """
    # Process the webhook data here
    return f"Webhook received with data: {data}"

# Example usage of send_webhook function
# url = "https://example.com/webhook"
# data = {"key": "value"}
# response = send_webhook(url, data)
# print(f"Webhook sent with status: {response.status_code}")

# Example usage of process_webhook function
# incoming_data = {"key": "value"}
# response_message = process_webhook(incoming_data)
# print(response_message)