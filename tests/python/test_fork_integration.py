"""Fork behavior retained when integrating the parent repository."""

import json
import os
from unittest import mock

from _support import IsolatedHomeTest, fixture
from aiusage.contract import finalize
from aiusage.normalize import normalize
from aiusage.providers import codex_rate_limits, zai

ACCESS = "enc:v1:BwcHBwcHBwcHBwcH.LDmacVRZeBX6IOn2zpkjOA.QCggnWXAsihbhkxWbtG4zWg"
JWT = "enc:v1:BwcHBwcHBwcHBwcH._ADpnKWlzGcSQC9tFztd-w.QCggnWXAuTxMzlxXJtY"


class ForkIntegrationTest(IsolatedHomeTest):
    def zcode_store(self):
        os.environ["ZCODE_CREDENTIAL_SECRET"] = "zcode-test-secret"
        return self.write(".zcode/v2/credentials.json", {"oauth:zai:access_token": ACCESS, "zcodejwttoken": JWT})

    def test_zcode_decryption_and_explicit_token_precedence(self):
        self.zcode_store()
        self.assertEqual(zai._zai_key(), ("zcode-access-cred", "zcode", "zcode-jwt-cred"))
        os.environ["ZCODE_CREDENTIAL_SECRET"] = "foreign-machine"
        self.assertEqual(zai._zai_key()[0], "")
        os.environ["ZCODE_CREDENTIAL_SECRET"] = "zcode-test-secret"
        self.write(".config/zai/token", "explicit-token\n")
        self.assertEqual(zai._zai_key()[0], "explicit-token")

    def test_zcode_without_access_token_is_absent(self):
        self.zcode_store()
        self.write(".zcode/v2/credentials.json", {"zcodejwttoken": JWT})
        self.assertEqual(zai._zai_key()[0], "")

    def test_coding_plan_and_start_plan_are_collected_without_leaking_tokens(self):
        self.zcode_store()
        quota = self.write(
            "quota.json",
            {
                "success": True,
                "data": {
                    "level": "lite",
                    "limits": [
                        {"type": "CREDIT_LIMIT", "percentage": 40, "currentValue": 48, "usage": 120, "nextResetTime": 3600000},
                        {"type": "CREDIT_LIMIT", "percentage": 65, "currentValue": 390, "usage": 600, "nextResetTime": 1785086400000},
                    ],
                },
            },
        )
        balance = self.write(
            "balance.json",
            {
                "data": {
                    "plans": [{"name": "Start Plan", "status": "active"}],
                    "balances": [{"show_name": "GLM-4.6", "used_units": 12000, "total_units": 45000, "period_end": 1785050000}],
                }
            },
        )
        os.environ.update({"ZAI_RESPONSE_FILE": str(quota), "ZCODE_BALANCE_RESPONSE_FILE": str(balance)})
        with mock.patch.object(zai, "_today_usage", return_value=None):
            usage = zai.get_zai_usage()
        result = finalize(normalize({"id": "zai", "now": 1785000000, "inputs": {"usage": usage}}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["historyValues"], {"zs": 40, "zw": 65})
        self.assertEqual(result["details"]["startPlan"]["name"], "Start Plan")
        self.assertEqual(len(result["details"]["startPlan"]["balances"]), 1)
        self.assertNotIn("zcode-access-cred", json.dumps(result))
        self.assertNotIn("zcode-jwt-cred", json.dumps(result))

    def test_expired_zcode_session_points_to_app_for_http_and_body_errors(self):
        self.zcode_store()
        with mock.patch.object(zai, "fetch_json", return_value=mock.Mock(status=401, body="")):
            self.assertEqual(zai.get_zai_usage()["error"], "ZCode session expired — log in again in the ZCode app")
        os.environ["ZAI_RESPONSE_FILE"] = str(self.write("expired.json", {"success": False, "msg": "token expired or incorrect"}))
        with mock.patch.object(zai, "_start_plan", return_value=None):
            self.assertIn("log in again in the ZCode app", zai.get_zai_usage()["error"])
            os.environ["ZAI_TOKEN"] = "explicit-token"
            self.assertEqual(zai.get_zai_usage()["error"], "token expired or incorrect")

    def test_codex_resolves_non_login_install_and_override(self):
        binary = self.write(".local/bin/codex", "#!/bin/sh\n")
        binary.chmod(0o755)
        with mock.patch.object(codex_rate_limits.shutil, "which", return_value=None):
            self.assertEqual(codex_rate_limits.codex_binary(), str(binary))
            os.environ["CODEX_BIN"] = "/custom/codex"
            self.assertEqual(codex_rate_limits.codex_binary(), "/custom/codex")

    def test_openrouter_remaining_allowance_including_zero(self):
        self.assertEqual(fixture("openrouter-unused")["details"]["limitRemainingUSD"], 10)
        self.assertEqual(fixture("openrouter-exhausted")["details"]["limitRemainingUSD"], 0)
        self.assertEqual(fixture("zai-credits")["historyValues"], {"zs": 40, "zw": 65})
