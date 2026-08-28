from datetime import UTC, datetime, timedelta

from reports import render_report
from schemas import RunStatus
from state import StateStore
from trends import load_trend


GIB = 1024**3


def add_run(store, index, percent, *, actual=0, estimated=0):
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index * 7)
    run_id = f"202601{index + 1:02d}T000000-00000000"
    store.write_json(
        f"runs/{run_id}/diagnosis.json",
        {
            "created_at": created.isoformat(),
            "filesystems": [
                {
                    "role": "root",
                    "percent_used": percent,
                    "used_bytes": percent * GIB,
                    "available_bytes": (100 - percent) * GIB,
                }
            ],
        },
    )
    if actual or estimated:
        store.write_json(
            f"runs/{run_id}/execution.json",
            {
                "actual_reclaim_bytes": actual,
                "estimation_error_bytes": actual - estimated,
            },
        )
    return run_id


def test_trend_keeps_last_eight_and_projects_only_after_four_points(tmp_path):
    store = StateStore(tmp_path / "state")
    for index in range(10):
        add_run(store, index, 60 + index)

    trend = load_trend(store, red_percent=85)

    assert len(trend["points"]) == 8
    assert trend["points"][0]["percent_used"] == 62
    assert trend["points"][-1]["growth_bytes"] == GIB
    assert trend["projected_days_to_red"] == 112.0
    assert trend["informational_only"] is True


def test_trend_includes_reclaim_error_and_renders_local_report(tmp_path):
    store = StateStore(tmp_path / "state")
    run_id = add_run(store, 0, 70, actual=3 * GIB, estimated=5 * GIB)

    trend = load_trend(store, red_percent=85)
    report = render_report(
        run_id=run_id,
        status=RunStatus.PROPOSED,
        before={"percent_used": 70, "available_bytes": 30 * GIB},
        after={"percent_used": 70, "available_bytes": 30 * GIB},
        action_results=[],
        next_steps=["revisar"],
        trend=trend,
    )

    assert "Tendência (até 8 execuções" in report
    assert "3.0 GiB" in report
    assert "-2.0 GiB" in report
    assert trend["projected_days_to_red"] is None
