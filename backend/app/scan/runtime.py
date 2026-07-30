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
    readiness_requires_gallery_convergence: bool
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
    unavailable_timeout_ms=500,
    estimated_model_rss_mb_per_process=600,
    readiness_requires_gallery_convergence=True,
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
    if topology.unavailable_timeout_ms > 500:
        raise ValueError("unavailable scan backend response must be under 500 ms")
    if not topology.readiness_requires_gallery_convergence:
        raise ValueError("readiness must be gated on gallery/index convergence")
    if not topology.load_models_once_per_process:
        raise ValueError("models must be loaded once per scan process, never per request")
