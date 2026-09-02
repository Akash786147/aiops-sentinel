# Retrieval strategy comparison

All strategies use the same 25 questions and top-k = 3.

| Strategy | Precision@3 | Recall@3 | File hit rate |
| --- | ---: | ---: | ---: |
| vector | 0.067 | 0.13 | 0.2 |
| lexical | 0.08 | 0.17 | 0.24 |
| hybrid | 0.067 | 0.15 | 0.2 |

The production retriever currently uses normalized hashing-vector similarity. This experiment is retained as evidence for Week 4 analysis; any production change must be tested separately.
