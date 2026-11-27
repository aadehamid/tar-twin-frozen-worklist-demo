# The cluster rules from docs/verification.md section 3, stated as laws.
import Base
import ./cost.bend as C

# A cluster never costs more than doing its items one by one.
law never_more:
  for +s: Nat
  for +xs: +List<Nat>
  exs d: Nat
  {Nat.add(C.cluster(s, xs), d) == C.standalone(s, xs) : Nat}

# A cluster of one or more items counts the shared setup exactly once.
law shared_once:
  for +s: Nat
  for +h: Nat
  for +t: +List<Nat>
  {C.cluster(s, h <> t) == Nat.add(C.own(h <> t), s) : Nat}

# The saving is the setup times the number of items after the first.
law saving:
  for +s: Nat
  for +h: Nat
  for +t: +List<Nat>
  {C.standalone(s, h <> t) == Nat.add(C.cluster(s, h <> t), Nat.mul(C.count(t), s)) : Nat}
