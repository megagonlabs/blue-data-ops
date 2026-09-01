# Runnable examples

Run these commands from `lib/` after following the main README installation steps.

- `python examples/core_quickstart.py`: filtering, aggregation, text normalization, and set operations; base install.
- `python examples/sqlite_quickstart.py`: a temporary ten-row SQLite database, registry discovery, and an insert; base install.
- `python examples/ml_quickstart.py`: local decision-tree classification; install `[ml]`.
- `python examples/vector_quickstart.py`: similarity from supplied embeddings, with no model download; install `[vector]`.
- `python examples/refinement.py`: credential-free multipart, routing, and registry-driven refinement; base install.
- `python examples/nl2llm.py`: live natural-language-to-JSON request; install `[llm]` and set `OPENAI_API_KEY`.
- `python examples/nl2sql_sqlite.py`: live SQL generation against the temporary SQLite schema; install `[llm]` and set `OPENAI_API_KEY`. Add `--execute` to run the generated query.
- `python examples/semantic_filter.py`: live semantic filtering; install `[llm]` and set `OPENAI_API_KEY`.

The live-provider examples incur provider traffic. Their model can be changed through the properties shown in each file.

`coverage.json` is the machine-checked map from each example to the operator IDs it exercises. It also names tag axes that belong in the generated reference but do not need a dedicated runnable example.
