import unittest

from parity import compare_scenario


class WorkflowParityTests(unittest.TestCase):
    def test_three_synthetic_scenarios_match_python_reference(self):
        for scenario in range(3):
            with self.subTest(scenario=scenario):
                result = compare_scenario(scenario)
                self.assertTrue(result["parity"])
                self.assertEqual(result["unique_participants"], 24)
                self.assertEqual(result["raw_submissions"], 25)
                self.assertEqual(result["deduplications"], 1)


if __name__ == "__main__":
    unittest.main()
