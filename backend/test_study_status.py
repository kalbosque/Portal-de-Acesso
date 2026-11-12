import unittest
from types import SimpleNamespace

from api_auth import _is_account_status_denied


class StudyAccountStatusTests(unittest.TestCase):
    def test_denies_pending_and_blocked_accounts(self):
        for status in ("pendente", "bloqueado"):
            with self.subTest(status=status):
                self.assertTrue(_is_account_status_denied(SimpleNamespace(status_conta=status)))

    def test_allows_active_and_unset_statuses(self):
        for status in ("ativo", None):
            with self.subTest(status=status):
                self.assertFalse(_is_account_status_denied(SimpleNamespace(status_conta=status)))


if __name__ == "__main__":
    unittest.main()
