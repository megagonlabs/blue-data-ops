from __future__ import annotations

import builtins
import gc
import math
import weakref
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, ClassVar, cast

import pytest

import blue_data_ops
import blue_data_ops.operators as operators
from blue_data_ops.operators import (
    DiscoveryError,
    EmbeddingDiscoveryError,
    Operator,
    OperatorCard,
    OperatorEmbedder,
    OperatorEmbeddingIndex,
    OperatorError,
    OperatorRegistry,
)
from blue_data_ops.operators.embedding_discovery import (
    _card_document,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import Attributes, DataBundle, Properties


class _ProbeOperator(Operator):
    name: ClassVar[str] = "probe"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return input_data


class _ScriptedEmbedder:
    def __init__(
        self,
        outputs: Sequence[object] = (),
        *,
        space_id: object = "test-space-v1",
        space_error: BaseException | None = None,
    ) -> None:
        self.outputs = list(outputs)
        self.space_value = space_id
        self.space_error = space_error
        self.space_reads = 0
        self.calls: list[tuple[str, ...]] = []

    @property
    def space_id(self) -> Any:
        self.space_reads += 1
        if self.space_error is not None:
            raise self.space_error
        return self.space_value

    def __call__(self, texts: tuple[str, ...]) -> Any:
        self.calls.append(texts)
        if not self.outputs:
            raise AssertionError("unexpected embedder call")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


class _ListViewRegistry(OperatorRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.view: list[OperatorCard] | None = None
        self.list_error: BaseException | None = None
        self.list_calls = 0

    def list_cards(self) -> list[OperatorCard]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        if self.view is not None:
            return list(self.view)
        return super().list_cards()


class _GetViewRegistry(OperatorRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.replacements: dict[str, OperatorCard | None] = {}
        self.get_error: BaseException | None = None

    def get_card(self, operator_id: str) -> OperatorCard | None:
        if self.get_error is not None:
            raise self.get_error
        if operator_id in self.replacements:
            return self.replacements[operator_id]
        return super().get_card(operator_id)


def _register(
    registry: OperatorRegistry,
    name: str,
    version: str = "1.0.0",
    *,
    description: str = "",
    tags: Sequence[str] = (),
    when: str = "",
) -> OperatorCard:
    class _NamedProbe(_ProbeOperator):
        pass

    _NamedProbe.name = name
    _NamedProbe.description = description
    operator = _NamedProbe()
    return registry.register(operator, version, tags=tags, when_to_invoke=when)


def _vectors(count: int) -> list[list[float]]:
    return [[float(index + 1), 1.0] for index in range(count)]


def _build(
    registry: OperatorRegistry,
    *outputs: object,
    space_id: object = "test-space-v1",
) -> tuple[OperatorEmbeddingIndex, _ScriptedEmbedder]:
    embedder = _ScriptedEmbedder(outputs, space_id=space_id)
    return OperatorEmbeddingIndex.build(registry, embedder), embedder


def test_public_surface_is_operators_only_and_error_has_both_bases() -> None:
    assert operators.OperatorEmbedder is OperatorEmbedder
    assert operators.OperatorEmbeddingIndex is OperatorEmbeddingIndex
    assert operators.EmbeddingDiscoveryError is EmbeddingDiscoveryError
    assert "OperatorEmbedder" in operators.__all__
    assert "OperatorEmbeddingIndex" in operators.__all__
    assert "EmbeddingDiscoveryError" in operators.__all__
    assert not hasattr(blue_data_ops, "OperatorEmbeddingIndex")

    error = EmbeddingDiscoveryError("BACKEND_MISMATCH")
    assert isinstance(error, DiscoveryError)
    assert isinstance(error, OperatorError)
    assert error.reason == "BACKEND_MISMATCH"


def test_protocol_accepts_the_documented_callable_shape() -> None:
    embedder: OperatorEmbedder = _ScriptedEmbedder()
    assert embedder.space_id == "test-space-v1"


def test_build_is_the_only_supported_construction_path() -> None:
    registry = OperatorRegistry()
    card = _register(registry, "one")
    index, _ = _build(registry, [[1.0]], [[1.0]])

    with pytest.raises(TypeError, match=r"OperatorEmbeddingIndex\.build"):
        cast(Any, OperatorEmbeddingIndex)(**vars(index))
    with pytest.raises(TypeError, match=r"OperatorEmbeddingIndex\.build"):
        replace(index, _vectors=())

    assert index.find("query") == [card]


def test_card_document_golden_bytes() -> None:
    card = OperatorCard(
        operator_id='quote"slash\\@1.0.0',
        name='quote"slash\\',
        version="1.0.0",
        description="平均",
        tags=(),
        when_to_invoke="line1\nline2",
    )
    expected = (
        'name: "quote\\"slash\\\\"\n'
        'when_to_invoke: "line1\\nline2"\n'
        'description: "平均"\n'
        "tags: []\n"
    )
    assert _card_document(card).encode("utf-8") == expected.encode("utf-8")


def test_card_document_empty_fields_golden() -> None:
    card = OperatorCard(
        operator_id="custom@1.0.0",
        name="custom",
        version="1.0.0",
        description="",
    )
    assert _card_document(card) == (
        'name: "custom"\nwhen_to_invoke: ""\ndescription: ""\ntags: []\n'
    )


def test_build_batches_exact_documents_in_registry_order() -> None:
    registry = OperatorRegistry()
    second = _register(
        registry,
        'b"slash\\',
        description="平均",
        when="line1\nline2",
    )
    first = _register(
        registry,
        "alpha",
        description="plain",
        tags=("domain-test", "flow-head"),
    )
    index, embedder = _build(registry, [[1.0, 0.0], [0.0, 1.0]])

    assert index.registry is registry
    assert embedder.calls == [(_card_document(first), _card_document(second))]
    expected_lines = [
        'name: "b\\"slash\\\\"\n',
        'when_to_invoke: "line1\\nline2"\n',
        'description: "平均"\n',
        "tags: []\n",
    ]
    assert embedder.calls[0][1].encode("utf-8") == "".join(expected_lines).encode()
    assert "@1.0.0" not in embedder.calls[0][0]
    assert "@1.0.0" not in embedder.calls[0][1]


def test_build_callback_preserves_non_sorted_tag_order_in_literal_bytes() -> None:
    registry = OperatorRegistry()
    _register(
        registry,
        "ordered",
        description="平均",
        tags=("flow-zeta", "domain-alpha"),
        when="records arrive",
    )
    _, embedder = _build(registry, ((1.0, 0.0),))

    expected = (
        'name: "ordered"\n'
        'when_to_invoke: "records arrive"\n'
        'description: "平均"\n'
        'tags: ["flow-zeta","domain-alpha"]\n'
    )
    assert embedder.calls == [(expected,)]
    assert embedder.calls[0][0].encode("utf-8") == expected.encode("utf-8")


def test_build_reads_the_registry_card_list_once() -> None:
    registry = _ListViewRegistry()
    _register(registry, "one")
    embedder = _ScriptedEmbedder([((1.0, 0.0),)])

    OperatorEmbeddingIndex.build(registry, embedder)

    assert registry.list_calls == 1


def test_equal_documents_share_vectors_but_pinned_identity_breaks_ties() -> None:
    registry = OperatorRegistry()
    v1 = _register(registry, "same", "1.0.0", description="equal")
    v2 = _register(registry, "same", "2.0.0", description="equal")
    index, embedder = _build(
        registry,
        [[1.0, 0.0], [1.0, 0.0]],
        [[1.0, 0.0]],
    )

    assert embedder.calls[0][0] == embedder.calls[0][1]
    found = index.find("same")
    assert found == [v2, v1]
    assert found[0] is registry.get_card("same@2.0.0")
    assert found[1] is registry.get_card("same@1.0.0")


def test_build_rejects_wrong_registry_type_before_embedding() -> None:
    embedder = _ScriptedEmbedder([[[1.0]]])
    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(cast(OperatorRegistry, object()), embedder)
    assert caught.value.reason == "BACKEND_MISMATCH"
    assert embedder.calls == []


def test_build_rejects_duplicate_ids_before_embedding() -> None:
    registry = _ListViewRegistry()
    card = _register(registry, "one")
    registry.view = [card, card]
    embedder = _ScriptedEmbedder([[[1.0], [1.0]]])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "BACKEND_MISMATCH"
    assert embedder.calls == []


def test_build_rejects_equal_foreign_card_before_embedding() -> None:
    registry = _ListViewRegistry()
    card = _register(registry, "one")
    registry.view = [replace(card)]
    embedder = _ScriptedEmbedder([[[1.0]]])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "BACKEND_MISMATCH"
    assert embedder.calls == []


def test_build_rejects_malformed_card_and_registry_inspection_error() -> None:
    registry = _ListViewRegistry()
    registry.view = [cast(OperatorCard, object())]
    embedder = _ScriptedEmbedder([[[1.0]]])
    with pytest.raises(EmbeddingDiscoveryError) as malformed:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert malformed.value.reason == "BACKEND_MISMATCH"
    assert embedder.calls == []

    registry.list_error = RuntimeError("private registry detail")
    with pytest.raises(EmbeddingDiscoveryError) as failed:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert failed.value.reason == "BACKEND_MISMATCH"
    assert "private registry detail" not in str(failed.value)
    assert embedder.calls == []


def test_new_registration_makes_index_stale_before_query_embedding() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0, 0.0]])
    _register(registry, "two")

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert len(embedder.calls) == 1


@pytest.mark.parametrize("mutation", ["foreign", "reorder", "remove"])
def test_changed_list_view_makes_index_stale(mutation: str) -> None:
    registry = _ListViewRegistry()
    first = _register(registry, "alpha")
    second = _register(registry, "beta")
    index, embedder = _build(registry, _vectors(2))

    if mutation == "foreign":
        registry.view = [replace(first), second]
    elif mutation == "reorder":
        registry.view = [second, first]
    else:
        registry.view = [first]

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert len(embedder.calls) == 1


def test_get_card_replacement_and_failure_make_index_stale() -> None:
    registry = _GetViewRegistry()
    card = _register(registry, "one")
    index, embedder = _build(registry, [[1.0]])

    registry.replacements[card.operator_id] = replace(card)
    with pytest.raises(EmbeddingDiscoveryError) as replaced:
        index.find("query")
    assert replaced.value.reason == "STALE_INDEX"

    registry.replacements.clear()
    registry.get_error = RuntimeError("private lookup detail")
    with pytest.raises(EmbeddingDiscoveryError) as failed:
        index.find("query")
    assert failed.value.reason == "STALE_INDEX"
    assert "private lookup detail" not in str(failed.value)
    assert len(embedder.calls) == 1


def test_document_mutation_makes_index_stale() -> None:
    registry = OperatorRegistry()
    card = _register(registry, "one", description="before")
    index, embedder = _build(registry, [[1.0]])
    object.__setattr__(card, "description", "after")

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert len(embedder.calls) == 1


def test_list_inspection_failure_after_build_is_sanitized_stale() -> None:
    registry = _ListViewRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]])
    registry.list_error = RuntimeError("private list detail")

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert "private list detail" not in str(caught.value)
    assert len(embedder.calls) == 1


def test_exact_and_tags_filter_before_query_embedding() -> None:
    registry = OperatorRegistry()
    first = _register(registry, "alpha", tags=("domain-one", "flow-head"))
    _register(registry, "beta", tags=("domain-one", "flow-tail"))
    _register(registry, "gamma", tags=("domain-two", "flow-head"))
    index, embedder = _build(
        registry,
        [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
        [[1.0, 0.0]],
    )

    found = index.find("query", tags=[" DOMAIN-ONE ", "flow-HEAD", "flow-head"])
    assert found == [first]
    assert len(embedder.calls) == 2

    no_candidates = index.find("query", tags=["domain-missing"])
    assert no_candidates == []
    assert len(embedder.calls) == 2


@pytest.mark.parametrize("token", ["BAD TAG", "  ", "nohyphen", ""])
def test_malformed_filter_tag_raises_discovery_error(token: str) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]])

    with pytest.raises(DiscoveryError):
        index.find("query", tags=[token])
    assert len(embedder.calls) == 1


def test_blank_query_paths_do_not_embed_query() -> None:
    registry = OperatorRegistry()
    beta_v1 = _register(registry, "beta", "1.0.0", tags=("domain-one",))
    beta_v2 = _register(registry, "beta", "2.0.0", tags=("domain-one",))
    alpha = _register(registry, "alpha", tags=("domain-one",))
    index, embedder = _build(registry, _vectors(3))

    assert index.find("   ") == []
    assert index.find("", tags=[]) == []
    assert index.find("", tags=["domain-one"]) == [alpha, beta_v2, beta_v1]
    assert len(embedder.calls) == 1


def test_nonblank_query_preserves_surrounding_whitespace_for_the_embedder() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]], [[1.0]])

    assert index.find("  query  ")
    assert embedder.calls[1] == ("  query  ",)


def test_cosine_ranking_has_no_positive_score_threshold() -> None:
    registry = OperatorRegistry()
    aligned = _register(registry, "aligned")
    diagonal = _register(registry, "diagonal")
    opposite = _register(registry, "opposite")
    index, _ = _build(
        registry,
        [[1.0, 0.0], [100.0, 100.0], [-1.0, 0.0]],
        [[1.0, 0.0]],
    )

    assert index.find("query") == [aligned, diagonal, opposite]


def test_equal_cosine_scores_tie_by_name_then_version_descending() -> None:
    registry = OperatorRegistry()
    beta_v1 = _register(registry, "beta", "1.0.0")
    beta_v2 = _register(registry, "beta", "2.0.0")
    alpha = _register(registry, "alpha")
    index, _ = _build(
        registry,
        [[1.0, 0.0], [10.0, 0.0], [2.0, 0.0]],
        [[1.0, 0.0]],
    )

    assert index.find("query") == [alpha, beta_v2, beta_v1]


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        1,
        "vector",
        {},
        [],
        [[1.0], [1.0]],
        [1.0],
        [[]],
        [[True]],
        [["1.0"]],
        [[object()]],
        [[math.nan]],
        [[math.inf]],
        [[-math.inf]],
        [[0.0, 0.0]],
    ],
)
def test_build_rejects_invalid_vector_results(invalid: object) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    embedder = _ScriptedEmbedder([invalid])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "INVALID_RESULT"
    assert str(invalid) not in str(caught.value)


def test_build_rejects_unequal_vector_dimensions() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    _register(registry, "two")
    embedder = _ScriptedEmbedder([[[1.0], [1.0, 0.0]]])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "INVALID_RESULT"


def test_non_list_sequences_are_valid_vector_results() -> None:
    registry = OperatorRegistry()
    card = _register(registry, "one")
    index, embedder = _build(
        registry,
        ((1.0, 0.0),),
        ((1.0, 0.0),),
    )

    assert index.find("query") == [card]
    assert len(embedder.calls) == 2


def test_build_rejects_an_outer_generator_result() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    outer = (vector for vector in ([1.0],))
    embedder = _ScriptedEmbedder([outer])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "INVALID_RESULT"


def test_build_rejects_an_inner_generator_result() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    inner = (component for component in (1.0,))
    embedder = _ScriptedEmbedder([[inner]])

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "INVALID_RESULT"


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        [[1.0], [1.0]],
        [[]],
        [[False]],
        [["private vector"]],
        [[math.nan]],
        [[math.inf]],
        [[0.0, 0.0]],
        [[1.0, 0.0, 0.0]],
    ],
)
def test_query_rejects_invalid_vector_results(invalid: object) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, _ = _build(registry, [[1.0, 0.0]], invalid)

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "INVALID_RESULT"
    assert str(invalid) not in str(caught.value)


def test_callback_exceptions_are_sanitized_by_stage() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")

    build_embedder = _ScriptedEmbedder([RuntimeError("private build detail")])
    with pytest.raises(EmbeddingDiscoveryError) as build_error:
        OperatorEmbeddingIndex.build(registry, build_embedder)
    assert build_error.value.reason == "BUILD_FAILED"
    assert "private build detail" not in str(build_error.value)
    assert build_error.value.__cause__ is None

    index, _ = _build(
        registry,
        [[1.0]],
        RuntimeError("private query detail"),
    )
    with pytest.raises(EmbeddingDiscoveryError) as query_error:
        index.find("query")
    assert query_error.value.reason == "QUERY_FAILED"
    assert "private query detail" not in str(query_error.value)
    assert query_error.value.__cause__ is None


class _StrSubclass(str):
    pass


@pytest.mark.parametrize("invalid", [None, 1, True, "", "   ", _StrSubclass("space")])
def test_build_rejects_invalid_space_id(invalid: object) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    embedder = _ScriptedEmbedder([[[1.0]]], space_id=invalid)

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "BUILD_FAILED"
    assert embedder.calls == []
    assert embedder.space_reads == 1


def test_build_sanitizes_space_id_property_failure() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    embedder = _ScriptedEmbedder(
        [[[1.0]]],
        space_error=RuntimeError("private property detail"),
    )

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorEmbeddingIndex.build(registry, embedder)
    assert caught.value.reason == "BUILD_FAILED"
    assert "private property detail" not in str(caught.value)
    assert embedder.calls == []
    assert embedder.space_reads == 1


@pytest.mark.parametrize("changed", [None, 1, "", " ", _StrSubclass(" space "), "space"])
def test_changed_or_invalid_space_id_makes_index_stale(changed: object) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]], space_id=" space ")
    embedder.space_value = changed

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert len(embedder.calls) == 1
    assert embedder.space_reads == 2


def test_space_id_property_failure_after_build_is_sanitized_stale() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]])
    embedder.space_error = RuntimeError("private changed property")

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"
    assert "private changed property" not in str(caught.value)
    assert len(embedder.calls) == 1


def test_leading_and_trailing_space_in_space_id_is_significant() -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    index, embedder = _build(registry, [[1.0]], [[1.0]], space_id=" space ")

    assert index.find("query")
    embedder.space_value = "space"
    with pytest.raises(EmbeddingDiscoveryError) as caught:
        index.find("query")
    assert caught.value.reason == "STALE_INDEX"


def test_empty_registry_never_calls_embedder_but_keeps_checks() -> None:
    registry = OperatorRegistry()
    index, embedder = _build(registry)

    assert index.registry is registry
    assert index._dimension is None  # pyright: ignore[reportPrivateUsage]
    assert index.find("query") == []
    assert index.find("", tags=["domain-one"]) == []
    assert embedder.calls == []
    assert embedder.space_reads == 3

    with pytest.raises(DiscoveryError):
        index.find("query", tags=["bad tag"])
    assert embedder.calls == []


def test_empty_registry_detects_registry_and_space_changes() -> None:
    registry = OperatorRegistry()
    index, embedder = _build(registry)
    _register(registry, "one")
    with pytest.raises(EmbeddingDiscoveryError) as registry_stale:
        index.find("query")
    assert registry_stale.value.reason == "STALE_INDEX"
    assert embedder.calls == []

    other_registry = OperatorRegistry()
    other_index, other_embedder = _build(other_registry)
    other_embedder.space_value = "changed-space"
    with pytest.raises(EmbeddingDiscoveryError) as space_stale:
        other_index.find("query")
    assert space_stale.value.reason == "STALE_INDEX"
    assert other_embedder.calls == []


def test_build_and_find_callback_counts_and_query_vector_is_not_retained() -> None:
    class _WeakVector(list[float]):
        pass

    registry = OperatorRegistry()
    _register(registry, "one")
    query_vector = _WeakVector([1.0, 0.0])
    query_ref = weakref.ref(query_vector)
    index, embedder = _build(registry, [[1.0, 0.0]], [query_vector])
    del query_vector

    before_fields = tuple(index.__dict__)
    assert index.find("query")
    gc.collect()

    assert query_ref() is None
    assert tuple(index.__dict__) == before_fields
    assert len(embedder.calls) == 2
    assert len(embedder.calls[0]) == 1
    assert embedder.calls[1] == ("query",)
    assert embedder.space_reads == 2


def test_index_does_not_open_files_or_load_skill_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = OperatorRegistry()
    _register(registry, "one")
    embedder = _ScriptedEmbedder([[[1.0]], [[1.0]]])

    def refuse_open(*args: object, **kwargs: object) -> Any:
        raise AssertionError("index opened a file")

    monkeypatch.setattr(builtins, "open", refuse_open)
    index = OperatorEmbeddingIndex.build(registry, embedder)
    assert index.find("query")
    assert "OperatorSkillLoader" not in vars(operators)
