# Memory RAG is separate from the skill knowledge base

`memory/*.md` is the document corpus. MEMORY.md is only the index. RAG here means: retrieve the few files that match the current task (search/read `memory/`), then answer.

Do not use SkillSet, SkillAlias, ESCO, pgvector skill embeddings, or Ollama skill pipelines for this. Those are market-skill intelligence.

Do not mix the two stores. Assistant corrections never become SkillSet rows; skill vectors never replace memory files.
