# Run

```bash
./scripts/start.sh
```

UI at **http://localhost:8001** — stop with `./scripts/stop_all.sh`

## .env

Create a `.env` file in the project root before starting:

```
QDRANT_URL=http://34.47.255.166:80
OPENAI_API_KEY=<LiteLLM key>
OPENAI_API_BASE=https://imllm.intermesh.net/v1
SMTP_USER=<Gmail address>
SMTP_PASSWORD=<Gmail app password>
VIOLATION_EMAIL_TO=<email to receive alerts>
SARVAM_API_KEY=<Sarvam AI key>
```

Optional (defaults shown):

```
QDRANT_COLLECTION=indiamart_sops
SOP_SEARCH_COLLECTION=indiamart_kb
REPORTS_COLLECTION=indiamart_reports
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIM=1536
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
DATABASE_PATH=database/jobs.db
```
