"""
Build module.
Dispatches to the platform build script (build_llamacpp.ps1 on Windows,
build_llamacpp.sh elsewhere), streams its output, verifies the result and
trims the checkout to an Auto-Tuner-compatible layout.
"""
import subprocess
import os
import json
import stat
import time
import platform
from datetime import datetime
from config import (
    BUILDS_DIR, BUILD_HISTORY_FILE, BUNDLE_DIR, EXE_DIR, get_dir_suffix
)
from logger import log_build, log_error, log_warning
from source_manager import get_source_by_id


# Executables that make up a usable Auto-Tuner folder. Used when the
# "core tools only" option is selected (--target ... instead of everything).
CORE_TARGETS = ["llama-server", "llama-cli", "llama-bench", "llama-quantize"]

CPU_TARGETS = ("portable", "native")


def get_build_path(source_id, build_type):
    """Legacy flat output path (kept as fallback for history entries)."""
    source_name = source_id.replace("_", "-")
    return os.path.join(BUILDS_DIR, f"{source_name}-{build_type.lower()}")


def find_source_checkout(source_id, build_type=None):
    """Find the newest versioned checkout for a source (and backend) in BUILDS_DIR."""
    source = get_source_by_id(source_id) or {}
    suffix = get_dir_suffix(source)
    if not suffix or not os.path.isdir(BUILDS_DIR):
        return None
    backend = f"_{build_type.lower()}_" if build_type else "_"
    candidates = []
    for name in os.listdir(BUILDS_DIR):
        if not name.endswith("_" + suffix):
            continue
        if build_type and backend not in name:
            continue
        path = os.path.join(BUILDS_DIR, name)
        if os.path.isdir(path):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _on_rm_error(func, path, exc_info):
    # Git marks object files read-only on Windows; clear the bit and retry.
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _remove_with_retry(path, attempts=10, delay=2.0):
    """Remove a file or directory tree, retrying while files are still locked
    (MSBuild nodes, antivirus scanners) right after a build."""
    import shutil
    for _ in range(attempts):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, onerror=_on_rm_error)
            else:
                try:
                    os.remove(path)
                except PermissionError:
                    os.chmod(path, stat.S_IWRITE)
                    os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except Exception:
            time.sleep(delay)
    return False


def trim_build_folder(checkout_dir):
    """Keep only build/bin inside the checkout (the Auto-Tuner-compatible
    layout holding llama-server) and remove the source tree plus all other
    CMake artifacts."""
    build_dir = os.path.join(checkout_dir, "build")
    if os.path.isdir(build_dir):
        for name in os.listdir(build_dir):
            if name.lower() == "bin":
                continue
            _remove_with_retry(os.path.join(build_dir, name))
    for name in os.listdir(checkout_dir):
        if name.lower() == "build":
            continue
        _remove_with_retry(os.path.join(checkout_dir, name))


def _run_binary(exe, args, timeout=90):
    """Run a built executable and return (returncode, combined output)."""
    try:
        result = subprocess.run(
            [exe] + args, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace", cwd=os.path.dirname(exe))
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    except Exception as e:
        return -1, str(e)


# Device-list prefix llama-server prints for each backend.
_BACKEND_DEVICE_PREFIX = {
    "CUDA": "CUDA",
    "HIP": "ROCm",
    "Vulkan": "Vulkan",
    "SYCL": "SYCL",
    "Metal": "Metal",
}


def verify_build(binaries, build_type, callback=None):
    """Smoke-test the fresh build: --version and --list-devices of llama-server.

    Returns a dict with "ok", "version", "devices" and "warnings". Problems
    are reported as warnings; the caller decides whether to fail the build.
    """
    result = {"ok": True, "version": "", "devices": [], "warnings": []}
    server = next((b for b in binaries if os.path.basename(b).lower().startswith("llama-server")), None)
    if not server:
        result["ok"] = False
        result["warnings"].append("llama-server was not built (LLAMA_BUILD_SERVER=ON missing?)")
        return result

    def say(msg):
        if callback:
            callback(msg)

    code, out = _run_binary(server, ["--version"], timeout=60)
    if code != 0:
        result["ok"] = False
        result["warnings"].append(f"llama-server --version failed (exit {code}): {out.strip()[-300:]}")
        return result
    version_line = next((l.strip() for l in out.splitlines() if "version" in l.lower() or "build" in l.lower()), out.strip())
    result["version"] = version_line
    say(f"  llama-server: {version_line}")

    code, out = _run_binary(server, ["--list-devices"], timeout=120)
    if code != 0:
        result["warnings"].append(f"llama-server --list-devices failed (exit {code}): {out.strip()[-300:]}")
        return result
    devices = [l.strip() for l in out.splitlines()
               if l.strip() and ":" in l and not l.lower().startswith("available")]
    result["devices"] = devices
    for d in devices:
        say(f"  device: {d}")

    prefix = _BACKEND_DEVICE_PREFIX.get(build_type)
    if prefix and not any(d.startswith(prefix) for d in devices):
        result["warnings"].append(
            f"No {prefix} device reported by the {build_type} build. The backend was "
            f"not compiled in, or its runtime/driver is missing.")
    if build_type == "CPU" and devices:
        result["warnings"].append("CPU build unexpectedly reports GPU devices: " + "; ".join(devices))
    return result


def run_build(source_id, build_type, update_repo_flag=False,
              custom_flags=None, clean_build=False, callback=None,
              build_ui=False, cpu_target="portable", jobs=None,
              core_only=False, cuda_major=""):
    """
    Run the full build process using the platform build script.
    Windows uses build_llamacpp.ps1 (PowerShell); macOS/Linux use
    build_llamacpp.sh. Returns (success, output_lines, error_message,
    binaries, build_path). callback(line) is called for each output line.

    cpu_target: "portable" (AVX2/FMA/F16C, runs on any x86-64-v3 CPU) or
                "native" (GGML_NATIVE=ON, tuned for this machine only).
    jobs:       parallel compile jobs (None = CPU count).
    core_only:  build only CORE_TARGETS instead of every example/tool.
    cuda_major: "12" / "13" to pin the CUDA toolkit generation, "" = newest.

    After a successful build the checkout is trimmed to an Auto-Tuner-
    compatible layout: builds/<bNNNN>_<backend>_<suffix>/build/bin/...
    keeps the finished llama-server while the source tree and all other
    CMake artifacts are deleted.
    """
    import sys
    import io

    # Windowed/frozen builds do not always have stdout/stderr streams.
    if sys.stdout is not None and sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

    source = get_source_by_id(source_id)
    if not source:
        msg = f"Source '{source_id}' not found."
        if callback:
            callback(msg)
        return False, [msg], msg, [], ""

    system = platform.system()
    if cpu_target not in CPU_TARGETS:
        cpu_target = "portable"
    try:
        jobs = int(jobs) if jobs else 0
    except (TypeError, ValueError):
        jobs = 0
    if jobs <= 0:
        jobs = os.cpu_count() or 4

    # Custom CMake flags are passed as a newline-joined string so that flags
    # may contain spaces (e.g. -DCMAKE_PREFIX_PATH=...) without quoting issues.
    flags_str = "\n".join(custom_flags) if custom_flags else ""
    targets_str = ",".join(CORE_TARGETS) if core_only else ""
    dir_suffix = get_dir_suffix(source)

    # Final output folder for the finished binaries (legacy fallback).
    build_path = get_build_path(source_id, build_type)

    if system == "Windows":
        script_path = os.path.join(BUNDLE_DIR, "build_llamacpp.ps1")
        if not os.path.exists(script_path):
            msg = f"Build script not found: {script_path}"
            if callback:
                callback(msg)
            return False, [msg], msg, [], ""
        # Use -File (not -Command) so args are bound cleanly and there are no
        # quoting headaches around -ExtraFlags / build paths.
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path,
               "-Source", source_id, "-BuildType", build_type,
               "-InstallDir", BUILDS_DIR,
               "-DepsDir", os.path.join(EXE_DIR, "deps"),
               "-DirSuffix", dir_suffix,
               "-CpuTarget", cpu_target,
               "-ParallelJobs", str(jobs)]
        if source.get("repo_url"):
            cmd += ["-RepoUrl", source.get("repo_url")]
        if source.get("branch"):
            cmd += ["-RepoBranch", source.get("branch")]
        if source.get("commit"):
            cmd += ["-SourceCommit", source.get("commit")]
        if source.get("fetch_ref"):
            cmd += ["-FetchRef", source.get("fetch_ref")]
        if source.get("pr"):
            cmd += ["-RepoPr", str(source.get("pr"))]
        if source.get("submodules"):
            cmd.append("-RepoSubmodules")
        if cuda_major:
            cmd += ["-CudaMajor", str(cuda_major)]
        if targets_str:
            cmd += ["-Targets", targets_str]
        if update_repo_flag:
            cmd.append("-Update")
        if clean_build:
            cmd.append("-CleanBuild")
        if build_ui:
            cmd.append("-BuildUi")
        if flags_str:
            cmd += ["-ExtraFlags", flags_str]
    else:
        script_path = os.path.join(BUNDLE_DIR, "build_llamacpp.sh")
        if not os.path.exists(script_path):
            msg = f"Build script not found: {script_path}"
            if callback:
                callback(msg)
            return False, [msg], msg, [], ""
        cmd = ["bash", script_path, "-s", source_id, "-t", build_type, "-d", BUILDS_DIR,
               "-o", dir_suffix, "-C", cpu_target, "-j", str(jobs)]
        if source.get("repo_url"):
            cmd += ["-r", source.get("repo_url")]
        if source.get("branch"):
            cmd += ["-b", source.get("branch")]
        if source.get("commit"):
            cmd += ["-x", source.get("commit")]
        if source.get("fetch_ref"):
            cmd += ["-f", source.get("fetch_ref")]
        if source.get("pr"):
            cmd += ["-p", str(source.get("pr"))]
        if source.get("submodules"):
            cmd.append("-m")
        if cuda_major:
            cmd += ["-V", str(cuda_major)]
        if targets_str:
            cmd += ["-T", targets_str]
        if update_repo_flag:
            cmd.append("-U")
        if clean_build:
            cmd.append("-c")
        if build_ui:
            cmd.append("-u")
        if flags_str:
            cmd += ["-F", flags_str]

    if callback:
        callback("=" * 60)
        callback(f"Starting build ({system})")
        callback(f"  Source: {source_id}")
        callback(f"  Build Type: {build_type}")
        callback(f"  CPU target: {cpu_target}  Jobs: {jobs}"
                 + (f"  Targets: {targets_str}" if targets_str else "")
                 + (f"  CUDA: {cuda_major}.x" if cuda_major else ""))
        callback(f"  Script: {script_path}")
        callback("=" * 60)

    try:
        # The build script switches its console to UTF-8; native tools that
        # still emit the OEM code page are decoded with replacement characters
        # instead of aborting the whole build (latin-1 produced mojibake).
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace"
        )

        all_output = []
        for line in process.stdout:
            line = line.rstrip('\n\r')
            all_output.append(line)
            if callback:
                callback(line)

        process.wait()

        if process.returncode != 0:
            msg = f"Build failed with exit code {process.returncode}"
            if callback:
                callback(msg)
            return False, all_output, msg, [], ""

        # One Auto-Tuner-compatible folder per build: <checkout>/build/bin/...
        # holds the finished llama-server. Source tree and CMake artifacts
        # are removed afterwards.
        checkout_dir = find_source_checkout(source_id, build_type)
        cmake_dir = os.path.join(checkout_dir, "build") if checkout_dir else None
        binaries = find_binaries(cmake_dir) if cmake_dir else []
        if not binaries:
            # Fallback for unexpected layouts: keep whatever is in build_path.
            binaries = find_binaries(build_path)
        if not binaries:
            msg = ("The build script reported success but no llama-* executables were "
                   f"found under {cmake_dir or build_path}.")
            if callback:
                callback(msg)
            return False, all_output, msg, [], checkout_dir or ""

        if callback:
            callback("-" * 60)
            callback("Verifying build output")
        verification = verify_build(binaries, build_type, callback)
        for warning in verification["warnings"]:
            log_warning(warning)
            if callback:
                callback(f"WARNING: {warning}")

        if checkout_dir and os.path.isdir(checkout_dir):
            if callback:
                callback(f"Cleaning up source/CMake files in: {checkout_dir}")
            trim_build_folder(checkout_dir)
            build_path = checkout_dir

        if callback:
            callback("=" * 60)
            callback("BUILD SUCCESSFUL!")
            callback(f"Output: {build_path}")
            callback(f"Binaries found: {len(binaries)}")

        return True, all_output, None, binaries, build_path

    except Exception as e:
        msg = f"Build error: {str(e)}"
        if callback:
            callback(msg)
        return False, [msg], msg, [], ""


_BINARY_SKIP_SUFFIXES = (
    ".pdb", ".lib", ".dll", ".ilk", ".exp", ".obj", ".o", ".a",
    ".so", ".dylib", ".manifest", ".recipe",
)


def find_binaries(build_path):
    """Find built executables in the build directory (under bin/)."""
    binaries = []
    if not build_path or not os.path.isdir(build_path):
        return binaries

    for root, dirs, files in os.walk(build_path):
        parts = os.path.normpath(root).lower().split(os.sep)
        if "bin" not in parts:
            continue
        for f in files:
            if not f.startswith("llama-"):
                continue
            if f.lower().endswith(_BINARY_SKIP_SUFFIXES):
                continue
            binaries.append(os.path.join(root, f))

    return binaries


def save_build_result(source_id, build_type, success, build_path,
                      binaries=None, duration=None, error_message=None):
    """Save build result to build_history.json."""
    source = get_source_by_id(source_id) if source_id else None

    entry = {
        "date": datetime.now().isoformat(),
        "source": source_id,
        "source_name": source.get("name", "unknown") if source else "unknown",
        "build_type": build_type,
        "success": success,
        "build_path": build_path,
        "duration_seconds": duration or 0,
        "error_message": error_message or ""
    }

    if binaries:
        entry["binaries"] = binaries

    if source:
        entry["repo_url"] = source.get("repo_url", "")
        entry["branch"] = source.get("branch", "")

    # Load existing history
    history = []
    if os.path.exists(BUILD_HISTORY_FILE):
        try:
            with open(BUILD_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append(entry)

    # Keep last 100 entries
    history = history[-100:]

    with open(BUILD_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    return entry


def get_build_history():
    """Load build history."""
    if not os.path.exists(BUILD_HISTORY_FILE):
        return []
    try:
        with open(BUILD_HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def extract_error_lines(output_lines, limit=15):
    """Return the last compiler/CMake error lines from a build log."""
    hits = []
    for line in output_lines or []:
        low = line.lower()
        if ("error" in low and "0 error" not in low and "-werror" not in low) or "fatal" in low:
            if low.strip().startswith("warning"):
                continue
            hits.append(line.strip())
    return hits[-limit:]


def get_error_explanation(error_message, output_lines=None):
    """Provide a human-readable explanation for common errors.

    Matching runs over the error message and the collected build output, so
    the explanation reflects what the compiler or CMake actually complained
    about, not only the generic "exit code 1" summary.
    """
    text = (error_message or "")
    if output_lines:
        text += "\n" + "\n".join(output_lines[-400:])
    error_lower = text.lower()

    def has(*needles):
        return all(n in error_lower for n in needles)

    if has("cmake") and (has("not found") or has("not recognized")) and not has("cmake error"):
        return {
            "cause": "CMake not found or not in PATH",
            "solution": "Install CMake and restart the application.",
            "fallback": "Install CMake via winget or package manager."
        }
    if has("__clang_hip_cmath.h") or has("cannot overload __host__ __device__"):
        return {
            "cause": "HIP SDK clang headers clash with the installed MSVC <cmath> (LLVM PR #201563)",
            "solution": "Update the build script (v2.3.0 applies a workspace-local header fix automatically) "
                        "or use an older MSVC toolset / newer HIP SDK.",
            "fallback": "Use the Vulkan build for AMD GPUs."
        }
    if has("cuda driver version is insufficient") or has("cudaerrorinsufficientdriver"):
        return {
            "cause": "The NVIDIA driver is older than the CUDA toolkit used for the build",
            "solution": "Update the NVIDIA driver or pick the CUDA 12.x profile.",
            "fallback": "Use the Vulkan build."
        }
    if has("cuda") and (has("not found") or has("no cuda toolset") or has("nvcc")) and has("error"):
        return {
            "cause": "CUDA Toolkit/compiler not found or its Visual Studio integration is missing",
            "solution": "Install the CUDA Toolkit (with Visual Studio integration) or choose CPU/Vulkan build.",
            "fallback": "Use main llama.cpp CPU build."
        }
    if has("sycl") and has("error") or has("icpx") or has("oneapi") and has("not found"):
        return {
            "cause": "Intel oneAPI DPC++/C++ Compiler not found",
            "solution": "Install Intel oneAPI Base Toolkit or choose CPU/Vulkan build.",
            "fallback": "Use main llama.cpp CPU build."
        }
    if has("git") and (has("not found") or has("not recognized")) and not has("git clone"):
        return {
            "cause": "Git not found or not in PATH",
            "solution": "Install Git and restart the application.",
            "fallback": "Install Git via winget or package manager."
        }
    if has("glslc") and (has("not found") or has("could not find")) or has("vulkan sdk not found"):
        return {
            "cause": "Vulkan SDK (glslc shader compiler) not found",
            "solution": "Install the LunarG Vulkan SDK and restart the application.",
            "fallback": "Use the CPU build."
        }
    if has("cl.exe") and has("not found") or has("msvc") and has("not found") or has("no cmake_c_compiler could be found"):
        return {
            "cause": "Visual Studio Build Tools (MSVC) not found",
            "solution": "Install Visual Studio Build Tools 2022 with the C++ workload.",
            "fallback": "Install via winget: Microsoft.VisualStudio.2022.BuildTools"
        }
    if has("ninja") and (has("not found") or has("not recognized")):
        return {
            "cause": "Ninja not found",
            "solution": "Install Ninja (winget install Ninja-build.Ninja) or the Visual Studio CMake tools.",
            "fallback": "Install via winget or package manager."
        }
    if has("no space left") or has("not enough space") or has("disk full"):
        return {
            "cause": "Not enough free disk space",
            "solution": "Free up disk space and try again.",
            "fallback": "Ensure at least 10 GB free space."
        }
    if has("generator") and has("could not create") or has("cmake") and has("does not support"):
        return {
            "cause": "CMake is too old for the installed Visual Studio (e.g. VS 2026 needs CMake 4.1+)",
            "solution": "Update CMake (winget upgrade Kitware.CMake).",
            "fallback": "Install an older Visual Studio Build Tools version."
        }
    if has("configuring incomplete") or has("configuration failed"):
        return {
            "cause": "CMake configuration failed",
            "solution": "See the error lines above (missing dependencies, compiler mismatch, wrong CMake flags).",
            "fallback": "Try the CPU build first, or check llama.cpp documentation for requirements."
        }
    if has("build failed") or has("compilation failed") or has("error c") or has("error:"):
        return {
            "cause": "Compilation failed",
            "solution": "See the last error lines above; usually a compiler/toolkit version mismatch.",
            "fallback": "Try main llama.cpp with a CPU build."
        }
    if has("remote branch") and has("not found") or has("couldn't find remote ref"):
        return {
            "cause": "Specified branch or ref not found in repository",
            "solution": "Check the branch name in the Sources tab.",
            "fallback": "Use the 'master' branch."
        }

    return {
        "cause": "Unknown error",
        "solution": "Check the build log for details.",
        "fallback": "Try main llama.cpp CPU build."
    }


if __name__ == "__main__":
    print("Build module loaded.")
