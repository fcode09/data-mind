# Controlled improvement, not autonomous self-modification

Explicit thumbs-up/down feedback is stored with the authenticated session and turn identifier. A turn retains its evidence envelope and scope. Free-text feedback is untrusted data, never an executable instruction or runtime system prompt.

A maintainer may select synthetic failed cases into a versioned golden dataset, propose one prompt/classifier change on a feature branch, compare correctness, tenant isolation, groundedness and latency against the current release, and review before promotion. Never train on private user data by default. No runtime code editing or automatic model fine-tuning is enabled. Roll back by restoring the previous reviewed release/configuration; preserve evidence and evaluation results.

Initial gates: zero cross-tenant rows; exact count match to generator oracle; no spoken factual answer without validated evidence; no arbitrary SQL/shell tools; no material regression in measured p95 on the same hardware. Higher model scores alone do not waive safety gates.
