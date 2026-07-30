from backend.app.scan.runtime import (
    DEFAULT_SCAN_TOPOLOGY,
    QueueBoundary,
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
    assert DEFAULT_SCAN_TOPOLOGY.unavailable_timeout_ms <= 500


def test_estimated_scan_memory_budget_is_explicit() -> None:
    assert DEFAULT_SCAN_TOPOLOGY.estimated_model_rss_mb_per_process == 600
    assert DEFAULT_SCAN_TOPOLOGY.estimated_scan_rss_mb == 1200
