[← Pestka](../README.md)

# Inside the kernel

Implementation notes and the measurements that motivated individual optimizations.
The percentages below describe those experiments, not cumulative speedups.

The checker follows the reference kernel's algorithm. What is its own:

- **It is written in Aver**, a pure functional language compiled to Rust:
  the checker's state is a value passed from function to function. A state
  could be kept and gone back to, but the checker never does: it hands its
  state on, so the compiled code finds each cache with a single owner and
  updates it in place. Caches kept as persistent tries, copying a path on
  every write so that an old version nobody held stayed intact, cost 17%
  more instructions on `Init`.
- **Declarations are checked in parallel with a sequential verdict.** The
  environment is built in file order; the other declarations are then
  checked on several workers, each against the environment at its own place
  in the file, and the verdict is the first failure in file order.
- **Free variables are named by what they are.** A variable is its type and
  value, and how many variables of that same type and value are open where
  its binder is opened. Two binders open at once with the same type and value
  get different counts, and Lean only needs variables that meet to be told
  apart; two binders that get the same variable are never open at once, and
  they have the same type and value, so whatever holds of a term with one
  holds of it with the other. The checker no longer makes a fresh variable
  for every opening, nor another for every place in a telescope: a binder
  opened again gets its variable again, and so does a type or an instance
  that is the third binder of one theorem and the seventh of the next, so
  what was found about the terms under it, instance diamonds included, is
  found again. On slices of `mathlib` naming variables by their place in the
  telescope and the next point cut 18–20% of the instructions; naming them
  by their kind instead cut 4–5% more.
- **Terms are equal as Lean's are.** Lean's kernel compares expressions
  without the names and annotations of their binders; Pestka's terms do not
  hold them, so equality of terms is equality up to the names of bound
  variables, and a cache finds its result again for a term that differs
  from one it has seen only in such a name. Leaving them out cut about 7%
  of the instructions on `Init`.
- **A term knows which variables may be in it.** Each free variable has one
  of ten bits, by its number, and each term the bits of the variables in it,
  kept with its hash in one word. Abstracting variables, as closing a binder
  does, skips every subterm that shares no bit with them; before, 59% of the
  nodes it rebuilt came back unchanged. This cut nearly 3% on `Init`.
- **Proofs are not compared.** Two applications of one constant are equal
  when their arguments are, and once the arguments before it are equal, an
  argument in a place whose domain is a proposition is a proof of the same
  proposition on both sides; proofs of one proposition are equal, so such
  arguments are left out. Whether a domain is a proposition is read from the
  constant's type, not inferred. This cut about 9% on a `mathlib`
  declaration.
- **Metadata and keys are machine words.** A term's packed metadata, the kind
  mixed into its hash, a variable's number and the key of every memo and
  cache are refinements over Int bounded below 2^62, which Aver holds as
  raw 64-bit words: making and reading them is machine arithmetic, and the
  caches are maps keyed by machine words. This cut about 15% on a `mathlib`
  declaration and 13% on `Init`.
- **A casesOn goes straight to its branch.** A definition named casesOn whose
  value is its recursor applied to its own arguments, each minor premise
  wrapped to drop the induction hypotheses, is not unfolded: the major
  premise is brought to its constructor and that constructor's minor premise
  takes the fields. Computations by `decide` meet one per number and list
  they take apart; this cut about 5% on the `perf/` tests.
- **What a worker finds is kept across declarations.** Each worker meets its
  declarations in file order, so every constant a result rests on is still
  there in the next one. It carries its variables and their context, and the
  results of inference, checking, reduction and comparison, about closed
  terms and, with variables named as above, open ones too; what checking
  found about a term with a universe parameter is kept under the
  declaration's parameters, for every declaration with the same ones.
  A constant's type and a definition's value at universe levels depend only
  on the levels as written, and are kept as well. Every cache has a limit and
  is emptied past it.
- **Failures are kept too.** Within a declaration, pairs found
  definitionally different are remembered as well as pairs found equal: its
  free variables each have one type and value, so the answer for a pair does
  not change while it is checked. In `std`, one proof compared the same pairs
  hundreds of times and took 211 s without this, 3 s with it.
- **Weak head normalization runs a lazy machine**: arguments wait as terms
  with their environment and are built only when needed, each at most once;
  definitions unfold and recursor rules fire inside it. What it does at a
  constant (the rule a recursor fires, the branch a casesOn or a matcher
  takes, the body a definition unfolds to) is worked out by plain functions,
  and the machine takes one step there: its loop has five arms, where each
  arm it had cost every other part of the checker as well.
- **A matcher is unfolded into its callers once.** A function compiled from
  pattern matching passes its arguments and one lambda per alternative to a
  matcher, which hands them to a casesOn. The body a definition unfolds to,
  kept for the rest of the run, has the matcher at its head unfolded into it
  and the alternatives applied to its fields, so a call goes from the
  function straight to the casesOn. A literal of `Nat` goes to its branch
  without being turned into `Nat.succ` of the one below. With the facts a
  recursor and a casesOn need found once, these and the machine's shorter
  loop cut about a third of the instructions on the `perf/` tests and a
  quarter on `reachability`, measured on one Aver.
- **Hot recursive definitions get rules.** Reduction commutes with
  substitution: what `f x1 … xn` reduces to on variables, `f a1 … an`
  reduces to with the arguments put in. A definition that reaches a
  recursor and unfolds 32 times in a declaration is reduced once on fresh
  variables and split on the constructors its recursor waits on, three
  levels deep; the tree of patterns and reducts is its rule for the rest of
  the run. A call whose arguments match a path skips the unfolding, the
  matcher and the course-of-values table of structural recursion. A rule
  that saves no more than one unfolding per form is not kept. This cut 12%
  of the instructions on `reachability`, 16% on the `perf/` tests and up to
  1% on the large tests.
- **Deep binders are not copied.** Opening a binder substitutes its variable
  into the body, as the reference does; past 128 open binders, bodies are
  inferred under their variables as they are instead, so deep nesting does
  not copy each body once per binder above it.
- **Laws** state the properties the optimizations rely on and are checked
  with the code; see [laws and verification](development.md#laws).
