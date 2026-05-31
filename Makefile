.PHONY: help lint test test-unit evals evals-offline evals-fast evals-list \
        eval-retrieval eval-retrieval-baseline eval-retrieval-routed \
        eval-retrieval-hybrid

help:
	@echo "Targets:"
	@echo "  lint                       ruff check src/ tests/ evals/"
	@echo "  test                       full unit suite"
	@echo "  test-unit                  unit suite (alias for test)"
	@echo "  evals                      run every agent eval suite (LLM judge spends \$\$)"
	@echo "  evals-offline              run every suite WITHOUT the LLM judge"
	@echo "  evals-fast                 run the deterministic firewall suite only"
	@echo "  evals-list                 list available eval suite names"
	@echo "  eval-retrieval             run retrieval-quality evals (raw mode, k=10)"
	@echo "  eval-retrieval-baseline    same, tagged baseline, written to results/baseline.json"
	@echo "  eval-retrieval-routed      retrieval evals via the full QueryEngine path"

lint:
	ruff check src/ tests/ evals/

test test-unit:
	python -m pytest tests/unit -q

# Runs the agent suites + the LLM judge. The judge tier is paid;
# evals never run automatically — this target is the only batch
# entry point.
evals:
	python -m evals.run_evals --suite all

# Same suites, judge disabled. Useful for offline runs and for the
# pre-commit loop where you only want the structural assertions.
evals-offline:
	SECBRAIN_EVAL_JUDGE_DISABLED=1 python -m evals.run_evals --suite all

evals-fast:
	python -m evals.run_evals --suite firewall_prompts

evals-list:
	@python -m evals.run_evals --list

# Retrieval-quality evals — numeric metrics (hit@k, MRR, NDCG@k)
# over the golden YAML at evals/datasets/retrieval_golden.yaml.
# Hits the live vector store; not part of CI.
eval-retrieval:
	python -m evals.retrieval.runner --mode raw --k 10

eval-retrieval-baseline:
	python -m evals.retrieval.runner --baseline --mode raw --k 10

eval-retrieval-routed:
	python -m evals.retrieval.runner --mode routed --k 10

eval-retrieval-hybrid:
	python -m evals.retrieval.runner --mode hybrid --k 10
