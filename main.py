import argparse
import json
import os
import shutil
import sys
import time
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


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
        "-a",
        "--add-label",
        nargs=2,
        metavar=("LABEL", "NUMBER"),
        help="Save a contact label to the config.",
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


def main():
    parser = build_parser()
    args = parser.parse_args()

    config_path = get_config_path()
    config = load_config(config_path)
    labels = normalize_contact_labels(config)

    if args.add_label:
        if args.mobile_no or args.text:
            raise SystemExit("Use --add-label by itself.")
        label, number = args.add_label
        label = label.strip()
        number = number.strip()
        if not label:
            raise SystemExit("Label cannot be empty.")
        if not number:
            raise SystemExit("Number cannot be empty.")
        contact_labels = config.get("contact_labels")
        if contact_labels is None:
            contact_labels = {}
            config["contact_labels"] = contact_labels
        if not isinstance(contact_labels, dict):
            raise SystemExit("contact_labels must be a JSON object.")
        contact_labels[label] = number
        save_config(config_path, config)
        print(f"Saved label '{label}' in {config_path}")
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

    target = labels.get(args.mobile_no, args.mobile_no)
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
            raise SystemExit(
                "Navigation timed out. If this repeats, try running once "
                "without --headless to refresh the session."
            )

        wait_for_ready(page, args.timeout)

        compose = find_compose_box(page)
        if compose is not None:
            compose.click()
            current = compose.inner_text().strip()
            if not current:
                page.keyboard.type(text)
            page.keyboard.press("Enter")
        else:
            page.click("span[data-icon='send']")
        time.sleep(1.5)
        print("Message sent.")
        context.close()


if __name__ == "__main__":
    main()
