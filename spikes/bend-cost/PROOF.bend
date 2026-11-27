# Proofs of the laws in LAWS.bend. bend PROOF.bend checks them.
import Base
import ./nat.bend as N
import ./cost.bend as C
import ./LAWS.bend as Laws

# Doing items one by one costs their own costs plus the setup once per item.
law sa_split:
  for +s: Nat
  for +xs: +List<Nat>
  {C.standalone(s, xs) == Nat.add(C.own(xs), Nat.mul(C.count(xs), s)) : Nat}

def sa_split(s, xs):
  match xs:
    case []:
      {==}
    case +h <> +t:
      %Equal.sym(Nat, C.standalone(s, t), Nat.add(C.own(t), Nat.mul(C.count(t), s)), sa_split(s, t)) : {Nat.add(Nat.add(h, s), _) == Nat.add(Nat.add(h, C.own(t)), Nat.add(s, Nat.mul(C.count(t), s))) : Nat}
      %Equal.sym(Nat, Nat.add(Nat.add(h, s), Nat.add(C.own(t), Nat.mul(C.count(t), s))), Nat.add(h, Nat.add(s, Nat.add(C.own(t), Nat.mul(C.count(t), s)))), N.add_assoc(h, s, Nat.add(C.own(t), Nat.mul(C.count(t), s)))) : {_ == Nat.add(Nat.add(h, C.own(t)), Nat.add(s, Nat.mul(C.count(t), s))) : Nat}
      %Equal.sym(Nat, Nat.add(Nat.add(h, C.own(t)), Nat.add(s, Nat.mul(C.count(t), s))), Nat.add(h, Nat.add(C.own(t), Nat.add(s, Nat.mul(C.count(t), s)))), N.add_assoc(h, C.own(t), Nat.add(s, Nat.mul(C.count(t), s)))) : {Nat.add(h, Nat.add(s, Nat.add(C.own(t), Nat.mul(C.count(t), s)))) == _ : Nat}
      %N.add_assoc(s, C.own(t), Nat.mul(C.count(t), s)) : {Nat.add(h, _) == Nat.add(h, Nat.add(C.own(t), Nat.add(s, Nat.mul(C.count(t), s)))) : Nat}
      %N.add_comm(C.own(t), s) : {Nat.add(h, Nat.add(_, Nat.mul(C.count(t), s))) == Nat.add(h, Nat.add(C.own(t), Nat.add(s, Nat.mul(C.count(t), s)))) : Nat}
      %N.add_assoc(C.own(t), s, Nat.mul(C.count(t), s)) : {Nat.add(h, Nat.add(Nat.add(C.own(t), s), Nat.mul(C.count(t), s))) == Nat.add(h, _) : Nat}
      {==}

def Laws.shared_once(s, h, t):
  {==}

def Laws.saving(s, h, t):
  %Equal.sym(Nat, Nat.add(Nat.add(Nat.add(h, C.own(t)), s), Nat.mul(C.count(t), s)), Nat.add(Nat.add(h, C.own(t)), Nat.add(s, Nat.mul(C.count(t), s))), N.add_assoc(Nat.add(h, C.own(t)), s, Nat.mul(C.count(t), s))) : {C.standalone(s, h <> t) == _ : Nat}
  sa_split(s, h <> t)

def Laws.never_more(s, xs):
  match xs:
    case []:
      (0n, {==})
    case +h <> +t:
      (Nat.mul(C.count(t), s), Equal.sym(Nat, C.standalone(s, h <> t), Nat.add(C.cluster(s, h <> t), Nat.mul(C.count(t), s)), Laws.saving(s, h, t)))
