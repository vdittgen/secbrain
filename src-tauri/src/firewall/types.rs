use serde::{Deserialize, Serialize};

/// One line of the SHA-256 chained audit log at
/// `~/.secbrain/data/audit.jsonl`.
///
/// Shape mirrors the Python writer in `src/agents/core/audit.py` so that
/// the same file can be read by both runtimes without schema drift.
/// All firewall events (`egress_decision`, `egress_redaction`,
/// `local_inference_toggle`, …) share this row format; per-event detail
/// lives in `extra`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub timestamp: String,
    pub event_type: String,
    pub agent_id: String,
    pub decision: String,
    #[serde(default)]
    pub tier: Option<u8>,
    #[serde(default)]
    pub payload_hash: Option<String>,
    pub previous_hash: String,
    #[serde(default)]
    pub extra: serde_json::Value,
}

/// Drilldown payload for an audit row that triggered a redaction.
///
/// Loaded from `~/.secbrain/data/redactions/{payload_hash}.json` via the
/// Python CLI handler `get-redaction-detail`. Mirrors the JSON shape
/// produced by `src/models/redaction_store.py`.
///
/// Tier 3 — never logged, never cached, only sent to the local IPC
/// caller in response to an explicit user click.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RedactionDetail {
    pub payload_hash: String,
    pub stored_at: String,
    pub agent_id: String,
    pub lane: String,
    pub original_messages: Vec<RedactionMessage>,
    pub redacted_messages: Vec<RedactionMessage>,
    /// `{placeholder: original}` — what each token in the redacted
    /// prompt stands for.
    pub placeholder_map: std::collections::BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RedactionMessage {
    pub role: String,
    pub content: String,
}

/// Response wrapper so the frontend can distinguish "no detail stored"
/// (e.g. an `egress_decision` row that didn't actually redact) from a
/// failed lookup.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RedactionDetailResponse {
    pub detail: Option<RedactionDetail>,
}
