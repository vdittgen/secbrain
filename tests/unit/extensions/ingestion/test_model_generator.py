"""Tests for the Model Generator and Review Flow.

Covers strategy selection, SQL generation, graph/ChromaDB extensions,
safety guards, LLM fallback, and the review staging/approve/reject flow.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.extensions.ingestion.model_generator import (
    MAX_MODELS_PER_EXTENSION,
    ChromaDBMapping,
    GeneratedModel,
    GraphExtension,
    ModelGenerator,
    ModelPreview,
    _build_sensitivity_comments,
    _build_sensitivity_summary,
    _find_detail_field,
    _find_id_field,
    _find_text_fields,
    _find_timestamp_field,
    _find_title_field,
    _make_connector_slug,
)
from src.extensions.ingestion.review_flow import (
    ReviewFlow,
    _deserialize_preview,
    _serialize_preview,
)
from src.extensions.ingestion.schema_discovery import (
    DiscoveredMapping,
    FieldMapping,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _make_field(
    name: str = "id",
    target_type: str = "VARCHAR",
    tier: int = 1,
    transform: str | None = None,
) -> FieldMapping:
    return FieldMapping(
        source_name=name,
        target_column=name,
        source_type="string",
        target_type=target_type,
        sensitivity_tier=tier,
        confidence=0.8,
        tier_source="keyword_match",
        transform=transform,
    )


def _make_mapping(
    domain: str = "music",
    is_new_table: bool = True,
    fields: tuple[FieldMapping, ...] | None = None,
) -> DiscoveredMapping:
    if fields is None:
        fields = (
            _make_field("id", "VARCHAR", 1),
            _make_field("track_name", "VARCHAR", 1),
            _make_field("artist_name", "VARCHAR", 2),
            _make_field("played_at", "TIMESTAMPTZ", 2),
            _make_field("content", "TEXT", 3),
        )
    return DiscoveredMapping(
        tool_name="list_tracks",
        target_table=f"raw_{domain}",
        is_new_table=is_new_table,
        domain=domain,
        confidence=0.7,
        analysis_method="rules_only",
        fields=fields,
        dedup_key=("id",),
        suggested_schedule="hourly",
        warnings=(),
    )


# ===========================================================================
# TestDetermineStrategy
# ===========================================================================


class TestDetermineStrategy:
    """Test strategy selection logic."""

    def test_extend_existing_when_not_new_table(self) -> None:
        mapping = _make_mapping(domain="messages", is_new_table=False)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-test")
        assert preview.strategy == "extend_existing"
        assert preview.total_models == 0

    def test_staging_only_for_known_domain(self) -> None:
        mapping = _make_mapping(domain="messages", is_new_table=True)
        gen = ModelGenerator()
        strategy = gen._determine_strategy(mapping)
        assert strategy == "staging_only"

    def test_staging_only_for_calendar(self) -> None:
        mapping = _make_mapping(domain="calendar", is_new_table=True)
        gen = ModelGenerator()
        assert gen._determine_strategy(mapping) == "staging_only"

    def test_full_pipeline_for_music(self) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        assert gen._determine_strategy(mapping) == "full_pipeline"

    def test_full_pipeline_for_general(self) -> None:
        mapping = _make_mapping(domain="general", is_new_table=True)
        gen = ModelGenerator()
        assert gen._determine_strategy(mapping) == "full_pipeline"


# ===========================================================================
# TestStagingModelGeneration
# ===========================================================================


class TestStagingModelGeneration:
    """Test staging SQL model generation."""

    def setup_method(self) -> None:
        self.mapping = _make_mapping(domain="music")
        self.gen = ModelGenerator()

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_model_name_has_ext_prefix(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        stg = preview.models[0]
        assert stg.model_name.startswith("staging.ext_stg_")
        assert "music" in stg.model_name

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sql_contains_model_declaration(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "MODEL (" in sql
        assert "kind FULL" in sql

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sql_has_cast_expressions(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "CAST(id AS VARCHAR)" in sql
        assert "CAST(track_name AS VARCHAR)" in sql

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sql_has_loaded_at(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "CURRENT_TIMESTAMP" in sql
        assert "_loaded_at" in sql

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sql_has_sensitivity_comments(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "Column Sensitivity Tiers:" in sql
        assert "tier 1" in sql
        assert "tier 2" in sql

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sql_has_audits(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "audits" in sql
        assert "not_null" in sql
        assert "unique_values" in sql
        assert "accepted_values" in sql

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_filename_has_ext_prefix(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        assert preview.models[0].filename.startswith("ext_stg_")
        assert preview.models[0].filename.endswith(".sql")

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_source_table_is_correct(self, _mock_llm: MagicMock) -> None:
        preview = self.gen.generate(self.mapping, "custom-spotify")
        sql = preview.models[0].sql_content
        assert "FROM raw_music" in sql


# ===========================================================================
# TestIntermediateModelGeneration
# ===========================================================================


class TestIntermediateModelGeneration:
    """Test intermediate SQL model generation."""

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_only_for_full_pipeline(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="messages", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-email")
        # staging_only → only 1 model
        assert len(preview.models) == 1
        assert preview.models[0].layer == "staging"

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_generated_for_full_pipeline(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        layers = [m.layer for m in preview.models]
        assert "intermediate" in layers

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_references_staging_model(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        int_model = [m for m in preview.models if m.layer == "intermediate"][0]
        assert "ext_stg_music" in int_model.sql_content

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_model_name_has_ext_int_prefix(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        int_model = [m for m in preview.models if m.layer == "intermediate"][0]
        assert int_model.model_name.startswith("intermediate.ext_int_")


# ===========================================================================
# TestMartModelGeneration
# ===========================================================================


class TestMartModelGeneration:
    """Test mart SQL model generation."""

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_only_for_full_pipeline(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="messages", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-email")
        layers = [m.layer for m in preview.models]
        assert "mart" not in layers

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_has_item_type_column(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        mart = [m for m in preview.models if m.layer == "mart"][0]
        assert "item_type" in mart.sql_content

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_has_dashboard_columns(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        mart = [m for m in preview.models if m.layer == "mart"][0]
        assert "AS title" in mart.sql_content
        assert "AS detail" in mart.sql_content
        assert "AS occurred_at" in mart.sql_content

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_grain_is_item_type_id(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music", is_new_table=True)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        mart = [m for m in preview.models if m.layer == "mart"][0]
        assert "grain (item_type, id)" in mart.sql_content


# ===========================================================================
# TestGraphExtension
# ===========================================================================


class TestGraphExtension:
    """Test Kuzu graph schema extension generation."""

    def test_music_generates_track_node(self) -> None:
        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        ext = gen._generate_graph_extension(mapping)
        assert ext is not None
        assert "Track" in ext.node_names
        assert "LISTENED_TO" in ext.relationship_names

    def test_browser_generates_webpage_node(self) -> None:
        mapping = _make_mapping(domain="browser")
        gen = ModelGenerator()
        ext = gen._generate_graph_extension(mapping)
        assert ext is not None
        assert "WebPage" in ext.node_names
        assert "VISITED" in ext.relationship_names

    def test_messages_returns_none(self) -> None:
        mapping = _make_mapping(domain="messages")
        gen = ModelGenerator()
        ext = gen._generate_graph_extension(mapping)
        assert ext is None

    def test_general_returns_none(self) -> None:
        mapping = _make_mapping(domain="general")
        gen = ModelGenerator()
        ext = gen._generate_graph_extension(mapping)
        assert ext is None


# ===========================================================================
# TestChromaDBMapping
# ===========================================================================


class TestChromaDBMapping:
    """Test ChromaDB collection assignment."""

    def test_music_maps_to_ideas(self) -> None:
        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        result = gen._determine_chromadb_collection(mapping)
        assert result.collection_name == "ideas"

    def test_health_maps_to_health(self) -> None:
        mapping = _make_mapping(domain="health")
        gen = ModelGenerator()
        result = gen._determine_chromadb_collection(mapping)
        assert result.collection_name == "health"

    def test_general_maps_to_personal(self) -> None:
        mapping = _make_mapping(domain="general")
        gen = ModelGenerator()
        result = gen._determine_chromadb_collection(mapping)
        assert result.collection_name == "personal"


# ===========================================================================
# TestSafetyGuards
# ===========================================================================


class TestSafetyGuards:
    """Test safety guard enforcement."""

    def test_empty_fields_raises_error(self) -> None:
        mapping = _make_mapping(fields=())
        gen = ModelGenerator()
        with pytest.raises(ValueError, match="no fields"):
            gen.generate(mapping, "custom-test")

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_ext_prefix_enforced(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        for model in preview.models:
            basename = model.model_name.split(".")[-1]
            assert basename.startswith("ext_"), (
                f"Model {model.model_name} missing ext_ prefix"
            )

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_sensitivity_tiers_preserved(self, _mock_llm: MagicMock) -> None:
        fields = (
            _make_field("id", "VARCHAR", 1),
            _make_field("content", "TEXT", 3),
        )
        mapping = _make_mapping(fields=fields)
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-test")
        # Check tier summary includes both tiers
        all_tiers = set()
        for model in preview.models:
            all_tiers.update(model.sensitivity_summary.keys())
        assert 1 in all_tiers
        assert 3 in all_tiers

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_max_models_constant_is_reasonable(self, _mock_llm: MagicMock) -> None:
        assert MAX_MODELS_PER_EXTENSION == 10

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_invalid_domain_still_works(self, _mock_llm: MagicMock) -> None:
        # Unknown domain should fall through to full_pipeline strategy
        mapping = _make_mapping(domain="unknown_domain")
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-test")
        assert preview.strategy == "full_pipeline"
        assert preview.total_models == 3


# ===========================================================================
# TestLLMFallback
# ===========================================================================


class TestLLMFallback:
    """Test LLM generation and fallback behavior."""

    @patch.object(ModelGenerator, "_generate_sql_via_llm", return_value=None)
    def test_rule_based_when_llm_unavailable(self, _mock_llm: MagicMock) -> None:
        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        # Should still generate models via rule-based fallback
        assert preview.total_models == 3
        for model in preview.models:
            assert "MODEL" in model.sql_content
            assert "SELECT" in model.sql_content

    def test_llm_invalid_sql_falls_back(self, monkeypatch) -> None:
        # SBAgent returns a GeneratedSQLModel with invalid SQL (no MODEL).
        from src.agents.core.output_types import GeneratedSQLModel

        monkeypatch.setattr(
            "src.agents.model_generator.agent.ModelGeneratorAgent.generate",
            lambda self, *, schema, layer, connector_id: GeneratedSQLModel(
                name="ext_stg_x",
                layer="staging",
                sql="This is not SQL at all",
            ),
        )
        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        preview = gen.generate(mapping, "custom-spotify")
        # Should still have valid models from fallback
        assert preview.total_models == 3
        for model in preview.models:
            assert "MODEL" in model.sql_content

    def test_llm_valid_sql_used(self, monkeypatch) -> None:
        from src.agents.core.output_types import GeneratedSQLModel

        valid_sql = """/*
    Staged music data.
    Column Sensitivity Tiers:
        id: tier 1
*/
MODEL (
    name staging.ext_stg_music_spotify,
    kind FULL,
    grain id,
    audits (
        not_null(columns=[id]),
        unique_values(columns=[id]),
        accepted_values(column=sensitivity_tier, is_in=(1, 2, 3))
    )
);

SELECT
    CAST(id AS VARCHAR) AS id,
    CURRENT_TIMESTAMP AS _loaded_at
FROM raw_music
"""
        monkeypatch.setattr(
            "src.agents.model_generator.agent.ModelGeneratorAgent.generate",
            lambda self, *, schema, layer, connector_id: GeneratedSQLModel(
                name="ext_stg_music_spotify",
                layer="staging",
                sql=valid_sql,
            ),
        )

        mapping = _make_mapping(domain="music")
        gen = ModelGenerator()
        stg = gen._generate_staging_model(
            mapping, "custom-spotify", "spotify",
        )
        assert "ext_stg_music_spotify" in stg.sql_content


# ===========================================================================
# TestReviewFlow
# ===========================================================================


class TestReviewFlow:
    """Test the ReviewFlow stage/approve/reject cycle."""

    def _make_preview(self, staging_dir: str) -> ModelPreview:
        return ModelPreview(
            connector_id="custom-spotify",
            strategy="full_pipeline",
            models=(
                GeneratedModel(
                    model_name="staging.ext_stg_music_spotify",
                    layer="staging",
                    filename="ext_stg_music_spotify.sql",
                    sql_content=(
                        "MODEL (\n"
                        "    name staging.ext_stg_music_spotify,\n"
                        "    kind FULL,\n"
                        "    grain id\n"
                        ");\n"
                        "SELECT CAST(id AS VARCHAR) AS id FROM raw_music"
                    ),
                    sensitivity_summary={1: 1},
                    depends_on=("raw_music",),
                ),
            ),
            graph_extension=None,
            chromadb_mapping=ChromaDBMapping(
                collection_name="ideas",
                domain="music",
                indexing_fields=("content",),
            ),
            staging_dir=staging_dir,
            warnings=(),
            total_models=1,
            sensitivity_summary={1: 1},
        )

    def test_stage_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging_dir = os.path.join(tmp, "generated")
            preview = self._make_preview(staging_dir)
            review = ReviewFlow()
            result_dir = review.stage(preview)
            assert os.path.isdir(result_dir)
            assert os.path.exists(
                os.path.join(result_dir, "ext_stg_music_spotify.sql")
            )
            assert os.path.exists(os.path.join(result_dir, "manifest.json"))

    def test_get_staged_reads_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging_dir = os.path.join(tmp, "generated")
            preview = self._make_preview(staging_dir)
            review = ReviewFlow()
            review.stage(preview)

            # Patch the base path to use our temp dir
            with patch(
                "src.extensions.ingestion.review_flow._EXTENSIONS_BASE",
                Path(tmp).parent,
            ):
                # Manually set up the expected directory structure
                connector_dir = Path(tmp).parent / "custom-spotify" / "generated"
                connector_dir.mkdir(parents=True, exist_ok=True)
                # Copy manifest
                import shutil
                manifest_src = Path(staging_dir) / "manifest.json"
                shutil.copy(manifest_src, connector_dir / "manifest.json")

                result = review.get_staged("custom-spotify")
                assert result is not None
                assert result.connector_id == "custom-spotify"
                assert len(result.models) == 1

    def test_reject_removes_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging_dir = os.path.join(tmp, "generated")
            preview = self._make_preview(staging_dir)
            review = ReviewFlow()
            review.stage(preview)

            # Create the expected path structure
            connector_dir = Path(tmp)
            generated_dir = connector_dir / "generated"
            assert generated_dir.exists()

            with patch(
                "src.extensions.ingestion.review_flow._EXTENSIONS_BASE",
                connector_dir.parent,
            ):
                review.reject(connector_dir.name)
                assert not generated_dir.exists()

    def test_dry_run_validates_model_structure(self) -> None:
        review = ReviewFlow()
        good_model = GeneratedModel(
            model_name="staging.ext_stg_test",
            layer="staging",
            filename="ext_stg_test.sql",
            sql_content="MODEL (\n    name x,\n    kind FULL\n);\nSELECT 1",
            sensitivity_summary={1: 1},
        )
        valid, err = review.dry_run_validate(good_model)
        assert valid is True
        assert err is None

    def test_dry_run_catches_missing_model(self) -> None:
        review = ReviewFlow()
        bad_model = GeneratedModel(
            model_name="staging.ext_stg_test",
            layer="staging",
            filename="ext_stg_test.sql",
            sql_content="SELECT 1 FROM foo",
            sensitivity_summary={1: 1},
        )
        valid, err = review.dry_run_validate(bad_model)
        assert valid is False
        assert "MODEL" in err

    def test_dry_run_catches_missing_kind_full(self) -> None:
        review = ReviewFlow()
        bad_model = GeneratedModel(
            model_name="staging.ext_stg_test",
            layer="staging",
            filename="ext_stg_test.sql",
            sql_content="MODEL (\n    name x\n);\nSELECT 1",
            sensitivity_summary={1: 1},
        )
        valid, err = review.dry_run_validate(bad_model)
        assert valid is False
        assert "kind FULL" in err


# ===========================================================================
# TestSerializationRoundTrip
# ===========================================================================


class TestSerializationRoundTrip:
    """Test ModelPreview serialization and deserialization."""

    def test_roundtrip_preserves_data(self) -> None:
        preview = ModelPreview(
            connector_id="custom-spotify",
            strategy="full_pipeline",
            models=(
                GeneratedModel(
                    model_name="staging.ext_stg_music_spotify",
                    layer="staging",
                    filename="ext_stg_music_spotify.sql",
                    sql_content="SELECT 1",
                    sensitivity_summary={1: 3, 2: 2},
                    depends_on=("raw_music",),
                ),
            ),
            graph_extension=GraphExtension(
                node_ddl=("CREATE NODE TABLE IF NOT EXISTS Track (...)",),
                relationship_ddl=("CREATE REL TABLE IF NOT EXISTS LISTENED_TO (...)",),
                node_names=("Track",),
                relationship_names=("LISTENED_TO",),
            ),
            chromadb_mapping=ChromaDBMapping(
                collection_name="ideas",
                domain="music",
                indexing_fields=("content",),
            ),
            staging_dir="/tmp/test",
            warnings=("some warning",),
            total_models=1,
            sensitivity_summary={1: 3, 2: 2},
        )

        serialized = _serialize_preview(preview)
        deserialized = _deserialize_preview(serialized)

        assert deserialized.connector_id == preview.connector_id
        assert deserialized.strategy == preview.strategy
        assert len(deserialized.models) == 1
        assert deserialized.models[0].model_name == "staging.ext_stg_music_spotify"
        assert deserialized.graph_extension is not None
        assert "Track" in deserialized.graph_extension.node_names
        assert deserialized.chromadb_mapping is not None
        assert deserialized.chromadb_mapping.collection_name == "ideas"
        assert deserialized.warnings == ("some warning",)

    def test_roundtrip_without_graph_extension(self) -> None:
        preview = ModelPreview(
            connector_id="custom-test",
            strategy="staging_only",
            models=(),
            graph_extension=None,
            chromadb_mapping=None,
            staging_dir="/tmp/test",
            warnings=(),
            total_models=0,
        )

        serialized = _serialize_preview(preview)
        deserialized = _deserialize_preview(serialized)

        assert deserialized.graph_extension is None
        assert deserialized.chromadb_mapping is None


# ===========================================================================
# TestHelperFunctions
# ===========================================================================


class TestHelperFunctions:
    """Test utility helper functions."""

    def test_make_connector_slug(self) -> None:
        assert _make_connector_slug("custom-spotify") == "spotify"
        assert _make_connector_slug("custom-my-server") == "my_server"

    def test_find_id_field(self) -> None:
        fields = (
            _make_field("user_id", "VARCHAR"),
            _make_field("name", "VARCHAR"),
        )
        assert _find_id_field(fields) == "user_id"

    def test_find_id_field_prefers_id(self) -> None:
        fields = (
            _make_field("id", "VARCHAR"),
            _make_field("user_id", "VARCHAR"),
        )
        assert _find_id_field(fields) == "id"

    def test_find_title_field(self) -> None:
        fields = (
            _make_field("id", "VARCHAR"),
            _make_field("title", "VARCHAR"),
            _make_field("content", "TEXT"),
        )
        assert _find_title_field(fields) == "title"

    def test_find_detail_field(self) -> None:
        fields = (
            _make_field("id", "VARCHAR"),
            _make_field("content", "TEXT"),
        )
        assert _find_detail_field(fields) == "content"

    def test_find_timestamp_field(self) -> None:
        fields = (
            _make_field("id", "VARCHAR"),
            _make_field("played_at", "TIMESTAMPTZ"),
        )
        assert _find_timestamp_field(fields) == "played_at"

    def test_find_text_fields(self) -> None:
        fields = (
            _make_field("id", "VARCHAR"),
            _make_field("content", "TEXT"),
            _make_field("title", "VARCHAR"),
            _make_field("count", "INTEGER"),
        )
        result = _find_text_fields(fields)
        assert "content" in result
        assert "title" in result
        assert "count" not in result

    def test_build_sensitivity_summary(self) -> None:
        fields = (
            _make_field("id", tier=1),
            _make_field("name", tier=2),
            _make_field("content", tier=3),
            _make_field("source", tier=1),
        )
        summary = _build_sensitivity_summary(fields)
        assert summary == {1: 2, 2: 1, 3: 1}

    def test_build_sensitivity_comments(self) -> None:
        fields = (
            _make_field("id", tier=1),
            _make_field("name", tier=2),
        )
        comments = _build_sensitivity_comments(fields)
        assert "id:" in comments
        assert "tier 1" in comments
        assert "name:" in comments
        assert "tier 2" in comments
        assert "_loaded_at:" in comments
