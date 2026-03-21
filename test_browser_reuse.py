import importlib.util
import json
import sys
import tempfile
import types
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


APP = Path(__file__).resolve().parent / "main.py"
sys.path.insert(0, str(APP.parent))

fake_contract = types.SimpleNamespace(
    AppSpec=lambda **kwargs: types.SimpleNamespace(**kwargs),
    resolve_install_script_path=lambda path: path,
    run_app=lambda spec, args, dispatch: dispatch(args),
)

with patch.dict(sys.modules, {"rgw_cli_contract": fake_contract}):
    SPEC = importlib.util.spec_from_file_location("whatsapp_main", APP)
    assert SPEC and SPEC.loader
    main = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(main)


class BrowserReuseTests(unittest.TestCase):
    def test_playwright_env_adds_no_deprecation_temporarily(self):
        with patch.dict(main.os.environ, {}, clear=True):
            with main._playwright_env():
                self.assertEqual(main.os.environ.get("NODE_OPTIONS"), "--no-deprecation")
            self.assertNotIn("NODE_OPTIONS", main.os.environ)

    def test_find_existing_whatsapp_page_prefers_whatsapp_tab(self):
        page1 = types.SimpleNamespace(url="https://example.com")
        page2 = types.SimpleNamespace(url="https://web.whatsapp.com/")
        context = types.SimpleNamespace(pages=[page1, page2])
        self.assertIs(main.find_existing_whatsapp_page(context), page2)

    def test_existing_browser_fallback_opens_tab_and_prints_instruction(self):
        with patch.object(sys, "argv", ["main.py", "mom", "hello world"]):
            with patch.object(
                main,
                "load_config",
                return_value={"contact_labels": {"mom": "919999999999"}},
            ):
                with patch.object(main, "find_cdp_endpoint", return_value=None):
                    with patch.object(main, "open_existing_browser", return_value=True) as open_browser:
                        with patch("sys.stdout", new=StringIO()) as stdout:
                            rc = main.main()
        self.assertEqual(rc, 0)
        open_browser.assert_called_once()
        self.assertIn("Opened WhatsApp Web in Chromium", stdout.getvalue())

    def test_default_cdp_send_spawns_background_worker_and_records_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(main.os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                with patch.object(main, "_new_job_id", return_value="job-123"):
                    with patch.object(sys, "argv", ["main.py", "919999999999", "hello world"]):
                        with patch.object(main, "load_config", return_value={}):
                            with patch.object(main, "find_cdp_endpoint", return_value="http://127.0.0.1:9222"):
                                with patch.object(main, "spawn_background_worker") as spawn_worker:
                                    with patch.object(
                                        main, "send_message_via_existing_chromium"
                                    ) as send_existing:
                                        with patch("sys.stdout", new=StringIO()) as stdout:
                                            rc = main.main()
                self.assertEqual(rc, 0)
                spawn_worker.assert_called_once_with(
                    [
                        "--job-id",
                        "job-123",
                        "--timeout",
                        "120",
                        "919999999999",
                        "hello world",
                    ]
                )
                send_existing.assert_not_called()
                self.assertEqual(stdout.getvalue().strip(), "Sending ...")
                payload = main.load_background_job("job-123")
                self.assertEqual(payload["status"], "queued")
                self.assertEqual(payload["recipient"], "919999999999")
                self.assertEqual(main.resolve_background_job_id(), "job-123")

    def test_status_command_returns_latest_job_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(main.os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                payload = {
                    "id": "job-123",
                    "status": "queued",
                    "recipient": "mom (919999999999)",
                    "phone": "919999999999",
                    "text_preview": "hello world",
                    "created_at": "2026-03-21T12:00:00Z",
                    "updated_at": "2026-03-21T12:00:00Z",
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                }
                main.save_background_job(payload)
                with patch.object(sys, "argv", ["main.py", "st"]):
                    with patch("sys.stdout", new=StringIO()) as stdout:
                        rc = main.main()
                self.assertEqual(rc, 0)
                self.assertEqual(json.loads(stdout.getvalue()), payload)

    def test_foreground_flag_uses_existing_chromium_automation(self):
        with patch.object(sys, "argv", ["main.py", "-fg", "919999999999", "hello world"]):
            with patch.object(main, "load_config", return_value={}):
                with patch.object(main, "find_cdp_endpoint", return_value="http://127.0.0.1:9222"):
                    with patch.object(main, "send_message_via_existing_chromium") as send_existing:
                        rc = main.main()
        self.assertEqual(rc, 0)
        send_existing.assert_called_once()
        args = send_existing.call_args[0]
        self.assertEqual(args[1], "hello world")
        self.assertEqual(args[2], 120)
        self.assertEqual(args[3], "http://127.0.0.1:9222")

    def test_profile_flag_spawns_background_worker_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(main.os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                with patch.object(main, "_new_job_id", return_value="job-456"):
                    with patch.object(
                        sys,
                        "argv",
                        ["main.py", "--profile", "~/tmp-wa", "919999999999", "hello world"],
                    ):
                        with patch.object(main, "load_config", return_value={}):
                            with patch.object(main, "spawn_background_worker") as spawn_worker:
                                with patch.object(main, "send_message_via_managed_browser") as send_managed:
                                    rc = main.main()
                self.assertEqual(rc, 0)
                spawn_worker.assert_called_once_with(
                    [
                        "--job-id",
                        "job-456",
                        "--timeout",
                        "120",
                        "--profile",
                        "~/tmp-wa",
                        "919999999999",
                        "hello world",
                    ]
                )
                send_managed.assert_not_called()
                self.assertEqual(main.resolve_background_job_id(), "job-456")

    def test_worker_mode_notifies_on_success_and_updates_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(main.os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                with patch.object(main, "_new_job_id", return_value="job-789"):
                    main.create_background_job("mom", "919999999999", "hello world from background")
                with patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--worker",
                        "--job-id",
                        "job-789",
                        "mom",
                        "hello world from background",
                    ],
                ):
                    with patch.object(
                        main,
                        "load_config",
                        return_value={"contact_labels": {"mom": "919999999999"}},
                    ):
                        with patch.object(main, "find_cdp_endpoint", return_value="http://127.0.0.1:9222"):
                            with patch.object(main, "send_message_via_existing_chromium") as send_existing:
                                with patch.object(main, "_notify") as notify:
                                    rc = main.main()
                self.assertEqual(rc, 0)
                send_existing.assert_called_once()
                payload = main.load_background_job("job-789")
                self.assertEqual(payload["status"], "sent")
                self.assertIsNotNone(payload["started_at"])
                self.assertIsNotNone(payload["completed_at"])
                notify.assert_called_once_with(
                    "WhatsApp sent",
                    "mom (919999999999): hello world from background",
                )

    def test_worker_mode_notifies_on_failure_and_updates_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(main.os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                with patch.object(main, "_new_job_id", return_value="job-999"):
                    main.create_background_job("919999999999", "919999999999", "hello world")
                with patch.object(
                    sys,
                    "argv",
                    [
                        "main.py",
                        "--worker",
                        "--job-id",
                        "job-999",
                        "919999999999",
                        "hello world",
                    ],
                ):
                    with patch.object(main, "load_config", return_value={}):
                        with patch.object(main, "find_cdp_endpoint", return_value="http://127.0.0.1:9222"):
                            with patch.object(
                                main,
                                "send_message_via_existing_chromium",
                                side_effect=SystemExit("Timed out waiting for WhatsApp Web."),
                            ):
                                with patch.object(main, "_notify") as notify:
                                    with patch.object(main, "_log_worker_error") as log_error:
                                        with self.assertRaises(SystemExit):
                                            main.main()
                payload = main.load_background_job("job-999")
                self.assertEqual(payload["status"], "failed")
                self.assertEqual(payload["error"], "Timed out waiting for WhatsApp Web.")
                log_error.assert_called_once_with("Timed out waiting for WhatsApp Web.")
                notify.assert_called_once_with(
                    "WhatsApp send failed",
                    "Timed out waiting for WhatsApp Web.",
                    urgency="critical",
                )


if __name__ == "__main__":
    unittest.main()
