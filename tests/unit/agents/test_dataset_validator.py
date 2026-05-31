"""DatasetValidator structural check tests.

sensitivity_tier: 1
"""

from __future__ import annotations

import yaml
from src.agents.dataset_validator import (
    canonicalize_dataset_yaml,
    structural_check,
)


def test_well_formed_passes() -> None:
    content = """
cases:
  - name: one
    inputs: hello
    expected_output: {tier: 1}
    evaluators:
      - {name: TierEquals, expected: 1}
"""
    result = structural_check(content)
    assert result.valid is True
    assert result.errors == ()


def test_well_formed_shorthand_evaluator_passes() -> None:
    content = """
cases:
  - name: one
    inputs: hello
    expected_output: {tier: 1}
    evaluators:
      - {TierEquals: {expected: 1}}
"""
    result = structural_check(content)
    assert result.valid is True
    assert result.errors == ()


def test_rejects_unknown_evaluator_in_shorthand() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: x\n"
        "    evaluators:\n"
        "      - {NoSuchEvaluator: {}}\n"
    )
    result = structural_check(content)
    assert result.valid is False
    assert any("unknown evaluator" in e for e in result.errors)


def test_rejects_non_mapping_root() -> None:
    result = structural_check("- not a mapping")
    assert result.valid is False
    assert any("mapping" in e for e in result.errors)


def test_rejects_empty_cases() -> None:
    result = structural_check("cases: []\n")
    assert result.valid is False
    assert any("non-empty" in e for e in result.errors)


def test_rejects_missing_name() -> None:
    result = structural_check("cases:\n  - inputs: hi\n")
    assert result.valid is False
    assert any("name" in e for e in result.errors)


def test_rejects_dict_inputs() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: {subject: hi, body: there}\n"
    )
    result = structural_check(content)
    assert result.valid is False
    assert any(
        "`inputs` must be a string" in e and "dict" in e for e in result.errors
    )


def test_rejects_list_inputs() -> None:
    content = "cases:\n  - name: a\n    inputs: [one, two]\n"
    result = structural_check(content)
    assert result.valid is False
    assert any("`inputs` must be a string" in e for e in result.errors)


def test_rejects_duplicate_names() -> None:
    content = (
        "cases:\n"
        "  - name: a\n    inputs: x\n"
        "  - name: a\n    inputs: y\n"
    )
    result = structural_check(content)
    assert result.valid is False
    assert any("duplicate" in e for e in result.errors)


def test_rejects_unknown_evaluator() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: x\n"
        "    evaluators:\n"
        "      - {name: NoSuchEvaluator}\n"
    )
    result = structural_check(content)
    assert result.valid is False
    assert any("unknown evaluator" in e for e in result.errors)


def test_rejects_unparseable_yaml() -> None:
    result = structural_check("::: this is\n   not valid: [")
    assert result.valid is False
    assert any("yaml parse error" in e for e in result.errors)


# ---------------------------------------------------------------------------
# canonicalize_dataset_yaml
# ---------------------------------------------------------------------------


def test_canonicalize_renames_args_to_arguments() -> None:
    # FieldNotEmpty has no per-keyword alias rule — exercises the
    # args→arguments rename in isolation.
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldNotEmpty\n"
        "        args:\n"
        "          field: status\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is True
    parsed = yaml.safe_load(rewritten)
    entry = parsed["cases"][0]["evaluators"][0]
    assert "args" not in entry
    assert entry["arguments"] == {"field": "status"}


def test_canonicalize_noop_when_already_canonical() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldEquals\n"
        "        arguments:\n"
        "          field: status\n"
        "          value: ok\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is False
    # No-op: caller relies on `changed=False` to skip the rewrite.
    assert rewritten == content


def test_canonicalize_keeps_existing_arguments_over_args() -> None:
    # Defensive: if both keys are present (shouldn't happen in practice)
    # we don't clobber the canonical `arguments` key. Use FieldNotEmpty
    # to keep the test focused on the args→arguments rename only.
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldNotEmpty\n"
        "        args: {field: s}\n"
        "        arguments: {field: t}\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    # No change because `arguments` is already present.
    assert changed is False
    parsed = yaml.safe_load(rewritten)
    entry = parsed["cases"][0]["evaluators"][0]
    assert entry["arguments"] == {"field": "t"}


def test_canonicalize_handles_string_evaluators() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - FieldNotEmpty\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is False
    assert rewritten == content


def test_canonicalize_tolerates_unparseable_yaml() -> None:
    # Bad YAML should not raise — caller wraps load in its own error path.
    rewritten, changed = canonicalize_dataset_yaml("::: not valid: [")
    assert changed is False


def test_canonicalize_renames_field_equals_expected_to_value() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldEquals\n"
        "        args:\n"
        "          field: status\n"
        "          expected: ok\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is True
    parsed = yaml.safe_load(rewritten)
    entry = parsed["cases"][0]["evaluators"][0]
    assert entry["arguments"] == {"field": "status", "value": "ok"}


def test_canonicalize_renames_field_in_expected_to_choices() -> None:
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldIn\n"
        "        arguments:\n"
        "          field: status\n"
        "          expected: [ok, pending]\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is True
    parsed = yaml.safe_load(rewritten)
    entry = parsed["cases"][0]["evaluators"][0]
    assert entry["arguments"] == {"field": "status", "choices": ["ok", "pending"]}


def test_canonicalize_leaves_unknown_evaluators_alone() -> None:
    # No alias map for IntInRange — its kwargs are correct already.
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: IntInRange\n"
        "        arguments:\n"
        "          field: count\n"
        "          lo: 1\n"
        "          hi: 10\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is False
    assert rewritten == content


def test_canonicalize_preserves_canonical_kwarg_when_alias_also_present() -> None:
    # Defensive: if the LLM emits both `value` and `expected`, keep
    # `value` (the canonical key) and leave the spurious alias alone.
    content = (
        "cases:\n"
        "  - name: a\n"
        "    inputs: hi\n"
        "    evaluators:\n"
        "      - name: FieldEquals\n"
        "        arguments:\n"
        "          field: status\n"
        "          value: ok\n"
        "          expected: somethingelse\n"
    )
    rewritten, changed = canonicalize_dataset_yaml(content)
    assert changed is False
    parsed = yaml.safe_load(rewritten)
    args = parsed["cases"][0]["evaluators"][0]["arguments"]
    assert args["value"] == "ok"
