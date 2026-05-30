from app.agent.evaluator import evaluate_result


def test_evaluate_result_with_required_metric() -> None:
    result = {
        "task_id": "scanned",
        "quality": {
            "validation_pass_rate": 1.0,
            "warning_count": 0,
            "failed_count": 0,
        },
        "tables": [
            {
                "name": "financial_metrics_from_ocr_text",
                "title": "Financial Metrics From OCR Text",
                "unit": "USD billions",
                "evidence": {"page_start": 1},
                "rows": [
                    {
                        "item": "Annual revenue",
                        "values": {
                            "amount_usd_billions": 245.0,
                            "year_over_year_percent": 16.0,
                        },
                        "evidence": {"page": 1, "bbox": [0, 0, 10, 10]},
                    }
                ],
            }
        ],
    }
    expectations = {
        "min_table_count": 1,
        "min_row_count": 1,
        "max_failed_count": 0,
        "min_validation_pass_rate": 1.0,
        "required_tables": ["financial_metrics"],
        "required_metrics": [
            {
                "table_contains": "financial_metrics",
                "row_contains": "annual revenue",
                "period": "amount_usd_billions",
                "expected_value": 245,
                "unit_contains": "USD",
                "evidence_required": True,
            }
        ],
    }

    evaluation = evaluate_result(result, expectations)

    assert evaluation["status"] == "pass"
    assert evaluation["score"] == 1.0
    assert evaluation["passed_count"] == evaluation["check_count"]


def test_evaluate_result_fails_missing_metric() -> None:
    result = {
        "task_id": "missing",
        "quality": {"validation_pass_rate": 1.0, "warning_count": 0, "failed_count": 0},
        "tables": [{"name": "table", "rows": [{"item": "Revenue", "values": {"2024": 100.0}}]}],
    }

    evaluation = evaluate_result(
        result,
        {
            "required_metrics": [
                {
                    "row_contains": "operating income",
                    "expected_value": 109,
                }
            ]
        },
    )

    assert evaluation["status"] == "fail"
    assert evaluation["score"] == 0.0
