import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int | None
    message: str


def _definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            definitions[node.target.id] = node.value
    return definitions


def _as_view_call(node: ast.AST) -> ast.Call | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "as_view"
    ):
        return node
    return None


def _resolve_definition(
    name: str,
    definitions: dict[str, ast.AST],
    source_path: str,
    visited: set[str] | None = None,
) -> tuple[str, str, int | None]:
    visited = set() if visited is None else visited
    if name in visited or name not in definitions:
        return "unresolved", source_path, None
    visited.add(name)
    definition = definitions[name]
    if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function", source_path, definition.lineno
    if isinstance(definition, ast.Name):
        return _resolve_definition(
            definition.id,
            definitions,
            source_path,
            visited,
        )
    if call := _as_view_call(definition):
        return "class", source_path, call.lineno
    return "unresolved", source_path, getattr(definition, "lineno", None)


def _route_imports(
    tree: ast.Module,
) -> tuple[set[str], set[str], dict[str, str]]:
    path_names: set[str] = set()
    view_modules: set[str] = set()
    view_imports: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "django.urls":
                path_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "path"
                )
            elif module == "crm.views" or (node.level == 1 and module == "views"):
                view_imports.update(
                    {alias.asname or alias.name: alias.name for alias in node.names}
                )
            elif module == "crm" or (node.level == 1 and not module):
                view_modules.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "views"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "crm.views" and alias.asname:
                    view_modules.add(alias.asname)
    return path_names, view_modules, view_imports


def _resolve_route_target(
    target: ast.AST | None,
    *,
    route_definitions: dict[str, ast.AST],
    view_definitions: dict[str, ast.AST],
    view_modules: set[str],
    view_imports: dict[str, str],
) -> tuple[str, str, int | None]:
    if target is None:
        return "unresolved", "app/crm/urls.py", None
    if call := _as_view_call(target):
        return "class", "app/crm/urls.py", call.lineno
    if isinstance(target, ast.Name):
        if target.id in view_imports:
            return _resolve_definition(
                view_imports[target.id],
                view_definitions,
                "app/crm/views.py",
            )
        return _resolve_definition(
            target.id,
            route_definitions,
            "app/crm/urls.py",
        )
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id in view_modules
    ):
        return _resolve_definition(
            target.attr,
            view_definitions,
            "app/crm/views.py",
        )
    return "unresolved", "app/crm/urls.py", getattr(target, "lineno", None)


def diagnose(workspace: Path) -> list[Finding]:
    findings: list[Finding] = []
    app = workspace / "app" / "crm"
    domain = app / "domain.py"
    if domain.exists():
        tree = ast.parse(domain.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "django" or name.startswith("django.") for name in names):
                findings.append(
                    Finding(
                        "DOMAIN_DJANGO_IMPORT",
                        "app/crm/domain.py",
                        node.lineno,
                        "Domain module imports Django directly.",
                    )
                )

    urls = app / "urls.py"
    if urls.exists():
        route_tree = ast.parse(urls.read_text())
        view_file = app / "views.py"
        view_tree = ast.parse(view_file.read_text()) if view_file.exists() else None
        route_definitions = _definitions(route_tree)
        view_definitions = _definitions(view_tree) if view_tree else {}
        path_names, view_modules, view_imports = _route_imports(route_tree)
        path_calls = [
            node
            for node in ast.walk(route_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in path_names
        ]
        if not path_calls:
            findings.append(
                Finding(
                    "ROUTE_INCONCLUSIVE",
                    "app/crm/urls.py",
                    None,
                    "Route registrations are dynamic or unsupported.",
                )
            )
        for node in path_calls:
            target = node.args[1] if len(node.args) > 1 else None
            kind, source_path, line = _resolve_route_target(
                target,
                route_definitions=route_definitions,
                view_definitions=view_definitions,
                view_modules=view_modules,
                view_imports=view_imports,
            )
            if kind == "class":
                findings.append(
                    Finding(
                        "CLASS_BASED_VIEW",
                        source_path,
                        line or node.lineno,
                        "Route registers a class-based view.",
                    )
                )
            elif kind == "unresolved":
                findings.append(
                    Finding(
                        "ROUTE_INCONCLUSIVE",
                        "app/crm/urls.py",
                        node.lineno,
                        "Dynamic route registration could not be resolved.",
                    )
                )
    return findings
