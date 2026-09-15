
# basic FastApi app
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import anthropic
import os
import json
 
app = FastAPI()
client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
 
 
class JobPosting(BaseModel):
    title: str
    company: str
    location: str | None = None
    country: str
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
    country: str
    reason: str   # give one line explanation for why it matched

class DigestResponse(BaseModel):
    top_overall: list[RankedJob]
    by_country: dict[str, list[RankedJob]]
 
 
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
def process_jobs(req: ProcessRequest) -> DigestResponse:
    unique_postings = dedupe(req.postings)

    if not unique_postings:
        return DigestResponse(top_overall=[], by_country={})

    listing_text = "\n".join(
        f"[{i}] {j.title} - {j.company} ({j.location or 'Unknown'}, {j.country}), "
        f"source: {j.source}\n  {j.description[:600] if j.description else 'No description provided.'}"
        for i, j in enumerate(unique_postings)
    )

    prompt = f"""You are filtering and ranking job postings for a final-year
Computer Science / IT student in Ireland, graduating October 2026, with
experience in full-stack development (React Native, FastAPI, Python), an
internship at Medtronic (software engineering, R&D), and interest in
software engineering / backend / ML-adjacent roles.

Here are today's postings:

{listing_text}

STRICT EXCLUSION RULES — reject the posting if:
- Minimum experience required is 2+ years
- Title contains "Senior", "Lead", "Principal", "Staff", "Manager", "Director", "Head of"
- Not a software/engineering/technical role
When in doubt about experience level, EXCLUDE rather than include.

Return ONLY a JSON object (no markdown, no preamble) in this exact shape:
{{
  "top_overall": [
    {{"index": N, "reason": "one short sentence"}}
  ],
  "by_country": {{
    "Ireland": [{{"index": N, "reason": "..."}}],
    "UK": [{{"index": N, "reason": "..."}}],
    "Netherlands": [{{"index": N, "reason": "..."}}],
    "Germany": [{{"index": N, "reason": "..."}}],
    "Canada": [{{"index": N, "reason": "..."}}],
    "US": [{{"index": N, "reason": "..."}}]
  }}
}}

"top_overall" should be your best 5-10 picks across ALL countries, ranked
best first. "by_country" should list every relevant posting for that
country, ranked best first — omit a country key entirely if it has no
relevant postings. If nothing is relevant anywhere, return
{{"top_overall": [], "by_country": {{}}}}."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return DigestResponse(top_overall=[], by_country={})

    def build_ranked(entries: list[dict]) -> list[RankedJob]:
        out = []
        for e in entries:
            idx = e.get("index")
            if idx is None or idx >= len(unique_postings):
                continue
            p = unique_postings[idx]
            out.append(RankedJob(
                title=p.title, company=p.company, url=p.url,
                country=p.country, reason=e.get("reason", ""),
            ))
        return out

    top_overall = build_ranked(parsed.get("top_overall", []))
    by_country = {
        country: build_ranked(entries)
        for country, entries in parsed.get("by_country", {}).items()
    }

    return DigestResponse(top_overall=top_overall, by_country=by_country)