# Pestycyd

**Pest control for Lean kernels.**

*Pestycyd* is Polish for **pesticide**. The name is deliberate: the tool grew
out of Pestka's soundness harness and now hunts bugs across every kernel, not
only Pestka.

Pestycyd runs `lean4export` NDJSON inputs through independent Lean kernel
implementations, creates structure-aware mutations, records reproducible
findings, grows an instrumentation-guided corpus, and minimizes cases. It is
checker-neutral: Pestka, the official kernel, Lean4Lean, Nanoda, Sokonanoda,
Kefir, MathGraph, Tenet and the `con-*` checkers are ordinary configured
targets.

The important distinction is explicit throughout the tool:

- `guaranteed-reject`: the mutation is invalid by construction; an acceptance
  is a soundness finding;
- `guaranteed-accept`: the transformation preserves validity; a rejection is
  a completeness finding;
- `differential`: disagreement is a lead, not proof that any checker is wrong.

An exit code is never a verdict on its own when a target requires verdict
output. In particular, exit code 1 without a `rejected:` line is a runner
error, not a rejection.

## Quick start

```bash
uv sync --locked
uv run pestycyd --config pestycyd.toml doctor
uv run pestycyd --config pestycyd.toml matrix corpus/good
uv run pestycyd --config pestycyd.toml campaigns
uv run pestycyd --config pestycyd.toml hunt corpus/good \
  --campaign closedness --campaign metadata-boundaries \
  --iterations 1000 --max-depth 3
uv run pestycyd --config pestycyd.toml hunt corpus/regressions \
  --seed-policy consensus --iterations 1000
uv run pestycyd --config pestycyd.toml minimize finding.ndjson minimal.ndjson \
  --expect official=reject --expect nanoda=accept
```

`uv.lock` is committed; normal development and CI use `uv run --locked ...`.

## Configuration

Copy `pestycyd.example.toml` and use argv arrays: commands never pass through
a shell. Paths and working directories are relative to the configuration
file. `{file}` must occur in either the command or an environment value. The
example contains every checker used during the original Pestka audit; only the
two native Pestka cores are enabled by default. A disabled target can still be
selected explicitly with `--kernel NAME`.

```toml
version = 1

[defaults]
timeout = 20.0
state = ".pestycyd"

[kernels.pestka]
command = ["../.build/target/release/main", "{file}", "1", "old"]
verdict = "required"

[kernels.kefir]
command = ["kefir", "--axiom-policy=allow-all-declared-axioms"]
env = { IN = "{file}" }
verdict = "none"
enabled = false

[kernels.tenet]
command = ["tenet", "check", "{file}", "--quiet"]
verdict = "none"

[kernels.tenet.exit_codes]
accept = 0
reject = 1
decline = 4
```

`required` means the process must print a recognized verdict matching its
exit code. `optional` falls back to the conventional 0/1/2 mapping when no
verdict is printed. `none` always uses the exit code. `exit_codes` handles
checkers such as Tenet whose explicit decline is not code 2.

## Instrumentation and the fuzzing loop

Instrumentation is optional per kernel. `{run_dir}` names a fresh private
directory for one execution and can be used in command arguments and
environment variables. A source-instrumented checker can emit stable feature
IDs directly:

```toml
[kernels.pestka-instrumented]
command = ["../pestka-cov", "{file}", "1", "old"]
verdict = "required"
env = { PESTYCYD_TRACE = "{run_dir}/trace" }

[kernels.pestka-instrumented.feedback]
format = "lines"
path = "{run_dir}/trace"
required = true
```

Each non-empty line is one feature; semantic points such as
`decl.safe.closed`, `whnf.delta`, or `recursor.rule.checked` are ideal. For
compiler or sanitizer coverage use `format = "bitmap"`: every non-zero byte
offset becomes a feature and counter values are bucketed. Large native profiles
can use `format = "bitmap-chunks"`; Pestycyd hashes non-zero 64-byte chunks,
retaining change feedback without allocating a feature string for every
metadata byte. The first 128 bytes are treated as a volatile native-profile
header and skipped. Instead of `path`,
`command = [...]` may run a postprocessor (for example `llvm-profdata` plus
`llvm-cov`); its stdout is interpreted in the selected format.

An LLVM-instrumented Pestka needs no manual source edits. The included adapter
builds it separately from the release binary:

```bash
adapters/pestka/build-coverage /path/to/pestka
```

The adapter uses `AVER` when set (and otherwise `aver` from PATH). To
instrument an already generated, known-good `.build/Cargo.toml` without
running Aver again:

```bash
PESTYCYD_REUSE_GENERATED=1 adapters/pestka/build-coverage /path/to/pestka
```

Point `LLVM_PROFILE_FILE` at the run directory and use the included converter:

```toml
[kernels.pestka-llvm]
command = ["../.build-pestycyd/target/release/main", "{file}", "1", "old"]
verdict = "required"
env = { LLVM_PROFILE_FILE = "{run_dir}/pestycyd-%p-%m.profraw" }

[kernels.pestka-llvm.feedback]
format = "lines"
command = [
  "pestycyd-llvm-feedback",
  "../.build-pestycyd/target/release/main",
  "{run_dir}/*.profraw",
  "--source-root", "../.build-pestycyd/generated",
  "--only-source-root",
]
required = true
```

The converter discovers the matching `llvm-profdata` and `llvm-cov` from PATH
or Rust's `llvm-tools-preview` component. LLVM export is deliberately the
high-fidelity, slower mode; a native bitmap or semantic line trace is the hot
loop mode for long campaigns.

`hunt` seeds the known feature set with accepted inputs. A mutant that adds
features is stored under `.pestycyd/corpus/` and, up to `--max-depth`, becomes
a new mutation parent. `--max-children` bounds frontier growth. A disagreement,
invalid acceptance, crash, timeout, or process error is stored independently
under `.pestycyd/findings/`. Thus code coverage guides exploration but never
becomes a soundness oracle.

By default, every selected kernel must accept a seed. `--seed-policy consensus`
also admits seeds that every kernel rejects, which makes repaired historical
reproductions useful as coverage-guided starting points. `--seed-policy any`
admits non-fatal baseline disagreement as well; `--seed-policy all` also admits
crashes and runner errors when the purpose of mutation is to repair an almost
working historical input. `--behavior-feedback` lets normalized outcome changes
grow a release-only corpus when no instrumented checker is available.

`--protect-final-goal` freezes the last theorem declaration and the expression
graph of its type while mutations continue attacking the environment it relies
on. Initial mutations are scheduled round-robin across seeds, so one large
export cannot starve smaller cases. `--semantic-only` keeps crash and timeout
noise out of findings without removing it from search feedback.

## Built-in corpus and generators

`corpus/regressions/` contains confirmed historical bugs and negative
escalation attempts. `corpus/leads/` contains composition material that is not
itself a soundness claim. Their READMEs link every filed upstream issue and
mark cases that were never filed.

The large boundary families are generated on demand:

```bash
uv run pestycyd generate deep-binder 16382 /tmp/deep.ndjson
uv run pestycyd generate con-k-params 10000 /tmp/WideK.lean
```

The structural campaigns from Pestka's `arena-candidate` branch were ported as
`expression-structure`, `declaration-structure`, and `inductive-structure`.
`expression-structure` truncates at the affected declaration for isolated
diagnosis; `expression-structure-full` preserves downstream declarations and
is the end-to-end variant for escalating old `False` reproductions.
They remain `differential`; only closedness and duplicate checked universe
parameters currently carry the stronger `guaranteed-reject` oracle.

The stateful campaigns attack relationships that single-field fuzzers miss:
`declaration-replay` and `declaration-shadow-copy` exercise duplicate environment
entries, `inductive-block-crosswire` transplants scope-compatible recursor
semantics, and `intern-table-shadowing` inserts a second expression under an
already-used intern ID immediately before a declaration consumes it. The latter
found the checked-in `sokonanoda-dangling-expr-ids.ndjson` regression without
reading Sokonanoda's source; Pestycyd then reduced it from 35 lines to six.

## Findings

`hunt` stores each novel interesting input under its SHA-256:

```text
.pestycyd/
  runs.jsonl
  corpus/
    2ac4....ndjson
    2ac4....json
  findings/
    8dc1....ndjson
    8dc1....json
```

The sidecar records the seed, campaign, exact mutation, kernel configuration,
outcomes, timing, output tail, and executable fingerprints where available.
Re-running the same content updates neither artifact, so parallel or repeated
campaigns naturally deduplicate.

## Development

```bash
uv run --locked python -m unittest discover -s tests -v
```

