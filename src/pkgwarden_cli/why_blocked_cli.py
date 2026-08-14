from datetime import datetime

import httpx
import typer
from pydantic import BaseModel, Field

from pkgwarden_cli import enterprise_hooks, http_client
from pkgwarden_cli.config import CliConfig
from pkgwarden_cli.output import emit
from pkgwarden_cli.runtime import CliRuntime
from pkgwarden_cli.spec import parse_package_argument


class WhyBlockedScanFinding(BaseModel):
    engine: str
    category: str
    rule_id: str
    severity: str
    detail: dict = Field(default_factory=dict)


class WhyBlockedScanDetails(BaseModel):
    status: str
    risk_score: int
    summary: str | None = None
    is_known_malware: bool = False
    findings: list[WhyBlockedScanFinding] = Field(default_factory=list)


class WhyBlockedVulnerabilityReference(BaseModel):
    vulnerability_id: str
    vuln_id: str | None = None
    cves: list[str] = Field(default_factory=list)


class WhyBlockedPolicyDetails(BaseModel):
    vulnerabilities: list[WhyBlockedVulnerabilityReference] = Field(default_factory=list)
    effective_moment_utc: datetime | None = None


class WhyBlockedCveDetails(BaseModel):
    cves: list[str] = Field(default_factory=list)


class WhyBlockedExceptionDetails(BaseModel):
    exception_id: str
    vulnerability_id: str
    created_by_email: str | None = None
    created_at: datetime | str | None = None
    expires_at: datetime | str | None = None


class WhyBlockedPendingDetails(BaseModel):
    request_group_id: str | None = None
    request_status: str | None = None
    web_url: str | None = None


class WhyBlockedResponse(BaseModel):
    blocked: bool
    reason: str | None = None
    details: (
        WhyBlockedScanDetails
        | WhyBlockedPendingDetails
        | WhyBlockedPolicyDetails
        | WhyBlockedCveDetails
        | WhyBlockedExceptionDetails
        | None
    ) = None


def why_blocked(
    ctx: typer.Context,
    spec: str = typer.Argument(
        ..., help="Package spec: name==version, name@version, or name with --version"
    ),
    version_option: str | None = typer.Option(
        None, "--version", "-v", help="Exact version (alternative to an inline pin)"
    ),
    ecosystem: str = typer.Option("pypi", "--ecosystem", "-e"),
) -> None:
    """Explain why a package version is (or is not) installable."""
    runtime: CliRuntime = ctx.find_root().obj["runtime"]
    name, version = _split_spec(spec, version_option)
    if runtime.config.mode == "enterprise":
        impl = enterprise_hooks.get_why_blocked_impl()
        if impl is None:
            typer.echo(
                "pw why-blocked: enterprise mode needs the airgapped API, but the "
                "pkgwarden-cli-enterprise plugin is not installed.",
                err=True,
            )
            raise typer.Exit(1)
        impl(runtime, name, version, ecosystem)
        return
    try:
        token = _why_blocked_token(runtime.config)
    except ValueError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    client = http_client.build_gate_resolution_client(
        api_base=runtime.config.api_base,
        bearer_token=token,
        timeout=runtime.timeout,
    )
    fetch_and_emit_why_blocked(runtime, client, name, version, ecosystem)


def fetch_and_emit_why_blocked(
    runtime: CliRuntime, client: httpx.Client, name: str, version: str, ecosystem: str
) -> None:
    try:
        response = client.get(
            "/packages/why-blocked",
            params={"name": name, "version": version, "ecosystem": ecosystem},
        )
        response.raise_for_status()
        payload = WhyBlockedResponse.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        typer.echo(http_client.http_error_message(exc), err=True)
        raise typer.Exit(1) from exc
    except httpx.RequestError as exc:
        typer.echo(f"pw why-blocked: could not reach the API ({exc}).", err=True)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo("pw why-blocked: unexpected non-JSON response from the API.", err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    human = format_why_blocked_human(name, version, ecosystem, payload)
    emit(runtime, human, payload.model_dump(mode="json"))


def _why_blocked_token(config: CliConfig) -> str:
    for getter in (
        http_client.gate_bearer_token,
        http_client.user_bearer_token,
        http_client.requests_bearer_token,
    ):
        try:
            return getter(config)
        except ValueError:
            continue
    raise ValueError(
        "Set PKGWARDEN_GATE_TOKEN, PKGWARDEN_USER_TOKEN, or PKGWARDEN_PROJECT_TOKEN",
    )


def _split_spec(spec: str, version_option: str | None) -> tuple[str, str]:
    parsed = parse_package_argument(spec, version_option)
    if parsed.version is None or not parsed.exact:
        raise typer.BadParameter(
            f"Spec {spec!r} needs an exact version: use --version <version>, "
            "or name==version / name@version.",
        )
    return parsed.name, parsed.version


def format_why_blocked_human(
    name: str, version: str, ecosystem: str, payload: WhyBlockedResponse
) -> str:
    header = f"{name}=={version} ({ecosystem})"
    if not payload.blocked:
        if payload.reason == "allowed_by_exception":
            return f"{header}: {_format_allowed_by_exception(payload.details)}"
        return f"{header}: available"
    reason = payload.reason
    details = payload.details
    if reason == "pending_approval":
        parts = [f"{header}: pending approval"]
        if isinstance(details, WhyBlockedPendingDetails):
            if details.request_group_id:
                parts.append(f"(request group {details.request_group_id})")
            if details.web_url:
                parts.append(f"— track {details.web_url}")
        return " ".join(parts)
    if reason == "not_requested":
        return (
            f"{header}: not yet requested — run `pw add {name}=={version}` "
            "to open an approval request"
        )
    if reason == "unknown_version":
        return f"{header}: unknown version on the registry — check the pin"
    if reason in ("scan_verdict", "known_malware") and isinstance(details, WhyBlockedScanDetails):
        return f"{header}: blocked - {_format_scan_verdict(details)}"
    if isinstance(details, WhyBlockedCveDetails) and details.cves:
        return f"{header}: blocked ({reason}) - cves={details.cves}"
    if isinstance(details, WhyBlockedPolicyDetails) and (
        details.vulnerabilities or details.effective_moment_utc is not None
    ):
        policy_details = details.model_dump(mode="json", exclude_none=True)
        return f"{header}: blocked ({reason}) - {policy_details}"
    return f"{header}: blocked ({reason})"


def _format_allowed_by_exception(
    details: (
        WhyBlockedScanDetails
        | WhyBlockedPendingDetails
        | WhyBlockedPolicyDetails
        | WhyBlockedCveDetails
        | WhyBlockedExceptionDetails
        | None
    ),
) -> str:
    if not isinstance(details, WhyBlockedExceptionDetails):
        return "allowed by exception"
    parts = ["allowed by exception", f"id={details.exception_id}"]
    if details.created_by_email:
        parts.append(f"by {details.created_by_email}")
    if details.expires_at:
        parts.append(f"expires {details.expires_at}")
    return " ".join(parts)


def _format_scan_verdict(details: WhyBlockedScanDetails) -> str:
    lead = "known malware (intel)" if details.is_known_malware else "malware scan"
    parts = [f"{lead}: {details.status}"]
    if details.summary:
        parts.append(details.summary)
    if details.findings:
        rendered = ", ".join(
            f"{finding.engine}/{finding.category} [{finding.severity}]"
            for finding in details.findings
        )
        parts.append(f"findings: {rendered}")
    iocs = _format_iocs(details.findings)
    if iocs:
        parts.append(f"iocs: {iocs}")
    return " - ".join(parts)


def _format_iocs(findings: list[WhyBlockedScanFinding]) -> str:
    sources = sorted(
        {
            str(finding.detail["source"])
            for finding in findings
            if finding.category == "known_malware" and finding.detail.get("source")
        }
    )
    return ", ".join(sources)


def register_why_blocked(app: typer.Typer) -> None:
    app.command("why-blocked")(why_blocked)
