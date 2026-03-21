import argparse
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from _version import __version__
from rgw_cli_contract import AppSpec, resolve_install_script_path, run_app

INSTALL_SCRIPT = resolve_install_script_path(__file__)
DEFAULT_MANAGED_PROFILE_DIR = "~/.whatsapp-web"
DEFAULT_CDP_ENDPOINTS = (
    "http://127.0.0.1:9222",
    "http://127.0.0.1:9223",
    "http://127.0.0.1:9333",
)
HELP_TEXT = """whatsapp

flags:
  whatsapp -h
    show this help
  whatsapp -v
    print the installed version
  whatsapp -u
    upgrade to the latest release
  whatsapp conf
    open the config in $VISUAL/$EDITOR

features:
  send a WhatsApp message in the background through your existing Chromium session
  # whatsapp <phone|label> <message...> | whatsapp -fg <phone|label> <message...> | whatsapp -pf <path> <phone|label> <message...>
  whatsapp 919999999999 "hello"
  whatsapp mom "reached home"
  whatsapp -fg mom "reached home"
  whatsapp -pf ~/.whatsapp-web mom "reached home"

  check the status of a background send
  # whatsapp st [job_id]
  whatsapp st
  whatsapp st 20260321123045-1a2b3c4d

  clear the saved browser session
  # whatsapp -c
  whatsapp -c

  save a contact label
  # whatsapp -ac <label> <number>
  whatsapp -ac mom 919999999999
"""


def normalize_phone(raw):
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise SystemExit("Phone number must include digits and country code.")
    return digits


def _playwright_symbols():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright, PlaywrightTimeoutError


@contextlib.contextmanager
def _playwright_env():
    original = os.environ.get("NODE_OPTIONS")
    option = "--no-deprecation"

    if original:
        existing = original.split()
        if option not in existing:
            os.environ["NODE_OPTIONS"] = f"{original} {option}".strip()
    else:
        os.environ["NODE_OPTIONS"] = option

    try:
        yield
    finally:
        if original is None:
            os.environ.pop("NODE_OPTIONS", None)
        else:
            os.environ["NODE_OPTIONS"] = original


def get_config_path():
    base = os.getenv("XDG_CONFIG_HOME")
    if not base:
        base = os.path.expanduser("~/.config")
    base = os.path.expanduser(base)
    return os.path.join(base, "whatsapp", "config.json")


def get_state_dir():
    base = os.getenv("XDG_STATE_HOME")
    if not base:
        base = os.path.expanduser("~/.local/state")
    return Path(os.path.expanduser(base)) / "whatsapp"


def get_worker_log_path():
    return get_state_dir() / "worker.log"


def get_jobs_dir():
    return get_state_dir() / "jobs"


def get_latest_job_path():
    return get_state_dir() / "latest-job"


def get_job_path(job_id):
    return get_jobs_dir() / f"{job_id}.json"


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


def _config_string(payload, key):
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _candidate_cdp_endpoints(config):
    explicit = (
        os.getenv("WHATSAPP_CHROMIUM_CDP_URL")
        or _config_string(config, "chromium_cdp_url")
    )
    if explicit:
        return [explicit], True
    return list(DEFAULT_CDP_ENDPOINTS), False


def _probe_cdp_endpoint(endpoint):
    base = endpoint.rstrip("/")
    request = Request(f"{base}/json/version", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, URLError, HTTPError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("webSocketDebuggerUrl"))


def find_cdp_endpoint(config):
    endpoints, explicit = _candidate_cdp_endpoints(config)
    for endpoint in endpoints:
        if _probe_cdp_endpoint(endpoint):
            return endpoint
    if explicit:
        raise SystemExit(
            f"Chromium CDP endpoint is not reachable: {endpoints[0]}. "
            "Start Chromium with --remote-debugging-port or unset WHATSAPP_CHROMIUM_CDP_URL."
        )
    return None


def _notify(summary, body=None, urgency="normal"):
    notify_send = shutil.which("notify-send")
    if not notify_send:
        return

    args = [notify_send, "-a", "whatsapp", "-u", urgency, summary]
    if body:
        args.append(body)
    try:
        subprocess.run(
            args,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def _log_worker_error(message):
    path = get_worker_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def _timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def _new_job_id():
    return f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def save_background_job(payload):
    job_id = payload.get("id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise SystemExit("Background job payload is missing an id.")
    _write_json(get_job_path(job_id), payload)
    latest_job_path = get_latest_job_path()
    latest_job_path.parent.mkdir(parents=True, exist_ok=True)
    latest_job_path.write_text(f"{job_id}\n", encoding="utf-8")


def _load_json(path, missing_message):
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise SystemExit(missing_message) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}.")
    return payload


def load_background_job(job_id):
    return _load_json(get_job_path(job_id), f"Background job not found: {job_id}")


def resolve_background_job_id(job_id=None):
    requested = (job_id or "").strip()
    if requested and requested.lower() != "latest":
        return requested

    latest_job_path = get_latest_job_path()
    try:
        latest_job_id = latest_job_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise SystemExit("No background WhatsApp job found.") from exc
    except OSError as exc:
        raise SystemExit(f"Unable to read {latest_job_path}: {exc}") from exc

    if not latest_job_id:
        raise SystemExit("No background WhatsApp job found.")
    return latest_job_id


def create_background_job(raw_target, phone, text):
    now = _timestamp()
    payload = {
        "id": _new_job_id(),
        "status": "queued",
        "recipient": _recipient_label(raw_target, phone),
        "phone": phone,
        "text_preview": _message_preview(text),
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "error": None,
    }
    save_background_job(payload)
    return payload


def update_background_job(job_id, status, error=None):
    payload = load_background_job(job_id)
    now = _timestamp()
    payload["status"] = status
    payload["updated_at"] = now
    if status == "running" and not payload.get("started_at"):
        payload["started_at"] = now
    if status in {"sent", "failed"}:
        payload["completed_at"] = now
    payload["error"] = error
    save_background_job(payload)
    return payload


def print_background_job_status(job_id=None):
    resolved_job_id = resolve_background_job_id(job_id)
    payload = load_background_job(resolved_job_id)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _self_command(extra_args):
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    return [sys.executable, os.path.abspath(__file__), *extra_args]


def spawn_background_worker(argv):
    command = _self_command(["-bg", *argv])
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SystemExit(f"Unable to start background worker: {exc}") from exc


def should_background_send(worker_mode, foreground_mode, profile_dir, cdp_endpoint):
    if worker_mode or foreground_mode:
        return False
    return bool(profile_dir or cdp_endpoint)


def _recipient_label(raw_target, phone):
    value = (raw_target or "").strip()
    if value and value != phone:
        return f"{value} ({phone})"
    return phone


def _message_preview(text, limit=80):
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _browser_command(config):
    raw = os.getenv("WHATSAPP_BROWSER_COMMAND") or _config_string(config, "browser_command")
    if raw:
        command = shlex.split(raw)
        if command:
            return command

    for candidate in ("chromium", "google-chrome", "chromium-browser"):
        path = shutil.which(candidate)
        if path:
            return [path]

    path = shutil.which("xdg-open")
    if path:
        return [path]
    return None


def open_existing_browser(url, config):
    command = _browser_command(config)
    if not command:
        return False

    executable = Path(command[0]).name.lower()
    args = list(command)
    if "chrom" in executable or "chrome" in executable:
        args.extend(["--new-tab", url])
    else:
        args.append(url)

    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SystemExit(f"Unable to launch browser command '{command[0]}': {exc}") from exc
    return True


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send a WhatsApp message via WhatsApp Web.",
        add_help=False,
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
        "-pf",
        dest="profile",
        help="Path for a dedicated WhatsApp Web session profile.",
    )
    parser.add_argument(
        "-fg",
        dest="foreground",
        action="store_true",
        help="Run in the foreground instead of spawning a background worker.",
    )
    parser.add_argument(
        "-tm",
        dest="timeout",
        type=int,
        default=120,
        help="Timeout in seconds to wait for login/send.",
    )
    parser.add_argument(
        "-c",
        dest="clear",
        action="store_true",
        help="Clear the saved WhatsApp Web session.",
    )
    parser.add_argument(
        "-ac",
        dest="add_contact",
        nargs=2,
        metavar=("LABEL", "NUMBER"),
        help="Save a contact label to the config.",
    )
    parser.add_argument(
        "-bg",
        dest="worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-jid",
        dest="job_id",
        help=argparse.SUPPRESS,
    )
    return parser


def wait_for_ready(page, timeout_s):
    deadline = time.time() + timeout_s
    informed = False
    last_status = time.time()
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
        if now - last_status >= 30:
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


def is_whatsapp_web_url(url):
    value = (url or "").strip().lower()
    return value.startswith("https://web.whatsapp.com/")


def find_existing_whatsapp_page(context):
    for page in context.pages:
        if is_whatsapp_web_url(page.url):
            return page
    return None


def create_background_page(browser, context):
    browser_session = browser.new_browser_cdp_session()
    with context.expect_page() as page_info:
        browser_session.send(
            "Target.createTarget",
            {
                "url": "about:blank",
                "background": True,
                "focus": False,
            },
        )
    return page_info.value


def send_message_via_managed_browser(url, text, timeout_s, profile_dir):
    playwright_symbols = _playwright_symbols()
    if playwright_symbols is None:
        raise SystemExit("Missing dependency: playwright. Install requirements.txt first.")
    sync_playwright, PlaywrightTimeoutError = playwright_symbols

    with _playwright_env():
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except PlaywrightTimeoutError as exc:
                    raise SystemExit("Navigation timed out. Try again.") from exc

                wait_for_ready(page, timeout_s)
                send_message(page, text)
                time.sleep(1.5)
                print("Message sent.")
            finally:
                context.close()


def send_message_via_existing_chromium(url, text, timeout_s, cdp_endpoint):
    playwright_symbols = _playwright_symbols()
    if playwright_symbols is None:
        raise SystemExit("Missing dependency: playwright. Install requirements.txt first.")
    sync_playwright, PlaywrightTimeoutError = playwright_symbols

    with _playwright_env():
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
            contexts = browser.contexts
            if not contexts:
                raise SystemExit(
                    f"Connected to Chromium at {cdp_endpoint}, but no browser context was available."
                )
            context = contexts[0]
            page = None
            created_page = False
            try:
                try:
                    page = create_background_page(browser, context)
                    created_page = True
                except Exception:
                    page = find_existing_whatsapp_page(context)
                    if page is None:
                        page = context.new_page()
                        created_page = True

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except PlaywrightTimeoutError as exc:
                    raise SystemExit("Navigation timed out. Try again.") from exc

                wait_for_ready(page, timeout_s)
                send_message(page, text)
                time.sleep(1.5)
                print("Message sent.")
            finally:
                if created_page and page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass


def execute_send(args, config, raw_target, phone, text, url, profile_dir):
    cdp_endpoint = None if profile_dir else find_cdp_endpoint(config)
    recipient = _recipient_label(raw_target, phone)

    if should_background_send(args.worker, args.foreground, profile_dir, cdp_endpoint):
        job = create_background_job(raw_target, phone, text)
        try:
            spawn_background_worker(
                    [
                    "-jid",
                    job["id"],
                    "-tm",
                    str(args.timeout),
                    *(["-pf", args.profile] if args.profile else []),
                    raw_target,
                    text,
                ]
            )
        except SystemExit as exc:
            update_background_job(job["id"], "failed", error=str(exc) or "Unable to start worker.")
            raise
        print("Sending ...")
        return 0

    if args.worker and args.job_id:
        update_background_job(args.job_id, "running")

    try:
        if profile_dir:
            send_message_via_managed_browser(url, text, args.timeout, profile_dir)
        elif cdp_endpoint:
            send_message_via_existing_chromium(url, text, args.timeout, cdp_endpoint)
        else:
            if not open_existing_browser(url, config):
                raise SystemExit(
                    "No Chromium command was found. Install chromium, set WHATSAPP_BROWSER_COMMAND, "
                    "or use -pf for a dedicated Playwright session."
                )
            print(
                "Opened WhatsApp Web in Chromium. "
                "Press Enter in the browser to send. "
                "For full auto-send in your existing browser, start Chromium with --remote-debugging-port=9222."
            )
            return 0
    except SystemExit as exc:
        message = str(exc) or "WhatsApp send failed."
        if args.worker:
            if args.job_id:
                update_background_job(args.job_id, "failed", error=message)
            _log_worker_error(message)
            _notify("WhatsApp send failed", message, urgency="critical")
        raise
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if args.worker:
            if args.job_id:
                update_background_job(args.job_id, "failed", error=message)
            _log_worker_error(message)
            _notify("WhatsApp send failed", message, urgency="critical")
        raise

    if args.worker:
        if args.job_id:
            update_background_job(args.job_id, "sent")
        _notify("WhatsApp sent", f"{recipient}: {_message_preview(text)}")
    return 0


def clear_managed_session(profile_dir):
    if os.path.exists(profile_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)


def _config_path() -> Path:
    return Path(get_config_path())


def _dispatch(argv: list[str]) -> int:
    if argv and argv[0] == "st":
        if len(argv) > 2:
            raise SystemExit("Usage: whatsapp st [job_id]")
        return print_background_job_status(argv[1] if len(argv) == 2 else None)

    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = get_config_path()
    config = load_config(config_path)
    contact_labels = normalize_contact_labels(config)

    if args.add_contact:
        if args.mobile_no or args.text:
            raise SystemExit("Use -ac by itself.")
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
        return 0

    profile_dir = os.path.expanduser(args.profile) if args.profile else None
    if args.clear:
        clear_target = profile_dir or os.path.expanduser(DEFAULT_MANAGED_PROFILE_DIR)
        clear_managed_session(clear_target)
        if not args.mobile_no and not args.text:
            print("Managed session cleared.")
            return 0

    if not args.mobile_no:
        raise SystemExit("Phone number is required unless using -c only.")

    text = " ".join(args.text).strip()
    if not text:
        parser.print_help()
        return 0

    raw_target = args.mobile_no
    target = contact_labels.get(raw_target, raw_target)
    phone = normalize_phone(target)
    message = quote(text)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={message}"
    return execute_send(args, config, raw_target, phone, text, url, profile_dir)


APP_SPEC = AppSpec(
    app_name="whatsapp",
    version=__version__,
    help_text=HELP_TEXT,
    install_script_path=INSTALL_SCRIPT,
    no_args_mode="help",
    config_path_factory=_config_path,
    config_bootstrap_text="{}\n",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return run_app(APP_SPEC, args, _dispatch)


if __name__ == "__main__":
    raise SystemExit(main())
