import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db.pool import get_pool

router = APIRouter(prefix="/runs", tags=["Query"])


class RatingRequest(BaseModel):
    rating: int = Field(
        ...,
        ge=1, 
        le=5, 
        description="The user's explicit rating for the generated answer, from 1 to 5.", 
        examples=[5]
    )


@router.patch(
    "/{run_id}/rating",
    summary="Submit user feedback rating",
    description=(
        "Allows end-users to submit a 1-5 star rating for a specific query run. If the user's "
        "explicit rating differs from the automated LLM-as-a-judge score by more than 0.3 "
        "(normalized), the evaluation is flagged with `calibration_needed=True` for human review. "
        "**Errors**: Returns 500 if the database transaction fails."
    ),
    response_description=(
        "A JSON object confirming success and indicating whether calibration is needed."
    )
)
async def update_rating(run_id: UUID, req: RatingRequest) -> Any:  # noqa: ANN401
    pool = get_pool()

    async with pool.acquire() as conn:
        # Check if the run exists in evaluations
        row = await conn.fetchrow(
            "SELECT overall_score, metadata FROM evaluations WHERE run_id = $1", run_id
        )

        if not row:
            # Maybe the judge hasn't run yet. Let's just create an empty evaluation row to store the rating for now, or error out depending on design.  # noqa: E501
            # Assuming the judge runs shortly after generation, but let's UPSERT to be safe.
            await conn.execute(
                """
                INSERT INTO evaluations (run_id, user_rating) 
                VALUES ($1, $2)
                ON CONFLICT (run_id) DO UPDATE SET user_rating = EXCLUDED.user_rating
                """,
                run_id,
                req.rating,
            )
            # Fetch again to do calibration check if it already existed
            row = await conn.fetchrow(
                "SELECT overall_score, metadata FROM evaluations WHERE run_id = $1", run_id
            )
            if not row:
                raise HTTPException(status_code=500, detail="Failed to retrieve evaluation row")

        automated_overall = row["overall_score"]
        current_metadata = row["metadata"] or {}

        if isinstance(current_metadata, str):
            current_metadata = json.loads(current_metadata)

        if automated_overall is not None:
            # Check for calibration needed
            normalized_user_rating = req.rating / 5.0

            if abs(automated_overall - normalized_user_rating) > 0.3:
                current_metadata["calibration_needed"] = True

        # Update row with the rating and potentially new metadata
        await conn.execute(
            """
            UPDATE evaluations 
            SET user_rating = $1, metadata = $2
            WHERE run_id = $3
            """,
            req.rating,
            json.dumps(current_metadata),
            run_id,
        )

    return {
        "status": "success",
        "calibration_needed": current_metadata.get("calibration_needed", False),
    }
