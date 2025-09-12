# FAQ

## How do I enable only the web service?
Set `FLASK_HOST` and run `python config/application.py`.

## Do I need Discord libraries installed?
No—Zeython runs without Discord when the token isn’t provided.

## Where do I add new services?
Create a class extending `ThreadedService` and register it with the service manager.
