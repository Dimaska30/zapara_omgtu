import unittest
from datetime import date, time
from app.auth import digest, passwords
from app.schedule_alerts import overlapping


class AccountAndAlertTests(unittest.TestCase):
    def test_password_hash_is_not_plaintext(self):
        password = 'sample-password-123'
        stored = passwords.hash(password)
        self.assertNotEqual(stored, password)
        self.assertTrue(passwords.verify(stored, password))

    def test_token_digest_does_not_store_token(self):
        self.assertEqual(digest('one-time-token'), digest('one-time-token'))
        self.assertNotEqual(digest('one-time-token'), b'one-time-token')
        self.assertNotEqual(digest('one-time-token'), digest('another-token'))

    def test_conflict_uses_full_interval_and_matching_day(self):
        payload = [{'date': '2026.11.05', 'beginLesson': '8:00', 'endLesson': '09:30'}]
        self.assertTrue(overlapping(payload, date(2026, 11, 5), time(9), time(10)))
        self.assertFalse(overlapping(payload, date(2026, 11, 5), time(9, 30), time(10)))
        self.assertFalse(overlapping(payload, date(2026, 11, 6), time(8), time(9)))


if __name__ == '__main__':
    unittest.main()
