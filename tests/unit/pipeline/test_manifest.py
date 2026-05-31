"""Tests for the pipeline manifest loader and dependency resolver.

sensitivity_tier: N/A
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.pipeline.manifest import (
    AuditSpec,
    ModelSpec,
    PipelineManifest,
    load_manifest,
    resolve_execution_order,
    topological_sort,
)

# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_empty_list(self) -> None:
        assert topological_sort([]) == []

    def test_single_model(self) -> None:
        m = ModelSpec(name="a", layer="staging", depends_on=["raw_x"])
        result = topological_sort([m])
        assert [r.name for r in result] == ["a"]

    def test_linear_chain(self) -> None:
        """A depends on nothing, B depends on A, C depends on B."""
        a = ModelSpec(name="a", layer="staging", depends_on=["raw_x"])
        b = ModelSpec(name="b", layer="intermediate", depends_on=["a"])
        c = ModelSpec(name="c", layer="mart", depends_on=["b"])
        result = topological_sort([c, a, b])
        names = [r.name for r in result]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_diamond_dependency(self) -> None:
        """A → B, A → C, B → D, C → D."""
        a = ModelSpec(name="a", layer="staging", depends_on=["raw"])
        b = ModelSpec(name="b", layer="int", depends_on=["a"])
        c = ModelSpec(name="c", layer="int", depends_on=["a"])
        d = ModelSpec(name="d", layer="mart", depends_on=["b", "c"])
        result = topological_sort([d, c, b, a])
        names = [r.name for r in result]
        assert names.index("a") < names.index("b")
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("d")
        assert names.index("c") < names.index("d")

    def test_circular_dependency_raises(self) -> None:
        a = ModelSpec(name="a", layer="staging", depends_on=["b"])
        b = ModelSpec(name="b", layer="staging", depends_on=["a"])
        with pytest.raises(ValueError, match="Circular dependency"):
            topological_sort([a, b])

    def test_external_deps_ignored(self) -> None:
        """Dependencies on raw tables (not in model list) are ignored."""
        a = ModelSpec(
            name="a", layer="staging",
            depends_on=["raw_messages", "raw_contacts"],
        )
        b = ModelSpec(name="b", layer="int", depends_on=["a"])
        result = topological_sort([b, a])
        assert [r.name for r in result] == ["a", "b"]

    def test_multiple_roots(self) -> None:
        """Multiple models with no inter-model dependencies."""
        a = ModelSpec(name="a", layer="staging", depends_on=["raw_x"])
        b = ModelSpec(name="b", layer="staging", depends_on=["raw_y"])
        c = ModelSpec(name="c", layer="staging", depends_on=["raw_z"])
        result = topological_sort([c, b, a])
        assert len(result) == 3
        # All should be present
        assert {r.name for r in result} == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# ModelSpec tests
# ---------------------------------------------------------------------------


class TestModelSpec:
    def test_sql_model_defaults(self) -> None:
        m = ModelSpec(name="test", layer="staging")
        assert m.model_type == "sql"
        assert m.python_module is None
        assert m.sql_file is None
        assert m.depends_on == []
        assert m.grain == []

    def test_python_model(self) -> None:
        m = ModelSpec(
            name="test",
            layer="intermediate",
            model_type="python",
            python_module="src.pipeline.test",
            python_function="execute",
        )
        assert m.model_type == "python"
        assert m.python_module == "src.pipeline.test"

    def test_audit_spec(self) -> None:
        a = AuditSpec(
            not_null=["id", "name"],
            unique=["id"],
            accepted_values={"tier": [1, 2, 3]},
        )
        assert "id" in a.not_null
        assert a.accepted_values["tier"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# PipelineManifest tests
# ---------------------------------------------------------------------------


class TestPipelineManifest:
    def test_get_model(self) -> None:
        m1 = ModelSpec(name="a", layer="staging")
        m2 = ModelSpec(name="b", layer="mart")
        manifest = PipelineManifest(version=1, models=[m1, m2])
        assert manifest.get_model("a") == m1
        assert manifest.get_model("c") is None

    def test_model_names(self) -> None:
        m1 = ModelSpec(name="a", layer="staging")
        m2 = ModelSpec(name="b", layer="mart")
        manifest = PipelineManifest(version=1, models=[m1, m2])
        assert manifest.model_names == ["a", "b"]


# ---------------------------------------------------------------------------
# load_manifest tests
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_load_real_manifest(self) -> None:
        """Load the actual pipeline_manifest.json file."""
        manifest = load_manifest()
        assert manifest.version == 1
        assert len(manifest.models) == 19

        # Check a known model
        stg = manifest.get_model("stg_messages")
        assert stg is not None
        assert stg.layer == "staging"
        assert "raw_messages" in stg.depends_on

    def test_load_custom_manifest(self, tmp_path: Path) -> None:
        data = {
            "version": 2,
            "models": [
                {
                    "name": "test_model",
                    "layer": "staging",
                    "sql_file": "test.sql",
                    "depends_on": ["raw_test"],
                    "grain": ["id"],
                    "audits": {
                        "not_null": ["id"],
                        "unique": ["id"],
                    },
                },
            ],
        }
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(data))

        manifest = load_manifest(path)
        assert manifest.version == 2
        assert len(manifest.models) == 1
        assert manifest.models[0].name == "test_model"
        assert manifest.models[0].audits.not_null == ["id"]

    def test_python_model_parsed(self) -> None:
        manifest = load_manifest()
        m = manifest.get_model("int_labeled_messages")
        assert m is not None
        assert m.model_type == "python"
        assert m.python_module == (
            "src.pipeline.intermediate.int_labeled_messages"
        )
        assert m.python_function == "execute"


# ---------------------------------------------------------------------------
# resolve_execution_order tests
# ---------------------------------------------------------------------------


class TestResolveExecutionOrder:
    def test_full_pipeline_order(self) -> None:
        """Every model should come after all its model-level dependencies."""
        manifest = load_manifest()
        order = resolve_execution_order(manifest)

        names = [m.name for m in order]
        model_names_set = set(names)

        # For each model, verify all its model-level deps come before it
        for model in order:
            model_idx = names.index(model.name)
            for dep in model.depends_on:
                if dep in model_names_set:
                    dep_idx = names.index(dep)
                    assert dep_idx < model_idx, (
                        f"{dep} (idx {dep_idx}) should come before "
                        f"{model.name} (idx {model_idx})"
                    )

        # All 17 models should be present
        assert len(order) == 19

    def test_selective_models(self) -> None:
        """Selecting mart_health should include stg_health_metrics."""
        manifest = load_manifest()
        order = resolve_execution_order(
            manifest, select_models=["mart_health"],
        )
        names = [m.name for m in order]
        assert "mart_health" in names
        assert "stg_health_metrics" in names
        # Should not include unrelated models
        assert "stg_messages" not in names

    def test_selective_with_transitive_deps(self) -> None:
        """Selecting mart_today should include all transitive deps."""
        manifest = load_manifest()
        order = resolve_execution_order(
            manifest, select_models=["mart_today"],
        )
        names = [m.name for m in order]
        assert "mart_today" in names
        assert "int_events_enriched" in names
        assert "stg_calendar_events" in names
        assert "stg_contacts" in names
