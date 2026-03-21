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

By default, `whatsapp` now reuses your existing Chromium session and detaches
immediately if it can auto-send. When the send completes, it posts a desktop
notification through `notify-send`, which shows up in `mako`.

For agent polling, `python main.py st` prints the latest background job as JSON.
You can also query a specific job with `python main.py st <job_id>`.

If Chromium is already running with WhatsApp Web logged in, the command opens the
conversation in that browser instead of launching a separate private browser.

If Chromium is exposing a DevTools endpoint such as
`http://127.0.0.1:9222`, `whatsapp` can attach to that existing browser and
send automatically in the background.
Without a DevTools endpoint, it opens a prefilled draft in your current browser
and tells you to press Enter in the tab to send.

If you want the command to stay attached to the terminal, use `-fg`:

```bash
python main.py -fg mom "hello world"
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

On first run, your existing Chromium tab opens to WhatsApp Web. Scan the QR code
there if needed.

If you still want the old isolated-browser behavior, pass `-pf`:

```bash
python main.py -pf ~/.whatsapp-web "15551234567" "hello world"
```

That launches a dedicated Playwright-managed Chromium profile and keeps its
session under the supplied profile path.

## Options

- `-pf`: Use a dedicated Playwright-managed WhatsApp Web session instead of your existing Chromium.
- `-fg`: Keep the send in the foreground instead of detaching to a background worker.
- `-tm`: Seconds to wait for login/send (default: 120).
- `-c`: Clear the saved WhatsApp Web session.
- `-v`: Print version and exit.
- `-u`: Upgrade via the installer script.
- `-h`: Show help.

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

## Existing Chromium Auto-Send

If you want `whatsapp` to auto-send while staying inside your already-running
Chromium window, start Chromium with a DevTools port, for example:

```bash
chromium --remote-debugging-port=9222
```

`whatsapp` probes common local endpoints such as `http://127.0.0.1:9222`.
You can override the endpoint with:

```bash
export WHATSAPP_CHROMIUM_CDP_URL="http://127.0.0.1:9222"
```

You can also override the Chromium launcher command:

```bash
export WHATSAPP_BROWSER_COMMAND="/usr/bin/chromium"
```

On Arch Linux, you may need system dependencies for Playwright. If you see warnings,
install:

```bash
sudo pacman -S --needed glibc libx11 libxcomposite libxdamage libxfixes libxrandr \
  libxkbcommon libxkbcommon-x11 libxcb libxext libxrender libdrm libegl libglvnd mesa \
  at-spi2-core atk cairo pango alsa-lib cups libxshmfence nss nspr openssl fontconfig \
  freetype2 harfbuzz libjpeg-turbo libpng libwebp
```
