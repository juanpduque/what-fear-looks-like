# Vision LLM QA tiers (do not merge / overwrite)

| File | Posters | Models | Role |
|------|--------:|--------|------|
| `nova_qa_sample.csv` | ~119 (8/decade) | Pro, Haiku, Pixtral, Scout | Pilot / nested baseline |
| `nova_qa_large.csv` | ~410 (30/decade) | Pro, Haiku, Pixtral, Scout | Main cross-model comparison |
| `nova_qa_sonnet.csv` | same ids as large | Claude Sonnet 4.5 | Gold captions / typography |
| `nova_qa_maverick.csv` | same ids as large | Llama 4 Maverick | Extra open-weight vision |

All use seed=42 stratified sampling (prefer Lite JSON-error ids).  
`nova_enrich.csv` = full-corpus Nova Lite — separate track.
