
# basic FastApi app
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import anthropic
import os
import json

app = FastAPI()
client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
EXPECTED_KEY = os.getenv("N8N_SHARED_SECRET")

@app.post("/process-jobs")
def process_jobs(req: ProcessRequest, x_api_key: str = Header(None)):
    if x_api_key != EXPECTED_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


class JobPosting(BaseModel):
    title: str
    company: str
    location: str | None = None
    url: str
    source: str   # adzuna / jsearch / linkedin alert
    date_posted: str | None = None
    description: str | None = None


class ProcessRequest(BaseModel):
    postings: list[JobPosting]


class RankedJob(BaseModel):
    title: str
    company: str
    url: str
    reason: str   # give one line explanation for why it matched


def dedupe(postings: list[JobPosting]) -> list[JobPosting]:
    seen = set()
    unique = []

    for j in postings:
        key = (j.title.strip().lower(), j.company.strip().lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique


@app.post("/process-jobs")
def process_jobs(req: ProcessRequest) -> list[RankedJob]:
    unique_postings = dedupe(req.postings)

    if not unique_postings:
        return []
    
    # build a compact listing for prompt
    listing_text = "\n".join(
        f"[{i}] {j.title} - {j.company} ({j.location or 'Unkown Location'}),"
        f"source: {j.source}\n  {j.description[:200] if j.description else 'No description provided.'}"
        for i, j in enumerate(unique_postings)
    )

    prompt = f"""You are filtering job postings for a final-year Computer Science / IT
    student in Ireland, graduating October 2026, with experience in full-stack
    development (React Native, FastAPI, Python), an internship at Medtronic
    (software engineering, R&D), and interest in software engineering / backend /
    ML-adjacent roles.

    Here are today's postings:

    {listing_text}

    Return ONLY a JSON array (no markdown, no preamble) of the postings that are
    genuinely relevant graduate/early-career software roles. For each, include:
    "index" (the [N] from above), "reason" (one short sentence on why it fits).
    Exclude anything senior/unrelated (e.g. senior-only roles, non-software roles).
    If none are relevant, return an empty array []."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        matches = json.loads(raw_text)
    except json.JSONDecodeError:
        return[]
    
    ranked=[]
    for match in matches:
        idx = match.get("index")
        if idx is None or idx >= len(unique_postings):
            continue
        posting = unique_postings[idx]
        ranked.append(RankedJob(
            title=posting.title,
            company = posting.company,
            url = posting.url,
            reason = match.get("reason", ""),
        ))

    return ranked