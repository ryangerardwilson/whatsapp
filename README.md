# whatsapp

Minimal CLI to send a WhatsApp message via WhatsApp Web.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install
```

## Usage

Send a message:

```bash
python main.py "15551234567" "hello world"
```

On first run, a browser opens to WhatsApp Web. Scan the QR code to log in.
Your session is stored in `~/.whatsapp-web` for future runs.

## Options

- `--profile`: Path to store the WhatsApp Web session.
- `--timeout`: Seconds to wait for login/send (default: 120).
- `-c`, `--clear`: Clear the saved WhatsApp Web session.
