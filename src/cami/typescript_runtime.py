"""Install the pinned compiler outside the package and target repository."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path


class TypeScriptSetupError(RuntimeError):
    pass


def sidecar_directory() -> Path:
    return Path(__file__).resolve().parent / "_typescript"


def clean_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key.upper() not in ("NODE_OPTIONS", "NODE_PATH")}


def manifest_fingerprint() -> str:
    directory = sidecar_directory()
    return hashlib.sha256(b"\0".join((directory / name).read_bytes()
                                   for name in ("package.json", "package-lock.json"))).hexdigest()


def runtime_directory() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base.resolve() / "cami" / "typescript" / ("6.0.3-" + manifest_fingerprint())


def compiler_path() -> Path:
    return runtime_directory() / "node_modules" / "typescript" / "lib" / "typescript.js"


def runtime_identity() -> dict[str, str | None]:
    compiler = compiler_path()
    node = shutil.which("node")
    identity: dict[str, str | None] = {
        "manifest": manifest_fingerprint(), "node": node,
        "compiler": (hashlib.sha256(compiler.read_bytes()).hexdigest()
                     if trusted_compiler(compiler) else None),
        "node_version": None,
    }
    if node:
        try:
            identity["node_version"] = _command([node, "--version"], sidecar_directory())
        except TypeScriptSetupError as error:
            identity["node_version"] = str(error)
    return identity


def _command(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, env=clean_environment(), capture_output=True,
                                text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TypeScriptSetupError(f"Cannot run {args[0]}: {error}") from error
    if result.returncode:
        raise TypeScriptSetupError(f"{args[0]} failed: {result.stderr.strip()[:4096]}")
    return result.stdout.strip()


def _owned_file(directory: Path, relative: str) -> Path:
    current = Path(directory.anchor)
    for part in directory.parts[1:]:
        current /= part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise TypeScriptSetupError(f"Untrusted compiler cache ancestor: {current}")
    current = directory
    parts = ("", *relative.split("/"))
    for index, part in enumerate(parts):
        current = current / part
        info = current.lstat()
        expected = stat.S_ISREG if index == len(parts) - 1 else stat.S_ISDIR
        if info.st_uid != os.geteuid() or not expected(info.st_mode):
            raise TypeScriptSetupError(f"Untrusted compiler cache path: {current}")
    return current


def trusted_compiler(compiler: Path) -> bool:
    if len(compiler.parents) < 4:
        return False
    directory = compiler.parents[3]
    try:
        ready: object = json.loads(_owned_file(directory, "ready.json").read_text())
        for name in ("package.json", "package-lock.json"):
            if _owned_file(directory, name).read_bytes() != (sidecar_directory() / name).read_bytes():
                return False
        checked = _owned_file(directory, "node_modules/typescript/lib/typescript.js")
        return ready == {"compiler": "6.0.3", "manifest": manifest_fingerprint(),
                         "sha256": hashlib.sha256(checked.read_bytes()).hexdigest()}
    except (OSError, ValueError, TypeScriptSetupError):
        return False


def _usable(directory: Path) -> bool:
    if not trusted_compiler(directory / "node_modules/typescript/lib/typescript.js"):
        return False
    try:
        _verify(directory)
        return True
    except (OSError, TypeScriptSetupError):
        return False


def _prepare_parent(parent: Path) -> None:
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise TypeScriptSetupError(f"Compiler cache ancestor is not a directory: {current}")
    if parent.stat().st_uid != os.geteuid():
        raise TypeScriptSetupError(f"Compiler cache is not owned by this user: {parent}")


def setup_typescript() -> Path:
    import fcntl

    directory = sidecar_directory()
    node_version = _command(["node", "--version"], directory)
    npm_version = _command(["npm", "--version"], directory)
    if not node_version.startswith("v24.") or not npm_version.startswith("11."):
        raise TypeScriptSetupError("cami setup-typescript requires Node.js 24 and npm 11")
    destination = runtime_directory()
    try:
        _prepare_parent(destination.parent)
        lock = os.open(destination.parent / (destination.name + ".lock"),
                       os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                raise TypeScriptSetupError("Compiler setup lock is not an owned regular file")
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _setup_locked(directory, destination)
        finally:
            os.close(lock)
    except OSError as error:
        raise TypeScriptSetupError(f"Cannot publish TypeScript compiler cache: {error}") from error


def _setup_locked(directory: Path, destination: Path) -> Path:
    if _usable(destination):
        return destination
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination.parent))
    try:
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(directory / name, temporary / name)
        _command(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], temporary)
        _verify(temporary)
        compiler = _owned_file(temporary, "node_modules/typescript/lib/typescript.js")
        (temporary / "ready.json").write_text(json.dumps({"compiler": "6.0.3",
            "manifest": manifest_fingerprint(), "sha256": hashlib.sha256(compiler.read_bytes()).hexdigest()}))
        quarantine = None
        if destination.exists() or destination.is_symlink():
            if destination.lstat().st_uid != os.geteuid():
                raise TypeScriptSetupError("Cannot replace a compiler cache owned by another user")
            quarantine = destination.with_name(".invalid-" + uuid.uuid4().hex)
            os.rename(destination, quarantine)
        try:
            os.rename(temporary, destination)
        except OSError:
            if quarantine is not None:
                os.rename(quarantine, destination)
            raise
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _verify(directory: Path) -> None:
    compiler = _owned_file(directory, "node_modules/typescript/lib/typescript.js")
    version = _command(["node", "--no-addons", "--no-global-search-paths", "-e",
                        "process.stdout.write(require(process.argv[1]).version)", str(compiler)],
                       sidecar_directory())
    if version != "6.0.3":
        raise TypeScriptSetupError(f"Expected TypeScript 6.0.3, received {version}")
