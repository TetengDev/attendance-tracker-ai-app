"""Very small Pydantic->TypeScript generator for kiosk schema saved in session-state.

This script imports the Pydantic models module (session-state copy) and emits a
hand-translation of known models into a TypeScript file. It's intentionally
simple: it only supports the models present in kiosk_schema.py and is a
placeholder until a full generator is wired into the repo.
"""
from datetime import datetime

TS_HEADER = "// Generated types — session-state placeholder\n\n"

def generate() -> str:
    out = [TS_HEADER]
    out.append("export interface Hello { device_token_jwt: string; app_version: string; camera_label?: string; }")
    out.append("export interface Heartbeat { fps: number; queue_depth: number; error_count: number; clock_skew_ms: number; }")
    out.append("export interface FrameItem { jpeg_b64: string; bbox: number[]; monotonic_offset_ms: number; }")
    out.append("export interface FrameBurst { idempotency_key: string; burst_seq: number; frames: FrameItem[]; gate_metrics?: Record<string, any>; }")
    out.append("export interface Ready { gallery_version: number; settings_version: number; }")
    out.append("export interface Person { id: string; display_name: string; photo_url?: string; }")
    out.append("export interface Result { status: string; person?: Person; direction?: string; occurred_at?: string; record_status?: string; committed?: boolean; }")
    out.append("export interface SettingsPush { settings_version: number; payload: Record<string, any>; }")
    out.append("export interface Backpressure { retry_after_ms: number; }")
    return "\n".join(out)

if __name__ == '__main__':
    ts = generate()
    with open('session_kiosk_protocol.d.ts', 'w', encoding='utf-8') as f:
        f.write(ts)
    print('Wrote session_kiosk_protocol.d.ts')
