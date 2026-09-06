"""
Dependency checker module.
Checks whether required programs are installed and available in PATH.
"""
import subprocess
import shutil
import os
import platform
from config import REQUIRED_FOR_ALL, REQUIRED_FOR_CUDA, REQUIRED_FOR_VULKAN, REQUIRED_FOR_HIP, REQUIRED_FOR_SYCL


def check_command(name):
    """Check if a command is available in PATH."""
    return shutil.which(name) is not None


def get_command_version(name):
    """Try to get the version of a command."""
    cmd_map = {
        "git": ["git", "--version"],
        "cmake": ["cmake", "--version"],
        "ninja": ["ninja", "--version"],
        "python": ["python", "--version"],
        "gcc": ["gcc", "--version"],
        "g++": ["g++", "--version"],
        "clang": ["clang", "--version"],
        "nvcc": ["nvcc", "--version"],
    }
    cmd = cmd_map.get(name, [name, "--version"])
    out = run_cmd(cmd)
    if out:
        return out.split("\n")[0]
    return None


def run_cmd(cmd, timeout=15):
    """Run a command and return stdout or None."""
    try:
        result = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                text=True, timeout=timeout, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _vswhere_path():
    vswhere = shutil.which("vswhere")
    if vswhere:
        return vswhere
    candidate = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    return candidate if os.path.isfile(candidate) else None


def _vs_instance():
    """Return (display_name, install_path) of the newest VS with C++ x64 tools, or None."""
    vswhere = _vswhere_path()
    if not vswhere:
        return None
    try:
        result = subprocess.run(
            [vswhere, "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "displayName"],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            name = result.stdout.strip().splitlines()[0]
            path_result = subprocess.run(
                [vswhere, "-latest", "-products", "*",
                 "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationPath"],
                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), text=True, timeout=15
            )
            path = path_result.stdout.strip() if path_result.returncode == 0 else ""
            return name, path
    except Exception:
        pass
    return None


def check_compiler():
    """Check if a compiler is available."""
    system = platform.system()

    if system == "Windows":
        # Check MSVC in PATH first.
        cl_path = shutil.which("cl")
        if cl_path:
            return {"found": True, "name": "MSVC (cl)", "path": cl_path}

        # Otherwise ask vswhere whether the VC++ tools workload is actually
        # installed (vswhere.exe itself exists even without C++ tools, so its
        # mere presence is NOT proof of a usable compiler).
        inst = _vs_instance()
        if inst:
            return {"found": True,
                    "name": f"MSVC via {inst[0]}",
                    "path": inst[1] or "found via vswhere"}
        return {"found": False, "name": "MSVC", "path": None}
    else:
        # Check GCC
        gcc_path = shutil.which("gcc")
        if gcc_path:
            return {"found": True, "name": "GCC", "path": gcc_path}
        # Check Clang
        clang_path = shutil.which("clang")
        if clang_path:
            return {"found": True, "name": "Clang", "path": clang_path}
        return {"found": False, "name": "GCC/Clang", "path": None}


def check_cuda_toolkit():
    """Check if CUDA toolkit is installed (PATH, CUDA_PATH or default install dir)."""
    nvcc = shutil.which("nvcc")
    if nvcc:
        version = get_command_version("nvcc")
        return {"found": True, "name": "CUDA Toolkit", "version": version, "path": nvcc}
    candidates = []
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        candidates.append(os.path.join(cuda_path, "bin", "nvcc.exe"))
    base = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if os.path.isdir(base):
        def _ver(name):
            try:
                return tuple(int(p) for p in name.lstrip("v").split("."))
            except ValueError:
                return (0,)
        for ver in sorted(os.listdir(base), key=_ver, reverse=True):
            candidates.append(os.path.join(base, ver, "bin", "nvcc.exe"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            version = run_cmd([candidate, "--version"])
            version = version.split("\n")[-1] if version else None
            return {"found": True, "name": "CUDA Toolkit", "version": version, "path": candidate}
    return {"found": False, "name": "CUDA Toolkit", "version": None, "path": None}


def check_vulkan_sdk():
    """Check if Vulkan SDK is installed (not just the runtime driver).

    llama.cpp needs glslc (Vulkan::glslc); glslangValidator ships alongside it.
    """
    for tool in ("glslc", "glslangValidator"):
        found = shutil.which(tool)
        if found:
            return {"found": True, "name": "Vulkan SDK", "path": found}
    vulkan_sdk = os.environ.get("VULKAN_SDK", "")
    exe = ".exe" if platform.system() == "Windows" else ""
    bin_dirs = ["Bin", "bin"]
    if vulkan_sdk and os.path.isdir(vulkan_sdk):
        for bin_dir in bin_dirs:
            candidate = os.path.join(vulkan_sdk, bin_dir, "glslc" + exe)
            if os.path.isfile(candidate):
                return {"found": True, "name": "Vulkan SDK", "path": candidate}
    for check_path in [r"C:\VulkanSDK", r"C:\Program Files\VulkanSDK"]:
        if os.path.isdir(check_path):
            for ver in sorted(os.listdir(check_path), reverse=True):
                candidate = os.path.join(check_path, ver, "Bin", "glslc.exe")
                if os.path.isfile(candidate):
                    return {"found": True, "name": "Vulkan SDK", "path": candidate}
    return {"found": False, "name": "Vulkan SDK", "path": None}


def check_rocm_hip():
    """Check if ROCm/HIP is installed (PATH, HIP_PATH/ROCM_PATH or default dirs).

    Mirrors the resolution order of build_llamacpp.ps1 so the GUI and the
    build script agree on whether HIP is available.
    """
    hipcc = shutil.which("hipcc")
    if hipcc:
        return {"found": True, "name": "ROCm/HIP", "path": hipcc}
    candidates = []
    for var in ("HIP_PATH", "ROCM_PATH"):
        val = os.environ.get(var, "")
        if val:
            candidates.append(val.rstrip("\\/"))
    for base in (r"C:\Program Files\AMD\ROCm", r"C:\AMD\ROCm", "/opt/rocm"):
        if os.path.isdir(base):
            if os.path.isdir(os.path.join(base, "bin")):
                candidates.append(base)
            for sub in sorted(os.listdir(base), reverse=True):
                candidates.append(os.path.join(base, sub))
    for root in candidates:
        for name in ("clang.exe", "hipcc.exe", "hipcc", "clang"):
            candidate = os.path.join(root, "bin", name)
            if os.path.isfile(candidate):
                return {"found": True, "name": "ROCm/HIP", "path": candidate}
    return {"found": False, "name": "ROCm/HIP", "path": None}


def check_intel_oneapi():
    """Check if Intel oneAPI DPC++/C++ Compiler is installed."""
    # Check for icpx (Intel DPC++ compiler)
    icpx = shutil.which("icpx")
    if icpx:
        return {"found": True, "name": "Intel oneAPI DPC++", "path": icpx}

    # Check for icx (Intel C++ compiler)
    icx = shutil.which("icx")
    if icx:
        return {"found": True, "name": "Intel oneAPI C++", "path": icx}

    # Check common installation paths
    oneapi_paths = [
        r"C:\Program Files (x86)\Intel\oneAPI",
        r"C:\Program Files\Intel\oneAPI",
        "/opt/intel/oneapi",
        os.path.expanduser("~/intel/oneapi")
    ]

    for base_path in oneapi_paths:
        if os.path.isdir(base_path):
            # Look for compiler in common locations
            compiler_paths = [
                os.path.join(base_path, "compiler", "latest", "bin", "icpx"),
                os.path.join(base_path, "compiler", "latest", "bin", "icx"),
                os.path.join(base_path, "compiler", "latest", "bin", "icx.exe"),
                os.path.join(base_path, "compiler", "latest", "windows", "bin", "icx.exe"),
            ]
            for compiler_path in compiler_paths:
                if os.path.isfile(compiler_path):
                    return {"found": True, "name": "Intel oneAPI", "path": compiler_path}

    return {"found": False, "name": "Intel oneAPI DPC++/C++", "path": None}


def check_ninja():
    """Ninja from PATH or the copy bundled with Visual Studio's CMake tools."""
    found = shutil.which("ninja")
    if found:
        return {"found": True, "name": "ninja", "version": get_command_version("ninja"), "path": found}
    if platform.system() == "Windows":
        inst = _vs_instance()
        if inst and inst[1]:
            candidate = os.path.join(inst[1], "Common7", "IDE", "CommonExtensions", "Microsoft",
                                     "CMake", "Ninja", "ninja.exe")
            if os.path.isfile(candidate):
                return {"found": True, "name": "ninja", "version": run_cmd([candidate, "--version"]),
                        "path": candidate}
    return {"found": False, "name": "ninja", "version": None, "path": None}


def check_all():
    """Check all common dependencies and return a status dict."""
    results = {}

    for dep in ["git", "cmake", "python"]:
        results[dep] = {
            "found": check_command(dep),
            "name": dep,
            "version": get_command_version(dep) if check_command(dep) else None,
            "path": shutil.which(dep) if check_command(dep) else None
        }
    results["ninja"] = check_ninja()

    results["compiler"] = check_compiler()
    results["cuda_toolkit"] = check_cuda_toolkit()
    results["vulkan_sdk"] = check_vulkan_sdk()
    results["rocmmhip"] = check_rocm_hip()
    results["intel_oneapi"] = check_intel_oneapi()

    # Visual Studio Build Tools on Windows: the compiler check already asked
    # vswhere; do not shell out to winget (slow, may block on source agreements).
    system = platform.system()
    if system == "Windows":
        comp = results["compiler"]
        results["vs_build_tools"] = {
            "found": bool(comp.get("found")),
            "name": "Visual Studio Build Tools",
            "path": comp.get("path")
        }

    return results


def get_missing_for_build_type(check_results, build_type):
    """Return list of missing dependencies for a given build type."""
    missing = []

    # Always required
    for dep in REQUIRED_FOR_ALL:
        if dep == "compiler":
            if not check_results.get("compiler", {}).get("found", False):
                missing.append("compiler")
        else:
            if not check_results.get(dep, {}).get("found", False):
                missing.append(dep)

    if build_type == "CUDA":
        if not check_results.get("cuda_toolkit", {}).get("found", False):
            missing.append("cuda_toolkit")
    elif build_type == "Vulkan":
        if not check_results.get("vulkan_sdk", {}).get("found", False):
            missing.append("vulkan_sdk")
    elif build_type == "HIP":
        if not check_results.get("rocmmhip", {}).get("found", False):
            missing.append("rocmmhip")
        if not check_results.get("ninja", {}).get("found", False):
            missing.append("ninja")
    elif build_type == "SYCL":
        if not check_results.get("intel_oneapi", {}).get("found", False):
            missing.append("intel_oneapi")
        if not check_results.get("ninja", {}).get("found", False):
            missing.append("ninja")

    return missing


def get_missing_programs_text(missing):
    """Convert missing dependency list to human-readable text."""
    name_map = {
        "git": "Git",
        "cmake": "CMake",
        "ninja": "Ninja",
        "python": "Python",
        "compiler": "Compiler",
        "cuda_toolkit": "CUDA Toolkit",
        "vulkan_sdk": "Vulkan SDK",
        "rocmmhip": "ROCm/HIP",
        "intel_oneapi": "Intel oneAPI DPC++/C++",
        "vs_build_tools": "Visual Studio Build Tools"
    }
    return [name_map.get(m, m) for m in missing]


if __name__ == "__main__":
    results = check_all()
    for name, info in results.items():
        status = "OK" if info.get("found") else "MISSING"
        version = info.get("version", "") or info.get("path", "")
        print(f"  {name}: {status} {version}")
