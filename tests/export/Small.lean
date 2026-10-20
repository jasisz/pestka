namespace Small

structure Point where
  x : Nat
  y : Nat
deriving Repr

inductive Tree (α : Type u) where
  | leaf : Tree α
  | node : Tree α → α → Tree α → Tree α

def Tree.size {α : Type u} : Tree α → Nat
  | .leaf => 0
  | .node l _ r => l.size + 1 + r.size

def Point.add (p q : Point) : Point := ⟨p.x + q.x, p.y + q.y⟩

def big : Nat := 123456789012345678901234567890
def greeting : String := "zażółć \"gęślą\"\n\tjaźń λ∀"

theorem add_zero' (n : Nat) : n + 0 = n := rfl

theorem Point.add_x (p q : Point) : (p.add q).x = p.x + q.x := rfl

theorem size_leaf {α : Type u} : (Tree.leaf : Tree α).size = 0 := rfl

def «weird name».«with.dot» : Nat := 7

end Small
