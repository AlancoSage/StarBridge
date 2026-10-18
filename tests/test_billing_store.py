"""Billing ownership, encrypted persistence and submit-once confirmations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from starbridge.billing_store import BillingStore, BillingStoreError


QQ = "123456789"
PROVIDER = "demo"
SECRET = "Api-Password-Do-Not-Print-763!"
CREDENTIALS = {"api_username": "api-client-763", "api_password": SECRET}


class BillingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.application_db = sqlite3.connect(":memory:")
        self.store = BillingStore(self.application_db, self.base)

    def tearDown(self):
        self.store.close()
        self.application_db.close()
        self.temp.cleanup()

    def bind(self, qq=QQ, provider=PROVIDER, account="42"):
        return self.store.bind(qq, provider, account, CREDENTIALS)

    def order(self, binding, **extra):
        return self.store.create_order(binding["qq"], binding["provider"], binding["account"],
                                       binding["generation"], "invoice-101", order_id="order-202", **extra)

    def checkout(self, binding, **extra):
        return self.store.save_checkout(binding["qq"], binding["provider"], binding["generation"],
                                        {"pid": 12, "qty": 1, "password": SECRET}, "测试商品 月付 x1", **extra)

    def test_credentials_encrypted_and_application_database_is_untouched(self):
        self.assertFalse(self.store.key_path.exists())
        binding = self.bind()
        self.assertTrue(self.store.key_path.exists())
        dump = "\n".join(self.store.db.iterdump())
        self.assertNotIn(SECRET, dump)
        self.assertNotIn(CREDENTIALS["api_username"], dump)
        self.assertEqual(self.store.get_binding(QQ, PROVIDER)["credentials"], CREDENTIALS)
        self.assertEqual(self.store.get_binding(QQ, PROVIDER)["account"], "42")
        self.assertEqual(self.store.get_binding(QQ, PROVIDER)["generation"], binding["generation"])
        self.assertEqual(self.application_db.execute("SELECT name FROM sqlite_schema").fetchall(), [])

    def test_restart_preserves_binding_and_does_not_rotate_key(self):
        binding = self.bind()
        key = self.store.key_path.read_bytes()
        self.store.close()
        self.store = BillingStore(self.application_db, self.base)
        self.assertEqual(self.store.get_binding(QQ, PROVIDER), binding)
        self.assertEqual(self.store.key_path.read_bytes(), key)

    def test_lost_key_fails_closed_instead_of_replacing_bindings(self):
        binding = self.bind()
        self.store.key_path.unlink()
        for action in (lambda: self.store.get_binding(QQ, PROVIDER), lambda: self.bind("987654321")):
            with self.subTest(action=action), self.assertRaises(BillingStoreError) as caught:
                action()
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertFalse(self.store.key_path.exists())
        row = self.store.db.execute("SELECT generation FROM billing_bindings").fetchone()
        self.assertEqual(row[0], binding["generation"])

    def test_wrong_key_and_corrupt_ciphertext_use_safe_errors(self):
        self.bind()
        self.store.key_path.write_bytes(b"invalid-key")
        with self.assertRaises(BillingStoreError) as caught:
            self.store.get_binding(QQ, PROVIDER)
        self.assertNotIn(SECRET, str(caught.exception))
        with self.store.db:
            self.store.db.execute("UPDATE billing_bindings SET credentials=?", (SECRET,))
        with self.assertRaises(BillingStoreError) as caught:
            self.store.get_binding(QQ, PROVIDER)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_invalid_credentials_use_safe_errors(self):
        for credentials in (SECRET, {"api_password": {SECRET}}, {"token": float("nan")}):
            with self.subTest(credentials=type(credentials)), self.assertRaises(BillingStoreError) as caught:
                self.store.bind(QQ, PROVIDER, "42", credentials)
            self.assertNotIn(SECRET, str(caught.exception))
        self.assertIsNone(self.store.get_binding(QQ, PROVIDER))

    def test_order_queries_require_current_user_provider_and_binding_generation(self):
        binding = self.bind()
        local_id = self.order(binding, summary="测试商品 月付 x1", status="unpaid")
        self.assertEqual(self.store.get_order(QQ, PROVIDER, local_id)["invoice_id"], "invoice-101")
        self.assertIsNone(self.store.get_order("987654321", PROVIDER, local_id))
        self.assertIsNone(self.store.get_order(QQ, "other", local_id))
        self.assertEqual(len(self.store.list_orders(QQ, PROVIDER)), 1)
        self.bind(account="84")
        self.assertIsNone(self.store.get_order(QQ, PROVIDER, local_id))
        self.assertEqual(self.store.list_orders(QQ, PROVIDER), [])
        self.assertFalse(self.store.set_order_status(QQ, PROVIDER, local_id, "paid"))

    def test_order_status_update_cannot_cross_users(self):
        binding = self.bind()
        local_id = self.order(binding)
        self.assertFalse(self.store.set_order_status("987654321", PROVIDER, local_id, "paid"))
        self.assertTrue(self.store.set_order_status(QQ, PROVIDER, local_id, "paid"))
        self.assertEqual(self.store.get_order(QQ, PROVIDER, local_id)["status"], "paid")

    def test_unbind_revokes_orders_and_pending_checkouts(self):
        binding = self.bind()
        local_id, token = self.order(binding), self.checkout(binding)
        self.assertTrue(self.store.unbind(QQ, PROVIDER))
        self.assertFalse(self.store.unbind(QQ, PROVIDER))
        self.assertIsNone(self.store.get_binding(QQ, PROVIDER))
        self.assertIsNone(self.store.get_order(QQ, PROVIDER, local_id))
        self.assertIsNone(self.store.claim_checkout(QQ, PROVIDER, binding["generation"], token))
        self.assertIsNone(self.store.get_checkout(QQ, PROVIDER, binding["generation"], token))

    def test_checkout_payload_is_encrypted_and_claim_is_single_use(self):
        binding = self.bind()
        token = self.checkout(binding)
        self.assertNotIn(SECRET, "\n".join(self.store.db.iterdump()))
        args = (QQ, PROVIDER, binding["generation"], token)
        checkout = self.store.get_checkout(*args)
        self.assertEqual(checkout["status"], "pending")
        self.assertEqual(checkout["payload"]["password"], SECRET)
        self.assertEqual(self.store.claim_checkout(*args), checkout["payload"])
        self.assertIsNone(self.store.claim_checkout(*args))
        self.assertEqual(self.store.get_checkout(*args)["status"], "submitting")

    def test_checkout_cannot_be_claimed_or_inspected_by_another_identity(self):
        binding = self.bind()
        token = self.checkout(binding)
        for args in (("987654321", PROVIDER, binding["generation"], token),
                     (QQ, "other", binding["generation"], token),
                     (QQ, PROVIDER, "old-generation", token)):
            with self.subTest(args=args):
                self.assertIsNone(self.store.get_checkout(*args))
                self.assertIsNone(self.store.claim_checkout(*args))
        self.assertIsNotNone(self.store.claim_checkout(QQ, PROVIDER, binding["generation"], token))

    def test_expired_confirmation_is_not_submitted(self):
        binding = self.bind()
        token = self.checkout(binding, ttl=1)
        args = (QQ, PROVIDER, binding["generation"], token)
        with patch("starbridge.billing_store.time.time", return_value=time.time() + 2):
            self.assertIsNone(self.store.claim_checkout(*args))
            self.assertEqual(self.store.get_checkout(*args)["status"], "expired")

    def test_restart_does_not_reset_claim_and_finish_requires_own_order(self):
        binding = self.bind()
        token = self.checkout(binding)
        args = (QQ, PROVIDER, binding["generation"], token)
        self.store.claim_checkout(*args)
        self.store.close()
        self.store = BillingStore(self.application_db, self.base)
        self.assertIsNone(self.store.claim_checkout(*args))
        other = self.bind("987654321")
        self.assertFalse(self.store.finish_checkout(token, self.order(other)))
        local_id = self.order(binding)
        self.assertTrue(self.store.finish_checkout(token, local_id))
        self.assertFalse(self.store.finish_checkout(token, local_id))
        checkout = self.store.get_checkout(*args)
        self.assertEqual(checkout["status"], "complete")
        self.assertEqual(checkout["local_order_id"], local_id)
        self.assertIsNone(self.store.claim_checkout(*args))

    def test_rebinding_invalidates_old_checkout_even_with_same_remote_account(self):
        binding = self.bind()
        token = self.checkout(binding)
        renewed = self.bind()
        self.assertNotEqual(binding["generation"], renewed["generation"])
        self.assertIsNone(self.store.claim_checkout(QQ, PROVIDER, binding["generation"], token))
        with self.assertRaises(BillingStoreError):
            self.checkout(binding)

    def test_simultaneous_claims_across_connections_only_submit_once(self):
        binding = self.bind()
        token = self.checkout(binding)

        def claim(_):
            worker = BillingStore(None, self.base)
            try:
                return worker.claim_checkout(QQ, PROVIDER, binding["generation"], token)
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)


if __name__ == "__main__":
    unittest.main()
