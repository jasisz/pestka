-- Traps/Origin.lean (Traps/Common.lean as in Walls.lean)
import Traps.Common
set_option debug.skipKernelTC true

/-! The shape of CFSG's optI_eq: one side, a step of `ite`, comes to the
definition the other side is, while lazy delta unfolds that definition first,
the higher one, into a loop. Unless a side that comes to the form the other side
began at meets it (OriginMet), the two pass each other and the loop is run;
the good statement holds without it, the bad one, over a small loop, must still
be rejected. -/

def sumTo (n : Nat) : Nat := Id.run do
  let mut a := 0
  for i in [0:n] do
    a := a + i % 7
  return a

def total : Nat := sumTo 300000
theorem originGood : (if true = true then total else 0) = total := by unchecked_rfl

def totalS : Nat := sumTo 40
theorem originBad : (if true = true then totalS else 0) = sumTo 41 := by unchecked_rfl

-- Exported one declaration per file with lean4export 3.1.0 (Lean 4.32.0):
--   lake env lean4export Traps.Origin -- originGood > origin_sumGood.ndjson
-- the good one into wellformed/, the bad one into illtyped/.
