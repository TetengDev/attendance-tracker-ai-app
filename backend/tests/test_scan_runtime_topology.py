from backend.app.scan.runtime import (
    DEFAULT_SCAN_TOPOLOGY,
    OnnxThreadingPolicy,
    QueueBoundary,
    ReadinessGate,
    ScanUnavailablePolicy,
    assert_topology_contract,
)


def test_default_scan_topology_matches_phase_0_5_decision() -> None:
    assert_topology_contract()
    assert DEFAULT_SCAN_TOPOLOGY.api.owns_models is False
    assert DEFAULT_SCAN_TOPOLOGY.scan.owns_models is True
    assert DEFAULT_SCAN_TOPOLOGY.scan.count == 2
    assert DEFAULT_SCAN_TOPOLOGY.queue_boundary is QueueBoundary.SHARED_QUEUE


def test_unavailable_policy_is_fast_error_not_spinner_or_offline_queue() -> None:
    assert DEFAULT_SCAN_TOPOLOGY.unavailable_policy is ScanUnavailablePolicy.RETURN_ERROR_FAST
    assert DEFAULT_SCAN_TOPOLOGY.unavailable_timeout_ms < 500


def test_readiness_gate_names_required_gallery_version_comparison() -> None:
    assert (
        DEFAULT_SCAN_TOPOLOGY.readiness_gate
        is ReadinessGate.INDEX_LOADED_VERSION_AT_LEAST_REQUIRED_GALLERY_VERSION
    )


def test_onnx_threading_is_explicit_runtime_configuration() -> None:
    assert DEFAULT_SCAN_TOPOLOGY.onnx_threading_policy is OnnxThreadingPolicy.EXPLICIT_RUNTIME_CONFIG


def test_estimated_scan_memory_budget_is_explicit() -> None:
    assert DEFAULT_SCAN_TOPOLOGY.estimated_model_rss_mb_per_process == 600
    assert DEFAULT_SCAN_TOPOLOGY.estimated_scan_rss_mb == 1200
