-- Traps/Common.lean
import Lean
open Lean Meta Elab Tactic

/-- Closes an equality goal with `Eq.refl` of its right-hand side, unchecked. -/
macro "unchecked_rfl" : tactic => `(tactic|
  run_tac closeMainGoalUsing `unchecked fun goalType _ => do
    let some (_, _, rhs) := goalType.eq? | throwError "goal is not an equality"
    mkEqRefl rhs)

/-- `g n a = a + 2^n`, by 2^n unit steps (no literal shortcut applies to the
recursion itself). -/
noncomputable def g (n : Nat) : Nat → Nat :=
  Nat.rec (motive := fun _ => Nat → Nat) (fun a => a + 1) (fun _ ih a => ih (ih a)) n

/-- 2^19 unit steps; value 524288. -/
noncomputable def slow : Nat := g 19 0

-- Traps/Walls.lean
import Traps.Common
set_option debug.skipKernelTC true

/-! The shapes of CFSG's three conversion walls, each next to a closed
computation that only the wrong order of definitional unfolding asks for.
`g 23 0` takes 2^23 unit steps; the good statements hold without it, the bad
ones (over `g 19`, small enough to be computed when a refutation needs it)
must still be rejected. -/

-- totalC: List.sum [X, 1] against X + (1 + 0) (ArithmeticWhenWanted)
noncomputable def big : Nat := g 23 0
theorem sumGood : [big, 1].sum = big + (1 + 0) := by unchecked_rfl
theorem sumBad : [slow, 1].sum = slow + (2 + 0) := by unchecked_rfl

-- inv_get: an element of a literal array against the definition it holds,
-- which is higher than Array.get!Internal (HeadsMetFromBelow)
noncomputable def lift0 (i : Nat) : Nat := g 23 i
noncomputable def lift1 (i : Nat) : Nat := lift0 i
noncomputable def lift (i : Nat) : Nat := lift1 i
noncomputable def table : Array Nat := #[lift 0, lift 1]
theorem getGood : table[0]! = lift 0 := by unchecked_rfl
noncomputable def low0 (i : Nat) : Nat := g 19 i
noncomputable def low (i : Nat) : Nat := low0 i
noncomputable def tableLow : Array Nat := #[low 0, low 1]
theorem getBad : tableLow[0]! = low 1 := by unchecked_rfl

-- invol_eq: (f * f) 1 against f (f 1), f's value behind a check that
-- computes before it gets stuck on the free c (SidesMeet)
structure Fn where
  fn : Nat → Nat
def Fn.comp (f g : Fn) : Fn := ⟨fun x => f.fn (g.fn x)⟩
instance : Mul Fn := ⟨Fn.comp⟩
noncomputable def fBig (c : Nat) : Fn := if big = c then ⟨fun x => x + c⟩ else ⟨fun x => x + 1⟩
theorem meetGood (c : Nat) : (fBig c * fBig c).fn 1 = (fBig c).fn ((fBig c).fn 1) := by unchecked_rfl
noncomputable def fSmall (c : Nat) : Fn := if slow = c then ⟨fun x => x + c⟩ else ⟨fun x => x + 1⟩
theorem meetBad (c : Nat) : (fSmall c * fSmall c).fn 1 = (fSmall c).fn ((fSmall c).fn 2) := by unchecked_rfl

-- Exported one declaration per file with lean4export 3.1.0 (Lean 4.35.0):
--   lake env lean4export Traps.Walls -- sumGood > walls_sumGood.ndjson
-- the good ones into wellformed/, the bad ones into illtyped/.
