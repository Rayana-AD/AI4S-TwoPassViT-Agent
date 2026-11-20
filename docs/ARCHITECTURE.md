# Architecture (Mermaid source)

GitHub renders Mermaid in `README.md` / `README_zh.md`. This file mirrors the diagrams for offline edit or `mmdc` export:

```bash
# optional: npm i -g @mermaid-js/mermaid-cli
mmdc -i docs/architecture-entry.mmd -o docs/gallery/architecture_entry.png
```

Diagrams cover: (1) `run_pipeline` dual-track, (2) per-object two-pass, (3) ULF detail, (4) Debater v0–v2 bridge.