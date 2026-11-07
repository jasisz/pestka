<p align="center">
  <img src="logo.svg" alt="" width="96">
</p>

<h1 align="center">Pestka</h1>

<p align="center">
  A Lean 4 kernel, written in <a href="https://github.com/jasisz/aver">Aver</a>.
</p>

<p align="center">
  <a href="#try-it">Try it</a> ·
  <a href="#what-it-checks">What it checks</a> ·
  <a href="docs/architecture.md">Inside the kernel</a> ·
  <a href="docs/benchmarks.md">Benchmarks</a>
</p>

---

Pestka checks Lean proofs with its own implementation of Lean’s type theory.
Give it a [lean4export](https://github.com/leanprover/lean4export) file and it
checks the declarations, down to universe levels, reduction and recursors.
Lean itself is not involved in the check.

It checks **all of mathlib**: 702,040 declarations in the recorded export.
The same Aver source also compiles to **WebAssembly**, where it checks the
same corpus under V8. On the small Lean Kernel Arena suite, the recorded
result is **179/179 correct**. [Measurements and setup →](docs/benchmarks.md)

*Pestka* is Polish for a fruit stone — a kernel. It's also what you call
something that's a piece of cake.

## Try it

You need a Rust toolchain. From a checkout of this repository:

```sh
# Install the Aver version this checkout uses.
cargo install aver-lang --version "$(cat .aver-version)" --locked

# Build the native checker and try a small included export.
bin/build
.build/target/release/main tests/export/wellformed/small.ndjson
```

The last line should be:

```text
accepted
```

To check your own export:

```sh
.build/target/release/main MyModule.ndjson
```

Pestka uses eight workers by default. Pass a worker count as the second
argument, for example `MyModule.ndjson 1`. Each declaration sees only the
environment available at its position in the file; the verdict reports the
first failure in file order.

Need an export first? See [producing input](docs/usage.md#producing-input).
Lean and `lean4export` are needed to make the file, but not to check it.

## What it checks

Pestka implements Lean's type theory, including:

- Universe polymorphism and definitional equality.
- Mutual and nested inductive types, with recursors derived by Pestka and
  compared against the export.
- Quotients, proof irrelevance, and the Nat and String literal extensions.

The input format is **lean4export NDJSON 3.1.0**. The last output line and
exit code give the result:

| Output | Exit code | Meaning |
| :--- | :---: | :--- |
| `accepted` | `0` | The check passed. |
| `rejected: <why>` | `1` | The input failed a check. |
| `declined: <why>` | `2` | The input needs something Pestka does not support. |

Axioms are assumptions: Pestka checks their types, not proofs of them.
Unsafe and partial declarations are skipped and kept out of the logical
environment. If an inductive block cannot be checked, the final result is
`declined`, never `accepted`.

## A few things inside

Most of the interesting work is in making repeated checks cheap.

**A binder doesn't always need a new variable.** Pestka identifies free
variables by their type, value and how many of the same kind are already
open. Opening an equivalent binder again can reuse the work from the first
one — even across declarations.

**A worker remembers what it learned.** Inference, reduction and equality
results survive between declarations, within bounded caches. The state is
passed around as a value in Aver; when it has one owner, the native build
updates its maps in place.

**Repeated unfolding can become a rule.** For hot recursive definitions,
Pestka derives reduction rules from their bodies. Later calls can use those
rules to skip the same unfolding and pattern matching.

The [implementation notes](docs/architecture.md) explain these choices,
the lazy reduction machine, term representation and the experiments behind
them. [Laws and verification](docs/development.md#laws) describe the
properties checked alongside the code, including which claims have proofs.

## Also runs as WebAssembly

Aver has its own wasm-gc backend. It compiles the same checker directly to
WebAssembly; terms, maps and closures become garbage-collected objects in
the engine.

With Node 24 or later and Binaryen's `wasm-opt` installed:

```sh
cargo install aver-lang --version "$(cat .aver-version)" --locked --features wasm
bin/build-wasm
bin/run-wasm tests/export/wellformed/small.ndjson
```

The runner uses V8 and checks that the verdict agrees with the exit status.
A host failure exits with `3`. Native and wasm measurements, including
mathlib, are in the [benchmark tables](docs/benchmarks.md).

## Working on Pestka

The checker is written in [Aver](https://github.com/jasisz/aver), by an AI
agent under human guidance. Aver is statically typed and pure functional;
its native backend compiles to Rust.

```sh
aver check . --module-root .     # Types, effects and lint
aver verify . --module-root .    # Examples and laws
bin/build
tests/run.sh                    # Accepted, rejected and unsupported fixtures
```

The core lives in [`core/`](core), the checker in [`check/`](check), and the
export reader in [`export/`](export). [`main.av`](main.av) ties them together.

For a closer look:

- [Build and run](docs/usage.md) — exports, PGO, command reference and runtimes.
- [Inside the kernel](docs/architecture.md) — algorithms and optimizations.
- [Benchmarks](docs/benchmarks.md) — native and WebAssembly results, with setup.
- [Development](docs/development.md) — tests, laws and the source map.
