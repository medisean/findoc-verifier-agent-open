from time import sleep

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_task_contract() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/tasks",
        json={
            "task_name": "contract-test",
            "document_type": "annual_report_pdf",
            "inputs": [{"path": "examples/inputs/__missing_contract_fixture__.pdf"}],
            "goal": "Extract financial tables.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"]
    assert body["status"] in {"queued", "running", "succeeded"}


def test_failed_task_propagates_status() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/tasks",
        json={
            "task_name": "failure-propagation",
            "document_type": "annual_report_pdf",
            "inputs": [{"path": "examples/inputs/__missing_contract_fixture__.pdf"}],
            "goal": "Extract financial tables.",
        },
    )
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    status = None
    for _ in range(20):
        status_response = client.get(f"/v1/tasks/{task_id}")
        assert status_response.status_code == 200
        status = status_response.json()["status"]
        if status in {"succeeded", "failed"}:
            break
        sleep(0.05)

    assert status == "failed"

    result_response = client.get(f"/v1/tasks/{task_id}/result")
    assert result_response.status_code == 200
    result_body = result_response.json()
    assert result_body["task_name"] == "failure-propagation"
    assert result_body["status"] == "failed"
