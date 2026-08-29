"""Read-only Docker inventory and image eligibility evidence.

Every Docker invocation is an explicit argv passed to an injected runner.  The
collector deliberately knows no removal or prune command.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class Runner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class DockerImageEvidence:
    image_id: str
    tags: tuple[str, ...]
    created_at: datetime
    active_container_ids: tuple[str, ...]
    compose_referenced: bool


def is_removable_image(
    image: DockerImageEvidence,
    *,
    now: datetime,
    protected_tag_patterns: tuple[str, ...],
    protect_newer_than_days: int,
) -> bool:
    if not image.image_id.startswith("sha256:"):
        return False
    if image.active_container_ids or image.compose_referenced:
        return False
    if image.created_at.tzinfo is None or now.tzinfo is None:
        return False
    if image.created_at >= now - timedelta(days=protect_newer_than_days):
        return False
    for tag in image.tags:
        candidates = (tag, tag.rsplit("/", 1)[-1], tag.rsplit(":", 1)[-1])
        if any(fnmatchcase(candidate, pattern) for pattern in protected_tag_patterns for candidate in candidates):
            return False
    return True


def collect_docker_runtime(
    runner: Runner,
    *,
    compose_files: Sequence[str | Path],
    now: datetime,
    protected_tag_patterns: Sequence[str] = ("rollback-*", "backup-*"),
    protect_newer_than_days: int = 7,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Collect serializable evidence, producing candidates only when complete."""
    errors: list[str] = []
    system_df = _run_text(runner, ["docker", "system", "df", "-v"], timeout, errors)

    container_ids_text = _run_text(
        runner,
        ["docker", "container", "ls", "--quiet", "--no-trunc"],
        timeout,
        errors,
    )
    container_ids = _nonempty_lines(container_ids_text)
    containers: list[dict[str, str]] | None = [] if container_ids is not None else None
    if container_ids:
        containers = _parse_containers(
            _run_json_lines(
                runner,
                ["docker", "container", "inspect", "--format", "{{json .}}", *container_ids],
                timeout,
                errors,
            ),
            errors,
        )

    image_ids_text = _run_text(
        runner,
        ["docker", "image", "ls", "--quiet", "--no-trunc"],
        timeout,
        errors,
    )
    image_ids = _nonempty_lines(image_ids_text)
    images: list[dict[str, Any]] | None = [] if image_ids is not None else None
    if image_ids:
        images = _parse_images(
            _run_json_lines(
                runner,
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{json .}}",
                    *sorted(set(image_ids)),
                ],
                timeout,
                errors,
            ),
            errors,
        )

    compose_images: list[str] = []
    compose_complete = True
    for configured_path in compose_files:
        path = str(Path(configured_path).expanduser())
        output = _run_text(
            runner,
            [
                "docker",
                "compose",
                "-f",
                path,
                "--profile",
                "*",
                "config",
                "--images",
            ],
            timeout,
            errors,
        )
        refs = _nonempty_lines(output)
        if refs is None:
            compose_complete = False
        else:
            compose_images.extend(refs)

    volume_names_text = _run_text(
        runner, ["docker", "volume", "ls", "--quiet"], timeout, errors
    )
    volume_names = _nonempty_lines(volume_names_text)
    volumes: list[dict[str, Any]] | None = [] if volume_names is not None else None
    if volume_names:
        volumes = _parse_volumes(
            _run_json_lines(
                runner,
                ["docker", "volume", "inspect", "--format", "{{json .}}", *volume_names],
                timeout,
                errors,
            ),
            errors,
        )

    policy_complete = now.tzinfo is not None and protect_newer_than_days >= 0
    if now.tzinfo is None:
        errors.append("policy: now must include timezone")
    if protect_newer_than_days < 0:
        errors.append("policy: protect_newer_than_days must be non-negative")

    active_by_image: dict[str, list[str]] = {}
    if containers is not None:
        for container in containers:
            active_by_image.setdefault(container["image_id"], []).append(container["container_id"])

    compose_refs = tuple(sorted(set(compose_images)))
    candidates: list[dict[str, Any]] = []
    evidence_complete = (
        not errors
        and system_df is not None
        and containers is not None
        and images is not None
        and compose_complete
        and volumes is not None
        and policy_complete
    )
    if evidence_complete and images is not None:
        patterns = tuple(protected_tag_patterns)
        for item in images:
            referenced = any(_reference_matches_image(ref, item) for ref in compose_refs)
            active_ids = tuple(sorted(active_by_image.get(item["image_id"], [])))
            protected = _has_protected_tag(tuple(item["tags"]), patterns)
            recent = datetime.fromisoformat(item["created_at"]) >= now - timedelta(
                days=protect_newer_than_days
            )
            evidence = DockerImageEvidence(
                image_id=item["image_id"],
                tags=tuple(item["tags"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                active_container_ids=active_ids,
                compose_referenced=referenced,
            )
            item["active_container_ids"] = list(evidence.active_container_ids)
            item["compose_referenced"] = referenced
            item["protected_tag"] = protected
            item["recent"] = recent
            if is_removable_image(
                evidence,
                now=now,
                protected_tag_patterns=patterns,
                protect_newer_than_days=protect_newer_than_days,
            ):
                candidates.append(
                    {
                        "image_id": evidence.image_id,
                        "size_bytes": item["size_bytes"],
                        "proofs": {
                            "not_active": True,
                            "not_compose_referenced": True,
                            "no_protected_tag": True,
                            "not_recent": True,
                        },
                    }
                )

    return {
        "status": "complete" if not errors else "partial",
        "errors": errors,
        "system_df": system_df,
        "containers": containers,
        "images": images,
        "compose": {
            "files": [str(Path(item).expanduser()) for item in compose_files],
            "images": list(compose_refs),
            "profiles_included": True,
        },
        "volumes": volumes,
        "candidates": candidates if not errors else [],
    }


def _run_text(
    runner: Runner,
    argv: list[str],
    timeout: float,
    errors: list[str],
) -> str | None:
    try:
        result = runner.run(argv, check=False, timeout=timeout)
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        errors.append(f"timeout: {' '.join(argv[:3])}: {exc}")
        return None
    except Exception as exc:  # runners may expose implementation-specific errors
        errors.append(f"unavailable: {' '.join(argv[:3])}: {exc}")
        return None
    returncode = _result_field(result, "returncode")
    stdout = _result_field(result, "stdout")
    if not isinstance(returncode, int) or returncode != 0 or not isinstance(stdout, str):
        errors.append(f"command failed or malformed: {' '.join(argv[:3])}")
        return None
    return stdout


def _run_json_lines(
    runner: Runner,
    argv: list[str],
    timeout: float,
    errors: list[str],
) -> list[Mapping[str, Any]] | None:
    output = _run_text(runner, argv, timeout, errors)
    lines = _nonempty_lines(output)
    if lines is None:
        return None
    parsed: list[Mapping[str, Any]] = []
    try:
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError("JSON item is not an object")
            parsed.append(value)
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"parse incomplete: {' '.join(argv[:3])}: {exc}")
        return None
    return parsed


def _parse_containers(
    raw: list[Mapping[str, Any]] | None, errors: list[str]
) -> list[dict[str, str]] | None:
    if raw is None:
        return None
    parsed: list[dict[str, str]] = []
    for item in raw:
        container_id, image_id = item.get("Id"), item.get("Image")
        if not _sha256_id(image_id) or not isinstance(container_id, str) or not container_id:
            errors.append("parse incomplete: container Id/Image")
            return None
        parsed.append({"container_id": container_id, "image_id": image_id})
    return parsed


def _parse_images(
    raw: list[Mapping[str, Any]] | None, errors: list[str]
) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    parsed: list[dict[str, Any]] = []
    for item in raw:
        image_id, tags, digests, created, size = (
            item.get("Id"),
            item.get("RepoTags"),
            item.get("RepoDigests"),
            item.get("Created"),
            item.get("Size"),
        )
        if tags is None:
            tags = []
        if digests is None:
            digests = []
        try:
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except ValueError:
            errors.append("parse incomplete: image Created")
            return None
        if (
            not _sha256_id(image_id)
            or not isinstance(tags, list)
            or not all(isinstance(tag, str) and tag for tag in tags)
            or not isinstance(digests, list)
            or not all(isinstance(digest, str) and digest for digest in digests)
            or not isinstance(size, int)
            or size < 0
            or created_at.tzinfo is None
        ):
            errors.append("parse incomplete: image Id/RepoTags/Created/Size")
            return None
        parsed.append(
            {
                "image_id": image_id,
                "tags": sorted(tags),
                "digests": sorted(digests),
                "created_at": created_at.isoformat(),
                "size_bytes": size,
            }
        )
    return parsed


def _parse_volumes(
    raw: list[Mapping[str, Any]] | None, errors: list[str]
) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    parsed: list[dict[str, Any]] = []
    for item in raw:
        name, driver, mountpoint = item.get("Name"), item.get("Driver"), item.get("Mountpoint")
        if not all(isinstance(value, str) and value for value in (name, driver, mountpoint)):
            errors.append("parse incomplete: volume Name/Driver/Mountpoint")
            return None
        parsed.append({"name": name, "driver": driver, "mountpoint": mountpoint})
    return parsed


def _reference_matches_image(reference: str, image: Mapping[str, Any]) -> bool:
    if (
        reference == image["image_id"]
        or reference in image["tags"]
        or reference in image["digests"]
    ):
        return True
    # Docker treats a reference without a tag or digest as :latest.
    last_component = reference.rsplit("/", 1)[-1]
    return ":" not in last_component and "@" not in reference and f"{reference}:latest" in image["tags"]


def _has_protected_tag(tags: tuple[str, ...], patterns: tuple[str, ...]) -> bool:
    for tag in tags:
        candidates = (tag, tag.rsplit("/", 1)[-1], tag.rsplit(":", 1)[-1])
        if any(fnmatchcase(candidate, pattern) for pattern in patterns for candidate in candidates):
            return True
    return False


def _result_field(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _nonempty_lines(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [line.strip() for line in value.splitlines() if line.strip()]


def _sha256_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) > 7
