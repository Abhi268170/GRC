# ai_contracts

The request and response models of the AI service's HTTP API. Both the backend (the caller)
and the AI service import this package, so the two can't drift apart.

It contains only Pydantic models and constants: no prompts, no database code, no HTTP code.
It is copied into both images at `/app/ai_contracts` (see the Dockerfiles and compose files).

- `common.py`: shared pieces (usage, errors, company, control and requirement descriptions).
- `tasks.py`: one input model and one output model per single-call task.
- `guide.py`: the guided conversation (system prompt, one model step, stream events).
