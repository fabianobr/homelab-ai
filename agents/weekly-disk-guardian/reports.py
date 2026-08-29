"""Local Markdown proof reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from schemas import ActionResult, RunStatus


def render_report(
    *,
    run_id: str,
    status: RunStatus,
    before: Mapping[str, int | float],
    after: Mapping[str, int | float],
    action_results: Sequence[ActionResult],
    next_steps: Sequence[str],
    trend: Mapping[str, object] | None = None,
) -> str:
    lines = [
        f"# Weekly Disk Guardian — {run_id}",
        "",
        f"Status: **{status.value}**",
        "",
        "## Espaço",
        "",
        "| Momento | Uso | Disponível |",
        "|---|---:|---:|",
        f"| Antes | {before.get('percent_used', 0)}% | {_gib(before.get('available_bytes', 0))} GiB |",
        f"| Depois | {after.get('percent_used', 0)}% | {_gib(after.get('available_bytes', 0))} GiB |",
        "",
        f"## Ações ({len(action_results)} ações)",
        "",
    ]
    if action_results:
        for item in action_results:
            detail = f" — {item.message}" if item.message else ""
            lines.append(f"- `{item.action_id}`: **{item.status.value}**{detail}")
    else:
        lines.append("Nenhuma ação foi executada.")
    if trend and trend.get("points"):
        lines.extend(
            [
                "",
                "## Tendência (até 8 execuções; apenas informativa)",
                "",
                "| Run | Uso | Crescimento | Recuperado | Erro da estimativa |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for point in trend["points"]:
            lines.append(
                f"| {point['run_id']} | {point['percent_used']}% | "
                f"{_signed_gib(point['growth_bytes'])} GiB | "
                f"{_gib(point['actual_reclaim_bytes'])} GiB | "
                f"{_signed_gib(point['estimation_error_bytes'])} GiB |"
            )
        projected = trend.get("projected_days_to_red")
        if projected is not None:
            lines.extend(
                [
                    "",
                    f"Projeção linear: **{projected} dias** até o limiar vermelho. "
                    "Esta projeção nunca autoriza ações.",
                ]
            )

    lines.extend(["", "## Próximos passos", ""])
    lines.extend(f"- {step}" for step in next_steps)
    return "\n".join(lines) + "\n"


def _gib(value: int | float) -> str:
    return f"{float(value) / (1024**3):.1f}"


def _signed_gib(value: int | float) -> str:
    return f"{float(value) / (1024**3):+.1f}"
