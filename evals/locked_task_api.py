from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import threading
import time
import tomllib
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Callable


class Evaluation:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            self.results.append({"name": name, "passed": False, "error": str(exc)})
        else:
            self.results.append({"name": name, "passed": True})


def request(
    host: str,
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, bytes]:
    connection = HTTPConnection(host, port, timeout=2)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    content_type = response.getheader("Content-Type") or ""
    connection.close()
    return response.status, content_type, payload


def json_request(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    status, content_type, payload = request(*args, **kwargs)
    if not content_type.startswith("application/json"):
        raise AssertionError(f"expected JSON content type, got {content_type!r}")
    return status, json.loads(payload)


def assert_equal(actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task", payload)
    if not isinstance(task, dict):
        raise AssertionError("task response must be a JSON object")
    return task


def tasks_payload(payload: Any) -> list[dict[str, Any]]:
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        raise AssertionError("task list response must contain a JSON array")
    return tasks


def module_root(candidate: Path) -> Path:
    for root in (candidate / "src", candidate):
        if (root / "task_api").is_dir():
            return root
    raise AssertionError("candidate does not provide a task_api module")


def runtime_dependencies(candidate: Path) -> list[str]:
    pyproject = candidate / "pyproject.toml"
    if not pyproject.is_file():
        raise AssertionError("candidate does not provide pyproject.toml")
    project = tomllib.loads(pyproject.read_text()).get("project", {})
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise AssertionError("project.dependencies must be a list")
    return dependencies


def evaluate(candidate: Path) -> dict[str, Any]:
    started = time.monotonic()
    candidate = candidate.expanduser().resolve()
    root = module_root(candidate)
    sys.path.insert(0, str(root))
    task_api = importlib.import_module("task_api")
    module_path = Path(task_api.__file__).resolve()
    if candidate not in module_path.parents:
        raise AssertionError(f"import escaped candidate: {module_path}")
    create_server = getattr(task_api, "create_server")
    server = create_server("127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks = Evaluation()

    checks.check(
        "health",
        lambda: assert_equal(
            json_request(host, port, "GET", "/health"),
            (HTTPStatus.OK, {"status": "ok"}),
        ),
    )

    def create_and_list() -> None:
        first = json_request(
            host,
            port,
            "POST",
            "/tasks",
            body=b'{"title":"  first  "}',
            headers={"Content-Type": "application/json"},
        )
        second = json_request(
            host,
            port,
            "POST",
            "/tasks",
            body=b'{"title":"second"}',
            headers={"Content-Type": "application/json"},
        )
        listed = json_request(host, port, "GET", "/tasks")
        assert_equal(first[0], HTTPStatus.CREATED)
        assert_equal(second[0], HTTPStatus.CREATED)
        assert_equal(task_payload(first[1]), {"id": 1, "title": "first"})
        assert_equal(task_payload(second[1]), {"id": 2, "title": "second"})
        assert_equal(listed[0], HTTPStatus.OK)
        assert_equal(
            tasks_payload(listed[1]),
            [
                {"id": 1, "title": "first"},
                {"id": 2, "title": "second"},
            ],
        )

    checks.check("create_list_trim_order", create_and_list)

    invalid_cases = [
        ("malformed_json", b"{bad", "application/json", HTTPStatus.BAD_REQUEST),
        ("non_object", b"[]", "application/json", HTTPStatus.BAD_REQUEST),
        (
            "unknown_field",
            b'{"title":"x","admin":true}',
            "application/json",
            HTTPStatus.BAD_REQUEST,
        ),
        ("missing_title", b"{}", "application/json", HTTPStatus.BAD_REQUEST),
        ("empty_title", b'{"title":"   "}', "application/json", HTTPStatus.BAD_REQUEST),
        ("wrong_type", b'{"title":1}', "application/json", HTTPStatus.BAD_REQUEST),
        ("wrong_media", b'{"title":"x"}', "text/plain", HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
    ]
    for name, body, content_type, expected in invalid_cases:
        checks.check(
            name,
            lambda body=body, content_type=content_type, expected=expected: assert_equal(
                json_request(
                    host,
                    port,
                    "POST",
                    "/tasks",
                    body=body,
                    headers={"Content-Type": content_type},
                )[0],
                expected,
            ),
        )

    oversized = b'{"title":"' + (b"x" * (16 * 1024)) + b'"}'
    checks.check(
        "oversized_body",
        lambda: assert_equal(
            json_request(
                host,
                port,
                "POST",
                "/tasks",
                body=oversized,
                headers={"Content-Type": "application/json"},
            )[0],
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        ),
    )

    for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
        checks.check(
            f"unsupported_{method.lower()}",
            lambda method=method: assert_equal(
                json_request(host, port, method, "/tasks")[0],
                HTTPStatus.METHOD_NOT_ALLOWED,
            ),
        )

    checks.check(
        "unknown_path",
        lambda: assert_equal(
            json_request(host, port, "GET", "/../../etc/passwd")[0],
            HTTPStatus.NOT_FOUND,
        ),
    )

    def injection_is_data() -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "executed"
            title = f"$(touch {marker})"
            status, payload = json_request(
                host,
                port,
                "POST",
                "/tasks",
                body=json.dumps({"title": title}).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert_equal(status, HTTPStatus.CREATED)
            assert_equal(task_payload(payload)["title"], title)
            assert_equal(marker.exists(), False)

    checks.check("injection_is_data", injection_is_data)
    checks.check(
        "runtime_dependencies",
        lambda: assert_equal(runtime_dependencies(candidate), []),
    )
    checks.check(
        "non_loopback_bind",
        lambda: _expect_exception(lambda: create_server("0.0.0.0", 0)),
    )

    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

    def socket_rebind() -> None:
        assert_equal(thread.is_alive(), False)
        replacement = create_server(host, port)
        replacement.server_close()

    checks.check("shutdown_and_rebind", socket_rebind)
    passed = sum(1 for result in checks.results if result["passed"])
    return {
        "schema": "corporate-site-locked-eval/v1",
        "candidate": str(candidate),
        "passed": passed,
        "total": len(checks.results),
        "ok": passed == len(checks.results),
        "duration_seconds": round(time.monotonic() - started, 6),
        "results": checks.results,
    }


def _expect_exception(action: Callable[[], Any]) -> None:
    try:
        action()
    except Exception:
        return
    raise AssertionError("expected operation to fail")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.candidate)
    except Exception as exc:
        result = {
            "schema": "corporate-site-locked-eval/v1",
            "candidate": str(args.candidate.resolve()),
            "passed": 0,
            "total": 1,
            "ok": False,
            "results": [{"name": "load_candidate", "passed": False, "error": str(exc)}],
        }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
