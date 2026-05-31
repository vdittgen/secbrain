use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Seek, SeekFrom, Write};
use std::path::PathBuf;

use fs4::fs_std::FileExt;
use sha2::{Digest, Sha256};

use crate::firewall::types::AuditEntry;

const GENESIS_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// Append-only audit logger with SHA-256 hash chain for tamper detection.
///
/// Each entry's `previous_hash` links to the hash of the prior entry,
/// forming an immutable chain. The first entry uses a genesis hash of all zeros.
pub struct AuditLogger {
    path: PathBuf,
}

impl AuditLogger {
    /// Create a new audit logger pointing at the given JSONL file path.
    /// Creates parent directories if they don't exist.
    pub fn new(path: PathBuf) -> Result<Self, std::io::Error> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        Ok(Self { path })
    }

    /// Create a logger using the default path: `~/.secbrain/data/audit.jsonl`.
    pub fn default_path() -> Result<Self, std::io::Error> {
        let home = dirs::home_dir().ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::NotFound, "home directory not found")
        })?;
        let path = home.join(".secbrain").join("data").join("audit.jsonl");
        Self::new(path)
    }

    /// Compute the SHA-256 hash of a serialized audit entry.
    fn hash_entry(entry_json: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(entry_json.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    /// Hash of the last non-empty line in `reader`, or the genesis
    /// hash when the reader is empty. Used by `log()` to resolve the
    /// chain's tail inside the file-lock critical section.
    fn last_hash_from_reader<R: BufRead>(reader: R) -> Result<String, std::io::Error> {
        let mut last_line: Option<String> = None;
        for line in reader.lines() {
            let line = line?;
            if !line.trim().is_empty() {
                last_line = Some(line);
            }
        }
        match last_line {
            Some(line) => Ok(Self::hash_entry(&line)),
            None => Ok(GENESIS_HASH.to_string()),
        }
    }

    /// Append an audit entry to the log file with race-safe chaining.
    ///
    /// # sensitivity_tier: all (logs decisions about all tiers)
    ///
    /// Takes the entry by value because we overwrite `previous_hash`
    /// with the freshly-resolved tail of the chain inside the
    /// `LOCK_EX` critical section. This is what makes the writer
    /// race-safe across processes: previously the caller computed
    /// `previous_hash` via `next_previous_hash()` and *then* called
    /// `log()`, leaving a window where another writer could append
    /// between the two calls and force both entries to claim the
    /// same `previous_hash`. The Python writer in
    /// `src/agents/core/audit.py` uses the same `flock` strategy.
    pub fn log(&self, mut entry: AuditEntry) -> Result<(), std::io::Error> {
        let mut file = OpenOptions::new()
            .create(true)
            .read(true)
            .append(true)
            .open(&self.path)?;

        FileExt::lock_exclusive(&file)?;
        let result = (|| -> Result<(), std::io::Error> {
            file.seek(SeekFrom::Start(0))?;
            let previous_hash =
                Self::last_hash_from_reader(BufReader::new(&file))?;
            entry.previous_hash = previous_hash;
            let json = serde_json::to_string(&entry).map_err(|e| {
                std::io::Error::new(std::io::ErrorKind::InvalidData, e)
            })?;
            writeln!(file, "{json}")?;
            file.sync_data()?;
            Ok(())
        })();
        // Release the lock regardless of write outcome; ignore unlock
        // errors since the fd is about to be dropped anyway.
        let _ = FileExt::unlock(&file);
        result
    }

    /// Retrieve the most recent `n` audit entries.
    ///
    /// # sensitivity_tier: all (reads audit log)
    pub fn get_recent(&self, n: usize) -> Result<Vec<AuditEntry>, std::io::Error> {
        self.get_recent_paginated(n, 0)
    }

    /// Retrieve audit entries with pagination support.
    ///
    /// Returns up to `limit` entries starting from `offset` positions
    /// from the end (most recent first). Malformed lines are logged and
    /// skipped — one bad line does not poison the whole read.
    ///
    /// # sensitivity_tier: all (reads audit log)
    pub fn get_recent_paginated(
        &self,
        limit: usize,
        offset: usize,
    ) -> Result<Vec<AuditEntry>, std::io::Error> {
        if !self.path.exists() {
            return Ok(vec![]);
        }

        let file = fs::File::open(&self.path)?;
        let reader = BufReader::new(file);
        let mut entries: Vec<AuditEntry> = Vec::new();

        for line in reader.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<AuditEntry>(&line) {
                Ok(entry) => entries.push(entry),
                Err(e) => {
                    eprintln!("audit: skipping malformed line ({e}): {line}");
                }
            }
        }

        let total = entries.len();
        let end = total.saturating_sub(offset);
        let start = end.saturating_sub(limit);
        Ok(entries[start..end].to_vec())
    }

    /// Verify the integrity of the entire hash chain.
    ///
    /// Returns `true` if every entry's `previous_hash` matches the SHA-256
    /// hash of the preceding entry (or the genesis hash for the first entry).
    /// Strict: any unparseable line breaks the chain, since chain integrity
    /// depends on the exact byte sequence written.
    pub fn verify_chain(&self) -> Result<bool, std::io::Error> {
        if !self.path.exists() {
            return Ok(true);
        }

        let file = fs::File::open(&self.path)?;
        let reader = BufReader::new(file);
        let mut expected_hash = GENESIS_HASH.to_string();

        for line in reader.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let entry: AuditEntry = match serde_json::from_str(&line) {
                Ok(e) => e,
                Err(_) => return Ok(false),
            };

            if entry.previous_hash != expected_hash {
                return Ok(false);
            }

            expected_hash = Self::hash_entry(&line);
        }

        Ok(true)
    }

}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use serde_json::json;
    use std::env;

    fn temp_audit_path() -> PathBuf {
        let dir = env::temp_dir().join(format!("secbrain_test_{}", uuid::Uuid::new_v4()));
        dir.join("audit.jsonl")
    }

    fn make_entry(previous_hash: &str) -> AuditEntry {
        AuditEntry {
            timestamp: Utc::now().to_rfc3339(),
            event_type: "egress_decision".to_string(),
            agent_id: "test-agent".to_string(),
            decision: "remote".to_string(),
            tier: Some(2),
            payload_hash: Some("abc123".to_string()),
            previous_hash: previous_hash.to_string(),
            extra: json!({"policy": "remote-default", "requires_redaction": true}),
        }
    }

    #[test]
    fn test_append_and_read() {
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        logger.log(make_entry(GENESIS_HASH)).unwrap();

        let recent = logger.get_recent(10).unwrap();
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0].agent_id, "test-agent");
        assert_eq!(recent[0].event_type, "egress_decision");
        assert_eq!(recent[0].decision, "remote");

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_hash_chain_valid() {
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        // `log()` resolves `previous_hash` itself inside the file
        // lock — callers no longer need to pre-compute it.
        logger.log(make_entry("")).unwrap();
        logger.log(make_entry("")).unwrap();

        assert!(logger.verify_chain().unwrap());

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_hash_chain_detects_tampering() {
        // `log()` now overwrites `previous_hash`, so the only way to
        // forge a broken chain is to write directly to the file
        // bypassing the logger — exactly what a tampering attempt
        // would look like.
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        logger.log(make_entry(GENESIS_HASH)).unwrap();

        let forged = make_entry("bad_hash_value");
        let forged_json = serde_json::to_string(&forged).unwrap();
        let mut file = OpenOptions::new().append(true).open(&path).unwrap();
        writeln!(file, "{forged_json}").unwrap();
        drop(file);

        assert!(!logger.verify_chain().unwrap());

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_empty_log_verifies() {
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        assert!(logger.verify_chain().unwrap());
        assert_eq!(logger.get_recent(10).unwrap().len(), 0);

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_get_recent_limits_results() {
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        for _ in 0..5 {
            logger.log(make_entry("")).unwrap();
        }

        let recent = logger.get_recent(3).unwrap();
        assert_eq!(recent.len(), 3);

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_reader_skips_malformed_lines() {
        let path = temp_audit_path();
        let logger = AuditLogger::new(path.clone()).unwrap();

        logger.log(make_entry(GENESIS_HASH)).unwrap();

        // Hand-append a malformed line directly to the file.
        let mut file = OpenOptions::new().append(true).open(&path).unwrap();
        writeln!(file, "this is not valid json").unwrap();
        drop(file);

        logger.log(make_entry(GENESIS_HASH)).unwrap();

        let recent = logger.get_recent(10).unwrap();
        assert_eq!(recent.len(), 2, "malformed line should be skipped, valid lines returned");

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_concurrent_appenders_keep_chain_valid() {
        // Regression: before the file-lock fix, threads racing through
        // `next_previous_hash()` + `log()` could write two entries
        // claiming the same `previous_hash`, leaving the chain broken.
        // With the fix, `log()` holds `LOCK_EX` across read-tail +
        // write, so every entry is correctly chained.
        use std::sync::Arc;
        use std::thread;

        let path = temp_audit_path();
        let logger = Arc::new(AuditLogger::new(path.clone()).unwrap());

        let threads_n = 8;
        let per_thread = 25;
        let mut handles = Vec::with_capacity(threads_n);
        for _ in 0..threads_n {
            let logger = Arc::clone(&logger);
            handles.push(thread::spawn(move || {
                for _ in 0..per_thread {
                    logger.log(make_entry("")).unwrap();
                }
            }));
        }
        for h in handles {
            h.join().unwrap();
        }

        assert!(
            logger.verify_chain().unwrap(),
            "chain must remain valid under concurrent appenders",
        );
        assert_eq!(
            logger.get_recent(usize::MAX).unwrap().len(),
            threads_n * per_thread,
        );

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn test_python_shape_round_trips() {
        // Exact shape Python's AuditChain.append() writes.
        let path = temp_audit_path();
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let python_line = r#"{"agent_id":"egress-firewall","decision":"remote","event_type":"egress_decision","extra":{"policy":"remote-default","requires_redaction":true,"requires_consent":false},"payload_hash":"deadbeef","previous_hash":"0000000000000000000000000000000000000000000000000000000000000000","tier":2,"timestamp":"2026-05-16T10:00:00+00:00"}"#;
        fs::write(&path, format!("{python_line}\n")).unwrap();

        let logger = AuditLogger::new(path.clone()).unwrap();
        let recent = logger.get_recent(10).unwrap();
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0].event_type, "egress_decision");
        assert_eq!(recent[0].decision, "remote");
        assert_eq!(recent[0].tier, Some(2));
        assert_eq!(recent[0].extra["policy"], "remote-default");

        let _ = fs::remove_dir_all(path.parent().unwrap());
    }
}
