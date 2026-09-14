import pandas as pd

from .base import ExtractedPage


def extract_csv(file_path: str) -> list[ExtractedPage]:
    df = pd.read_csv(file_path)
    pages: list[ExtractedPage] = []

    total_rows = len(df)

    if total_rows < 1000:
        # Convert to markdown tables, 100 rows per page
        for i in range(0, total_rows, 100):
            chunk = df.iloc[i : i + 100]
            md_table = chunk.to_markdown(index=False)
            pages.append(
                ExtractedPage(
                    page_number=(i // 100) + 1,
                    content=md_table,
                    content_type="table",
                    metadata={
                        "total_rows": total_rows,
                        "chunk_start": i,
                        "chunk_end": min(i + 100, total_rows),
                    },
                )
            )
    else:
        # Generate statistical summary
        summary_lines = [
            f"# Dataset Summary\n**Total Rows**: {total_rows}\n**Total Columns**: {len(df.columns)}\n"  # noqa: E501
        ]

        for col in df.columns:
            summary_lines.append(f"### Column: {col}")
            summary_lines.append(f"- **Type**: {df[col].dtype}")
            if pd.api.types.is_numeric_dtype(df[col]):
                summary_lines.append(f"- **Min**: {df[col].min()}")
                summary_lines.append(f"- **Max**: {df[col].max()}")
                summary_lines.append(f"- **Mean**: {df[col].mean()}")
            else:
                top_5 = df[col].value_counts().head(5)
                summary_lines.append("- **Top 5 Values**:")
                for val, count in top_5.items():
                    summary_lines.append(f"  - {val}: {count}")
            summary_lines.append("")

        summary_lines.append("### Sample Data (First 10 rows)")
        summary_lines.append(df.head(10).to_markdown(index=False))

        content = "\n".join(summary_lines)
        pages.append(
            ExtractedPage(
                page_number=1,
                content=content,
                content_type="text",
                metadata={"is_summary": True, "total_rows": total_rows},
            )
        )

    return pages
