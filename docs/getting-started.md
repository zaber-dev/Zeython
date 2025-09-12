# Getting Started

This guide brings your Zeython app online in minutes.

## Prerequisites
- Python 3.9+
- pip

## Install
```bash
git clone https://github.com/zaber-dev/Zeython.git
cd Zeython
pip install -r requirements.txt
```

## Configure
Create `.env` in the project root:

```env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
DATABASE_URL=sqlite:///database.db
```

For Discord (optional):
```env
DISCORD_TOKEN=your_discord_token_here
DISCORD_PREFIX=!
```

## Run
```bash
python config/application.py
```

Open http://127.0.0.1:5000/
