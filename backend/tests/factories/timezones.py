NON_UTC_TIMEZONES: tuple[str, ...] = (
    "Asia/Manila",
    "America/New_York",
    "Europe/Rome",
    "Pacific/Auckland",
)

DETERMINISTIC_ONNX_SESSION_OPTIONS: dict[str, int] = {
    "intra_op_num_threads": 1,
    "inter_op_num_threads": 1,
}
