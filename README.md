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

Show version:

```bash
python main.py -v
```

Upgrade:

```bash
python main.py -u
```

Use contact labels via XDG config:

Create `~/.config/whatsapp/config.json`:

```json
{
  "contact_labels": {
    "mom": "+91438438473"
  }
}
```

Then:

```bash
python main.py mom "hello world"
```

Add a label from the CLI:

```bash
python main.py -ac mom "91834384384"
```

On first run, a browser opens to WhatsApp Web. Scan the QR code to log in.
Your session is stored in `~/.whatsapp-web` for future runs.

## Options

- `--profile`: Path to store the WhatsApp Web session.
- `--timeout`: Seconds to wait for login/send (default: 120).
- `-c`, `--clear`: Clear the saved WhatsApp Web session.
- `-v`, `--version`: Print version and exit.
- `-u`, `--upgrade`: Upgrade via the installer script.
- `-h`, `--help`: Show help.

## Shell completion (bash)

For local development:

```bash
source completions/whatsapp.bash
```

For installed binary:

```bash
source ~/.whatsapp/completions/whatsapp.bash
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/whatsapp/main/install.sh | bash
```

The installer sets up a private virtualenv in `~/.whatsapp/venv` and installs Playwright
plus browser binaries into your user cache.

On Arch Linux, you may need system dependencies for Playwright. If you see warnings,
install:

```bash
sudo pacman -S --needed glibc libx11 libxcomposite libxdamage libxfixes libxrandr \
  libxkbcommon libxkbcommon-x11 libxcb libxext libxrender libdrm libegl libglvnd mesa \
  at-spi2-core atk cairo pango alsa-lib cups libxshmfence nss nspr openssl fontconfig \
  freetype2 harfbuzz libjpeg-turbo libpng libwebp
```
