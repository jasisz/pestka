-- Two renovation tests beyond the Arena's: run in the Arena's renovation project
-- (lean-kernel-arena, renovation/), as OUT=DIR lake env lean RenovationNested.lean.
import Renovation.Meta
set_option linter.unusedVariables false
open Lean

/-- A container in `Type` without large elimination: its recursor has no rules. -/
good_inductive {} in
inductive SBox (α : Type) : Type where
  | mk (a : α)

/- A nested type with large elimination, nested through `SBox`, which has none. Sent to the kernel
directly: the elaborator's own constructions over it need the auxiliary recursor to reduce. -/
run_cmd Elab.Command.liftTermElabM do
  let tr := mkConst `SBTree
  let leaf : Constructor := { name := `SBTree.leaf, type := tr }
  let node : Constructor := { name := `SBTree.node, type := Expr.forallE `b (mkApp (mkConst ``SBox) tr) tr BinderInfo.default }
  let ind : InductiveType := { name := `SBTree, type := mkSort Level.one, ctors := [leaf, node], isImpredicative := false, isK := false, hasProjections := false, hasEta := false, hasLargeElim := true }
  addDecl (Declaration.inductDecl [] 0 [ind] false)
  registerTestCase { decls := #[`SBTree], outcome := Outcome.good, description := some "A nested type with large elimination, nested through `SBox`, which has none." }

/-- `rec` or `rec_1` of `SBTree` into `Nat`: 0 at `leaf`, the hypothesis at `node`, its successor at `SBox.mk`. -/
def sbRec (n : Name) (major : Expr) : Expr :=
  let nat := mkConst ``Nat
  let tr := mkConst `SBTree
  let box := mkApp (mkConst ``SBox) tr
  mkAppN (mkConst n [Level.one])
    #[.lam `t tr nat .default, .lam `t box nat .default, mkNatLit 0,
      .lam `b box (.lam `n nat (.bvar 0) .default) .default,
      .lam `a tr (.lam `n nat (mkApp (mkConst ``Nat.succ) (.bvar 0)) .default) .default, major]

def sbMkLeaf : Expr := mkApp2 (mkConst ``SBox.mk) (mkConst `SBTree) (mkConst `SBTree.leaf)

/-- An equation `lhs = rhs` in `Nat` proved by `Eq.refl lhs`. -/
def reflThm (n : Name) (lhs rhs : Expr) : Declaration :=
  let nat := mkConst ``Nat
  .thmDecl { name := n, levelParams := [], type := mkApp3 (mkConst ``Eq [Level.one]) nat lhs rhs,
             value := mkApp2 (mkConst ``Eq.refl [Level.one]) nat lhs }

run_cmd Elab.Command.liftCoreM do
  addTestCaseDeclCore (some "The recursor reduces on a constructor of `SBTree` itself, to the auxiliary recursor on the field.") (reflThm `sBTreeNode (sbRec `SBTree.rec (mkApp (mkConst `SBTree.node) sbMkLeaf)) (sbRec `SBTree.rec_1 sbMkLeaf)) Outcome.good
  addTestCaseDeclCore (some "The auxiliary recursor does not reduce: the type of its major premise, `SBox`, has no large elimination.") (reflThm `sBTreeRecOne (sbRec `SBTree.rec_1 sbMkLeaf) (mkNatLit 1)) Outcome.bad
