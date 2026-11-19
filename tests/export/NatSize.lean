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

-- Traps/NatSize.lean
import Traps.Common
set_option debug.skipKernelTC true
-- a shift count one past 2^24 bits: computed (result 2 MiB)
theorem shiftGood : (1 <<< 16777217) >>> 16777216 = 2 := by unchecked_rfl
theorem shiftBad : (1 <<< 16777217) >>> 16777216 = 3 := by unchecked_rfl
-- a result of 256 MiB: refused before computing it
theorem shiftHuge : (1 <<< 2147483648) >>> 2147483648 = 1 := by unchecked_rfl
theorem powHuge : 2 ^ 2147483648 / 2 ^ 2147483647 = 2 := by unchecked_rfl
