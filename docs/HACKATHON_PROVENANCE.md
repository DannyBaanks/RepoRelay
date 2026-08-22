# Hackathon Provenance Documentation

## Project: RepoRelay

### Submission Period
- Hackathon: All Things Agentic Hackathon
- Devpost: https://allthingsagentichackathon.devpost.com/
- Submission Period: August 2026
- Deadline: August 31, 2026 — 5:00 PM Pacific Time

### Declaration of Originality

This project was created **entirely during the submission period** (August 2026) for the All Things Agentic Hackathon. No pre-existing code, private laboratory implementations, or forked products were incorporated into this repository.

### Git History

The repository was initialized on August 22, 2026, with the first commit establishing the project structure. All subsequent commits represent work done during the hackathon period.

```
git log --oneline
```

### Technologies Used (Mandatory Hackathon Stack)

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| LLM | Gemini | 1.5 Flash (gemini-1.5-flash) | Primary reasoning model via Google ADK |
| Agent Framework | Google ADK | 0.1.0 | Agent orchestration |
| Cloud Runtime | Cloud Run | N/A | Serverless container hosting |
| State Store | Firestore | N/A | Idempotency, event state, retry tracking |
| Web Framework | FastAPI | 0.115.0 | ASGI webhook handler |
| GitHub API | PyGithub | 2.4.0 | GitHub REST API client |
| Language | Python | 3.12+ | Primary implementation language |

### No Pre-existing Code Incorporated

The following were **NOT** used:
- No forked repositories
- No copied private/internal implementations
- No proprietary codebases
- No starter templates beyond standard Python/FastAPI project structure
- No boilerplate from other hackathon submissions

### Standard Development Tools Used

The following standard tools were used (explicitly permitted by rules):
- Git for version control
- VS Code / Cursor as IDE
- Python standard library
- pip for dependency management
- Docker for containerization
- gcloud CLI for deployment
- pytest for testing
- ruff for linting

### AI Coding Assistance

AI coding assistants (including the model generating this documentation) were used for:
- Code generation and scaffolding
- Documentation writing
- Test case generation
- Architecture discussion

All AI-generated code was reviewed, modified, and committed by human developers during the submission period.

### Repository Initialization Timeline

| Date | Action |
|------|--------|
| 2026-08-22 | Repository created at `C:\Development\ISyCo\git\RepoRelay` |
| 2026-08-22 | Initial project structure committed |
| 2026-08-22 | Core modules implemented (config, events, state, webhook) |
| 2026-08-22 | GitHub tools (read/write) implemented |
| 2026-08-22 | Evidence gathering, policy engine, agent, executor implemented |
| 2026-08-22 | FastAPI app entry point created |
| 2026-08-22 | Dockerfile, requirements, README, provenance docs added |

### Verification Commands

```bash
# Verify git history
git log --oneline --all

# Verify no pre-existing directories
ls -la

# Verify all source files created during submission period
git ls-files | xargs -I {} sh -c 'echo "$(git log --format="%ci" -1 -- {}) {}"' | sort
```

### Disclosure Statement

**No nontrivial pre-existing code was incorporated into this project.** All code in this repository was written during the hackathon submission period (August 2026) specifically for the All Things Agentic Hackathon Taskmaster category.

---

*Signed: RepoRelay Team*
*Date: August 22, 2026*