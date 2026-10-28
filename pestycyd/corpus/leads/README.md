# Composition leads

These inputs reached interesting checker paths but are not independently
claimed as soundness regressions. They stay separate from `regressions/` so a
matrix disagreement cannot be mistaken for a proof that one checker is wrong.

| Input | Why retained | Related upstream report |
| --- | --- | --- |
| `nanoda-prop-rule-forged.ndjson` | Forged proposition recursor rule; useful for combining proof irrelevance with later rule application. | Related family: [sokonanoda #7](https://github.com/intgrah/sokonanoda/issues/7). |
| `cyclic-rec-rule-seed.ndjson` | Seed for cyclic and self-referential recursor-rule mutations. | Not filed as an independent bug. |
| `nested-name-shadow-seed.ndjson` | Seed for temporary nested-name capture across later declarations. | Final exploits: [nanoda #74](https://github.com/ammkrn/nanoda_lib/issues/74), [sokonanoda #10](https://github.com/intgrah/sokonanoda/issues/10), Arena [PR #308](https://github.com/leanprover/lean-kernel-arena/pull/308). |
| `recursor-rule-swap-0.ndjson`, `recursor-rule-swap-1.ndjson` | Adjacent proposition recursor-rule RHS swaps for differential mutation. | Related family: [sokonanoda #7](https://github.com/intgrah/sokonanoda/issues/7). |

When one of these is escalated to a closed false proof, move the minimized
case to `regressions/` and add the exact upstream issue rather than merely a
related-family link.
