import unittest
from datetime import date
from unittest.mock import patch

from app.schedule_worker import FetchError, fetch_dictionary, fetch_window, retry_after


class ScheduleWorkerTests(unittest.TestCase):
    def test_keeps_parallel_lessons_and_subgroups(self):
        lessons = [
            {"date": "2026.10.19", "beginLesson": "13:15", "endLesson": "14:45", "listSubGroups": [{"subgroup": "ФИТ-242/1"}]},
            {"date": "2026.10.19", "beginLesson": "13:15", "endLesson": "14:45", "listSubGroups": [{"subgroup": "ФИТ-242/2"}]},
        ]
        job = {"entity_kind": "group", "external_id": "696", "range_start": date(2026, 10, 19), "range_end": date(2026, 10, 25)}
        with patch("app.schedule_worker.fetch_json", return_value=lessons):
            self.assertEqual(fetch_window(job), lessons)

    def test_missing_time_is_not_a_success(self):
        job = {"entity_kind": "group", "external_id": "696", "range_start": date(2026, 10, 19), "range_end": date(2026, 10, 25)}
        with patch("app.schedule_worker.fetch_json", return_value=[{"date": "2026.10.19"}]):
            with self.assertRaises(FetchError) as error:
                fetch_window(job)
        self.assertEqual(error.exception.code, "partial_or_invalid_response")

    def test_empty_buildings_are_unverified(self):
        with patch("app.schedule_worker.fetch_json", return_value=[]):
            with self.assertRaises(FetchError) as error:
                fetch_dictionary({"kind": "buildings", "scope": ""})
        self.assertEqual(error.exception.code, "empty_unverified_dictionary")

    def test_lecturer_private_fields_not_persisted(self):
        payload = [{"lecturerOid": 844, "person": "709789", "fio": "Федотова", "email": "private@example.invalid", "lecturerHR_PERSON_ID": 123}]
        with patch("app.schedule_worker.fetch_json", return_value=payload):
            result = fetch_dictionary({"kind": "lecturers", "scope": ""})
        self.assertEqual(result, [{"lecturerOid": 844, "person": "709789", "fio": "Федотова"}])

    def test_room_scope_is_checked(self):
        with patch("app.schedule_worker.fetch_json", return_value=[{"auditoriumOid": 127, "buildingOid": 18}]):
            with self.assertRaises(FetchError):
                fetch_dictionary({"kind": "auditoriums", "scope": "16"})

    def test_retry_after_does_not_shorten_a_long_pause(self):
        self.assertEqual(retry_after("172800"), 172800)


if __name__ == "__main__":
    unittest.main()
