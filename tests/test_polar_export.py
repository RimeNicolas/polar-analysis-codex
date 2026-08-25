import json
import sys
import time
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polar_mcp import polar_account, polar_export, polar_mcp_auth, polar_mcp_oauth, polar_oauth, polar_service


class PolarExportTests(unittest.TestCase):
    def test_ranges_split_and_stay_inclusive(self):
        self.assertEqual(
            list(polar_export.date_ranges(date(2026, 1, 1), date(2026, 1, 3), max_days=1)),
            [(date(2026, 1, 1), date(2026, 1, 1)), (date(2026, 1, 2), date(2026, 1, 2)), (date(2026, 1, 3), date(2026, 1, 3))],
        )

    def test_flattens_objects_and_preserves_list_json(self):
        row = polar_export.flatten({"name": "Ride", "stats": {"speed": 20}, "laps": [{"n": 1}]})
        self.assertEqual(row["stats.speed"], "20")
        self.assertEqual(row["laps"], '[{"n":1}]')

    def test_export_row_puts_summary_values_in_named_columns(self):
        session = {
            "startTime": "2026-08-16T09:31:09",
            "sport": {"id": "2"},
            "durationMillis": 3723000,
            "distanceMeters": 25400,
            "calories": 700,
            "hrAvg": 144,
            "statistics": {"statistics": [{"type": "STATISTICS_TYPE_SPEED", "avg": 7.5}, {"type": "STATISTICS_TYPE_POWER", "avg": 210}]},
        }
        row = polar_export.export_row(session, {"2": "Cycling"})
        self.assertEqual({key: row[key] for key in ("date", "sport_type", "duration", "distance", "avg_speed", "calories", "avg_hr", "avg_power")}, {"date": "2026-08-16", "sport_type": "Cycling", "duration": "01:02:03", "distance": "25.400", "avg_speed": "7.5", "calories": "700", "avg_hr": "144", "avg_power": "210"})

    @patch("polar_mcp.polar_export.requests.get")
    def test_request_uses_exclusive_end_date_and_features(self, get: Mock):
        response = Mock()
        response.json.return_value = {"trainingSessions": []}
        get.return_value = response
        polar_export.get_sessions("token", date(2026, 1, 1), date(2026, 1, 1), ("zones",), 5)
        self.assertEqual(get.call_args.kwargs["params"], [("from", "2026-01-01T00:00:00"), ("to", "2026-01-02T00:00:00"), ("features", "zones")])

    def test_default_token_path_is_separate_from_project(self):
        path = polar_oauth.default_credentials_file()
        self.assertEqual(path.name, "credentials.yml")
        self.assertEqual(path.parent.name, "polar-csv-exporter")

    def test_yaml_cache_round_trip(self):
        with TemporaryDirectory() as directory:
            path = polar_oauth.Path(directory) / "credentials.yml"
            polar_oauth.write_private_yaml(path, {"client_secret": "a:token", "expires_at": 42})
            self.assertEqual(polar_oauth.read_yaml(path), {"client_secret": "a:token", "expires_at": 42})

    @patch("polar_mcp.polar_service.get_sport_names", return_value={"2": "Cycling"})
    @patch("polar_mcp.polar_service.get_sessions")
    @patch("polar_mcp.polar_service.load_token", return_value="token")
    def test_service_returns_normalized_activities(self, _: Mock, get_sessions: Mock, __: Mock):
        get_sessions.return_value = [{"startTime": "2026-08-16T09:31:09", "sport": {"id": "2"}, "durationMillis": 60000}]
        result = polar_service.get_activities("2026-08-16", "2026-08-16", features=[])
        self.assertEqual(result["activity_count"], 1)
        self.assertEqual(result["activities"][0]["sport_type"], "Cycling")
        self.assertEqual(result["features"], [])

    @patch("polar_mcp.polar_account.requests.get")
    def test_account_request_uses_bearer_token_without_query_credentials(self, get: Mock):
        response = Mock()
        response.json.return_value = {"accountData": {"physicalInformation": {"weight": "70.0"}}}
        get.return_value = response
        result = polar_account.get_account_data("secret-token", 5)
        self.assertEqual(result["accountData"]["physicalInformation"]["weight"], "70.0")
        self.assertEqual(get.call_args.args, (polar_account.ACCOUNT_URL,))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertNotIn("params", get.call_args.kwargs)

    @patch("polar_mcp.polar_account.requests.get")
    def test_account_request_accepts_live_unwrapped_response(self, get: Mock):
        response = Mock()
        response.json.return_value = {"physicalInformation": {"weight": "70.0"}}
        get.return_value = response
        result = polar_account.get_account_data("secret-token", 5)
        self.assertEqual(result, {"accountData": {"physicalInformation": {"weight": "70.0"}}})

    def test_account_json_is_owner_only(self):
        with TemporaryDirectory() as directory:
            path = polar_oauth.Path(directory) / "account.json"
            polar_account.write_private_json(path, {"accountData": {"email": "private@example.com"}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"accountData": {"email": "private@example.com"}})

    def test_mcp_oauth_state_is_bound_to_one_user_and_single_use(self):
        with TemporaryDirectory() as directory:
            store = polar_mcp_oauth.SQLitePolarCredentialStore(polar_oauth.Path(directory) / "credentials.sqlite3")
            state = store.create_state("user-a")
            self.assertEqual(store.consume_state(state), "user-a")
            self.assertIsNone(store.consume_state(state))

    def test_mcp_oauth_credentials_are_isolated_per_user(self):
        with TemporaryDirectory() as directory:
            store = polar_mcp_oauth.SQLitePolarCredentialStore(polar_oauth.Path(directory) / "credentials.sqlite3")
            store.save_credentials("user-a", {"access_token": "access-a", "refresh_token": "refresh-a", "expires_in": 3600})
            store.save_credentials("user-b", {"access_token": "access-b", "refresh_token": "refresh-b", "expires_in": 3600})
            self.assertEqual(store.load_credentials("user-a").access_token, "access-a")
            self.assertEqual(store.load_credentials("user-b").access_token, "access-b")
            self.assertIsNone(store.load_credentials("unknown"))

    def test_mcp_usage_metrics_count_requests_and_connected_users(self):
        with TemporaryDirectory() as directory:
            store = polar_mcp_oauth.SQLitePolarCredentialStore(polar_oauth.Path(directory) / "credentials.sqlite3")
            store.record_activity_request("user-a")
            store.record_activity_request("user-a")
            store.record_activity_request("user-b")
            store.save_credentials("user-a", {"access_token": "access-a", "refresh_token": "refresh-a", "expires_in": 3600})
            today = date.today().isoformat()
            metrics = store.usage_metrics(today, today)
            self.assertEqual(metrics.activity_requests, 3)
            self.assertEqual(metrics.unique_requesting_users, 2)
            self.assertEqual(metrics.new_polar_connections, 1)
            self.assertEqual(metrics.total_polar_connected_users, 1)

    def test_mcp_usage_metrics_reject_reversed_dates(self):
        with self.assertRaises(polar_mcp_oauth.PolarOAuthError):
            polar_mcp_oauth.usage_range("2026-08-02", "2026-08-01")

    def test_auth0_admin_role_requires_matching_verified_claim(self):
        from mcp.server.auth.provider import AccessToken

        token = AccessToken(
            token="opaque",
            client_id="chatgpt",
            scopes=["polar:activities:read"],
            expires_at=int(time.time()) + 3600,
            resource="https://polar-mcp.example.test",
            subject="auth0-user",
            claims={"iss": "https://tenant.example.test/", "roles": ["polar-mcp-admin"]},
        )
        self.assertTrue(polar_mcp_auth.is_admin(token, "polar-mcp-admin"))
        self.assertFalse(polar_mcp_auth.is_admin(token, "other-role"))

    def test_mcp_oauth_authorization_url_includes_state_and_redirect(self):
        with TemporaryDirectory() as directory:
            store = polar_mcp_oauth.SQLitePolarCredentialStore(polar_oauth.Path(directory) / "credentials.sqlite3")
            config = polar_mcp_oauth.PolarOAuthConfig("client-id", "client-secret", "https://example.test/polar/callback")
            query = parse_qs(urlsplit(polar_mcp_oauth.authorization_url(config, store, "user-a")).query)
            self.assertEqual(query["client_id"], ["client-id"])
            self.assertEqual(query["redirect_uri"], [config.redirect_uri])
            self.assertEqual(query["scope"], [polar_mcp_oauth.POLAR_SCOPE])
            self.assertEqual(store.consume_state(query["state"][0]), "user-a")

    @patch("polar_mcp.polar_mcp_oauth.exchange_token")
    def test_mcp_oauth_refreshes_expired_credentials(self, exchange_token: Mock):
        with TemporaryDirectory() as directory:
            store = polar_mcp_oauth.SQLitePolarCredentialStore(polar_oauth.Path(directory) / "credentials.sqlite3")
            store.save_credentials("user-a", {"access_token": "expired", "refresh_token": "refresh-a", "expires_in": 0})
            exchange_token.return_value = {"access_token": "fresh", "refresh_token": "refresh-b", "expires_in": 3600}
            config = polar_mcp_oauth.PolarOAuthConfig("client-id", "client-secret", "https://example.test/polar/callback")
            self.assertEqual(polar_mcp_oauth.get_valid_polar_access_token("user-a", config, store), "fresh")
            self.assertEqual(store.load_credentials("user-a").access_token, "fresh")
            self.assertEqual(exchange_token.call_args.args[1]["grant_type"], "refresh_token")

if __name__ == "__main__":
    unittest.main()
