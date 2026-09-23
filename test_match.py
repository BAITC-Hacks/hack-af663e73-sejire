"""Проверки подбора, пустых исходов, занятости и импорта каталога."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import app


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        app.DB = Path(self.tmp.name) / "contractors.db"
        app.ADMIN_FILE = Path(self.tmp.name) / "admin.json"
        app.init_db()
        self.catalog = app.load_catalog()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def query(self, **overrides: object) -> app.Query:
        values = {
            "city": "Алматы",
            "event_date": date(2026, 10, 14),
            "event_format": "корпоратив",
            "category": "Ведущий",
            "budget": 1_500_000,
        }
        values.update(overrides)
        return app.Query(**values)

    def test_official_catalog_size_and_flags(self) -> None:
        self.assertEqual(len(self.catalog), 66)
        self.assertTrue(any(item.synthetic for item in self.catalog))
        self.assertTrue(any(item.price_imputed for item in self.catalog))
        self.assertTrue(any(item.city_imputed for item in self.catalog))
        self.assertTrue(any(item.max_hours is None for item in self.catalog))

    def test_dense_category_is_stable_and_sorted_by_price(self) -> None:
        first = app.search(self.catalog, self.query())
        second = app.search(self.catalog, self.query())
        self.assertEqual(first["outcome"], "matched")
        self.assertGreaterEqual(first["passed"], 3)
        self.assertEqual(len(first["cards"]), 3)
        self.assertLess(first["passed"], first["pool"])
        order = [(card["price_from"], card["id"]) for card in first["cards"]]
        self.assertEqual(order, sorted(order))
        self.assertEqual([card["id"] for card in first["cards"]], [card["id"] for card in second["cards"]])
        explanations = [card["explanation"] for card in first["cards"]]
        self.assertEqual(len(set(explanations)), 3)
        for card in first["cards"]:
            self.assertIn("Алматы", card["explanation"])
            self.assertIn("Ведущий", card["explanation"])
            self.assertIn("2026-10-14", card["explanation"])
            self.assertIn(str(card["price_from"])[:3], card["explanation"].replace(" ", ""))

    def test_same_request_on_busy_date_is_blocked(self) -> None:
        october = app.search(self.catalog, self.query())
        december = app.search(self.catalog, self.query(event_date=date(2026, 12, 12)))
        self.assertEqual(december["outcome"], "blocked")
        self.assertEqual(december["passed"], 0)
        self.assertGreater(december["pool"], 0)
        self.assertTrue(any(item["kind"] == "busy" for item in december["failed"]))
        self.assertEqual(len(december["failed"]), december["pool"])
        self.assertNotEqual(
            [card["id"] for card in october["cards"]],
            [item["name"] for item in december["failed"][:3]],
        )

    def test_rare_florist_keeps_synthetic_badge(self) -> None:
        result = app.search(
            self.catalog,
            self.query(event_format="свадьба", category="Флорист", budget=500_000),
        )
        self.assertEqual(result["outcome"], "matched")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(len(result["cards"]), 1)
        self.assertTrue(result["cards"][0]["synthetic"])
        self.assertIn("синтетический", result["cards"][0]["explanation"])

    def test_restaurant_missing_in_astana(self) -> None:
        result = app.search(
            self.catalog,
            self.query(
                city="Астана",
                event_date=date(2026, 11, 14),
                event_format="конференция",
                category="Ресторан",
                budget=2_000_000,
            ),
        )
        self.assertEqual(result["outcome"], "no_category")
        self.assertEqual(result["pool"], 0)
        self.assertIn("Астана", result["summary"])
        self.assertIn("Алматы", result["summary"])

    def test_null_hours_do_not_fail_duration(self) -> None:
        result = app.search(
            self.catalog,
            self.query(event_format="свадьба", category="Флорист", budget=500_000, duration=12),
        )
        self.assertEqual(result["passed"], 1)
        self.assertIsNone(result["cards"][0]["max_hours"])
        self.assertIn("12", result["cards"][0]["explanation"])

    def test_unknown_price_is_not_recommended(self) -> None:
        sample = next(item for item in self.catalog if item.city == "Алматы" and "Ведущий" in item.categories)
        blank = app.Contractor(
            id="HK-NOPRICE",
            name="Без цены",
            city=sample.city,
            categories=sample.categories,
            formats=sample.formats,
            price_from=None,
            languages=sample.languages,
            max_hours=sample.max_hours,
            busy_dates=(),
            description="Профиль без стартовой цены для проверки фильтра.",
        )
        result = app.search(self.catalog + [blank], self.query())
        kinds = {item["name"]: item["kind"] for item in result["failed"]}
        self.assertEqual(kinds.get("Без цены"), "price_unknown")
        self.assertNotIn("HK-NOPRICE", [card["id"] for card in result["cards"]])

    def test_duration_limit_rejects_only_when_hours_exist(self) -> None:
        short = app.Contractor(
            id="HK-SHORT",
            name="Короткий лимит",
            city="Алматы",
            categories=("Ведущий",),
            formats=("корпоратив",),
            price_from=100_000,
            languages=("русский",),
            max_hours=2,
            busy_dates=(),
            description="Профиль с лимитом в два часа на площадке.",
        )
        result = app.search([short], self.query(duration=5))
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["failed"][0]["kind"], "duration")

    def test_import_keeps_flags_updates_same_id_and_reports_errors(self) -> None:
        before = len(app.load_catalog())
        text = (
            "\ufeffid,anon_name,categories,city,city_imputed,synthetic,price_from_kzt,"
            "price_imputed,event_formats,languages,max_hours,busy_dates,description\n"
            'HK-TEST1,Тест Один,Флорист,Алматы,True,True,100000,True,свадьба,русский,,"2026-10-01","Описание, с запятой и флагом."\n'
            "HK-TEST1,Тест Повтор,Флорист,Алматы,False,True,120000,False,свадьба,русский,,,Повтор в том же файле.\n"
            "HK-BAD,Плохой,Флорист,Алматы,False,False,100000,False,свадьба,русский,,не-дата,Плохая дата.\n"
        )
        preview = app.preview_csv(text)
        self.assertEqual(preview["added"], 1)
        self.assertEqual(preview["skipped"], 2)
        self.assertEqual(len(app.load_catalog()), before)

        result = app.import_csv(text)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped"], 2)
        saved = next(item for item in app.load_catalog() if item.id == "HK-TEST1")
        self.assertTrue(saved.synthetic)
        self.assertTrue(saved.price_imputed)
        self.assertTrue(saved.city_imputed)
        self.assertEqual(saved.busy_dates, (date(2026, 10, 1),))
        self.assertIn("запятой", saved.description)
        self.assertFalse(any(item.id == "HK-BAD" for item in app.load_catalog()))

        updated = app.import_csv(
            "id,anon_name,categories,city,city_imputed,synthetic,price_from_kzt,"
            "price_imputed,event_formats,languages,max_hours,busy_dates,description\n"
            "HK-TEST1,Тест Один,Флорист,Алматы,True,True,90000,True,свадьба,русский,,2026-10-01,Описание обновлено.\n"
        )
        self.assertEqual(updated["added"], 0)
        self.assertEqual(updated["updated"], 1)
        again = next(item for item in app.load_catalog() if item.id == "HK-TEST1")
        self.assertEqual(again.price_from, 90000)
        self.assertEqual(len([item for item in app.load_catalog() if item.id == "HK-TEST1"]), 1)

        with self.assertRaises(ValueError):
            app.import_csv("id,city\n1,Алматы\n")
        self.assertTrue(any(item.id == "HK-TEST1" for item in app.load_catalog()))


if __name__ == "__main__":
    unittest.main()
