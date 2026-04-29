import json
from pathlib import Path
from typing import Any

import httpx
import typer

from pkgwarden_cli import http_client
from pkgwarden_cli.capabilities import fetch_capabilities
from pkgwarden_cli.output import emit
from pkgwarden_cli.package_manager import detect_managers
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.version_info import format_pw_version_line


def doctor(ctx: typer.Context) -> None:
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    cfg = runtime.config
    caps = _probe_capabilities(runtime)
    detected = [
        {"manager": d.manager, "ecosystem": d.ecosystem, "lockfile": d.lockfile}
        for d in detect_managers(Path.cwd())
    ]
    summary: dict[str, Any] = {
        "pw": format_pw_version_line(),
        "api_base": cfg.api_base,
        "configured_mode": cfg.mode,
        "deployment_type": caps.deployment_type,
        "features": list(caps.features),
        "min_cli_version": caps.min_cli_version,
        "configured_package_manager": cfg.package_manager,
        "detected_managers": detected,
        "has_user_token": bool(cfg.user_token),
        "has_project_token": bool(cfg.project_token),
        "has_tape_token": bool(cfg.tape_token),
        "has_project_id": bool(cfg.project_id),
        "has_mirror_token": bool(cfg.mirror_token or cfg.project_token),
    }
    summary["requests_probe"] = _probe_requests(runtime, cfg)
    human = _format_human(summary)
    emit(runtime, human, summary)


def _probe_capabilities(runtime: CliRuntime):
    client = http_client.build_api_client(
        api_base=runtime.config.api_base,
        bearer_token=runtime.config.user_token or runtime.config.tape_token or "",
        timeout=runtime.timeout,
    )
    try:
        return fetch_capabilities(client)
    finally:
        client.close()


def _probe_requests(runtime: CliRuntime, cfg) -> object:
    try:
        token = http_client.requests_bearer_token(cfg)
    except ValueError:
        return "skipped_no_requests_token"
    client = http_client.build_api_client(
        api_base=cfg.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )
    try:
        response = client.get("/requests", params={"limit": 1})
        response.raise_for_status()
        return {"status_code": response.status_code}
    except httpx.HTTPStatusError as exc:
        return {
            "status_code": exc.response.status_code,
            "detail": http_client.http_error_message(exc),
        }
    except httpx.HTTPError as exc:
        return {"error": str(exc)}
    finally:
        client.close()


def _format_human(summary: dict[str, Any]) -> str:
    lines = [
        format_pw_version_line(),
        f"api_base: {summary['api_base']}",
        f"deployment_type: {summary['deployment_type']}",
        f"configured_mode: {summary['configured_mode'] or 'unset'}",
        f"features: {', '.join(summary['features']) if summary['features'] else '(none)'}",
        f"min_cli_version: {summary['min_cli_version'] or 'unset'}",
        f"configured_package_manager: {summary['configured_package_manager'] or 'unset'}",
    ]
    if summary["detected_managers"]:
        manager_names = [d["manager"] for d in summary["detected_managers"]]
        lines.append(f"detected_managers: {', '.join(manager_names)}")
    else:
        lines.append("detected_managers: (none)")
    lines.extend(
        [
            f"user_token: {'set' if summary['has_user_token'] else 'missing'}",
            f"project_token: {'set' if summary['has_project_token'] else 'missing'}",
            f"tape_token: {'set' if summary['has_tape_token'] else 'missing'}",
            f"project_id: {'set' if summary['has_project_id'] else 'missing'}",
            f"mirror_token: {'set' if summary['has_mirror_token'] else 'missing'}",
            f"requests_probe: {json.dumps(summary['requests_probe'], indent=2, default=str)}",
        ]
    )
    return "\n".join(lines)


def register_doctor(app: typer.Typer) -> None:
    app.command("doctor")(doctor)
