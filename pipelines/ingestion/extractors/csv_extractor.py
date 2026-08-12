"""
CSV extraction via pandas. Small CSVs become paginated markdown tables
(100 rows per ExtractedPage); large CSVs become a statistical summary page
plus a sample-rows page instead of dumping thousands of rows into the
vector store as near-duplicate table chunks.
"""
import io
import logging

import pandas as pd

from pipelines.ingestion.extractors.base import ExtractedPage
from pipelines.ingestion.extractors.markdown import rows_to_markdown_table

logger = logging.getLogger("neuroflow.ingestion.csv")

SMALL_CSV_ROW_THRESHOLD = 1000
ROWS_PER_PAGE = 100
SAMPLE_ROWS = 20
TOP_N_CATEGORICAL = 5


def _column_kinds(df: pd.DataFrame) -> dict[str, str]:
    kinds = {}
    for col in df.columns:
        kinds[col] = "numeric" if pd.api.types.is_numeric_dtype(df[col]) else "text"
    return kinds


def _df_to_markdown_page(df_slice: pd.DataFrame, page_number: int) -> ExtractedPage:
    rows = [df_slice.columns.tolist()] + df_slice.astype(str).values.tolist()
    return ExtractedPage(
        page_number=page_number,
        content=rows_to_markdown_table(rows),
        content_type="table",
        metadata={"source": "csv", "row_start": df_slice.index.min(), "row_end": df_slice.index.max()},
    )


def _summary_page(df: pd.DataFrame, kinds: dict[str, str]) -> ExtractedPage:
    lines = [f"CSV summary — {len(df)} rows, {len(df.columns)} columns.", ""]
    for col in df.columns:
        if kinds[col] == "numeric":
            series = df[col].dropna()
            lines.append(
                f"- **{col}** (numeric): min={series.min():.4g}, max={series.max():.4g}, "
                f"mean={series.mean():.4g}, dtype={df[col].dtype}"
            )
        else:
            top = df[col].astype(str).value_counts().head(TOP_N_CATEGORICAL)
            top_str = ", ".join(f"{val!r}: {count}" for val, count in top.items())
            lines.append(f"- **{col}** (text): top {TOP_N_CATEGORICAL} values — {top_str}")

    return ExtractedPage(
        page_number=0,
        content="\n".join(lines),
        content_type="text",
        metadata={"source": "csv", "region": "summary", "row_count": len(df), "column_kinds": kinds},
    )


def extract_csv(csv_bytes: bytes) -> list[ExtractedPage]:
    df = pd.read_csv(io.BytesIO(csv_bytes))
    kinds = _column_kinds(df)
    pages: list[ExtractedPage] = []

    if len(df) < SMALL_CSV_ROW_THRESHOLD:
        for page_number, start in enumerate(range(0, len(df), ROWS_PER_PAGE), start=1):
            pages.append(_df_to_markdown_page(df.iloc[start : start + ROWS_PER_PAGE], page_number))
    else:
        pages.append(_summary_page(df, kinds))
        pages.append(
            ExtractedPage(
                page_number=1,
                content=rows_to_markdown_table(
                    [df.columns.tolist()] + df.head(SAMPLE_ROWS).astype(str).values.tolist()
                ),
                content_type="table",
                metadata={"source": "csv", "region": "sample_rows", "sample_size": SAMPLE_ROWS},
            )
        )

    return pages
