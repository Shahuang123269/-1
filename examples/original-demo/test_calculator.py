"""Offline tests: these use no API key and create no API cost."""

import unittest

from calculator import CalculationError, calculate


class CalculatorTests(unittest.TestCase):
    def test_basic_arithmetic(self) -> None:
        self.assertEqual(calculate("(25 + 17) * 3"), "126")

    def test_division(self) -> None:
        self.assertEqual(calculate("7 / 2"), "3.5")

    def test_rejects_python_code(self) -> None:
        with self.assertRaises(CalculationError):
            calculate("__import__('os').system('whoami')")


if __name__ == "__main__":
    unittest.main()
