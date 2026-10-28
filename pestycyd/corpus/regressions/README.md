# Regression corpus

These small, hand-audited cases came from the `arena-candidate` investigation.
They are seeds and regression inputs, not an assertion that current upstream
versions still contain the bugs.

| Input | Construction and historical result | Upstream tracking |
| --- | --- | --- |
| `nanoda-proj-rec-rule.ndjson` | Nanoda accepted an invalid imported recursor rule; not by itself a proof of `False`. | Related root cause: [nanoda #47](https://github.com/ammkrn/nanoda_lib/issues/47), fixed by [PR #48](https://github.com/ammkrn/nanoda_lib/pull/48). |
| `nanoda-proj-rec-rule-prefix.ndjson` | Prefix retaining the malformed rule for composition with another bug. | Same root cause as [nanoda #47](https://github.com/ammkrn/nanoda_lib/issues/47). |
| `nanoda-proj-rec-rule-attempt-false.ndjson` | Negative escalation attempt: Nanoda rejects the final theorem. Kept so fuzzing can mutate the almost-working construction. | Same root cause as [nanoda #47](https://github.com/ammkrn/nanoda_lib/issues/47); not reported as a consistency bug. |
| `nanoda-forged-quot-ind-false.ndjson` | A forged, forward-referencing `Quot.ind` gave Nanoda a closed proof of `False`. | [nanoda #73](https://github.com/ammkrn/nanoda_lib/issues/73), fixed by [PR #75](https://github.com/ammkrn/nanoda_lib/pull/75), added to Arena in [PR #308](https://github.com/leanprover/lean-kernel-arena/pull/308). |
| `sokonanoda-infer-closure-false.ndjson` | Sokonanoda `492227c` accepted an axiom-free closed proof of `∀ P : Prop, P` because closure context was ignored. | [sokonanoda #8](https://github.com/intgrah/sokonanoda/issues/8), Arena [PR #307](https://github.com/leanprover/lean-kernel-arena/pull/307). |
| `sokonanoda-level-substitution.ndjson` | Minimal wrong acceptance caused by ignoring a closure's universe substitution. | [sokonanoda #9](https://github.com/intgrah/sokonanoda/issues/9), Arena [PR #307](https://github.com/leanprover/lean-kernel-arena/pull/307). |
| `sokonanoda-level-substitution-false.ndjson` | The same independent bug escalated to an axiom-free closed proof of `False`. | [sokonanoda #9](https://github.com/intgrah/sokonanoda/issues/9), Arena [PR #307](https://github.com/leanprover/lean-kernel-arena/pull/307). |
| `sokonanoda-dangling-expr-ids.ndjson` | Found and reduced automatically by Pestycyd. Sokonanoda `9a021b6` accepted a recursor whose serialized type and rule RHS point to missing expression IDs `14` and `20`; the official kernel rejected it and Nanoda `d0a02cc` trapped on the malformed table. | Not filed upstream yet. |
| `tenet-sampled-primitive-false.ndjson` | Tenet 0.11.3 accepted 69 declarations ending in a closed false proof through sampled primitive validation. | Not filed upstream yet. |
| `pestka-loose-bvar-historical-hang.ndjson` | Invalid loose bound variable reached reduction and made old Pestka VM/native loop. Nanoda-family and Sokonanoda robustness reports used the same class of input. | [nanoda #72](https://github.com/ammkrn/nanoda_lib/issues/72), [sokonanoda #6](https://github.com/intgrah/sokonanoda/issues/6), Arena [PR #306](https://github.com/leanprover/lean-kernel-arena/pull/306). |

Always run the corpus against freshly fingerprinted binaries. A historical
status is provenance, not an oracle for a new version.

```bash
uv run pestycyd --config pestycyd.toml matrix corpus/regressions --report regressions.json
```

Generated boundaries are kept as recipes rather than multi-megabyte fixtures:

- `uv run pestycyd generate deep-binder 16382 /tmp/deep.ndjson` covers the
  old Pestka loose-range saturation bug, fixed and bumped in Arena
  [PR #312](https://github.com/leanprover/lean-kernel-arena/pull/312).
- `uv run pestycyd generate con-k-params 10000 /tmp/WideK.lean` recreates the
  con-leche wide-`fvar` scaling candidate; it has not been filed upstream.
