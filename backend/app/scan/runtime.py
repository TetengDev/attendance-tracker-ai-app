from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessRole(str, Enum):
    API = "api"
    SCAN = "scan"


class ScanUnavailablePolicy(str, Enum):
    RETURN_ERROR_FAST = "return_error_fast"


class QueueBoundary(str, Enum):
    SHARED_QUEUE = "shared_queue"


class ReadinessGate(str, Enum):
    INDEX_LOADED_VERSION_AT_LEAST_REQUIRED_GALLERY_VERSION = (
        "index_loaded_version_at_least_required_gallery_version"
    )


class OnnxThreadingPolicy(str, Enum):
    EXPLICIT_RUNTIME_CONFIG = "explicit_runtime_config"


@dataclass(frozen=True)
class RuntimeProcessSpec:
    role: ProcessRole
    count: int
    owns_models: bool
    description: str


@dataclass(frozen=True)
class ScanRuntimeTopology:
    api: RuntimeProcessSpec
    scan: RuntimeProcessSpec
    queue_boundary: QueueBoundary
    unavailable_policy: ScanUnavailablePolicy
    unavailable_timeout_ms: int
    estimated_model_rss_mb_per_process: int
    readiness_gate: ReadinessGate
    onnx_threading_policy: OnnxThreadingPolicy
    load_models_once_per_process: bool

    @property
    def estimated_scan_rss_mb(self) -> int:
        return self.scan.count * self.estimated_model_rss_mb_per_process


DEFAULT_SCAN_TOPOLOGY = ScanRuntimeTopology(
    api=RuntimeProcessSpec(
        role=ProcessRole.API,
        count=2,
        owns_models=False,
        description="model-free FastAPI workers for HTTP, WS upgrade, auth, and admin APIs",
    ),
    scan=RuntimeProcessSpec(
        role=ProcessRole.SCAN,
        count=2,
        owns_models=True,
        description="dedicated model-owning scan processes behind a shared queue",
    ),
    queue_boundary=QueueBoundary.SHARED_QUEUE,
    unavailable_policy=ScanUnavailablePolicy.RETURN_ERROR_FAST,
    unavailable_timeout_ms=499,
    estimated_model_rss_mb_per_process=600,
    readiness_gate=ReadinessGate.INDEX_LOADED_VERSION_AT_LEAST_REQUIRED_GALLERY_VERSION,
    onnx_threading_policy=OnnxThreadingPolicy.EXPLICIT_RUNTIME_CONFIG,
    load_models_once_per_process=True,
)


def assert_topology_contract(topology: ScanRuntimeTopology = DEFAULT_SCAN_TOPOLOGY) -> None:
    if topology.api.owns_models:
        raise ValueError("API workers must remain model-free")
    if not topology.scan.owns_models:
        raise ValueError("scan processes own the face models")
    if topology.scan.count < 2:
        raise ValueError("at least two scan processes are required for rolling restart availability")
    if topology.queue_boundary is not QueueBoundary.SHARED_QUEUE:
        raise ValueError("scan work must cross the shared queue boundary")
    if topology.unavailable_policy is not ScanUnavailablePolicy.RETURN_ERROR_FAST:
        raise ValueError("kiosks must receive SCAN_BACKEND_UNAVAILABLE quickly")
    if topology.unavailable_timeout_ms >= 500:
        raise ValueError("unavailable scan backend response must be under 500 ms")
    if (
        topology.readiness_gate
        is not ReadinessGate.INDEX_LOADED_VERSION_AT_LEAST_REQUIRED_GALLERY_VERSION
    ):
        raise ValueError("readiness must require index_loaded_version >= required_gallery_version")
    if topology.onnx_threading_policy is not OnnxThreadingPolicy.EXPLICIT_RUNTIME_CONFIG:
        raise ValueError("ONNX thread counts must be explicit runtime configuration")
    if not topology.load_models_once_per_process:
        raise ValueError("models must be loaded once per scan process, never per request")
