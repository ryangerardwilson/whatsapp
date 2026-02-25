import argparse
import json
import os
import shutil
import sys
import time
from urllib.parse import quote
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from _version import __version__
except Exception:
    __version__ = "0.0.0"

INSTALL_URL = "https://raw.githubusercontent.com/ryangerardwilson/whatsapp/main/install.sh"
LATEST_RELEASE_API = "https://api.github.com/repos/ryangerardwilson/whatsapp/releases/latest"


def normalize_phone(raw):
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise SystemExit("Phone number must include digits and country code.")
    return digits


def get_config_path():
    base = os.getenv("XDG_CONFIG_HOME")
    if not base:
        base = os.path.expanduser("~/.config")
    base = os.path.expanduser(base)
    return os.path.join(base, "whatsapp", "config.json")


def load_config(config_path):
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read config at {config_path}: {exc}")

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise SystemExit("Config file must contain a JSON object.")
    return payload


def save_config(config_path, payload):
    directory = os.path.dirname(config_path)
    os.makedirs(directory, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def normalize_contact_labels(payload):
    labels = payload.get("contact_labels", {})
    if labels is None:
        return {}
    if not isinstance(labels, dict):
        raise SystemExit("contact_labels must be a JSON object.")

    cleaned = {}
    for key, value in labels.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            cleaned[key] = value
    return cleaned


def _version_tuple(version):
    if not version:
        return (0,)
    version = version.strip()
    if version.startswith("v"):
        version = version[1:]
    parts = []
    for segment in version.split("."):
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def _is_version_newer(candidate, current):
    cand_tuple = _version_tuple(candidate)
    curr_tuple = _version_tuple(current)
    length = max(len(cand_tuple), len(curr_tuple))
    cand_tuple += (0,) * (length - len(cand_tuple))
    curr_tuple += (0,) * (length - len(curr_tuple))
    return cand_tuple > curr_tuple


def _get_latest_version(timeout=5.0):
    try:
        request = Request(LATEST_RELEASE_API, headers={"User-Agent": "whatsapp-updater"})
        with urlopen(request, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError):
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    tag = payload.get("tag_name") or payload.get("name")
    if isinstance(tag, str) and tag.strip():
        return tag.strip()
    return None


def _run_upgrade():
    try:
        curl = subprocess.Popen(
            ["curl", "-fsSL", INSTALL_URL],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("Upgrade requires curl", file=sys.stderr)
        return 1

    try:
        bash = subprocess.Popen(["bash"], stdin=curl.stdout)
        if curl.stdout is not None:
            curl.stdout.close()
    except FileNotFoundError:
        print("Upgrade requires bash", file=sys.stderr)
        curl.terminate()
        curl.wait()
        return 1

    bash_rc = bash.wait()
    curl_rc = curl.wait()

    if curl_rc != 0:
        stderr = (
            curl.stderr.read().decode("utf-8", errors="replace") if curl.stderr else ""
        )
        if stderr:
            sys.stderr.write(stderr)
        return curl_rc

    return bash_rc




def build_parser():
    parser = argparse.ArgumentParser(
        description="Send a WhatsApp message via WhatsApp Web."
    )
    parser.add_argument(
        "mobile_no",
        nargs="?",
        help="Phone number with country code (digits only).",
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Message text to send.",
    )
    parser.add_argument(
        "--profile",
        default="~/.whatsapp-web",
        help="Path for the WhatsApp Web session profile.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds to wait for login/send.",
    )
    parser.add_argument(
        "-c",
        "--clear",
        action="store_true",
        help="Clear the saved WhatsApp Web session.",
    )
    parser.add_argument(
        "-ac",
        "--add-contact",
        nargs=2,
        metavar=("LABEL", "NUMBER"),
        help="Save a contact label to the config.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Show version and exit.",
    )
    parser.add_argument(
        "-u",
        "--upgrade",
        action="store_true",
        help="Upgrade to the latest version.",
    )
    return parser


def wait_for_ready(page, timeout_s):
    deadline = time.time() + timeout_s
    informed = False
    last_status = 0.0
    while True:
        if time.time() >= deadline:
            raise SystemExit("Timed out waiting for WhatsApp Web.")

        if page.locator("span[data-icon='send']").first.is_visible(timeout=0):
            return

        if find_compose_box(page) is not None:
            return


        qr_visible = False
        for selector in ("div[data-testid='qrcode']", "canvas[aria-label*='Scan']"):
            if page.locator(selector).first.is_visible(timeout=0):
                qr_visible = True
                break

        if qr_visible and not informed:
            print(
                "Waiting for WhatsApp Web to be ready. "
                "If this is your first run, scan the QR code.",
                file=sys.stderr,
            )
            informed = True

        now = time.time()
        if now - last_status >= 10:
            print("Still waiting for WhatsApp Web...", file=sys.stderr)
            last_status = now

        time.sleep(0.8)


def find_compose_box(page):
    selectors = [
        "div[data-testid='conversation-compose-box-input']",
        "div[contenteditable='true'][data-tab='10']",
        "div[contenteditable='true'][data-tab='6']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.is_visible(timeout=0):
            return locator
    return None


def send_message(page, text):
    compose = find_compose_box(page)
    if compose is not None:
        compose.click()
        current = compose.inner_text().strip()
        if not current:
            page.keyboard.type(text)
        page.keyboard.press("Enter")
        return
    page.click("span[data-icon='send']")


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return

    if args.upgrade:
        if args.mobile_no or args.text or args.add_contact or args.clear:
            raise SystemExit("Use -u by itself to upgrade.")

        latest = _get_latest_version()
        if latest is None:
            print(
                "Unable to determine latest version; attempting upgrade…",
                file=sys.stderr,
            )
            rc = _run_upgrade()
            sys.exit(rc)

        if (
            __version__
            and __version__ != "0.0.0"
            and not _is_version_newer(latest, __version__)
        ):
            print(f"Already running the latest version ({__version__}).")
            sys.exit(0)

        if __version__ and __version__ != "0.0.0":
            print(f"Upgrading from {__version__} to {latest}…")
        else:
            print(f"Upgrading to {latest}…")
        rc = _run_upgrade()
        sys.exit(rc)

    config_path = get_config_path()
    config = load_config(config_path)
    contact_labels = normalize_contact_labels(config)

    if args.add_contact:
        if args.mobile_no or args.text:
            raise SystemExit("Use --add-contact by itself.")
        label, number = args.add_contact
        label = label.strip()
        number = number.strip()
        if not label:
            raise SystemExit("Label cannot be empty.")
        if not number:
            raise SystemExit("Number cannot be empty.")
        contact_labels[label] = number
        config["contact_labels"] = contact_labels
        save_config(config_path, config)
        print(f"Saved contact label '{label}' in {config_path}")
        return

    profile_dir = os.path.expanduser(args.profile)
    if args.clear:
        if os.path.exists(profile_dir):
            shutil.rmtree(profile_dir, ignore_errors=True)
        if not args.mobile_no and not args.text:
            print("Session cleared.")
            return

    if not args.mobile_no:
        raise SystemExit("Phone number is required unless using --clear only.")

    text = " ".join(args.text).strip()
    if not text:
        parser.print_help()
        return

    target = contact_labels.get(args.mobile_no, args.mobile_no)
    phone = normalize_phone(target)
    message = quote(text)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={message}"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            raise SystemExit("Navigation timed out. Try again.")

        wait_for_ready(page, args.timeout)
        send_message(page, text)
        time.sleep(1.5)
        print("Message sent.")
        context.close()


if __name__ == "__main__":
    main()
