from __future__ import annotations

import importlib.util
import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "vidux_browser_server", ROOT / "browser" / "server.py"
)
browser_server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(browser_server)


def synthetic_secret() -> str:
    # Built at runtime so repository secret scanners never see a token-shaped
    # fixture while the browser policy still exercises a realistic value.
    return "sk-" + ("A1b2C3d4" * 6)


class BrowserSensitiveContentTests(unittest.TestCase):
    def test_redacts_provider_assignment_and_standalone_entropy_without_hash_noise(self):
        provider_secret = synthetic_secret()
        pasted_secret = "".join((
            "Ab3_", "kL7#", "Qx9_", "mN2#", "Rs5_", "tU8#",
            "Vw1_", "yZ4#", "Cd6_", "fG0#", "Hi2_", "jK7#",
        ))
        digest = "a1b2c3d4" * 8
        text = (
            f"API_TOKEN={provider_secret}\n"
            f"pasted value: {pasted_secret}\n"
            f"fixture digest: {digest}\n"
            "API_TOKEN=example-placeholder\n"
        )

        redacted, count = browser_server.redact_sensitive_text(text)

        self.assertEqual(count, 2)
        self.assertNotIn(provider_secret, redacted)
        self.assertNotIn(pasted_secret, redacted)
        self.assertIn("[REDACTED:secret]", redacted)
        self.assertIn(digest, redacted)
        self.assertIn("example-placeholder", redacted)

    def test_redacts_short_explicit_password_but_keeps_empty_state_marker(self):
        redacted, count = browser_server.redact_sensitive_text(
            'password="s3cr3t!"\npassword=unset\n'
        )

        self.assertEqual(count, 1)
        self.assertNotIn("s3cr3t!", redacted)
        self.assertIn("password=unset", redacted)

    def test_recursive_json_redaction_covers_values_and_keys(self):
        secret = synthetic_secret()

        safe = browser_server.redact_sensitive_value({secret: {"token": (secret,)}})
        rendered = json.dumps(safe)

        self.assertNotIn(secret, rendered)
        self.assertEqual(list(safe), ["[REDACTED:secret]"])

    def test_session_and_ledger_excerpts_share_the_redaction_boundary(self):
        secret = synthetic_secret()

        session = browser_server.compact_session_text(f"rotate {secret} now")
        ledger = browser_server.compact_ledger_text(f"proof token={secret}")

        self.assertNotIn(secret, session)
        self.assertNotIn(secret, ledger)
        self.assertIn("[REDACTED:secret]", session)
        self.assertIn("[REDACTED:secret]", ledger)

    def test_plan_metadata_is_derived_from_redacted_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = browser_server.DEV_ROOT
            root = Path(tmpdir).resolve()
            browser_server.DEV_ROOT = root
            try:
                plan = root / "repo" / "projects" / "demo" / "PLAN.md"
                plan.parent.mkdir(parents=True)
                secret = synthetic_secret()
                plan.write_text(
                    "# Demo\n\n"
                    f"## Purpose\nUse API_TOKEN={secret} for deploys.\n\n"
                    "## Tasks\n"
                    f"- [in_progress] rotate {secret}\n",
                    encoding="utf-8",
                )

                metadata = browser_server.plan_meta(plan)
            finally:
                browser_server.DEV_ROOT = original_root

        self.assertTrue(metadata["content_redacted"])
        self.assertGreaterEqual(metadata["sensitive_redactions"], 2)
        self.assertNotIn(secret, json.dumps(metadata))
        self.assertIn("[REDACTED:secret]", json.dumps(metadata))

    def test_root_level_plan_reports_scanned_root_as_repo(self):
        # Regression: in a root-scoped browse (`vidux browse --root <repo>`) a
        # PLAN.md directly under DEV_ROOT used to surface repo="PLAN.md", which
        # became the sidebar group header.
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = browser_server.DEV_ROOT
            root = Path(tmpdir).resolve() / "myproject"
            root.mkdir()
            browser_server.DEV_ROOT = root
            try:
                plan = root / "PLAN.md"
                plan.write_text(
                    "# My Project\n\n## Purpose\nTest.\n\n## Tasks\n"
                    "- [pending] Task 1: do the thing [Evidence: seeded]\n",
                    encoding="utf-8",
                )
                metadata = browser_server.plan_meta(plan)
                ledger_repo, _ = browser_server.plan_ledger_match_paths(plan)
            finally:
                browser_server.DEV_ROOT = original_root

        self.assertEqual(metadata["repo"], "myproject")
        self.assertEqual(metadata["slug"], "_root_")
        self.assertEqual(ledger_repo, "myproject")

    def test_repo_subdir_plan_keeps_directory_repo_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = browser_server.DEV_ROOT
            root = Path(tmpdir).resolve()
            browser_server.DEV_ROOT = root
            try:
                plan = root / "somerepo" / "PLAN.md"
                plan.parent.mkdir(parents=True)
                plan.write_text("# Repo\n\n## Tasks\n", encoding="utf-8")
                metadata = browser_server.plan_meta(plan)
            finally:
                browser_server.DEV_ROOT = original_root

        self.assertEqual(metadata["repo"], "somerepo")
        self.assertEqual(metadata["slug"], "_root_")


class BrowserLocalPlanNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.plan_dir = self.dev_root / "repo" / "projects" / "demo"
        self.plan_dir.mkdir(parents=True)
        self.plan_path = self.plan_dir / "PLAN.md"
        self.plan_path.write_text(
            "# Demo\n\n## Purpose\nLocal test plan.\n",
            encoding="utf-8",
        )
        browser_server.DEV_ROOT = self.dev_root

    def tearDown(self):
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def test_write_plan_note_creates_inbox_under_open(self):
        ok, path = browser_server.write_plan_note(
            self.plan_path,
            "capture this local-only note",
            source="codex/test",
            agent="codex/demo",
        )

        self.assertTrue(ok, path)
        inbox = Path(path)
        text = inbox.read_text(encoding="utf-8")
        self.assertIn("## Open", text)
        self.assertIn("## Processed", text)
        self.assertIn("- Source: codex/test", text)
        self.assertIn("- Agent: codex/demo", text)
        self.assertIn("> capture this local-only note", text)
        self.assertLess(text.index("capture this"), text.index("## Processed"))

    def test_write_plan_note_preserves_existing_processed_section(self):
        inbox = self.plan_dir / "INBOX.md"
        inbox.write_text(
            "## Open\n\n## Processed\n\n### Old\n",
            encoding="utf-8",
        )

        ok, msg = browser_server.write_plan_note(self.plan_path, "new note")

        self.assertTrue(ok, msg)
        text = inbox.read_text(encoding="utf-8")
        self.assertEqual(text.count("## Open"), 1)
        self.assertIn("> new note", text)
        self.assertLess(text.index("> new note"), text.index("## Processed"))
        self.assertIn("### Old", text)

    def test_write_plan_note_rejects_sensitive_content(self):
        secret = synthetic_secret()

        ok, message = browser_server.write_plan_note(
            self.plan_path,
            f"save this credential: {secret}",
        )

        self.assertFalse(ok)
        self.assertEqual(message, "note contains sensitive content")
        self.assertFalse((self.plan_dir / "INBOX.md").exists())

    def test_write_plan_note_rejects_sensitive_source_and_agent(self):
        secret = synthetic_secret()

        for field in ("source", "agent"):
            with self.subTest(field=field):
                kwargs = {field: secret}
                ok, message = browser_server.write_plan_note(
                    self.plan_path,
                    "safe note",
                    **kwargs,
                )

                self.assertFalse(ok)
                self.assertEqual(message, "note contains sensitive content")
                self.assertFalse((self.plan_dir / "INBOX.md").exists())

    def test_resolve_plan_note_target_requires_plan_md_under_dev_root(self):
        evidence = self.plan_dir / "evidence.md"
        evidence.write_text("nope", encoding="utf-8")
        outside = Path(self.tmp.name).parent / "outside-plan.md"
        outside.write_text("# Outside", encoding="utf-8")

        self.assertEqual(
            browser_server.resolve_plan_note_target(str(self.plan_path)),
            self.plan_path.resolve(),
        )
        self.assertIsNone(browser_server.resolve_plan_note_target(str(evidence)))
        self.assertIsNone(browser_server.resolve_plan_note_target(str(outside)))

    def test_loopback_guard(self):
        self.assertTrue(browser_server.is_loopback_host("127.0.0.1"))
        self.assertTrue(browser_server.is_loopback_host("::1"))
        self.assertFalse(browser_server.is_loopback_host("192.0.2.55"))

    def test_allowed_request_host_accepts_loopback_identities(self):
        for host in ("127.0.0.1:7191", "localhost:7191", "[::1]:7191", "127.0.0.1"):
            self.assertTrue(
                browser_server.is_allowed_request_host(host, "127.0.0.1"),
                f"expected {host!r} to be allowed",
            )

    def test_allowed_request_host_rejects_dns_rebound_hostname(self):
        # A rebound page presents Host and Origin that agree with EACH OTHER
        # (both "evil.example") -- origin_matches_host alone would pass this.
        # The Host allowlist must reject it independently of Origin.
        self.assertFalse(
            browser_server.is_allowed_request_host("evil.example:7191", "127.0.0.1")
        )
        self.assertTrue(
            browser_server.origin_matches_host(
                "http://evil.example:7191", "evil.example:7191"
            ),
            "sanity check: Origin==Host agreement alone is not a defense",
        )

    def test_allowed_request_host_permits_private_ip_in_lan_bind_mode(self):
        # Wildcard bind exposes the server to a trusted LAN, but it must still
        # admit a concrete private IP identity rather than every Host value.
        self.assertTrue(
            browser_server.is_allowed_request_host("192.168.1.50:7191", "0.0.0.0")
        )

    def test_allowed_request_host_rejects_domain_in_lan_bind_mode(self):
        # A DNS-rebound page presents its registered domain as both Host and
        # Origin. Wildcard bind cannot mean wildcard Host trust.
        for bind_host in ("0.0.0.0", "::"):
            self.assertFalse(
                browser_server.is_allowed_request_host("evil.example:7191", bind_host)
            )

    def test_allowed_request_host_normalizes_specific_ipv6_bind(self):
        self.assertTrue(
            browser_server.is_allowed_request_host("[fd00::1]:7191", "fd00::1")
        )

    def test_private_lan_ip_literal_accepts_rfc1918_and_rejects_domains(self):
        for host in ("192.168.1.50", "10.0.0.5", "172.16.4.4", "[fd00::1]"):
            self.assertTrue(
                browser_server.is_private_lan_ip_literal(host),
                f"expected {host!r} to be recognized as a private-LAN literal",
            )
        # A DNS-rebound page's Host header is always the attacker's own
        # registered domain name (what the address bar held) -- never a raw
        # private-IP literal, since there's no reason to register one.
        for host in ("evil.example", "127.0.0.1", "8.8.8.8", "169.254.1.1", ""):
            self.assertFalse(
                browser_server.is_private_lan_ip_literal(host),
                f"expected {host!r} to be rejected",
            )


class BrowserWriteEndpointHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.artifacts_dir = self.dev_root / ".artifacts"
        self.comments_file = self.dev_root / ".vidux-browser-comments.jsonl"
        self.original_dev_root = browser_server.DEV_ROOT
        self.original_artifacts_dir = browser_server.ARTIFACTS_DIR
        self.original_comments_file = browser_server.COMMENTS_FILE
        self.original_steering_file = browser_server.STEERING_FILE
        self.original_claims_file = browser_server.CLAIMS_FILE
        browser_server.DEV_ROOT = self.dev_root
        browser_server.ARTIFACTS_DIR = self.artifacts_dir
        browser_server.COMMENTS_FILE = self.comments_file
        self.steering_file = self.dev_root / ".vidux-browser-steering.jsonl"
        browser_server.STEERING_FILE = self.steering_file
        self.claims_file = self.dev_root / ".agent-ledger-claims.jsonl"
        browser_server.CLAIMS_FILE = self.claims_file

        self.plan_dir = self.dev_root / "repo" / "projects" / "demo"
        self.plan_dir.mkdir(parents=True)
        self.plan_path = self.plan_dir / "PLAN.md"
        self.plan_path.write_text("# Demo\n\n## Purpose\nTest.\n", encoding="utf-8")

        self.httpd = browser_server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            browser_server.Handler,
        )
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.ARTIFACTS_DIR = self.original_artifacts_dir
        browser_server.COMMENTS_FILE = self.original_comments_file
        browser_server.STEERING_FILE = self.original_steering_file
        browser_server.CLAIMS_FILE = self.original_claims_file
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def post(self, path: str, payload: dict | str, headers: dict[str, str]):
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return self.post_bytes(path, body.encode("utf-8"), headers)

    def post_bytes(self, path: str, body: bytes, headers: dict[str, str]):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=body, headers=headers)
        res = conn.getresponse()
        text = res.read().decode("utf-8", errors="replace")
        conn.close()
        return res.status, text

    def get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        res = conn.getresponse()
        text = res.read().decode("utf-8", errors="replace")
        conn.close()
        return res.status, text

    def get_with_headers(self, path: str, headers: dict[str, str]):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers)
        res = conn.getresponse()
        text = res.read().decode("utf-8", errors="replace")
        conn.close()
        return res.status, text

    def head(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("HEAD", path)
        res = conn.getresponse()
        body = res.read()
        headers = dict(res.getheaders())
        status = res.status
        conn.close()
        return status, headers, body

    def json_headers(self, **extra: str) -> dict[str, str]:
        return {"Content-Type": "application/json", **extra}

    def test_head_health_returns_headers_without_body(self):
        status, headers, body = self.head("/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_head_static_returns_headers_without_body(self):
        status, headers, body = self.head("/")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_head_missing_route_keeps_status_without_body(self):
        status, headers, body = self.head("/nope")

        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_get_rejects_dns_rebound_host_header(self):
        # Simulates a DNS-rebound page: Host and Origin both present as the
        # attacker's domain (so they agree with each other), but the TCP
        # connection still lands on this loopback server. Must be blocked
        # by the Host allowlist, not by Origin==Host agreement.
        status, text = self.get_with_headers(
            "/api/health",
            {"Host": "evil.example:1234", "Origin": "http://evil.example:1234"},
        )

        self.assertEqual(status, 403, text)

    def test_get_accepts_legitimate_loopback_host_header(self):
        status, text = self.get_with_headers(
            "/api/health", {"Host": f"127.0.0.1:{self.port}"}
        )

        self.assertEqual(status, 200, text)

    def test_get_rejects_dns_rebound_host_header_in_lan_bind_mode(self):
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            status, text = self.get_with_headers(
                "/api/plans",
                {"Host": "evil.example:7191", "Origin": "http://evil.example:7191"},
            )
        finally:
            browser_server.HOST = original_host

        self.assertEqual(status, 403, text)

    def test_get_accepts_private_ip_host_header_in_lan_bind_mode(self):
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            status, text = self.get_with_headers(
                "/api/plans", {"Host": "192.168.1.50:7191"}
            )
        finally:
            browser_server.HOST = original_host

        self.assertEqual(status, 200, text)

    def test_steering_http_lifecycle_is_plan_scoped_and_hides_host_fields(self):
        plan_query = quote(str(self.plan_path), safe="")
        status, text = self.get(f"/api/steering?plan_path={plan_query}")
        self.assertEqual(status, 200, text)
        self.assertEqual(json.loads(text)["items"], [])

        status, text = self.post(
            "/api/steering",
            {
                "plan_path": str(self.plan_path),
                "action": "enqueue",
                "message": "Use the intermediate plan on the next cycle.",
                "source": "browser-test",
            },
            self.json_headers(Origin=self.origin()),
        )
        self.assertEqual(status, 200, text)
        item_id = json.loads(text)["item"]["id"]

        status, text = self.get(f"/api/steering?plan_path={plan_query}")
        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(payload["capacity"], browser_server.STEERING_CAPACITY)
        self.assertEqual(payload["items"][0]["status"], "queued")
        self.assertEqual(
            payload["items"][0]["message"],
            "Use the intermediate plan on the next cycle.",
        )
        for private_field in (
            "plan_path", "body", "source", "consumer", "lease_token", "lease_token_hash"
        ):
            self.assertNotIn(private_field, payload["items"][0])

        mailbox = browser_server.steering_mailbox()
        lease = mailbox.lease_next_intent(self.plan_path, "outer-host-test")
        mailbox.fail_intent(item_id, lease["lease_token"], "usage_exhausted")
        status, text = self.get(f"/api/steering?plan_path={plan_query}")
        self.assertEqual(status, 200, text)
        self.assertEqual(json.loads(text)["items"][0]["status"], "retryable")
        self.assertEqual(json.loads(text)["items"][0]["failure_code"], "usage_exhausted")

        status, text = self.post(
            "/api/steering",
            {"plan_path": str(self.plan_path), "action": "retry", "id": item_id},
            self.json_headers(Origin=self.origin()),
        )
        self.assertEqual(status, 200, text)
        lease = mailbox.lease_next_intent(self.plan_path, "outer-host-test")
        mailbox.acknowledge_intent(item_id, lease["lease_token"])

        status, text = self.get(f"/api/steering?plan_path={plan_query}")
        self.assertEqual(status, 200, text)
        self.assertEqual(json.loads(text)["items"], [])
        self.assertNotIn(
            "Use the intermediate plan on the next cycle.",
            self.steering_file.read_text(encoding="utf-8"),
        )

    def test_coordination_http_projects_four_owners_and_resumable_handoff(self):
        store = browser_server.coordination_claims()
        for index in range(4):
            store.claim(
                claim_id=f"clm_owner_{index}",
                repo="repo",
                claim=f"Sources/Currency{index}.swift",
                owner=f"demo-chat-{index + 1}",
                lane=f"currency-{index + 1}",
                plan_path=str(self.plan_path),
                task_id=f"row-{index + 1}",
                host=f"secret-host-{index}",
                pid=9000 + index,
            )
        handoff = store.claim(
            claim_id="clm_handoff",
            repo="repo",
            claim="Sources/Workbench.swift",
            owner="demo-chat-old",
            lane="workbench",
            plan_path=str(self.plan_path),
            task_id="row-handoff",
            host="secret-handoff-host",
            pid=9999,
        )
        store.checkpoint(
            claim_id=handoff["claim"]["claim_id"],
            owner="demo-chat-old",
            summary="layout proof pending",
            resume="run focused workbench tests",
            proof="git diff --check",
        )
        store.release(
            claim_id=handoff["claim"]["claim_id"],
            owner="demo-chat-old",
            status="usage_exhausted",
        )
        # More than the store's historical 256-row global window from another
        # plan must not evict this plan's resume pointer before limiting.
        other_plan = str(self.dev_root / "other" / "PLAN.md")
        events = list(store.read().events)
        for index in range(257):
            claim_id = f"clm_other_{index}"
            owner = f"other-chat-{index}"
            events.extend(
                [
                    {
                        "schema": 2,
                        "event": "claim",
                        "claim_id": claim_id,
                        "ts": "2000-01-01T00:00:00Z",
                        "repo": "repo",
                        "claim": f"Sources/Other{index}.swift",
                        "files_claimed": [f"Sources/Other{index}.swift"],
                        "owner": owner,
                        "lane": "other-plan",
                        "plan_path": other_plan,
                        "task_id": f"other-{index}",
                        "ttl_hours": 2,
                        "expires_at": "2000-01-01T02:00:00Z",
                    },
                    {
                        "schema": 2,
                        "event": "checkpoint",
                        "claim_id": claim_id,
                        "owner": owner,
                        "ts": "2000-01-01T00:01:00Z",
                        "ttl_hours": 2,
                        "expires_at": "2000-01-01T02:01:00Z",
                        "summary": "other work",
                        "resume": "other resume",
                        "proof": "",
                    },
                    {
                        "schema": 2,
                        "event": "release",
                        "claim_id": claim_id,
                        "owner": owner,
                        "ts": "2000-01-01T00:02:00Z",
                        "status": "usage_exhausted",
                    },
                ]
            )
        store._write(events)

        query = quote(str(self.plan_path), safe="")
        status, text = self.get(f"/api/coordination?plan_path={query}")

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(len(payload["active"]), 4)
        self.assertEqual(payload["active"][3]["owner"], "demo-chat-4")
        self.assertEqual(len(payload["handoffs"]), 1)
        self.assertEqual(payload["handoffs"][0]["status"], "usage_exhausted")
        self.assertEqual(
            payload["handoffs"][0]["checkpoint"]["resume"],
            "run focused workbench tests",
        )
        self.assertNotIn("secret-host", text)
        self.assertNotIn('"pid"', text)

    def test_coordination_get_rejects_lan_before_storage(self):
        sent = []
        handler = object.__new__(browser_server.Handler)
        handler.path = f"/api/coordination?plan_path={quote(str(self.plan_path), safe='')}"
        handler.client_address = ("192.168.1.50", 49152)
        handler.headers = {"Host": "192.168.1.50:7191"}
        handler._send = lambda code, msg: sent.append((code, msg))
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            with mock.patch.object(browser_server, "coordination_claims") as claims:
                browser_server.Handler.do_GET(handler)
        finally:
            browser_server.HOST = original_host
        self.assertEqual(sent, [(403, "coordination requires loopback client")])
        claims.assert_not_called()

    def test_steering_http_rejects_sensitive_and_host_only_actions(self):
        status, text = self.post(
            "/api/steering",
            {
                "plan_path": str(self.plan_path),
                "action": "enqueue",
                "message": f"credential={synthetic_secret()}",
            },
            self.json_headers(Origin=self.origin()),
        )
        self.assertEqual(status, 400, text)
        self.assertFalse(self.steering_file.exists())

        for action in ("lease", "ack", "fail"):
            with self.subTest(action=action):
                status, text = self.post(
                    "/api/steering",
                    {"plan_path": str(self.plan_path), "action": action},
                    self.json_headers(Origin=self.origin()),
                )
                self.assertEqual(status, 400, text)

    def test_steering_http_rejects_non_string_action_without_disconnect(self):
        status, text = self.post(
            "/api/steering",
            {"plan_path": str(self.plan_path), "action": []},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "action must be enqueue, retry, or dismiss")

    def test_steering_http_rejects_invalid_utf8(self):
        status, text = self.post_bytes(
            "/api/steering",
            b'{"plan_path":"' + str(self.plan_path).encode("utf-8") + b'","action":"enqueue","message":"\xff"}',
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "body must be valid UTF-8")

    def test_steering_http_accepts_worst_case_encoded_valid_intent(self):
        # ensure_ascii turns each control character into a six-byte JSON escape;
        # decoded mailbox policy, not incidental transport expansion, is the cap.
        message = "\x01" * browser_server.STEERING_INTENT_MAX_BYTES
        body = json.dumps(
            {
                "plan_path": str(self.plan_path),
                "action": "enqueue",
                "message": message,
            }
        ).encode("utf-8")
        self.assertGreater(len(body), browser_server.STEERING_INTENT_MAX_BYTES + 4096)
        self.assertLessEqual(len(body), browser_server.STEERING_HTTP_MAX_BYTES)

        status, text = self.post_bytes(
            "/api/steering",
            body,
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)

    def test_steering_get_rejects_lan_before_storage(self):
        sent = []
        handler = object.__new__(browser_server.Handler)
        handler.path = f"/api/steering?plan_path={quote(str(self.plan_path), safe='')}"
        handler.client_address = ("192.168.1.50", 49152)
        handler.headers = {"Host": "192.168.1.50:7191"}
        handler._send = lambda code, msg: sent.append((code, msg))

        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            with mock.patch.object(browser_server, "steering_mailbox") as mailbox:
                browser_server.Handler.do_GET(handler)
        finally:
            browser_server.HOST = original_host

        self.assertEqual(sent, [(403, "steering requires loopback client")])
        mailbox.assert_not_called()

    def test_steering_corrupt_journal_fails_closed_without_partial_items(self):
        mailbox = browser_server.steering_mailbox()
        mailbox.enqueue_intent(self.plan_path, "valid prefix")
        with self.steering_file.open("a", encoding="utf-8") as handle:
            handle.write("{not-json}\n")

        status, text = self.get(
            f"/api/steering?plan_path={quote(str(self.plan_path), safe='')}"
        )
        self.assertEqual(status, 409, text)
        self.assertEqual(text, "local steering state needs repair")
        self.assertNotIn("valid prefix", text)

    def test_artifact_post_accepts_same_origin_json(self):
        status, text = self.post(
            "/api/artifact",
            {"slug": "safe-artifact", "html": "<h1>Safe</h1>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        self.assertTrue((self.artifacts_dir / "safe-artifact.html").is_file())

    def test_artifact_post_rejects_symlink_target_without_touching_referent(self):
        self.artifacts_dir.mkdir(parents=True)
        outside = self.dev_root / "outside-artifact.html"
        outside.write_text("outside sentinel", encoding="utf-8")
        (self.artifacts_dir / "aliased-artifact.html").symlink_to(outside)

        status, text = self.post(
            "/api/artifact",
            {"slug": "aliased-artifact", "html": "<h1>Overwritten</h1>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside sentinel")

    def test_artifact_post_rejects_hardlink_target_without_touching_referent(self):
        self.artifacts_dir.mkdir(parents=True)
        outside = self.dev_root / "outside-artifact.html"
        outside.write_text("outside sentinel", encoding="utf-8")
        os.link(outside, self.artifacts_dir / "aliased-artifact.html")

        status, text = self.post(
            "/api/artifact",
            {"slug": "aliased-artifact", "html": "<h1>Overwritten</h1>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside sentinel")

    def test_artifact_post_rejects_symlinked_store_directory(self):
        outside = self.dev_root / "outside-artifacts"
        outside.mkdir()
        self.artifacts_dir.symlink_to(outside, target_is_directory=True)

        status, text = self.post(
            "/api/artifact",
            {"slug": "aliased-parent", "html": "<h1>Must stay local</h1>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertFalse((outside / "aliased-parent.html").exists())

    def test_artifact_post_rejects_sensitive_content(self):
        secret = synthetic_secret()

        status, text = self.post(
            "/api/artifact",
            {"slug": "secret-artifact", "html": f"<p>token={secret}</p>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "artifact contains sensitive content")
        self.assertFalse((self.artifacts_dir / "secret-artifact.html").exists())

    def test_artifact_post_rejects_sensitive_slug(self):
        secret_slug = "sk-" + ("a1b2c3d4" * 4)

        status, text = self.post(
            "/api/artifact",
            {"slug": secret_slug, "html": "<p>Safe body</p>"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "artifact contains sensitive content")
        self.assertFalse((self.artifacts_dir / f"{secret_slug}.html").exists())

    def test_artifact_post_rejects_malformed_content_length_header(self):
        """every write route parsed
        Content-Length with a bare int() call, so a hand-crafted non-numeric
        header (e.g. "abc") raised an uncaught ValueError deep inside the
        request handler -- no HTTP response sent, traceback dumped to the
        server's stderr instead. Must degrade to a clean 400."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST",
            "/api/artifact",
            body=b'{"slug": "x", "html": "<h1>x</h1>"}',
            headers={
                "Content-Type": "application/json",
                "Origin": self.origin(),
                "Content-Length": "not-a-number",
            },
        )
        res = conn.getresponse()
        text = res.read().decode("utf-8", errors="replace")
        conn.close()

        self.assertEqual(res.status, 400, text)
        self.assertIn("Content-Length", text)
        self.assertFalse((self.artifacts_dir / "x.html").exists())

    def test_artifact_post_rejects_lan_client(self):
        sent = []
        handler = object.__new__(browser_server.Handler)
        handler.client_address = ("192.0.2.55", 49152)
        handler.headers = {
            "Content-Type": "application/json",
            "Host": f"127.0.0.1:{self.port}",
            "Origin": self.origin(),
        }
        handler._send = lambda code, msg: sent.append((code, msg))

        self.assertFalse(browser_server.Handler._require_json_write(handler))
        self.assertEqual(sent, [(403, "write endpoints require loopback client")])

    def test_artifact_post_rejects_simple_content_type(self):
        status, text = self.post(
            "/api/artifact",
            json.dumps({"slug": "simple-body", "html": "<h1>Nope</h1>"}),
            {"Content-Type": "text/plain", "Origin": self.origin()},
        )

        self.assertEqual(status, 415, text)
        self.assertFalse((self.artifacts_dir / "simple-body.html").exists())

    def test_artifact_post_rejects_cross_origin(self):
        status, text = self.post(
            "/api/artifact",
            {"slug": "evil-origin", "html": "<h1>Nope</h1>"},
            self.json_headers(Origin="http://evil.example"),
        )

        self.assertEqual(status, 403, text)
        self.assertFalse((self.artifacts_dir / "evil-origin.html").exists())

    def test_plan_note_post_accepts_same_origin_json(self):
        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": "safe note"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        self.assertIn("safe note", (self.plan_dir / "INBOX.md").read_text(encoding="utf-8"))

    def test_plan_note_post_rejects_symlink_inbox_without_touching_referent(self):
        outside = self.dev_root / "outside-inbox.md"
        outside.write_text("# Outside\n\n## Open\n", encoding="utf-8")
        (self.plan_dir / "INBOX.md").symlink_to(outside)

        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": "must stay local"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(
            outside.read_text(encoding="utf-8"),
            "# Outside\n\n## Open\n",
        )

    def test_plan_note_post_rejects_hardlink_inbox_without_touching_referent(self):
        outside = self.dev_root / "outside-inbox.md"
        outside.write_text("# Outside\n\n## Open\n", encoding="utf-8")
        os.link(outside, self.plan_dir / "INBOX.md")

        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": "must stay local"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(
            outside.read_text(encoding="utf-8"),
            "# Outside\n\n## Open\n",
        )

    def test_plan_note_post_rejects_sensitive_content_without_inbox_write(self):
        secret = synthetic_secret()

        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": f"credential={secret}"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "note contains sensitive content")
        self.assertFalse((self.plan_dir / "INBOX.md").exists())

    def test_plan_note_post_rejects_cross_origin(self):
        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": "evil note"},
            self.json_headers(Origin="http://evil.example"),
        )

        self.assertEqual(status, 403, text)
        self.assertFalse((self.plan_dir / "INBOX.md").exists())

    def test_plan_note_post_requires_origin_or_referer(self):
        # _require_json_write() (used by every write
        # route except /api/comments) previously allowed a request through
        # when BOTH Origin and Referer were absent. Not exploitable from a
        # real browser, but a loopback process with no headers at all
        # shouldn't get a free pass either -- matches /api/comments's
        # already-stricter require_origin=True.
        status, text = self.post(
            "/api/local-plan-note",
            {"plan_path": str(self.plan_path), "note": "no-origin note"},
            {"Content-Type": "application/json"},
        )

        self.assertEqual(status, 403, text)
        self.assertFalse((self.plan_dir / "INBOX.md").exists())

    def test_comments_post_accepts_same_origin_json_for_plan_without_inbox_write(self):
        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": "This needs a quick annotation.",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        self.assertFalse((self.plan_dir / "INBOX.md").exists())
        status, text = self.get(f"/api/comments?path={self.plan_path}")
        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(payload["target_kind"], "plan")
        self.assertEqual(payload["comments"][0]["author"], "Viewer")
        self.assertEqual(payload["comments"][0]["body"], "This needs a quick annotation.")

    def test_comments_post_rejects_symlink_store_without_touching_referent(self):
        outside = self.dev_root / "outside-comments.jsonl"
        outside.write_text('{"outside":true}\n', encoding="utf-8")
        self.comments_file.symlink_to(outside)

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": "must stay local",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"outside":true}\n')

    def test_comments_post_rejects_hardlink_store_without_touching_referent(self):
        outside = self.dev_root / "outside-comments.jsonl"
        outside.write_text('{"outside":true}\n', encoding="utf-8")
        os.link(outside, self.comments_file)

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": "must stay local",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"outside":true}\n')

    def test_comments_post_rejects_aliased_lock_file(self):
        outside = self.dev_root / "outside-comments-lock"
        outside.write_text("outside sentinel", encoding="utf-8")
        lock_path = self.comments_file.with_suffix(self.comments_file.suffix + ".lock")

        for alias_kind in ("symlink", "hardlink"):
            with self.subTest(alias_kind=alias_kind):
                lock_path.unlink(missing_ok=True)
                if alias_kind == "symlink":
                    lock_path.symlink_to(outside)
                else:
                    os.link(outside, lock_path)

                status, text = self.post(
                    "/api/comments",
                    {
                        "target_path": str(self.plan_path),
                        "author": "Viewer",
                        "body": "must stay local",
                    },
                    self.json_headers(Origin=self.origin()),
                )

                self.assertEqual(status, 400, text)
                self.assertFalse(self.comments_file.exists())
                self.assertEqual(outside.read_text(encoding="utf-8"), "outside sentinel")

        lock_path.unlink(missing_ok=True)

    def test_comments_cross_process_writes_do_not_lose_records(self):
        start_file = self.dev_root / "release-comment-workers"
        script = """
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import server

original_atomic_write = server.atomic_write_text

def delayed_atomic_write(*args, **kwargs):
    time.sleep(0.05)
    return original_atomic_write(*args, **kwargs)

server.atomic_write_text = delayed_atomic_write
while not Path(sys.argv[4]).exists():
    time.sleep(0.01)
ok, message = server.append_comment(
    Path(sys.argv[2]),
    "worker",
    sys.argv[3],
    "127.0.0.1",
)
if not ok:
    print(message, file=sys.stderr)
    raise SystemExit(1)
"""
        env = os.environ.copy()
        env["VIDUX_DEV_ROOT"] = str(self.dev_root)
        env["VIDUX_BROWSER_COMMENTS_FILE"] = str(self.comments_file)
        workers = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(ROOT / "browser"),
                    str(self.plan_path),
                    f"worker-{index}",
                    str(start_file),
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(8)
        ]
        start_file.touch()

        failures = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=15)
            if worker.returncode != 0:
                failures.append((worker.returncode, stdout, stderr))
        self.assertEqual(failures, [])

        records = [
            json.loads(line)
            for line in self.comments_file.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(records), 8)
        self.assertEqual(
            {record["body"] for record in records},
            {f"worker-{index}" for index in range(8)},
        )

    def test_comments_post_rejects_symlinked_store_directory(self):
        outside = self.dev_root / "outside-comments"
        outside.mkdir()
        alias = self.dev_root / "comments-alias"
        alias.symlink_to(outside, target_is_directory=True)
        browser_server.COMMENTS_FILE = alias / "comments.jsonl"

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": "must stay local",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertFalse((outside / "comments.jsonl").exists())

    def test_comments_post_rejects_sensitive_content(self):
        secret = synthetic_secret()

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": f"credential={secret}",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 400, text)
        self.assertEqual(text, "comment contains sensitive content")
        self.assertFalse(self.comments_file.exists())

    def test_comments_post_rejects_sensitive_author_and_anchor(self):
        secret = synthetic_secret()
        cases = (
            {"author": secret, "body": "safe body"},
            {
                "author": "Viewer",
                "body": "safe body",
                "anchor": {"label": f"credential={secret}"},
            },
        )

        for payload in cases:
            with self.subTest(payload_fields=tuple(payload)):
                status, text = self.post(
                    "/api/comments",
                    {"target_path": str(self.plan_path), **payload},
                    self.json_headers(Origin=self.origin()),
                )

                self.assertEqual(status, 400, text)
                self.assertEqual(text, "comment contains sensitive content")
                self.assertFalse(self.comments_file.exists())

    def test_comments_get_redacts_legacy_sensitive_content(self):
        secret = synthetic_secret()
        self.comments_file.write_text(
            json.dumps({
                "id": "legacy-secret",
                "target_path": str(self.plan_path),
                "target_kind": "plan",
                "author": "Viewer",
                "body": f"old token={secret}",
            }) + "\n",
            encoding="utf-8",
        )

        status, text = self.get(f"/api/comments?path={self.plan_path}")

        self.assertEqual(status, 200, text)
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED:secret]", text)

    def test_comments_post_persists_clean_anchor_metadata(self):
        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(self.plan_path),
                "author": "Viewer",
                "body": "Anchored note.",
                "anchor": {
                    "selector": '[data-vidux-anchor="a3"]',
                    "label": "Tasks / - [pending] Demo task",
                    "excerpt": "- [pending] Demo task",
                    "tag": "li",
                    "kind": "rendered",
                    "index": 3,
                    "ignored": "nope",
                },
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        anchor = payload["comment"]["anchor"]
        self.assertEqual(anchor["version"], 1)
        self.assertEqual(anchor["selector"], '[data-vidux-anchor="a3"]')
        self.assertEqual(anchor["label"], "Tasks / - [pending] Demo task")
        self.assertEqual(anchor["excerpt"], "- [pending] Demo task")
        self.assertEqual(anchor["tag"], "li")
        self.assertEqual(anchor["kind"], "rendered")
        self.assertEqual(anchor["index"], 3)
        self.assertNotIn("ignored", anchor)

    def test_comments_post_accepts_artifact_target(self):
        self.artifacts_dir.mkdir(parents=True)
        artifact = self.artifacts_dir / "demo.html"
        artifact.write_text("<h1>Demo</h1>", encoding="utf-8")

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(artifact),
                "author": "viewer/lan",
                "body": "Artifact comment.",
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(payload["comment"]["target_kind"], "artifact")
        status, text = self.get(f"/api/comments?path={artifact}")
        self.assertEqual(status, 200, text)
        self.assertIn("Artifact comment.", text)

    def test_comments_post_accepts_evidence_markdown_target(self):
        evidence_dir = self.plan_dir / "evidence"
        evidence_dir.mkdir()
        evidence = evidence_dir / "2026-05-24-browser-proof.md"
        evidence.write_text("# Browser proof\n\nLooks good.\n", encoding="utf-8")

        status, text = self.post(
            "/api/comments",
            {
                "target_path": str(evidence),
                "author": "Viewer",
                "body": "Evidence annotation.",
                "anchor": {"selector": '[data-vidux-anchor="a1"]', "label": "Content / Browser proof"},
            },
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(payload["comment"]["target_kind"], "plan")
        self.assertEqual(payload["comment"]["target_path"], str(evidence.resolve()))
        status, text = self.get(f"/api/comments?path={evidence}")
        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertEqual(payload["comments"][0]["body"], "Evidence annotation.")
        self.assertEqual(payload["comments"][0]["anchor"]["label"], "Content / Browser proof")

    def test_comments_post_rejects_cross_origin(self):
        status, text = self.post(
            "/api/comments",
            {"target_path": str(self.plan_path), "author": "bad", "body": "evil note"},
            self.json_headers(Origin="http://evil.example"),
        )

        self.assertEqual(status, 403, text)
        self.assertFalse(self.comments_file.exists())

    def test_comments_post_rejects_simple_content_type(self):
        status, text = self.post(
            "/api/comments",
            json.dumps({"target_path": str(self.plan_path), "author": "bad", "body": "evil note"}),
            {"Content-Type": "text/plain", "Origin": self.origin()},
        )

        self.assertEqual(status, 415, text)
        self.assertFalse(self.comments_file.exists())

    def test_comments_post_requires_origin_or_referer(self):
        status, text = self.post(
            "/api/comments",
            {"target_path": str(self.plan_path), "author": "bad", "body": "no origin"},
            self.json_headers(),
        )

        self.assertEqual(status, 403, text)
        self.assertFalse(self.comments_file.exists())

    def test_comments_browser_json_guard_allows_lan_same_origin(self):
        sent = []
        handler = object.__new__(browser_server.Handler)
        handler.client_address = ("192.0.2.55", 49152)
        handler.headers = {
            "Content-Type": "application/json",
            "Host": f"127.0.0.1:{self.port}",
            "Origin": self.origin(),
        }
        handler._send = lambda code, msg: sent.append((code, msg))

        self.assertTrue(browser_server.Handler._require_browser_json(handler, require_origin=True))
        self.assertEqual(sent, [])

    def test_comment_write_accepts_real_lan_peer_only_in_lan_bind_mode(self):
        # /api/comments skipped the loopback backstop every other
        # write route gets, so its Origin/Referer==Host check alone was as
        # DNS-rebinding-exploitable as every route was before the Host
        # allowlist fix. _require_comment_write closes this for the default
        # (127.0.0.1) bind by requiring the loopback TCP peer, same as every
        # other route; only in the documented LAN-bind mode does it accept a
        # non-loopback peer, and only when the Host header is a private-IP
        # literal (never what a rebound domain's Host header looks like).
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            sent = []
            handler = object.__new__(browser_server.Handler)
            handler.client_address = ("192.168.1.50", 49152)
            handler.headers = {
                "Content-Type": "application/json",
                "Host": "192.168.1.50:7191",
                "Origin": "http://192.168.1.50:7191",
            }
            handler._send = lambda code, msg: sent.append((code, msg))

            self.assertTrue(browser_server.Handler._require_comment_write(handler))
            self.assertEqual(sent, [])
        finally:
            browser_server.HOST = original_host

    def test_comment_write_rejects_rebound_lan_peer_even_with_matching_origin(self):
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            sent = []
            handler = object.__new__(browser_server.Handler)
            # Real TCP peer is on the LAN (not loopback), but its Host header
            # is a registered domain, not a private-IP literal -- exactly
            # what a DNS-rebound page presents.
            handler.client_address = ("192.168.1.77", 49152)
            handler.headers = {
                "Content-Type": "application/json",
                "Host": "evil.example:7191",
                "Origin": "http://evil.example:7191",
            }
            handler._send = lambda code, msg: sent.append((code, msg))

            self.assertFalse(browser_server.Handler._require_comment_write(handler))
            self.assertEqual(
                sent, [(403, "comments require a loopback or private-LAN client")]
            )
        finally:
            browser_server.HOST = original_host

    def test_comment_write_rejects_public_peer_with_lan_shaped_host_header(self):
        original_host = browser_server.HOST
        browser_server.HOST = "0.0.0.0"
        try:
            sent = []
            handler = object.__new__(browser_server.Handler)
            handler.client_address = ("8.8.8.8", 49152)
            handler.headers = {
                "Content-Type": "application/json",
                "Host": "192.168.1.50:7191",
                "Origin": "http://192.168.1.50:7191",
            }
            handler._send = lambda code, msg: sent.append((code, msg))

            self.assertFalse(browser_server.Handler._require_comment_write(handler))
            self.assertEqual(
                sent, [(403, "comments require a loopback or private-LAN client")]
            )
        finally:
            browser_server.HOST = original_host

    def test_comment_write_rejects_non_loopback_peer_in_default_bind_mode(self):
        # HOST stays at the module default ("127.0.0.1") -- the LAN carve-out
        # must not apply outside the explicit LAN-bind opt-in.
        sent = []
        handler = object.__new__(browser_server.Handler)
        handler.client_address = ("192.168.1.50", 49152)
        handler.headers = {
            "Content-Type": "application/json",
            "Host": "192.168.1.50:7191",
            "Origin": "http://192.168.1.50:7191",
        }
        handler._send = lambda code, msg: sent.append((code, msg))

        self.assertFalse(browser_server.Handler._require_comment_write(handler))
        self.assertEqual(
            sent, [(403, "comments require a loopback or private-LAN client")]
        )

    def test_comment_write_accepts_real_loopback_peer_regardless_of_bind_mode(self):
        status, text = self.post(
            "/api/comments",
            {"target_path": str(self.plan_path), "body": "hello"},
            self.json_headers(Origin=self.origin()),
        )

        self.assertEqual(status, 200, text)

    def test_api_file_returns_404_for_allowed_missing_file(self):
        missing = self.plan_dir / "INBOX.md"

        status, text = self.get(f"/api/file?path={quote(str(missing), safe='')}")

        self.assertEqual(status, 404, text)
        self.assertEqual(text, "file missing: INBOX.md")

    def test_api_file_still_rejects_forbidden_missing_file(self):
        forbidden = self.plan_dir / ".env"

        status, text = self.get(f"/api/file?path={quote(str(forbidden), safe='')}")

        self.assertEqual(status, 403, text)
        self.assertEqual(text, "forbidden")

    def test_artifact_file_response_enforces_network_isolation_headers(self):
        self.artifacts_dir.mkdir(parents=True)
        artifact = self.artifacts_dir / "isolated.html"
        artifact.write_text("<h1>Isolated</h1>", encoding="utf-8")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"/api/file?path={quote(str(artifact), safe='')}")
        res = conn.getresponse()
        body = res.read().decode("utf-8", errors="replace")
        headers = dict(res.getheaders())
        conn.close()

        self.assertEqual(res.status, 200, body)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(
            headers.get("Content-Disposition"),
            'attachment; filename="vidux-artifact.html"',
        )
        policy = headers.get("Content-Security-Policy", "")
        for directive in (
            "default-src 'none'",
            "connect-src 'none'",
            "frame-src 'none'",
            "form-action 'none'",
            "object-src 'none'",
            "script-src 'none'",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, policy)
        self.assertIn("style-src 'unsafe-inline'", policy)
        self.assertNotIn("style-src 'self'", policy)

    def test_plain_text_error_backstop_redacts_sensitive_filename(self):
        secret = synthetic_secret()
        missing = self.artifacts_dir / f"{secret}.html"

        original_stderr = browser_server.sys.stderr
        browser_server.sys.stderr = io.StringIO()
        try:
            status, text = self.get(f"/api/file?path={quote(str(missing), safe='')}")
            log = browser_server.sys.stderr.getvalue()
        finally:
            browser_server.sys.stderr = original_stderr

        self.assertEqual(status, 404, text)
        self.assertNotIn(secret, text)
        self.assertEqual(text, "file missing: [REDACTED:secret].html")
        self.assertNotIn(secret, log)
        self.assertIn("[REDACTED:secret]", log)

    def test_request_log_flattens_decoded_control_characters(self):
        secret = synthetic_secret()
        handler = object.__new__(browser_server.Handler)
        handler.log_date_time_string = lambda: "10/Jul/2026 04:00:00"

        original_stderr = browser_server.sys.stderr
        browser_server.sys.stderr = io.StringIO()
        try:
            handler.log_message(
                '"GET /probe%%0Aforged/%s HTTP/1.1" %s -',
                secret,
                "404",
            )
            log = browser_server.sys.stderr.getvalue()
        finally:
            browser_server.sys.stderr = original_stderr

        self.assertNotIn(secret, log)
        self.assertIn("[REDACTED:secret]", log)
        self.assertEqual(log.count("\n"), 1)
        self.assertNotIn("\nforged", log)

    def test_api_file_and_plan_payload_redact_sensitive_content(self):
        secret = synthetic_secret()
        self.plan_path.write_text(
            "# Demo\n\n"
            f"## Purpose\nDeploy with API_TOKEN={secret}.\n\n"
            "## Tasks\n"
            f"- [in_progress] rotate {secret}\n",
            encoding="utf-8",
        )
        browser_server.clear_plans_cache()

        status, file_text = self.get(
            f"/api/file?path={quote(str(self.plan_path), safe='')}"
        )
        plans_status, plans_text = self.get("/api/plans")

        self.assertEqual(status, 200, file_text)
        self.assertEqual(plans_status, 200, plans_text)
        self.assertNotIn(secret, file_text)
        self.assertNotIn(secret, plans_text)
        self.assertIn("[REDACTED:secret]", file_text)
        payload = json.loads(plans_text)
        plan = next(item for item in payload["plans"] if item["path"] == str(self.plan_path))
        self.assertTrue(plan["content_redacted"])
        self.assertGreaterEqual(plan["sensitive_redactions"], 2)

    def test_json_response_backstop_redacts_route_metadata(self):
        secret = synthetic_secret()
        original_artifacts_dir = browser_server.ARTIFACTS_DIR
        browser_server.ARTIFACTS_DIR = self.dev_root / secret
        try:
            status, text = self.get("/api/health")
        finally:
            browser_server.ARTIFACTS_DIR = original_artifacts_dir

        self.assertEqual(status, 200, text)
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED:secret]", text)


class BrowserArtifactBaseCssTests(unittest.TestCase):
    def test_shared_artifact_base_css_contract(self):
        css_path = ROOT / "browser" / "static" / "artifact-base.css"

        self.assertTrue(css_path.is_file())
        css = css_path.read_text(encoding="utf-8")

        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn("color-scheme: light dark", css)
        self.assertIn("--paper:", css)
        self.assertIn("--bg:", css)
        self.assertIn("--ink:", css)
        self.assertIn("--shadow:", css)
        self.assertIn(".hero", css)

    def test_artifact_iframe_network_isolation_static_contract(self):
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function isolateArtifactHTML", app)
        self.assertIn("function artifactEmbedPolicy", app)
        self.assertIn("function loadArtifactBaseCSS", app)
        self.assertIn("meta.setAttribute('http-equiv', 'Content-Security-Policy')", app)
        self.assertIn(
            "doc.querySelectorAll('base, script, iframe, frame, object, embed')",
            app,
        )
        self.assertIn("doc.querySelectorAll('link').forEach(link => link.remove())", app)
        self.assertIn("style.setAttribute('data-vidux-artifact-base', '')", app)
        self.assertIn('sandbox=\"allow-same-origin\"', app)
        self.assertIn('referrerpolicy=\"no-referrer\"', app)
        self.assertIn("node.localName === 'a' || node.localName === 'area'", app)
        self.assertIn("removeAttribute('xlink:href')", app)
        self.assertNotIn('sandbox=\"allow-same-origin allow-popups\"', app)



class BrowserViduxTruthTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.original_runner = browser_server.run_truth_command

        def fake_runner(args, *, timeout):
            self.commands.append(list(args))
            joined = " ".join(str(part) for part in args)
            if "vidux-config.py" in joined:
                stdout = json.dumps({
                    "status": "ok",
                    "source": "example",
                    "path": "/repo/vidux.config.example.json",
                    "live_config_present": False,
                    "using_example": True,
                    "issues": [],
                    "plan_store": {"mode": "local", "path_exists": True},
                })
            elif "vidux-doctor.sh" in joined:
                stdout = json.dumps({
                    "pass": 13,
                    "total": 14,
                    "checks": [
                        {"id": "worktree_count", "status": "pass"},
                        {"id": "orphan_automations", "status": "warn"},
                        {
                            "id": "system_memory_pressure",
                            "status": "pass",
                            "available": True,
                            "memory_pressure_free_pct": 64,
                            "memory_free_pct": 64,
                            "min_memory_free_pct": 15,
                            "memory_pct_source": "memory_pressure -Q",
                            "vm_free_mb": 91.0,
                            "vm_speculative_mb": 41.5,
                            "free_mb": 91.0,
                            "speculative_mb": 41.5,
                            "vm_pages_source": "vm_stat",
                            "total_bytes": 68719476736,
                        },
                    ],
                })
            else:
                stdout = "{}"
            return subprocess.CompletedProcess(args, 0, stdout, "")

        browser_server.run_truth_command = fake_runner
        browser_server.clear_vidux_truth_cache()
        self.httpd = browser_server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            browser_server.Handler,
        )
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()
        browser_server.run_truth_command = self.original_runner
        browser_server.clear_vidux_truth_cache()

    def get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        res = conn.getresponse()
        text = res.read().decode("utf-8", errors="replace")
        conn.close()
        return res.status, text

    def test_vidux_truth_cached_payload_can_warm_without_blocking(self):
        payload = browser_server.vidux_truth_cached_payload(background=False)

        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["browser_runs_install_doctor"])
        self.assertFalse(payload["browser_runs_runtime_fix"])
        self.assertEqual(payload["cache"]["status"], "warming")
        self.assertFalse(payload["cache"]["refreshing"])
        self.assertEqual(payload["config"]["status"], "warming")
        self.assertEqual(payload["runtime_doctor"]["status"], "warming")
        self.assertEqual(self.commands, [])

    def test_vidux_truth_endpoint_is_read_only_and_splits_doctors(self):
        status, text = self.get("/api/vidux/truth?refresh=sync")

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["browser_runs_install_doctor"])
        self.assertFalse(payload["browser_runs_runtime_fix"])
        self.assertEqual(payload["cache"]["status"], "fresh")
        self.assertEqual(payload["config"]["source"], "example")
        self.assertEqual(payload["install_doctor"]["browser_status"], "not_run")
        self.assertFalse(payload["install_doctor"]["pre_hook_safe"])
        self.assertEqual(payload["runtime_doctor"]["command"], "scripts/vidux-doctor.sh --json")
        self.assertTrue(payload["runtime_doctor"]["pre_hook_safe"])
        self.assertEqual(payload["runtime_doctor"]["status"], "warn")
        self.assertEqual(payload["runtime_doctor"]["warnings"], ["orphan_automations"])
        self.assertEqual(payload["runtime_doctor"]["system_memory"]["memory_pressure_free_pct"], 64)
        self.assertEqual(payload["runtime_doctor"]["system_memory"]["memory_pct_source"], "memory_pressure -Q")
        self.assertEqual(payload["runtime_doctor"]["system_memory"]["vm_pages_source"], "vm_stat")
        self.assertEqual(payload["runtime_doctor"]["system_memory"]["free_mb"], 91.0)
        self.assertNotIn("signposts", payload)

        command_text = "\n".join(" ".join(str(part) for part in cmd) for cmd in self.commands)
        self.assertIn("vidux-config.py check --json", command_text)
        self.assertIn("vidux-doctor.sh --json", command_text)
        self.assertNotIn("vidux_signpost.py", command_text)
        self.assertNotIn("vidux-doctor-cli.sh", command_text)
        self.assertNotIn("vidux doctor", command_text)
        self.assertNotIn("--fix", command_text)

    def test_health_payload_identifies_repo_root_for_launcher_reuse(self):
        status, text = self.get("/api/health")

        self.assertEqual(status, 200, text)
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo_root"], str(browser_server.VIDUX_ROOT))
        self.assertEqual(payload["dev_root"], str(browser_server.DEV_ROOT))
        self.assertEqual(payload["server_path"], str(browser_server.SERVER_FILE))
        self.assertEqual(payload["server_mtime_ns"], browser_server.SERVER_MTIME_NS)
        self.assertEqual(payload["steering_store_id"], browser_server.steering_store_id())
        self.assertEqual(
            payload["steering_module_mtime_ns"],
            browser_server.steering_module_mtime_ns(),
        )
        self.assertEqual(
            payload["coordination_store_id"], browser_server.coordination_store_id()
        )
        self.assertEqual(
            payload["coordination_module_mtime_ns"],
            browser_server.coordination_module_mtime_ns(),
        )
        self.assertNotIn(str(browser_server.STEERING_FILE), text)
        self.assertNotIn(str(browser_server.CLAIMS_FILE), text)
        self.assertIn("port", payload)

    def test_vidux_truth_static_contract(self):
        server = (ROOT / "browser" / "server.py").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('route == "/api/vidux/truth"', server)
        self.assertIn("vidux_truth_cached_payload", server)
        self.assertIn('refresh == "sync"', server)
        self.assertIn("browser_runs_install_doctor", server)
        self.assertIn("browser_runs_runtime_fix", server)
        self.assertIn('"vidux-doctor.sh"), "--json"', server)
        self.assertIn('fetch("/api/vidux/truth")', app)
        self.assertIn("function renderOpsTruth", app)
        self.assertIn("cache.refreshing", app)
        self.assertIn("install doctor not run here", app)
        self.assertIn("scripts/vidux-doctor.sh --json", app)
        self.assertIn("runtime.system_memory", app)
        self.assertIn("memory_pressure", app)
        self.assertIn("vm_stat", app)
        self.assertIn("function renderMarkdownBody", app)
        self.assertIn("markdown render failed", app)
        self.assertIn("markdown-source-fallback", style)
        self.assertIn('const SESSION_TAB = "Sessions"', app)
        self.assertIn("function renderSessionPanel", app)
        self.assertIn("No Claude session found", app)
        self.assertIn(".session-panel", style)
        self.assertIn(".session-turn", style)
        self.assertIn("function refreshOpsTruth", app)
        for klass in [
            "ops-truth",
            "ops-truth-grid",
            "ops-truth-item",
            "ops-chip",
            "ops-chip.is-warn",
        ]:
            self.assertIn(klass, style)


class BrowserResponseWriteTests(unittest.TestCase):
    def test_response_helpers_swallow_client_disconnect_writes(self):
        class BrokenWriter:
            def write(self, body):
                raise BrokenPipeError("client closed")

        handler = object.__new__(browser_server.Handler)
        handler.wfile = BrokenWriter()
        handler.send_response = lambda code: None
        handler.send_header = lambda name, value: None
        handler.end_headers = lambda: None

        self.assertFalse(browser_server.Handler._write_body(handler, b"hello"))
        browser_server.Handler._json(handler, {"ok": True})
        browser_server.Handler._send_with_type(handler, b"body", "text/plain")
        browser_server.Handler._send_text(handler, "markdown")
        browser_server.Handler._send(handler, 404, "missing")

    def test_head_only_response_helpers_skip_body_write(self):
        writes = []
        handler = object.__new__(browser_server.Handler)
        handler._head_only = True
        handler.wfile = type("Writer", (), {"write": lambda _self, body: writes.append(body)})()
        handler.send_response = lambda code: None
        handler.send_header = lambda name, value: None
        handler.end_headers = lambda: None

        self.assertTrue(browser_server.Handler._write_body(handler, b"hello"))
        browser_server.Handler._json(handler, {"ok": True})
        browser_server.Handler._send_with_type(handler, b"body", "text/plain")
        browser_server.Handler._send_text(handler, "markdown")
        browser_server.Handler._send(handler, 404, "missing")

        self.assertEqual(writes, [])


class BrowserPlanDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.original_claude_projects_dir = browser_server.CLAUDE_PROJECTS_DIR
        browser_server.DEV_ROOT = self.dev_root
        browser_server.CLAUDE_PROJECTS_DIR = self.dev_root / ".claude" / "projects"

    def tearDown(self):
        browser_server.CLAUDE_PROJECTS_DIR = self.original_claude_projects_dir
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def write_plan(self, repo: str, rel: str, title: str = "Demo") -> Path:
        path = self.dev_root / repo / rel / "PLAN.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            f"# {title}\n\n## Purpose\nLocal test plan.\n",
            encoding="utf-8",
        )
        return path

    def test_discovers_repo_native_named_authority_plan(self):
        plan = self.dev_root / "acme-ios" / ".cursor" / "plans" / "NORTH-STAR.plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            "# Acme North Star\n\n## Purpose\nCanonical iOS authority.\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()

        discovered = {item["path"]: item for item in plans}
        self.assertIn(str(plan.resolve()), discovered)
        self.assertEqual(discovered[str(plan.resolve())]["slug"], "NORTH-STAR")
        self.assertEqual(browser_server.resolve_plan_note_target(str(plan)), plan.resolve())

        private = self.dev_root / "acme-ios" / "docs" / "private.plan.md"
        private.parent.mkdir(parents=True)
        private.write_text("# Not an authority\n", encoding="utf-8")
        self.assertIsNone(browser_server.safe_resolve(str(private)))
        self.assertIsNone(browser_server.resolve_plan_note_target(str(private)))

    def test_discovers_plan_at_scan_root_itself(self):
        # `vidux browse --root <dir>` where <dir> IS the project: PLAN.md sits
        # directly at the scan root. Every directory-prefixed glob misses it,
        # so a stranger pointing the browser at their own repo saw 0 plans.
        root_plan = self.dev_root / "PLAN.md"
        root_plan.write_text(
            "# Root Plan\n\n## Purpose\nPlan at the scan root.\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()

        discovered = {item["path"] for item in plans}
        self.assertIn(str(root_plan.resolve()), discovered)

    def test_symlink_escaping_dev_root_does_not_crash_discovery(self):
        # a symlink under DEV_ROOT whose target
        # resolves OUTSIDE it made glob+resolve() hand an out-of-root path to
        # plan_meta(), whose unguarded path.relative_to(DEV_ROOT) raised
        # ValueError and crashed the entire /api/plans dashboard (cache never
        # populated -> every request re-crashed). discover_plans() must skip
        # the escaping entry, not raise, and still surface the valid plans.
        good = self.write_plan("realrepo", "projects/proj")
        with tempfile.TemporaryDirectory() as outside:
            outside_plan = Path(outside) / "PLAN.md"
            outside_plan.write_text("# Outside\n\n## Purpose\nEscaped.\n", encoding="utf-8")
            # Sits at a globbed depth (*/projects/*/PLAN.md) so it IS matched,
            # then resolves outside DEV_ROOT via the symlink.
            link_dir = self.dev_root / "evilrepo" / "projects" / "escape"
            link_dir.mkdir(parents=True)
            (link_dir / "PLAN.md").symlink_to(outside_plan)

            # Must not raise (pre-fix this raised ValueError from plan_meta).
            plans = browser_server.discover_plans()

            paths = {p["path"] for p in plans}
            self.assertIn(str(good), paths, "valid in-root plan should still be discovered")
            self.assertNotIn(
                str(outside_plan.resolve()),
                paths,
                "a symlink target resolving outside DEV_ROOT must be skipped, not surfaced",
            )

    def test_repo_aliases_dedup_prefers_canonical_checkout(self):
        """When env `VIDUX_REPO_ALIASES` maps an old checkout name to a
        canonical one, discover_plans() should keep only the canonical copy
        when the same plan path exists in both. The alias map is read from
        the environment, not hardcoded — the test injects its own map to
        validate the dedup mechanism."""
        canonical = self.write_plan("app-web", "vidux/game-plan", "Game Plan")
        self.write_plan("old-app-web", "vidux/game-plan", "Old Game Plan")

        original = browser_server.LEGACY_REPO_ALIASES
        browser_server.LEGACY_REPO_ALIASES = {"old-app-web": "app-web"}
        try:
            plans = browser_server.discover_plans()
        finally:
            browser_server.LEGACY_REPO_ALIASES = original

        game_plans = [
            plan
            for plan in plans
            if Path(plan["rel"]).parts[1:] == ("vidux", "game-plan", "PLAN.md")
        ]

        self.assertEqual(len(game_plans), 1)
        self.assertEqual(game_plans[0]["repo"], "app-web")
        self.assertEqual(Path(game_plans[0]["path"]), canonical.resolve())

    def test_project_inventory_includes_git_repos_without_plans(self):
        for name in ("alpha", "beta", "gamma"):
            (self.dev_root / name / ".git").mkdir(parents=True)
        self.write_plan("alpha", "projects/current", "Current")

        inventory = browser_server.discover_project_inventory(browser_server.discover_plans())

        self.assertEqual([item["name"] for item in inventory], ["alpha", "beta", "gamma"])
        self.assertEqual(inventory[0]["plans"], 1)
        self.assertEqual(inventory[0]["state"], "needs_brief")
        self.assertEqual(inventory[1]["plans"], 0)
        self.assertEqual(inventory[1]["state"], "unconnected")
        self.assertTrue(all("path" not in item for item in inventory))

    def test_discover_plans_handles_missing_evidence_directory(self):
        plan_path = self.write_plan("demo-repo", "projects/no-evidence", "No Evidence")

        plans = browser_server.discover_plans()
        plan = next(p for p in plans if Path(p["path"]) == plan_path.resolve())

        self.assertEqual(plan["evidence"], [])

    def test_discover_evidence_sorts_dated_files_and_keeps_odd_markdown_names(self):
        plan_path = self.write_plan("demo-repo", "projects/receipts", "Receipts")
        evidence_dir = plan_path.parent / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "notes without date.md").write_text("# Notes\n", encoding="utf-8")
        (evidence_dir / "2026-05-24-browser-proof.md").write_text("# Latest\n", encoding="utf-8")
        (evidence_dir / "2026-05-01-research.md").write_text("# Research\n", encoding="utf-8")
        (evidence_dir / "2026-05-02-screenshot.png").write_text("not markdown", encoding="utf-8")
        (evidence_dir / "nested.md").mkdir()

        plans = browser_server.discover_plans()
        plan = next(p for p in plans if Path(p["path"]) == plan_path.resolve())

        names = [item["name"] for item in plan["evidence"]]
        self.assertEqual(
            names,
            [
                "2026-05-01-research.md",
                "2026-05-24-browser-proof.md",
                "notes without date.md",
            ],
        )
        labels = [item["label"] for item in plan["evidence"]]
        self.assertEqual(labels[0], "2026-05-01 - research")
        self.assertEqual(labels[1], "2026-05-24 - browser proof")
        self.assertEqual(labels[2], "notes without date")
        self.assertTrue(plan["evidence"][0]["is_dated"])
        self.assertFalse(plan["evidence"][2]["is_dated"])

    def test_plan_list_payload_uses_child_rels_without_nested_children(self):
        parent = self.write_plan("demo-repo", "projects/parent", "Parent")
        child_dir = parent.parent / "child"
        child_dir.mkdir()
        child_rel = "demo-repo/projects/parent/child/PLAN.md"
        (child_dir / "PLAN.md").write_text(
            "# Child\n\n"
            "> Parent: ../PLAN.md\n\n"
            "## Purpose\nChild plan.\n\n"
            "## Tasks\n- [completed] child task\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()
        payload = browser_server.plan_list_payload(plans)
        parent_item = next(item for item in payload if item["rel"] == "demo-repo/projects/parent/PLAN.md")

        self.assertNotIn("children", parent_item)
        self.assertEqual(parent_item["child_rels"], [child_rel])

    def test_build_fleet_summary_sums_completion_and_active_eta(self):
        plan_a = self.write_plan("demo-repo", "projects/eta-a", "ETA A")
        plan_a.write_text(
            "# ETA A\n\n"
            "## Tasks\n"
            "- [completed] done already [ETA: 99h]\n"
            "- [pending] next up [ETA: 1.25h]\n"
            "- [in_progress] active now [ETA: 2h]\n"
            "- [in_review] review lane [ETA: 0.75h]\n"
            "- [blocked] blocked elsewhere [ETA: 6h]\n",
            encoding="utf-8",
        )
        plan_b = self.write_plan("other-repo", "projects/eta-b", "ETA B")
        plan_b.write_text(
            "# ETA B\n\n"
            "## Tasks\n"
            "- [pending] untagged active row\n"
            "- [completed] shipped row\n",
            encoding="utf-8",
        )

        summary = browser_server.build_fleet_summary(browser_server.discover_plans())

        self.assertEqual(summary["plans"], 2)
        self.assertEqual(summary["repos"], 2)
        self.assertEqual(summary["tasks_completed"], 2)
        self.assertEqual(summary["tasks_total"], 7)
        self.assertEqual(summary["completion_pct"], 29)
        self.assertEqual(summary["eta_remaining_hours"], 4.0)
        self.assertEqual(summary["eta_remaining_label"], "4h tagged estimate")
        self.assertEqual(summary["eta_tagged"], 3)
        self.assertEqual(summary["eta_eligible"], 4)

    def test_plan_payload_includes_latest_claude_session_summary(self):
        plan_path = self.write_plan("demo-repo", "projects/session", "Session")
        session_dir = (
            browser_server.CLAUDE_PROJECTS_DIR
            / browser_server.claude_project_slug(self.dev_root / "demo-repo")
        )
        session_dir.mkdir(parents=True)
        old_session = session_dir / "old.jsonl"
        old_session.write_text(
            json.dumps({
                "type": "user",
                "sessionId": "old-session",
                "message": {"role": "user", "content": "old session text"},
            }) + "\n",
            encoding="utf-8",
        )
        latest_session = session_dir / "latest.jsonl"
        rows = [
            {"type": "last-prompt", "sessionId": "latest-session"},
            {
                "type": "user",
                "timestamp": "2026-06-03T08:00:00Z",
                "sessionId": "latest-session",
                "message": {"role": "user", "content": [{"type": "text", "text": "first should drop"}]},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-03T08:01:00Z",
                "sessionId": "latest-session",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "second kept"}]},
            },
            {
                "type": "user",
                "timestamp": "2026-06-03T08:02:00Z",
                "sessionId": "latest-session",
                "message": {"role": "user", "content": "third kept"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-03T08:03:00Z",
                "sessionId": "latest-session",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "ignored"}, {"type": "text", "text": "fourth kept"}],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-06-03T08:04:00Z",
                "sessionId": "latest-session",
                "message": {"role": "user", "content": [{"type": "text", "text": "fifth kept"}]},
            },
            "{not-json",
            {
                "type": "assistant",
                "timestamp": "2026-06-03T08:05:00Z",
                "sessionId": "latest-session",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "sixth kept"}]},
            },
        ]
        latest_session.write_text(
            "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )
        os.utime(old_session, (1_000, 1_000))
        os.utime(latest_session, (2_000, 2_000))

        plans = browser_server.plan_list_payload(browser_server.discover_plans())
        plan = next(p for p in plans if Path(p["path"]) == plan_path.resolve())
        session = plan["session"]

        self.assertTrue(session["available"])
        self.assertEqual(session["status"], "ok")
        self.assertEqual(session["file"], "latest.jsonl")
        self.assertEqual(session["session_id"], "latest-session")
        self.assertEqual(session["turns_seen"], 6)
        self.assertEqual(session["invalid_lines"], 1)
        self.assertEqual(len(session["turns"]), 5)
        self.assertEqual([turn["role"] for turn in session["turns"]], [
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ])
        joined = " ".join(turn["text"] for turn in session["turns"])
        self.assertNotIn("first should drop", joined)
        self.assertNotIn("old session text", joined)
        self.assertIn("sixth kept", joined)

    def test_plan_payload_reports_missing_claude_session(self):
        plan_path = self.write_plan("demo-repo", "projects/no-session", "No Session")

        plans = browser_server.plan_list_payload(browser_server.discover_plans())
        plan = next(p for p in plans if Path(p["path"]) == plan_path.resolve())
        session = plan["session"]

        self.assertFalse(session["available"])
        self.assertEqual(session["status"], "missing")
        self.assertEqual(session["turns"], [])
        self.assertIn(".claude/projects", session["project_dir"])

    def test_discover_plans_cached_reuses_recent_scan(self):
        self.write_plan("demo-repo", "projects/cache", "Cache")
        original_discover = browser_server.discover_plans
        original_ttl = browser_server.PLANS_CACHE_TTL_SECONDS
        calls = []

        def fake_discover():
            calls.append("scan")
            return original_discover()

        browser_server.PLANS_CACHE_TTL_SECONDS = 60
        browser_server.discover_plans = fake_discover
        browser_server.clear_plans_cache()
        try:
            first = browser_server.discover_plans_cached()
            second = browser_server.discover_plans_cached()
        finally:
            browser_server.discover_plans = original_discover
            browser_server.PLANS_CACHE_TTL_SECONDS = original_ttl
            browser_server.clear_plans_cache()

        self.assertEqual(first, second)
        self.assertEqual(calls, ["scan"])


class BrowserDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.original_dev_root = browser_server.DEV_ROOT
        self.original_claude_projects_dir = browser_server.CLAUDE_PROJECTS_DIR
        browser_server.DEV_ROOT = self.dev_root
        browser_server.CLAUDE_PROJECTS_DIR = self.dev_root / ".claude" / "projects"

    def tearDown(self):
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.CLAUDE_PROJECTS_DIR = self.original_claude_projects_dir
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def test_dashboard_extracts_bounded_tasks_and_open_sibling_entries(self):
        plan_dir = self.dev_root / "repo" / "projects" / "dashboard"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "PLAN.md"
        plan_path.write_text(
            "# Dashboard\n\n"
            "## Purpose\nFleet queue.\n\n"
            "## Tasks\n"
            "- [in_progress] Ship cross-plan dashboard [ETA: 1h]\n"
            "- [blocked] Wait for external proof [Blocker: real thing]\n"
            "- [pending] Ignore pending row\n",
            encoding="utf-8",
        )
        (plan_dir / "INBOX.md").write_text(
            "# Inbox\n\n"
            "## Open\n\n"
            "### First open inbox item\n"
            "- Second open inbox item\n\n"
            "## Processed\n\n"
            "- Old processed item\n",
            encoding="utf-8",
        )
        (plan_dir / "ASK-OWNER.md").write_text(
            "# Ask owner\n\n"
            "- Decide whether dashboard ships as default pane\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()
        payload = browser_server.plan_list_payload(plans)
        plan_payload = next(item for item in payload if item["rel"] == "repo/projects/dashboard/PLAN.md")
        dashboard = browser_server.build_dashboard(plans)

        self.assertNotIn("dashboard_tasks", plan_payload)
        self.assertNotIn("dashboard_inbox_entries", plan_payload)
        self.assertNotIn("dashboard_ask_owner_entries", plan_payload)
        self.assertEqual(dashboard["plans_scanned"], 1)
        self.assertEqual(dashboard["repos"], 1)

        in_progress = dashboard["categories"]["in_progress"]
        blocked = dashboard["categories"]["blocked"]
        inbox = dashboard["categories"]["inbox"]
        ask_owner = dashboard["categories"]["ask_owner"]

        self.assertEqual(in_progress["total"], 1)
        self.assertEqual(blocked["total"], 1)
        self.assertEqual(inbox["total"], 2)
        self.assertEqual(ask_owner["total"], 1)
        self.assertFalse(inbox["truncated"])

        task_item = in_progress["items"][0]
        self.assertEqual(task_item["kind"], "task")
        self.assertEqual(task_item["tab"], "PLAN.md")
        self.assertEqual(task_item["status"], "in_progress")
        self.assertEqual(task_item["source_rel"], "repo/projects/dashboard/PLAN.md")
        self.assertGreater(task_item["line"], 0)
        self.assertIn("Ship cross-plan dashboard", task_item["label"])
        self.assertNotIn("[ETA:", task_item["label"])

        inbox_labels = [item["label"] for item in inbox["items"]]
        self.assertEqual(inbox_labels, ["First open inbox item", "Second open inbox item"])
        self.assertNotIn("Old processed item", " ".join(inbox_labels))
        self.assertEqual(inbox["items"][0]["tab"], "INBOX.md")
        self.assertEqual(ask_owner["items"][0]["tab"], "ASK-OWNER.md")

    def test_dashboard_ranks_urgent_work_and_preserves_task_truth(self):
        old_dir = self.dev_root / "old-project"
        new_dir = self.dev_root / "new-project"
        old_dir.mkdir()
        new_dir.mkdir()
        today = browser_server.date.today().isoformat()
        (old_dir / "PLAN.md").write_text(
            "# Old\n\n"
            "## Operator Brief\n"
            "- Status: watching\n- Priority: 10\n- Outcome: Stop data loss.\n"
            f"- Next: Repair checkout.\n- Updated: {today}\n\n"
            "## Tasks\n"
            "- [pending] P0 customer data loss [Owner: Core] [validation: python3 checks.py]\n"
            "- [in_progress] P0 reconcile durable state [Owner: Core] [Evidence: evidence/state.md]\n"
            "- [blocked] P1 vendor callback [Owner: Web] [Blocker: vendor]\n",
            encoding="utf-8",
        )
        (new_dir / "PLAN.md").write_text(
            "# New\n\n"
            "## Operator Brief\n"
            "- Status: watching\n- Priority: 100\n- Outcome: Polish a recent lane.\n"
            f"- Next: Keep polishing.\n- Updated: {today}\n\n"
            "## Tasks\n- [in_progress] P1 recent polish\n",
            encoding="utf-8",
        )
        os.utime(old_dir / "PLAN.md", (1_700_000_000, 1_700_000_000))
        os.utime(new_dir / "PLAN.md", (1_800_000_000, 1_800_000_000))

        dashboard = browser_server.build_dashboard(browser_server.discover_plans())
        next_item = dashboard["categories"]["next"]["items"][0]
        active = dashboard["categories"]["in_progress"]["items"]
        blocked = dashboard["categories"]["blocked"]["items"][0]

        self.assertEqual(next_item["repo"], "old-project")
        self.assertEqual(next_item["severity"], "p0")
        self.assertEqual(next_item["owner"], "Core")
        self.assertEqual(next_item["validation"], "python3 checks.py")
        self.assertNotIn("[Owner:", next_item["label"])
        self.assertEqual([item["repo"] for item in active], ["old-project", "new-project"])
        self.assertEqual(active[0]["proof"], "evidence/state.md")
        self.assertEqual(blocked["owner"], "Web")
        self.assertEqual(blocked["blocker"], "vendor")

    def test_mission_control_rejects_terminal_and_prefers_fresh_truth(self):
        today = browser_server.date.today().isoformat()
        fixtures = [
            ("done", "completed", 100, today),
            ("stale", "watching", 100, "2000-01-01"),
            ("fresh", "watching", 5, today),
        ]
        for name, status, priority, updated in fixtures:
            root = self.dev_root / name
            root.mkdir()
            (root / "PLAN.md").write_text(
                f"# {name}\n\n## Operator Brief\n- Status: {status}\n"
                f"- Priority: {priority}\n- Outcome: Ship {name}.\n- Next: Prove {name}.\n"
                f"- Updated: {updated}\n\n## Tasks\n- [pending] P1 work\n",
                encoding="utf-8",
            )

        mission = browser_server.build_dashboard(browser_server.discover_plans())["mission_control"]

        self.assertEqual(mission["selected"]["repo"], "fresh")
        self.assertEqual(mission["selected"]["selection_reason"], "only fresh current goal")
        self.assertEqual(mission["terminal_briefs_total"], 1)
        self.assertEqual(mission["deferred_briefs_total"], 1)
        self.assertEqual(mission["authority"]["claims_total"], 1)

    def test_scorecard_reports_explicit_total_when_the_safety_limit_is_reached(self):
        plan_dir = self.dev_root / "scorecard"
        plan_dir.mkdir()
        rows = "".join(
            f"| Metric {index} | 0 | 0 | 1 | unproven | proof {index} |\n"
            for index in range(51)
        )
        (plan_dir / "PLAN.md").write_text(
            "# Scorecard\n\n## Operator Brief\n- Status: watching\n- Priority: 1\n"
            "- Outcome: Count every result.\n- Next: Inspect all results.\n\n"
            "## Outcome Scorecard\n"
            "| Metric | Baseline | Current | Target | Status | Proof |\n"
            "|---|---|---|---|---|---|\n"
            f"{rows}\n## Tasks\n- [pending] P1 inspect\n",
            encoding="utf-8",
        )

        plan = browser_server.discover_plans()[0]
        selected = browser_server.build_dashboard([plan])["mission_control"]["selected"]

        self.assertEqual(len(plan["outcome_scorecard"]), 50)
        self.assertEqual(plan["outcome_scorecard_total"], 51)
        self.assertTrue(plan["outcome_scorecard_truncated"])
        self.assertEqual(selected["scorecard_total"], 51)
        self.assertTrue(selected["scorecard_truncated"])

    def test_dashboard_surfaces_recent_decision_directions(self):
        plan_dir = self.dev_root / "repo" / "projects" / "decision"
        plan_dir.mkdir(parents=True)
        (plan_dir / "PLAN.md").write_text(
            "# Decision\n\n"
            "## Purpose\nMake the pivot visible.\n\n"
            "## Decisions\n"
            "- [DIRECTION] [2026-07-01] Keep an older direction.\n"
            "- [PIVOT] [2026-07-02] Freeze kernel handoff as default route.\n\n"
            "## Tasks\n"
            "- [pending] next\n",
            encoding="utf-8",
        )

        dashboard = browser_server.build_dashboard(browser_server.discover_plans())
        decisions = dashboard["categories"]["decisions"]

        self.assertEqual(decisions["total"], 2)
        labels = [item["label"] for item in decisions["items"]]
        self.assertIn("2026-07-02 Freeze kernel handoff as default route.", labels)
        item = decisions["items"][1]
        self.assertEqual(item["kind"], "decision")
        self.assertEqual(item["status"], "pivot")
        self.assertEqual(item["tab"], "Decision Log")
        self.assertEqual(item["source_rel"], "repo/projects/decision/PLAN.md")
        self.assertGreater(item["line"], 0)

    def test_dashboard_surfaces_pe_verdict_receipts(self):
        plan_dir = self.dev_root / "repo" / "projects" / "verdict"
        plan_dir.mkdir(parents=True)
        proof_path = (
            self.dev_root
            / "vidux"
            / "evaluations"
            / "vidux-vs-native-bakeoff"
            / "results"
            / "pe"
            / "decision.md"
        )
        (plan_dir / "PLAN.md").write_text(
            "# Verdict\n\n"
            "## Purpose\nMake the bakeoff receipt visible.\n\n"
            "## Evidence\n"
            f"- [Source: {proof_path}, 2026-07-03] Full planner-executor matrix wrote 119 rows, "
            "117 clean after protocol exclusions; H1/H2/H3 all refuted, and kernel handoff "
            "lost to freeform by 18 percentage points.\n"
            "- [Source: notes.md] Planner research is still useful.\n\n"
            "## Tasks\n"
            "- [pending] next\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()
        payload = browser_server.plan_list_payload(plans)
        plan_payload = next(item for item in payload if item["rel"] == "repo/projects/verdict/PLAN.md")
        dashboard = browser_server.build_dashboard(plans)
        verdicts = dashboard["categories"]["verdicts"]

        self.assertNotIn("dashboard_verdicts", plan_payload)
        self.assertEqual(verdicts["total"], 1)
        item = verdicts["items"][0]
        self.assertEqual(item["kind"], "verdict")
        self.assertEqual(item["status"], "refuted")
        self.assertEqual(item["tab"], "PLAN.md")
        self.assertEqual(item["source_rel"], "repo/projects/verdict/PLAN.md")
        self.assertEqual(item["proof_path"], str(proof_path))
        self.assertEqual(
            item["proof_rel"],
            "vidux/evaluations/vidux-vs-native-bakeoff/results/pe/decision.md",
        )
        self.assertIn("H1/H2/H3 all refuted", item["label"])
        self.assertNotIn("[Source:", item["label"])
        self.assertGreater(item["line"], 0)

    def test_dashboard_parses_open_ask_owner_question_blocks(self):
        plan_dir = self.dev_root / "repo" / "projects" / "asks"
        plan_dir.mkdir(parents=True)
        (plan_dir / "PLAN.md").write_text("# Asks\n\n## Tasks\n", encoding="utf-8")
        (plan_dir / "ASK-OWNER.md").write_text(
            "# ASK-OWNER\n\n"
            "## Q1 — resolved question\n"
            "Opened: 2026-06-03\n"
            "Resolved: Owner decided no.\n"
            "Status: resolved\n\n"
            "## Q2 — open explicit question\n"
            "Opened: 2026-06-03\n"
            "Status: open\n\n"
            "## Q3 — implicit open question\n"
            "Opened: 2026-06-03\n",
            encoding="utf-8",
        )

        dashboard = browser_server.build_dashboard(browser_server.discover_plans())
        ask_owner = dashboard["categories"]["ask_owner"]
        labels = [item["label"] for item in ask_owner["items"]]

        self.assertEqual(ask_owner["total"], 2)
        self.assertEqual(labels, ["Q2 — open explicit question", "Q3 — implicit open question"])
        self.assertTrue(all(item["tab"] == "ASK-OWNER.md" for item in ask_owner["items"]))

    def test_mission_control_parses_and_ranks_operator_briefs(self):
        low_dir = self.dev_root / "repo" / "projects" / "low"
        high_dir = self.dev_root / "other" / "projects" / "high"
        low_dir.mkdir(parents=True)
        high_dir.mkdir(parents=True)
        (low_dir / "PLAN.md").write_text(
            "# Low\n\n"
            "## Operator Brief\n"
            "- Status: watching\n"
            "- Priority: 10\n"
            "- Outcome: Keep a background lane healthy.\n"
            "- Next: Run the small check.\n\n"
            "## Tasks\n- [pending] check\n",
            encoding="utf-8",
        )
        # A recent literal date here rots: "fresh" means age <= 7 days, so a
        # hardcoded Updated value silently flips the ranking when the suite
        # runs a week later. Compute it relative to today instead.
        recent_updated = (date.today() - timedelta(days=3)).isoformat()
        (high_dir / "PLAN.md").write_text(
            "# High\n\n"
            "## Operator Brief\n"
            "- Status: SHIPPING\n"
            "- Priority: 250\n"
            "- Outcome: Prove the cockpit earns its overhead.\n"
            "- Next: Ship mission control.\n"
            "- Why: Operators cannot see the value gap.\n"
            "- Validation: API and rendered-browser proof.\n"
            "- Cost: One bounded advisor call.\n"
            "- Evidence: evidence/decision.md\n"
            f"- Updated: {recent_updated}\n"
            "- Unknown field: ignored\n\n"
            "## Outcome Scorecard\n"
            "| Metric | Baseline | Current | Target | Status | Proof |\n"
            "|---|---|---|---|---|---|\n"
            "| Resolution | 76% | 59% | >= 76% | LOSING | decision.md |\n"
            "| Net wins | 0 | 0 | >= 3 | unproven | benchmark v2 |\n\n"
            "## Tasks\n- [in_progress] ship\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()
        payload = browser_server.plan_list_payload(plans)
        dashboard = browser_server.build_dashboard(plans)
        selected = dashboard["mission_control"]["selected"]
        high_payload = next(item for item in payload if item["repo"] == "other")

        self.assertEqual(dashboard["mission_control"]["briefs_total"], 2)
        self.assertEqual(selected["repo"], "other")
        self.assertEqual(selected["status"], "shipping")
        self.assertEqual(selected["priority"], 100)
        self.assertEqual(selected["outcome"], "Prove the cockpit earns its overhead.")
        self.assertEqual(selected["next"], "Ship mission control.")
        self.assertEqual(selected["source_rel"], "other/projects/high/PLAN.md")
        self.assertEqual(selected["tab"], "PLAN.md")
        self.assertEqual(selected["selection_reason"], "only fresh current goal")
        self.assertEqual(dashboard["mission_control"]["authority"]["state"], "ranked")
        self.assertEqual(dashboard["mission_control"]["deferred_briefs_total"], 1)
        self.assertEqual(selected["evidence_target"]["state"], "missing")
        self.assertEqual(len(selected["scorecard"]), 2)
        self.assertEqual(selected["scorecard"][0]["status"], "losing")
        self.assertEqual(selected["scorecard"][0]["proof_target"]["state"], "needed")
        self.assertGreater(selected["scorecard"][0]["line"], selected["line"])
        self.assertEqual(high_payload["operator_brief"]["priority"], 100)
        self.assertEqual(high_payload["outcome_scorecard"][1]["metric"], "Net wins")
        self.assertNotIn("unknown field", high_payload["operator_brief"])

    def test_mission_control_has_explicit_empty_shape_and_ignores_bad_table_rows(self):
        plan_dir = self.dev_root / "repo" / "projects" / "empty"
        plan_dir.mkdir(parents=True)
        (plan_dir / "PLAN.md").write_text(
            "# Empty\n\n"
            "## Outcome Scorecard\n"
            "| Wrong | Columns |\n"
            "|---|---|\n"
            "| should | disappear |\n\n"
            "## Tasks\n- [pending] next\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()
        plan = plans[0]
        mission = browser_server.build_dashboard(plans)["mission_control"]

        self.assertEqual(plan["operator_brief"], {})
        self.assertEqual(plan["outcome_scorecard"], [])
        self.assertEqual(mission["briefs_total"], 0)
        self.assertIsNone(mission["selected"])
        self.assertEqual(mission["authority"]["state"], "missing")

    def test_onboarding_clean_root_has_public_first_step(self):
        dashboard = browser_server.build_dashboard([])
        onboarding = dashboard["onboarding"]

        self.assertEqual(onboarding["state"], "empty")
        self.assertEqual(onboarding["projects_total"], 0)
        self.assertEqual(onboarding["plans_total"], 0)
        self.assertEqual(onboarding["init_command"], "vidux init --here")
        self.assertNotIn(str(self.dev_root), json.dumps(onboarding))

    def test_onboarding_explains_tied_current_work_across_three_projects(self):
        for name in ("alpha", "beta", "gamma"):
            (self.dev_root / name / ".git").mkdir(parents=True)

        def write_brief(repo: str, priority: int, mtime: int) -> None:
            plan = self.dev_root / repo / "PLAN.md"
            plan.write_text(
                f"# {repo.title()}\n\n"
                "## Operator Brief\n"
                "- Status: watching\n"
                f"- Priority: {priority}\n"
                f"- Outcome: Ship {repo}.\n"
                "- Next: Run the proof.\n\n"
                "## Tasks\n- [pending] prove it\n",
                encoding="utf-8",
            )
            os.utime(plan, (mtime, mtime))

        write_brief("alpha", 80, 1_700_000_000)
        write_brief("beta", 80, 1_700_000_100)

        dashboard = browser_server.build_dashboard(browser_server.discover_plans())
        mission = dashboard["mission_control"]
        onboarding = dashboard["onboarding"]

        self.assertEqual(mission["selected"]["repo"], "beta")
        self.assertEqual(mission["selected"]["selection_reason"], "priority 80 · newest of 2 tied current goals")
        self.assertEqual(mission["authority"]["state"], "conflict")
        self.assertEqual(mission["authority"]["tied_total"], 2)
        self.assertEqual(mission["authority"]["tied_projects"], ["alpha", "beta"])
        self.assertIn("2 plans share priority 80", mission["authority"]["explanation"])
        self.assertIn("Showing beta", mission["authority"]["explanation"])
        self.assertEqual(onboarding["state"], "authority_conflict")
        self.assertEqual(onboarding["projects_total"], 3)
        self.assertEqual(onboarding["connected_projects"], 2)
        self.assertEqual(onboarding["unconnected_projects"], 1)

    def test_operator_brief_freshness_is_explicit_and_deterministic(self):
        today = browser_server.date(2026, 7, 9)

        self.assertEqual(
            browser_server.operator_brief_freshness("2026-07-02", today),
            {"status": "fresh", "age_days": 7},
        )
        self.assertEqual(
            browser_server.operator_brief_freshness("2026-07-01", today),
            {"status": "stale", "age_days": 8},
        )
        self.assertEqual(
            browser_server.operator_brief_freshness("not-a-date", today),
            {"status": "unknown", "age_days": None},
        )

    def test_plan_proof_resolution_is_inspectable_and_cannot_escape_owner(self):
        plan_dir = self.dev_root / "repo" / "projects" / "proof"
        evidence_dir = plan_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        plan_path = plan_dir / "PLAN.md"
        plan_path.write_text("# Proof\n", encoding="utf-8")
        receipt = evidence_dir / "receipt.md"
        receipt.write_text("# Receipt\n", encoding="utf-8")

        available = browser_server.resolve_plan_proof(
            plan_path,
            "evidence/receipt.md H3 counts",
        )
        missing = browser_server.resolve_plan_proof(plan_path, "evidence/missing.md")
        note = browser_server.resolve_plan_proof(plan_path, "benchmark v2 required")
        escaped = browser_server.resolve_plan_proof(
            plan_path,
            "../../other/evidence/receipt.md",
        )

        self.assertEqual(available["state"], "available")
        self.assertEqual(available["path"], str(receipt))
        self.assertEqual(available["tab"], f"EVD:{receipt}")
        self.assertEqual(missing, {
            "state": "missing",
            "label": "Proof missing",
            "rel": "evidence/missing.md",
        })
        self.assertEqual(note["state"], "needed")
        self.assertEqual(escaped["state"], "invalid")

    def test_dashboard_limit_marks_truncated_categories(self):
        plan_dir = self.dev_root / "repo" / "projects" / "many"
        plan_dir.mkdir(parents=True)
        (plan_dir / "PLAN.md").write_text(
            "# Many\n\n"
            "## Tasks\n"
            "- [in_progress] first task\n"
            "- [in_progress] second task\n",
            encoding="utf-8",
        )

        dashboard = browser_server.build_dashboard(browser_server.discover_plans(), limit=1)
        bucket = dashboard["categories"]["in_progress"]

        self.assertEqual(bucket["total"], 2)
        self.assertEqual(len(bucket["items"]), 1)
        self.assertTrue(bucket["truncated"])
        self.assertEqual(bucket["limit"], 1)

    def test_simple_queue_slice_is_exact_even_when_selected_plan_fills_api_limit(self):
        today = browser_server.date.today().isoformat()
        selected_dir = self.dev_root / "selected"
        other_dir = self.dev_root / "other"
        selected_dir.mkdir()
        other_dir.mkdir()
        (selected_dir / "PLAN.md").write_text(
            "# Selected\n\n## Operator Brief\n- Status: shipping\n- Priority: 100\n"
            "- Outcome: Own the current goal.\n- Next: Keep going.\n"
            f"- Updated: {today}\n\n## Tasks\n"
            "- [in_progress] P0 selected one\n"
            "- [in_progress] P0 selected two\n",
            encoding="utf-8",
        )
        (other_dir / "PLAN.md").write_text(
            "# Other\n\n## Tasks\n- [in_progress] P1 resumable other work\n",
            encoding="utf-8",
        )

        dashboard = browser_server.build_dashboard(browser_server.discover_plans(), limit=1)
        bucket = dashboard["categories"]["in_progress"]

        self.assertEqual(bucket["total"], 3)
        self.assertEqual(bucket["items"][0]["repo"], "selected")
        self.assertEqual(bucket["simple_total"], 1)
        self.assertEqual([item["repo"] for item in bucket["simple_items"]], ["other"])

    def test_dashboard_static_contract(self):
        server = (ROOT / "browser" / "server.py").read_text(encoding="utf-8")
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        sidebar_sort = (ROOT / "browser" / "static" / "sidebar-sort.js").read_text(encoding="utf-8")
        sidebar_filters = (ROOT / "browser" / "static" / "sidebar-filters.js").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('"summary": build_fleet_summary(plans)', server)
        self.assertIn("def build_fleet_summary", server)
        self.assertIn('"dashboard": build_dashboard(plans)', server)
        self.assertIn("def build_dashboard", server)
        self.assertIn("def build_mission_control", server)
        self.assertIn("def parse_operator_brief", server)
        self.assertIn("def parse_outcome_scorecard", server)
        self.assertIn("extract_dashboard_tasks", server)
        self.assertIn("extract_dashboard_verdicts", server)
        self.assertIn("extract_open_entries", server)
        self.assertIn('"verdicts": {"label": "Verdicts"', server)
        self.assertIn('"decisions": {"label": "Decisions"', server)
        self.assertIn('"next": {"label": "Next"', server)
        self.assertIn("fleetSummary", app)
        self.assertIn("function topbarFleetSummary", app)
        self.assertIn("tagged estimate", app)
        self.assertIn("open tasks estimated", app)
        self.assertIn("function renderDashboardPane", app)
        self.assertIn("function renderMissionControl", app)
        empty_pane = app[app.index("function renderEmptyPane()") : app.index("function updateOpsTruthSurface")]
        self.assertIn("${renderMissionControl()}", empty_pane)
        self.assertIn("renderSimpleHomeQueue()", empty_pane)
        self.assertIn("setupDashboardPane();", empty_pane)
        self.assertNotIn("state.devRoot", empty_pane)
        self.assertIn("else renderEmptyPane();", app)
        self.assertIn("function selectDashboard", app)
        self.assertIn('renderDashboardCard("verdicts", "Verdicts")', app)
        self.assertIn('renderDashboardCard("decisions", "Decisions")', app)
        self.assertIn('renderDashboardList("verdicts", "Recent Verdicts"', app)
        self.assertIn('renderDashboardList("decisions", "Recent Decisions"', app)
        self.assertIn('data-kind="dashboard"', app)
        self.assertIn("Cross-plan queue", app)
        self.assertIn('id="sort"', index)
        self.assertIn('<link rel="icon" href="data:," />', index)
        self.assertIn('/static/sidebar-sort.js', index)
        self.assertIn('/static/sidebar-filters.js', index)
        self.assertIn('/static/work-queue.js', index)
        self.assertIn('/static/annotation-state.js', index)
        self.assertLess(index.index('/static/sidebar-sort.js'), index.index('/static/app.js'))
        self.assertLess(index.index('/static/sidebar-filters.js'), index.index('/static/app.js'))
        self.assertLess(index.index('/static/work-queue.js'), index.index('/static/app.js'))
        self.assertLess(index.index('/static/annotation-state.js'), index.index('/static/app.js'))
        self.assertIn('data-filter-chip="hot"', index)
        self.assertIn('data-filter-chip="tasks"', index)
        self.assertIn('data-filter-chip="eta"', index)
        self.assertIn("ViduxSidebarSort", app)
        self.assertIn("ViduxSidebarFilters", app)
        self.assertIn("workQueueUi.render", app)
        self.assertIn("function planComparator", sidebar_sort)
        self.assertIn("function repoComparator", sidebar_sort)
        self.assertIn("vidux:sidebar-sort", sidebar_sort)
        self.assertIn("vidux:sidebar-filter-chips", sidebar_filters)
        self.assertIn("function matches", sidebar_filters)
        self.assertIn("function syncButtons", sidebar_filters)
        self.assertIn(".sidebar-controls", style)
        self.assertIn(".sidebar-filter-chips", style)
        self.assertIn(".filter-chip.is-active", style)
        self.assertIn(".progress-row .progress-bar", style)
        self.assertIn(".dashboard-panel", style)
        self.assertIn("max-height: min(560px, 70vh)", style)
        self.assertIn("overflow-y: auto", style)
        self.assertIn(".dashboard-item", style)
        self.assertIn(".mission-control", style)


class BrowserLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.ledger_file = self.dev_root / "activity.jsonl"
        self.original_dev_root = browser_server.DEV_ROOT
        self.original_ledger_file = browser_server.LEDGER_FILE
        self.original_item_limit = browser_server.LEDGER_ITEM_LIMIT
        self.original_scan_limit = browser_server.LEDGER_SCAN_LIMIT
        browser_server.DEV_ROOT = self.dev_root
        browser_server.LEDGER_FILE = self.ledger_file
        browser_server.LEDGER_ITEM_LIMIT = 2
        browser_server.LEDGER_SCAN_LIMIT = 20
        self.plan_dir = self.dev_root / "demo-repo" / "projects" / "ledger"
        self.plan_dir.mkdir(parents=True)
        self.plan_path = self.plan_dir / "PLAN.md"
        self.plan_path.write_text("# Ledger\n\n## Tasks\n", encoding="utf-8")

    def tearDown(self):
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.LEDGER_FILE = self.original_ledger_file
        browser_server.LEDGER_ITEM_LIMIT = self.original_item_limit
        browser_server.LEDGER_SCAN_LIMIT = self.original_scan_limit
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def write_ledger_rows(self, rows):
        self.ledger_file.write_text(
            "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_ledger_payload_matches_plan_rows_first_then_repo_rows(self):
        self.write_ledger_rows([
            "{bad json",
            {
                "ts": "2026-06-03T08:00:00Z",
                "eid": "evt_other",
                "event": "publish",
                "repo": "other-repo",
                "summary": "ignored other repo",
                "plan_path": "projects/ledger/PLAN.md",
            },
            {
                "ts": "2026-06-03T08:01:00Z",
                "eid": "evt_repo",
                "event": "publish",
                "repo": "demo-repo",
                "lane": "demo-lane",
                "task_id": "R1",
                "summary": "repo level proof",
                "plan_path": "PLAN.md",
                "files": ["README.md"],
                "files_claimed": ["README.md"],
            },
            {
                "ts": "2026-06-03T08:02:00Z",
                "eid": "evt_checkpoint",
                "event": "vidux_checkpoint",
                "repo": "demo-repo",
                "lane": "demo-lane",
                "task_id": "T4b",
                "summary": "absolute checkpoint",
                "plan_path": str(self.plan_path),
                "proof": "checkpoint proof",
                "handoff_status": "done",
                "next_agent_resume": "resume from the plan",
                "files": [str(self.plan_path)],
                "files_claimed": [str(self.plan_path)],
            },
            {
                "ts": "2026-06-03T08:03:00Z",
                "eid": "evt_plan",
                "event": "publish",
                "repo": "demo-repo",
                "lane": "demo-lane",
                "task_id": "T4b",
                "summary": "relative plan publish",
                "plan_path": "projects/ledger/PLAN.md",
                "proof": "plan proof",
                "handoff_status": "done",
                "next_agent_resume": "resume again",
                "files": ["projects/ledger/PLAN.md"],
                "files_claimed": ["projects/ledger/PLAN.md"],
            },
            {
                "ts": "2026-06-03T08:04:00Z",
                "event": "vidux_loop_start",
                "repo": "demo-repo",
                "summary": "ignored noisy loop row",
                "files": ["projects/ledger/PLAN.md"],
            },
        ])

        payload = browser_server.ledger_payload_for_plan(self.plan_path)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["invalid_rows"], 1)
        self.assertEqual(payload["plan_total"], 2)
        self.assertEqual(payload["repo_total"], 1)
        self.assertEqual(payload["returned"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual([item["scope"] for item in payload["items"]], ["plan", "plan"])
        self.assertEqual([item["eid"] for item in payload["items"]], ["evt_plan", "evt_checkpoint"])
        self.assertEqual(payload["items"][0]["files_claimed_count"], 1)
        self.assertIn("plan proof", payload["items"][0]["proof"])
        self.assertIn("resume again", payload["items"][0]["next_agent_resume"])

    def test_ledger_endpoint_accepts_plan_and_rejects_non_plan_targets(self):
        self.write_ledger_rows([
            {
                "ts": "2026-06-03T08:03:00Z",
                "eid": "evt_plan",
                "event": "publish",
                "repo": "demo-repo",
                "summary": "relative plan publish",
                "plan_path": "projects/ledger/PLAN.md",
            },
        ])
        inbox = self.plan_dir / "INBOX.md"
        inbox.write_text("# Inbox\n", encoding="utf-8")
        httpd = browser_server.ThreadingHTTPServer(("127.0.0.1", 0), browser_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", f"/api/ledger?path={quote(str(self.plan_path))}")
            res = conn.getresponse()
            ok_text = res.read().decode("utf-8", errors="replace")
            conn.close()
            self.assertEqual(res.status, 200, ok_text)
            self.assertEqual(json.loads(ok_text)["items"][0]["eid"], "evt_plan")

            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", f"/api/ledger?path={quote(str(inbox))}")
            res = conn.getresponse()
            forbidden_text = res.read().decode("utf-8", errors="replace")
            conn.close()
            self.assertEqual(res.status, 403, forbidden_text)
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

    def test_ledger_payload_marks_an_unsearched_older_tail_as_partial(self):
        rows = [{
            "ts": "2026-06-03T07:00:00Z",
            "eid": "evt_old_plan",
            "event": "publish",
            "repo": "demo-repo",
            "summary": "older matching proof",
            "plan_path": "projects/ledger/PLAN.md",
        }]
        rows.extend({
            "ts": f"2026-06-03T08:{index:02d}:00Z",
            "eid": f"evt_other_{index}",
            "event": "publish",
            "repo": "other-repo",
            "summary": "newer unrelated proof",
            "plan_path": "PLAN.md",
        } for index in range(20))
        self.write_ledger_rows(rows)

        payload = browser_server.ledger_payload_for_plan(self.plan_path)

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["total_rows"], 21)
        self.assertEqual(payload["scanned_rows"], 20)
        self.assertTrue(payload["scan_tail_truncated"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["plan_total"], 0)
        self.assertEqual(payload["items"], [])

    def test_ledger_static_contract(self):
        server = (ROOT / "browser" / "server.py").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('route == "/api/ledger"', server)
        self.assertIn("ledger_payload_for_plan", server)
        self.assertIn('const LEDGER_TAB = "Ledger"', app)
        self.assertIn("function renderLedgerPanel", app)
        self.assertIn("/api/ledger?path=", app)
        self.assertIn(".ledger-panel", style)
        self.assertIn(".ledger-entry", style)


class BrowserDecisionLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.original_dev_root = browser_server.DEV_ROOT
        browser_server.DEV_ROOT = self.dev_root

    def tearDown(self):
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def test_parse_decision_log_zero_when_section_is_missing(self):
        result = browser_server.parse_decision_log(
            "# Demo\n\n## Purpose\nNo decisions yet.\n\n## Tasks\n- [pending] one\n"
        )

        self.assertFalse(result["present"])
        self.assertIsNone(result["heading_line"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["recent_directions"], [])

    def test_parse_decision_log_handles_messy_markdown_and_wrapped_bullets(self):
        result = browser_server.parse_decision_log(
            "# Demo\n\n"
            "### Decision Log\n"
            "Intro text should not become an entry.\n"
            "- [DIRECTION] [2026-05-01] Keep browser read-only.\n"
            "  Reason: PLAN.md remains canonical.\n"
            "* [REFRAME] 2026-05-02 Promote decisions instead of scanning full markdown.\n"
            "1. Plain note without a tag still renders.\n"
            "#### Nested notes\n"
            "- [PIVOT] [2026-05-03 app chrome] Keep large modes out of the topbar.\n"
            "## Tasks\n"
            "- [pending] next task\n"
        )

        self.assertTrue(result["present"])
        self.assertEqual(result["heading_line"], 3)
        self.assertEqual(result["count"], 4)
        first = result["entries"][0]
        self.assertEqual(first["kind"], "DIRECTION")
        self.assertEqual(first["date"], "2026-05-01")
        self.assertIn("Reason: PLAN.md remains canonical.", first["body"])
        self.assertFalse(first["is_recent"])
        self.assertTrue(result["entries"][1]["is_recent"])
        self.assertEqual(result["entries"][2]["kind"], "NOTE")
        self.assertEqual(result["entries"][3]["date"], "2026-05-03 app chrome")
        self.assertEqual(
            [entry["kind"] for entry in result["recent_directions"]],
            ["DIRECTION", "REFRAME", "PIVOT"],
        )

    def test_discover_plans_exposes_decision_log_metadata(self):
        plan_dir = self.dev_root / "repo" / "projects" / "demo"
        plan_dir.mkdir(parents=True)
        (plan_dir / "PLAN.md").write_text(
            "# Demo\n\n"
            "## Decision Log\n"
            "- [DIRECTION] [2026-05-01] Keep it visible.\n\n"
            "## Tasks\n"
            "- [pending] ship pane\n",
            encoding="utf-8",
        )

        plans = browser_server.discover_plans()

        self.assertEqual(len(plans), 1)
        decision_log = plans[0]["decision_log"]
        self.assertTrue(decision_log["present"])
        self.assertEqual(decision_log["count"], 1)
        self.assertEqual(decision_log["entries"][0]["kind"], "DIRECTION")

    def test_decision_log_pane_static_contract(self):
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('const DECISION_LOG_TAB = "Decision Log"', app)
        self.assertIn("function renderDecisionLogPane", app)
        self.assertIn("recent_directions", app)
        self.assertIn("No Decision Log section", app)
        for klass in [
            "decision-log-summary",
            "decision-log-recent",
            "decision-entry",
            "decision-recent",
        ]:
            self.assertIn(klass, style)


class BrowserPlanBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        self.original_dev_root = browser_server.DEV_ROOT
        browser_server.DEV_ROOT = self.dev_root

    def tearDown(self):
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def test_plan_meta_includes_deterministic_brief_for_cockpit_view(self):
        plan_dir = self.dev_root / "repo" / "projects" / "pm"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "PLAN.md"
        plan_path.write_text(
            "# PM\n\n"
            "## Purpose\n"
            "Replace external PM surfaces with Vidux-native steering.\n\n"
            "## Tasks\n"
            "- [pending] PM-2 Later thing [ETA: 1h]\n"
            "- [completed] PM-0 Done thing\n"
            "- [in_progress] PM-1 Build `Now` strip [Evidence: user asked]\n"
            "- [blocked] PM-3 Waiting on browser proof [Blocker: screenshot]\n\n"
            "## Decision Log\n"
            "- [DIRECTION] [2026-05-24] Keep PLAN.md canonical and use comments for steering.\n\n"
            "## Progress\n"
            "- [2026-07-10] Shipped the newest cockpit slice.\n"
            "- [completed] malformed task-shaped bullet should not win\n"
            "- [2026-05-24] Shipped the first cockpit slice.\n",
            encoding="utf-8",
        )

        plan = browser_server.plan_meta(plan_path)
        brief = plan["brief"]

        self.assertEqual(brief["state"], "blocked")
        self.assertEqual(brief["open_count"], 3)
        self.assertEqual(brief["summary"], "Replace external PM surfaces with Vidux-native steering.")
        self.assertEqual(
            [item["status"] for item in brief["focus_tasks"]],
            ["in_progress", "blocked", "pending"],
        )
        self.assertIn("Build Now strip", brief["focus_tasks"][0]["label"])
        self.assertEqual(brief["latest_progress"], "[2026-07-10] Shipped the newest cockpit slice.")
        self.assertIn("Keep PLAN.md canonical", brief["latest_decision"])

    def test_plan_brief_keeps_execution_out_of_browser_and_mounts_local_steering_inbox(self):
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        comment_rail = (
            ROOT / "browser" / "static" / "comment-rail.js"
        ).read_text(encoding="utf-8")
        steering = (
            ROOT / "browser" / "static" / "steering-inbox.js"
        ).read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn("function renderPlanBrief", app)
        self.assertIn('const tabs = ["PLAN.md", DECISION_LOG_TAB', app)
        self.assertIn("showEvidenceStrip", app)
        self.assertIn("No proof files yet", app)
        self.assertNotIn("function setupPlanSteering", app)
        self.assertNotIn("Steer this plan", app)
        self.assertIn("ViduxSteeringInbox", app)
        self.assertIn("function render", steering)
        self.assertIn("function setup", steering)
        self.assertIn("Steer next turn", steering)
        self.assertIn("This does not send a chat message", steering)
        self.assertIn("/api/steering", steering)
        self.assertNotIn("function codingWorkbenchUrl", app)
        self.assertNotIn("Code lane", app)
        self.assertNotIn("/api/coding-handoff", app)
        self.assertNotIn("plan-steering", app)
        self.assertIn("is-steering", comment_rail)
        for klass in [
            "plan-brief",
            "plan-brief-task",
            "comment-item.is-steering",
            "steering-inbox",
            "steering-composer",
            "steering-item.is-retryable",
        ]:
            self.assertIn(klass, style)
        self.assertNotIn(".plan-steering", style)
        self.assertNotIn(".plan-brief-code-link", style)


class BrowserSubplanRollupTests(unittest.TestCase):
    """Recursive parent→child task-stat rollup via `> Parent:` backlinks.

    Sets up a parent plan with 5 completed + 5 pending tasks, then two child
    plans pointing back at the parent (3/3 + 2/2). Asserts:
      * `task_stats` stays scoped to the file's own ## Tasks (5/10).
      * `aggregate_stats` rolls in descendants (10/15, 2 descendants).
      * `parent_rel` parsing handles the `> Parent: <relpath>` form.
      * `children` are wired as a list of plan-dicts on the parent.
    Without this, the sidebar progress bar lies about parent completion.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name).resolve()
        browser_server.DEV_ROOT = self.dev_root

        # Parent plan: 5 completed + 5 pending = 5/10 own tasks.
        parent_dir = self.dev_root / "demo-repo" / "vidux" / "design-overhaul"
        parent_dir.mkdir(parents=True)
        parent_path = parent_dir / "PLAN.md"
        parent_tasks = (
            "\n".join(f"- [completed] task done {i}" for i in range(5))
            + "\n"
            + "\n".join(f"- [pending] task pending {i}" for i in range(5))
        )
        parent_path.write_text(
            "# Parent\n\n## Purpose\nParent plan.\n\n## Tasks\n" + parent_tasks + "\n",
            encoding="utf-8",
        )
        self.parent_rel = "demo-repo/vidux/design-overhaul/PLAN.md"

        # Child A: 3/3 — every task completed.
        child_a_dir = parent_dir / "alpha"
        child_a_dir.mkdir(parents=True)
        (child_a_dir / "PLAN.md").write_text(
            "# Child A\n\n"
            f"> Parent: {self.parent_rel} task D2\n\n"
            "## Tasks\n"
            "- [completed] a1\n- [completed] a2\n- [completed] a3\n",
            encoding="utf-8",
        )

        # Child B: 0/2 — nothing done.
        child_b_dir = parent_dir / "beta"
        child_b_dir.mkdir(parents=True)
        (child_b_dir / "PLAN.md").write_text(
            "# Child B\n\n"
            f"**Parent:** {self.parent_rel}\n\n"
            "## Tasks\n"
            "- [pending] b1\n- [pending] b2\n",
            encoding="utf-8",
        )

    def tearDown(self):
        browser_server.clear_plans_cache()
        self.tmp.cleanup()

    def _find(self, plans, rel: str) -> dict:
        for plan in plans:
            if plan["rel"] == rel:
                return plan
        raise AssertionError(f"plan {rel} not in {[p['rel'] for p in plans]}")

    def test_extract_parent_rel_handles_both_forms(self):
        self.assertEqual(
            browser_server.extract_parent_rel(
                "# T\n\n> Parent: vidux/x/PLAN.md task D2\n"
            ),
            "vidux/x/PLAN.md",
        )
        self.assertEqual(
            browser_server.extract_parent_rel("# T\n\n**Parent:** vidux/y/PLAN.md\n"),
            "vidux/y/PLAN.md",
        )
        self.assertIsNone(browser_server.extract_parent_rel("# T\n\nno parent\n"))

    def test_parent_task_stats_count_only_own_tasks(self):
        plans = browser_server.discover_plans()
        parent = self._find(plans, self.parent_rel)
        self.assertEqual(parent["task_stats"]["total"], 10)
        self.assertEqual(parent["task_stats"]["counts"]["completed"], 5)
        self.assertEqual(parent["task_stats"]["counts"]["pending"], 5)

    def test_aggregate_stats_rolls_up_children(self):
        plans = browser_server.discover_plans()
        parent = self._find(plans, self.parent_rel)
        agg = parent["aggregate_stats"]
        # 10 own + 3 child-A + 2 child-B = 15 total tasks under this branch.
        self.assertEqual(agg["total"], 15)
        # 5 own completed + 3 child-A completed + 0 child-B completed = 8.
        self.assertEqual(agg["counts"]["completed"], 8)
        # 5 own pending + 0 child-A pending + 2 child-B pending = 7.
        self.assertEqual(agg["counts"]["pending"], 7)
        self.assertEqual(agg["descendants"], 2)

    def test_children_attached_to_parent(self):
        plans = browser_server.discover_plans()
        parent = self._find(plans, self.parent_rel)
        rels = sorted(child["rel"] for child in parent["children"])
        self.assertEqual(
            rels,
            [
                "demo-repo/vidux/design-overhaul/alpha/PLAN.md",
                "demo-repo/vidux/design-overhaul/beta/PLAN.md",
            ],
        )

    def test_child_keeps_own_task_stats_independent(self):
        plans = browser_server.discover_plans()
        child_a = self._find(plans, "demo-repo/vidux/design-overhaul/alpha/PLAN.md")
        # Children should get their own aggregate_stats too — no descendants
        # for a leaf, so it equals the own task_stats.
        self.assertEqual(child_a["task_stats"]["total"], 3)
        self.assertEqual(child_a["aggregate_stats"]["total"], 3)
        self.assertEqual(child_a["aggregate_stats"]["descendants"], 0)
        self.assertEqual(child_a["parent_rel"], self.parent_rel)


class BrowserMarkdownSanitizeContractTests(unittest.TestCase):
    # renderMarkdownBody() (app.js) fed the
    # raw output of marked.parse() -- which renders embedded HTML/script
    # verbatim by design -- directly into innerHTML, for arbitrary file
    # content sourced from anywhere under DEV_ROOT via /api/file. Fixed by
    # sanitizing through a locally-vendored DOMPurify before ever returning
    # HTML for innerHTML assignment. A real DOM-based behavioral test lives
    # in browser/tests/unit/ where feasible; happy-dom does not reliably
    # reproduce DOMPurify's real-browser script-stripping behavior for every
    # input shape (verified directly: identical sanitize() calls diverge
    # under happy-dom depending on unrelated sibling-markup ordering, which
    # does not happen in a real browser), so the security-critical wiring
    # itself is proven here as a static contract instead.
    def test_vendored_dompurify_is_present_and_real(self):
        vendor = ROOT / "browser" / "static" / "vendor" / "dompurify.min.js"
        self.assertTrue(vendor.is_file(), "browser/static/vendor/dompurify.min.js must exist")
        content = vendor.read_text(encoding="utf-8")
        self.assertIn("DOMPurify", content)
        self.assertIn("@license DOMPurify", content[:400])
        self.assertGreater(len(content), 20_000, "vendored file looks truncated/stubbed")
        license_file = ROOT / "browser" / "static" / "vendor" / "dompurify.LICENSE"
        self.assertTrue(license_file.is_file())

    def test_index_html_loads_dompurify_before_app_js(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        dompurify_idx = index.index('src="/static/vendor/dompurify.min.js"')
        app_idx = index.index('src="/static/app.js"')
        self.assertLess(
            dompurify_idx, app_idx,
            "dompurify.min.js must load before app.js so window.DOMPurify exists in time",
        )

    def test_render_markdown_body_sanitizes_before_returning(self):
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        start = app.index("function renderMarkdownBody(md) {")
        end = app.index("\n}\n", start)
        body = app[start:end]

        self.assertIn("window.marked.parse(", body)
        self.assertIn("window.DOMPurify.sanitize(", body)
        # The sanitize call must be what actually gets returned -- not just
        # invoked and discarded (that would be a checkbox fix, not a real one).
        self.assertIn("return window.DOMPurify.sanitize(html)", body)
        # If the sanitizer failed to load, must fall back to the escaping
        # path (naiveMarkdown), never fall through to unsanitized `html`.
        self.assertIn("if (!window.DOMPurify) return naiveMarkdown(md);", body)


class BrowserReadaloudStaticContractTests(unittest.TestCase):
    """Read-aloud player + annotation FAB removed from product (2026-07)."""

    def test_readaloud_surface_files_are_gone(self):
        static = ROOT / "browser" / "static"
        scripts = ROOT / "browser" / "scripts"
        for rel in [
            "readaloud.js",
            "readaloud-kokoro.js",
            "readaloud-fixture.html",
            "readaloud-fixture-manifest.json",
        ]:
            self.assertFalse((static / rel).exists(), rel)
        for rel in [
            "start-voxtral-mlx-server.sh",
            "voxtral_mlx_server.py",
        ]:
            self.assertFalse((scripts / rel).exists(), rel)

    def test_main_shell_has_no_fab_or_readaloud_player(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")
        self.assertNotIn("root-annotation-toggle", index)
        self.assertNotIn("annotation-fab", index)
        self.assertNotIn("readaloud-player", index)
        self.assertNotIn("root-readaloud", index)
        self.assertNotIn("readaloud.js", index)
        self.assertNotIn("floating-action", index)
        self.assertNotIn("footer-player", index)
        self.assertNotIn("Voxtral", index)
        for token in [
            "annotation-fab",
            "readaloud-player",
            "ra-section-play",
            "ra-word",
            "--z-footer-player",
            "--z-floating-action",
            "--footer-player-bottom",
            "--footer-player-block-size",
            "--floating-action-footer-gap",
        ]:
            self.assertNotIn(token, style)

    def test_readaloud_storybook_decision_does_not_add_browser_build_stack(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        deps = {
            **package.get("dependencies", {}),
            **package.get("devDependencies", {}),
        }
        scripts = package.get("scripts", {})
        self.assertNotIn("react", deps)
        self.assertNotIn("react-dom", deps)
        self.assertFalse(any(key.startswith("@storybook/") for key in deps))
        self.assertNotIn("storybook", scripts)

    def test_app_action_zoning_contract_names_chrome_layers(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        topbar_meta = index.split('<div class="topbar-meta">', 1)[1].split("</div>", 1)[0]
        self.assertIn('data-vidux-zone="status-header"', index)
        self.assertIn('data-vidux-zone="app-shell"', index)
        self.assertIn('data-vidux-zone="navigation-sidebar"', index)
        self.assertIn('data-vidux-zone="content-pane"', index)
        self.assertNotIn('data-vidux-zone="floating-action"', index)
        self.assertNotIn('data-vidux-zone="footer-player"', index)
        self.assertIn('data-vidux-zone", "mode-popover"', app)
        self.assertNotIn("root-annotation-toggle", topbar_meta)
        self.assertNotIn("readaloud-player", topbar_meta)

        for token in [
            "--z-mobile-sidebar:",
            "--z-header:",
            "--z-mode-popover:",
            "--z-skip-link:",
            "--pane-footer-reserve:",
        ]:
            self.assertIn(token, style)

        self.assertIn("z-index: var(--z-header)", style)
        self.assertIn("z-index: var(--z-mobile-sidebar)", style)
        self.assertIn("z-index: var(--z-mode-popover)", style)

    def test_subplan_row_is_keyboard_and_screen_reader_accessible(self):
        """`.subplan-row` was a click-only div with no
        tabindex/role/aria-label and no keydown handler -- unreachable by
        keyboard and silent to screen readers despite being the only way to
        navigate into a sub-plan from this view."""
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")

        render_fn = app.split("function renderPaneSubplans(plan) {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn('role="button"', render_fn)
        self.assertIn('tabindex="0"', render_fn)
        self.assertIn("aria-label=", render_fn)

        wiring = app.split('querySelectorAll(".subplan-row")', 1)[1].split(
            "\n  });", 1
        )[0]
        self.assertIn('"keydown"', wiring)
        self.assertIn('"Enter"', wiring)

    def test_annotation_state_helper_contract_is_named(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        annotation_helper = (
            ROOT / "browser" / "static" / "annotation-state.js"
        ).read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('/static/annotation-state.js', index)
        self.assertLess(index.index('/static/annotation-state.js'), index.index('/static/app.js'))
        self.assertNotIn('id="root-annotation-toggle"', index)
        self.assertIn("ViduxAnnotationState", app)
        self.assertIn("ANNOTATION_STATES", app)
        for state_name in [
            "unavailable",
            "idle",
            "capture-active",
            "target-picked",
            "composer-open",
            "saving",
            "saved",
            "error",
        ]:
            self.assertIn(state_name, annotation_helper)

        self.assertIn("dataset.annotationState", annotation_helper)
        self.assertIn("paintButton", annotation_helper)
        self.assertIn("derive", annotation_helper)
        self.assertIn("annotationUiState", app)
        self.assertIn("status.dataset.state", app)
        self.assertIn("setPopoverStatus(AS.SAVING", app)
        self.assertIn("setPopoverStatus(AS.SAVED", app)
        self.assertIn("setPopoverStatus(AS.ERROR", app)
        self.assertIn("aria-pressed", annotation_helper)
        self.assertIn("z-index: var(--z-skip-link)", style)
        self.assertIn("padding: 24px clamp(20px, 3vw, 40px) var(--pane-footer-reserve)", style)


    def test_annotation_review_rail_contract_is_named(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        comment_rail = (
            ROOT / "browser" / "static" / "comment-rail.js"
        ).read_text(encoding="utf-8")
        markers = (
            ROOT / "browser" / "static" / "comment-markers.js"
        ).read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('/static/comment-rail.js', index)
        self.assertLess(index.index('/static/comment-rail.js'), index.index('/static/app.js'))
        self.assertIn("ViduxCommentRail", app)
        self.assertIn("commentRail.countLabel", app)
        self.assertIn("commentRail.renderList", app)
        self.assertIn('class="comments-panel annotation-review-rail"', markers)
        self.assertIn('data-comment-scope="current-view"', markers)
        self.assertIn('data-comment-state="loading"', markers)
        self.assertIn('data-comment-count="0"', markers)
        self.assertIn('data-comment-filter="all"', markers)
        self.assertIn('data-comment-filter="open"', markers)
        self.assertIn('data-comment-filter="mine"', markers)
        self.assertIn('data-comment-list', markers)
        self.assertIn("data-comment-empty", comment_rail)
        self.assertIn("data-comment-jump", comment_rail)
        self.assertIn("targetLabel", comment_rail)
        self.assertIn("data-comment-state", app)
        self.assertIn("data-comment-count", app)
        self.assertIn(".annotation-review-rail", style)
        self.assertIn(".comment-filter-row", style)
        self.assertIn(".comment-filter.is-active", style)
        self.assertIn(".comment-empty", style)

    def test_annotation_anchor_marker_contract_is_named(self):
        index = (ROOT / "browser" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "browser" / "static" / "app.js").read_text(encoding="utf-8")
        markers = (
            ROOT / "browser" / "static" / "comment-markers.js"
        ).read_text(encoding="utf-8")
        style = (ROOT / "browser" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('/static/comment-markers.js', index)
        self.assertLess(index.index('/static/comment-rail.js'), index.index('/static/comment-markers.js'))
        self.assertLess(index.index('/static/comment-markers.js'), index.index('/static/app.js'))
        self.assertIn("ViduxCommentMarkers", app)
        self.assertIn("commentMarkers.render", app)
        self.assertIn("commentMarkers.renderPanel", app)
        self.assertIn("commentMarkers.bindToggle", app)
        self.assertIn("commentMarkers.jumpToTarget", app)
        self.assertIn("commentMarkers.setPreview", app)
        self.assertIn("commentMarkers.resolveAnchorTarget", app)
        self.assertIn("resolveAnchorTarget", app)
        self.assertIn("renderCommentMarkers", app)
        self.assertIn("vidux:comment-markers-hidden", markers)
        self.assertIn('data-comment-markers-hidden', markers)
        self.assertIn('data-comment-marker-toggle', markers)
        self.assertIn("updateToggle", markers)
        self.assertIn("setStoredHidden", markers)
        self.assertIn("accessibleArtifactFrames", markers)
        self.assertIn("ensureFrameAnchorStyle", markers)
        self.assertIn("resolveAnchorTarget", markers)
        self.assertIn('data-comment-target-map', markers)
        self.assertIn("comment-marker-layer", markers)
        self.assertIn("data-comment-marker-count", markers)
        self.assertIn("comment-target-map", markers)
        self.assertIn(".comment-marker-layer", style)
        self.assertIn(".comment-marker", style)
        self.assertIn(".comment-marker-toggle", style)
        self.assertIn(".comment-target-map", style)
        self.assertIn(".comment-target-chip", style)
        self.assertIn(".is-anchor-preview", style)


class BrowserMainCliStorageIsolationTests(unittest.TestCase):
    """Fixture roots must explicitly configure artifacts and store paths."""

    class _NonBlockingServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            return

        def server_close(self):
            return

    def setUp(self):
        self.original_host = browser_server.HOST
        self.original_port = browser_server.PORT
        self.original_dev_root = browser_server.DEV_ROOT
        self.original_comments_file = browser_server.COMMENTS_FILE
        self.original_steering_file = browser_server.STEERING_FILE
        self.original_claims_file = browser_server.CLAIMS_FILE
        self.original_artifacts_dir = browser_server.ARTIFACTS_DIR
        self.original_server_cls = browser_server.ThreadingHTTPServer
        browser_server.ThreadingHTTPServer = self._NonBlockingServer

    def tearDown(self):
        browser_server.ThreadingHTTPServer = self.original_server_cls
        browser_server.HOST = self.original_host
        browser_server.PORT = self.original_port
        browser_server.DEV_ROOT = self.original_dev_root
        browser_server.COMMENTS_FILE = self.original_comments_file
        browser_server.STEERING_FILE = self.original_steering_file
        browser_server.CLAIMS_FILE = self.original_claims_file
        browser_server.ARTIFACTS_DIR = self.original_artifacts_dir

    def test_artifacts_dir_flag_overrides_the_checkout_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = Path(tmpdir) / "fixture-artifacts"
            custom.mkdir()

            browser_server.main(["--port", "0", "--artifacts-dir", str(custom)])

            self.assertEqual(browser_server.ARTIFACTS_DIR, custom.resolve())

    def test_steering_path_flag_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = Path(tmpdir) / "fixture-steering" / "steering.jsonl"

            browser_server.main(["--port", "0", "--steering-path", str(custom)])

            self.assertEqual(browser_server.STEERING_FILE, custom)

    def test_claims_path_flag_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = Path(tmpdir) / "fixture-claims" / "claims.jsonl"

            browser_server.main(["--port", "0", "--claims-path", str(custom)])

            self.assertEqual(browser_server.CLAIMS_FILE, custom)

    def test_artifacts_dir_untouched_when_flag_omitted(self):
        browser_server.main(["--port", "0"])

        self.assertEqual(
            browser_server.ARTIFACTS_DIR,
            self.original_artifacts_dir,
        )


if __name__ == "__main__":
    unittest.main()
