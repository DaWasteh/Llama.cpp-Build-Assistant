"""
Global configuration for the Llama.cpp Build Assistant.
All paths, URLs, and default settings are defined here.
"""
import os
import json
import sys

# Directory containing the running executable (never depends on the current
# working directory). For frozen builds this is the folder with the .exe,
# for source runs it is the project directory.
_exe_path = getattr(sys, "executable", None) or sys.argv[0]
EXE_DIR = os.path.dirname(os.path.abspath(_exe_path))

# Root directory of the project
if getattr(sys, "frozen", False):
    BUNDLE_DIR = getattr(sys, "_MEIPASS", EXE_DIR)
    if sys.platform == "win32":
        user_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))
    elif sys.platform == "darwin":
        user_data = os.path.expanduser("~/Library/Application Support")
    else:
        user_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    ROOT_DIR = os.path.join(user_data, "Llama.cpp-Build-Assistant")
else:
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = ROOT_DIR
    EXE_DIR = ROOT_DIR

# Subdirectories
REPOS_DIR = os.path.join(ROOT_DIR, "repos")
BUILDS_DIR = os.path.join(EXE_DIR, "builds")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
DATA_DIR = os.path.join(ROOT_DIR, "data")

# Ensure directories exist
for d in [REPOS_DIR, BUILDS_DIR, LOGS_DIR, DATA_DIR]:
    os.makedirs(d, exist_ok=True)

# Data files
SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
LEGACY_BUILD_SOURCES_FILE = os.path.join(DATA_DIR, "build_sources.json")
BUILD_SOURCES_FILE = SOURCES_FILE
BUILD_HISTORY_FILE = os.path.join(DATA_DIR, "build_history.json")
SYSTEM_REPORT_FILE = os.path.join(DATA_DIR, "system_report.json")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")

# Log files
BUILD_LOG_FILE = os.path.join(LOGS_DIR, "build.log")
INSTALL_LOG_FILE = os.path.join(LOGS_DIR, "install.log")
ERROR_LOG_FILE = os.path.join(LOGS_DIR, "error.log")

# Default build sources
DEFAULT_BUILD_SOURCES = [
    {
        "id": "main",
        "name": "llama.cpp mainline",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "local_path": os.path.join(REPOS_DIR, "llama.cpp-main"),
        "type": "official",
        "experimental": False,
        "default_cmake_flags": []
    },
    {
        "id": "turboquant",
        "name": "TurboQuant KV-cache",
        "repo_url": "https://github.com/TheTom/llama-cpp-turboquant",
        "branch": "master",
        "commit": "df7f5472949ce37cdc6a2155ef6b8836a8c10bac",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-turboquant"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "ternary_bonsai",
        "name": "PrismML Ternary/Bonsai",
        "repo_url": "https://github.com/PrismML-Eng/llama.cpp",
        "branch": "prism",
        "commit": "e311ed38fe7ab8fb577a5435b049d48b7d040923",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-prismml-ternary"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "ocr_llama",
        "name": "OCR llama.cpp",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "pr": 17400,
        "fetch_ref": "pull/17400/head",
        "commit": "95cc5665859b49d7158c5c4abc9943adf109c6d5",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-ocr"),
        "type": "pr",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "diffusion_gemma",
        "name": "Diffusion-Gemma PR #24427",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "pr": 24427,
        "fetch_ref": "pull/24427/head",
        "commit": "dd0cf04459b0c4f43aa6667dbc0879ac0cd50323",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-diffusion-gemma"),
        "type": "pr",
        "experimental": True,
        "default_cmake_flags": []
    }
]

# Default build profiles
DEFAULT_BUILD_PROFILES = [
    {
        "name": "CPU",
        "build_type": "CPU",
        "cmake_flags": [
            "-DGGML_NATIVE=OFF",
            "-DGGML_AVX2=ON",
            "-DGGML_AVX_VNNI=ON",
            "-DGGML_BMI2=ON",
            "-DGGML_AVX512=OFF",
            "-DGGML_AVX512_VBMI=OFF",
            "-DGGML_AVX512_VNNI=OFF",
            "-DGGML_AVX512_BF16=OFF",
            "-DGGML_LTO=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_BUILD_TESTS=OFF",
            "-DLLAMA_BUILD_TOOLS=ON",
            "-DLLAMA_BUILD_EXAMPLES=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "CUDA NVIDIA",
        "build_type": "CUDA",
        "cmake_flags": [
            "-DLLAMA_BUILD_IS_DEV=ON",
            "-DGGML_CUDA=ON",
            "-DGGML_VULKAN=OFF",
            "-DGGML_NATIVE=OFF",
            "-DGGML_AVX2=ON",
            "-DGGML_FMA=ON",
            "-DGGML_F16C=ON",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_BUILD_UI=ON",
            "-DLLAMA_USE_PREBUILT_UI=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": True
    },
    {
        "name": "Vulkan",
        "build_type": "Vulkan",
        "cmake_flags": [
            "-DGGML_VULKAN=ON",
            "-DGGML_HIP=OFF",
            "-DGGML_NATIVE=OFF",
            "-DGGML_AVX2=ON",
            "-DGGML_AVX_VNNI=ON",
            "-DGGML_BMI2=ON",
            "-DGGML_AVX512=OFF",
            "-DGGML_AVX512_VBMI=OFF",
            "-DGGML_AVX512_VNNI=OFF",
            "-DGGML_AVX512_BF16=OFF",
            "-DGGML_LTO=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_BUILD_TESTS=OFF",
            "-DLLAMA_BUILD_TOOLS=ON",
            "-DLLAMA_BUILD_EXAMPLES=ON",
            "-DLLAMA_BUILD_UI=ON",
            "-DLLAMA_USE_PREBUILT_UI=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF",
            "-DGGML_VULKAN_CHECK_RESULTS=OFF",
            "-DGGML_VULKAN_DEBUG=OFF",
            "-DGGML_VULKAN_MEMORY_DEBUG=OFF",
            "-DGGML_VULKAN_SHADER_DEBUG_INFO=OFF",
            "-DGGML_VULKAN_VALIDATE=OFF",
            "-DGGML_VULKAN_RUN_TESTS=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "HIP ROCm AMD",
        "build_type": "HIP",
        "cmake_flags": [
            "-DGGML_HIP=ON",
            "-DGGML_VULKAN=OFF",
            "-DGPU_TARGETS=gfx1201",
            "-DGGML_HIP_GRAPHS=ON",
            "-DGGML_HIP_NO_VMM=ON",
            "-DGGML_HIP_RCCL=OFF",
            "-DGGML_CUDA_NO_PEER_COPY=ON",
            "-DGGML_CUDA_FA=ON",
            "-DGGML_CUDA_FA_ALL_QUANTS=ON",
            "-DGGML_FMA=ON",
            "-DGGML_F16C=ON",
            "-DGGML_NATIVE=OFF",
            "-DGGML_AVX2=ON",
            "-DGGML_AVX_VNNI=ON",
            "-DGGML_BMI2=ON",
            "-DGGML_AVX512=OFF",
            "-DGGML_AVX512_VBMI=OFF",
            "-DGGML_AVX512_VNNI=OFF",
            "-DGGML_AVX512_BF16=OFF",
            "-DGGML_LTO=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_BUILD_TESTS=OFF",
            "-DLLAMA_BUILD_TOOLS=ON",
            "-DLLAMA_BUILD_EXAMPLES=ON",
            "-DLLAMA_BUILD_UI=ON",
            "-DLLAMA_USE_PREBUILT_UI=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "SYCL Intel GPU",
        "build_type": "SYCL",
        "cmake_flags": [
            "-DGGML_SYCL=ON",
            "-DGGML_SYCL_F16=ON",
            "-DGGML_NATIVE=ON",
            "-DBUILD_SHARED_LIBS=ON",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "Metal macOS",
        "build_type": "Metal",
        "cmake_flags": [
            "-DGGML_METAL=ON",
            "-DGGML_METAL_EMBED_LIBRARY=ON",
            "-DGGML_CUDA=OFF",
            "-DGGML_VULKAN=OFF",
            "-DBUILD_SHARED_LIBS=ON",
            "-DLLAMA_BUILD_SERVER=ON",
            "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF"
        ],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    }
]

# Required programs for building
REQUIRED_FOR_ALL = ["git", "cmake", "compiler"]
REQUIRED_FOR_CUDA = ["cuda_toolkit"]
REQUIRED_FOR_VULKAN = ["vulkan_sdk"]
REQUIRED_FOR_HIP = ["rocmmhip"]
REQUIRED_FOR_SYCL = ["intel_oneapi"]

# Build type to CMake flag mapping
BUILD_TYPE_FLAGS = {
    "CPU": "-DGGML_NATIVE=ON",
    "CUDA": "-DGGML_CUDA=ON",
    "Vulkan": "-DGGML_VULKAN=ON",
    "HIP": "-DGGML_HIP=ON",
    "SYCL": "-DGGML_SYCL=ON",
    "Metal": "-DGGML_METAL=ON"
}

# Build type display names
BUILD_TYPE_DISPLAY = {
    "CPU": "CPU",
    "CUDA": "CUDA",
    "Vulkan": "Vulkan",
    "HIP": "HIP/ROCm",
    "SYCL": "SYCL (Intel)",
    "Metal": "Metal (macOS)"
}

# Build types list
BUILD_TYPES = ["CPU", "CUDA", "Vulkan", "HIP", "SYCL", "Metal"]

if getattr(sys, "frozen", False):
    from runtime_data import initialize_data
    initialize_data(DATA_DIR, BUNDLE_DIR, {
        "sources.json": DEFAULT_BUILD_SOURCES,
        "profiles.json": DEFAULT_BUILD_PROFILES,
        "build_history.json": [],
        "system_report.json": {},
    })
