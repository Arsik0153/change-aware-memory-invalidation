"""Fast authored checks for nonadditive interval accounting."""

import unittest

from diagnose_costs import duration, stats, timeline


class CostAccountingChecks(unittest.TestCase):
    def test_parallel_native_intervals_are_union_not_sum(self):
        self.assertEqual(duration([(0, 3), (1, 2), (2, 4)]), 4)

    def test_streamed_argument_interval_not_tool_execution(self):
        messages = [
            {"type": "user", "time": {"created": 0}},
            {
                "type": "assistant",
                "id": "assistant",
                "time": {"created": 0, "completed": 100000},
                "content": [
                    {
                        "type": "tool",
                        "id": "patch",
                        "name": "patch",
                        "state": {"status": "completed"},
                        "time": {"created": 1000, "ran": 99000, "completed": 100000},
                    }
                ],
            },
            {"type": "idle", "time": {"created": 100000}},
        ]
        result, tools = timeline(messages, "fixture")
        self.assertEqual(result["all_tool_execution_union_seconds"], 1)
        self.assertEqual(result["non_tool_execution_seconds"], 99)
        self.assertEqual(tools[0]["created_to_ran_seconds"], 98)

    def test_absent_metrics_do_not_impute_zero(self):
        self.assertIsNone(stats([None, None])["sum"])
        self.assertEqual(stats([None, None])["missing"], 2)


if __name__ == "__main__":
    unittest.main()
