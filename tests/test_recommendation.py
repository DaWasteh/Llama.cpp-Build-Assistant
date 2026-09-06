"""Platform-independent tests for the recommendation logic (synthetic reports)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEFAULT_BUILD_PROFILES, get_dir_suffix  # noqa: E402
from hardware_check import (  # noqa: E402
    get_recommendation, recommend_cuda_major, select_profile_name,
    is_rdna4, has_rdna4_gpu, _parse_nvcc_version,
)


def _report(os_name="Windows 11", arch="x86_64", gpus=None, **gpu_flags):
    gpu = {
        "gpus": gpus or [],
        "has_nvidia": any(g.get("vendor") == "NVIDIA" for g in gpus or []),
        "has_amd": any(g.get("vendor") == "AMD" for g in gpus or []),
        "has_intel": any(g.get("vendor") == "Intel" for g in gpus or []),
        "has_apple": any(g.get("vendor") == "Apple" for g in gpus or []),
        "cuda_available": False, "rocm_available": False, "sycl_available": False,
        "vulkan_available": False, "metal_available": False,
        "amd_gfx_targets": [], "nvidia_driver_cuda_version": "",
    }
    gpu.update(gpu_flags)
    return {"os": os_name, "arch": arch, "cpu": {"arch": arch, "features": []}, "gpu": gpu}


def test_rdna4_names():
    assert is_rdna4("AMD Radeon RX 9070 XT")
    assert is_rdna4("AMD Radeon AI PRO R9700")
    assert is_rdna4("AMD Radeon RX 9060 XT")
    assert not is_rdna4("AMD Radeon RX 7900 XTX")
    assert not is_rdna4("AMD Radeon RX 6800")


def test_rdna4_via_gfx_target_beats_rocm():
    r = _report(gpus=[{"name": "AMD Radeon Graphics", "vendor": "AMD"}],
                rocm_available=True, vulkan_available=True, amd_gfx_targets=["gfx1201"])
    assert has_rdna4_gpu(r)
    assert get_recommendation(r) == "Vulkan"


def test_rdna3_with_rocm_is_hip():
    r = _report(gpus=[{"name": "AMD Radeon RX 7900 XTX", "vendor": "AMD"}],
                rocm_available=True, vulkan_available=True, amd_gfx_targets=["gfx1100"])
    assert get_recommendation(r) == "HIP"


def test_nvidia_cuda_generations():
    r = _report(gpus=[{"name": "NVIDIA GeForce RTX 4090", "vendor": "NVIDIA", "compute_cap": "8.9"}],
                cuda_available=True, nvidia_driver_cuda_version="13.0")
    assert get_recommendation(r) == "CUDA"
    assert recommend_cuda_major(r) == "13"
    r["gpu"]["nvidia_driver_cuda_version"] = "12.8"
    assert recommend_cuda_major(r) == "12"
    pascal = _report(gpus=[{"name": "NVIDIA GeForce GTX 1080", "vendor": "NVIDIA", "compute_cap": "6.1"}],
                     cuda_available=True, nvidia_driver_cuda_version="13.0")
    assert recommend_cuda_major(pascal) == "12"


def test_profile_selection_cuda():
    r = _report(gpus=[{"name": "NVIDIA GeForce RTX 3080", "vendor": "NVIDIA", "compute_cap": "8.6"}],
                cuda_available=True, nvidia_driver_cuda_version="13.1")
    assert select_profile_name(r, DEFAULT_BUILD_PROFILES) == "CUDA 13.x NVIDIA"
    r["gpu"]["nvidia_driver_cuda_version"] = "12.6"
    assert select_profile_name(r, DEFAULT_BUILD_PROFILES) == "CUDA 12.x NVIDIA"


def test_mac_split():
    silicon = _report(os_name="macOS 15.1", arch="arm64",
                      gpus=[{"name": "Apple M3 Max", "vendor": "Apple"}], metal_available=True)
    assert get_recommendation(silicon) == "Metal"
    assert select_profile_name(silicon, DEFAULT_BUILD_PROFILES) == "Metal (Apple Silicon)"
    intel = _report(os_name="macOS 13.6", arch="x86_64",
                    gpus=[{"name": "AMD Radeon Pro 5500M", "vendor": "AMD"}])
    assert get_recommendation(intel) == "CPU"
    assert select_profile_name(intel, DEFAULT_BUILD_PROFILES) == "CPU (Intel Mac)"


def test_windows_profiles_ignore_mac_only_entries():
    r = _report(vulkan_available=True, gpus=[{"name": "Intel(R) Arc(TM) A770", "vendor": "Intel"}])
    assert get_recommendation(r) == "Vulkan"
    assert select_profile_name(r, DEFAULT_BUILD_PROFILES) == "Vulkan"
    cpu_only = _report()
    assert select_profile_name(cpu_only, DEFAULT_BUILD_PROFILES) == "CPU"


def test_nvcc_version_parse():
    text = "nvcc: NVIDIA (R) Cuda compiler driver\nCuda compilation tools, release 12.8, V12.8.93\n"
    assert _parse_nvcc_version(text) == "12.8"


def test_dir_suffixes_follow_auto_tuner_convention():
    assert get_dir_suffix({"id": "main"}) == "llama.cpp"
    assert get_dir_suffix({"id": "turboquant"}) == "tq_llama.cpp"
    assert get_dir_suffix({"id": "my fork"}) == "my_fork_llama.cpp"
    assert get_dir_suffix({"id": "x", "dir_suffix": "x_llama.cpp"}) == "x_llama.cpp"
    for source_id in ("main", "turboquant", "ternary_bonsai", "ocr_llama", "diffusion_gemma"):
        assert get_dir_suffix({"id": source_id}).endswith("_llama.cpp") or get_dir_suffix({"id": source_id}) == "llama.cpp"


def test_default_profiles_have_no_machine_specific_flags():
    for prof in DEFAULT_BUILD_PROFILES:
        flags = " ".join(prof["cmake_flags"])
        assert "GPU_TARGETS" not in flags, prof["name"]
        assert "GGML_AVX" not in flags, prof["name"]
        assert "LLAMA_BUILD_UI" not in flags, prof["name"]
