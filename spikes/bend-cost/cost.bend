# Cluster costs, in whole hours. Each item has its own cost, and every item in a cluster
# needs the same shared setup, such as one blinding and isolation of an envelope.
import Base

def count(xs: +List<Nat>) -> Nat:
  match xs:
    case []:
      0n
    case h <> t:
      1n+count(t)

def own(xs: +List<Nat>) -> Nat:
  match xs:
    case []:
      0n
    case h <> t:
      Nat.add(h, own(t))

# Each item done on its own pays the setup itself.
def standalone(+s: Nat, xs: +List<Nat>) -> Nat:
  match xs:
    case []:
      0n
    case h <> t:
      Nat.add(Nat.add(h, s), standalone(s, t))

# Done as a cluster, the items share one setup.
def cluster(+s: Nat, xs: +List<Nat>) -> Nat:
  match xs:
    case []:
      0n
    case h <> t:
      Nat.add(Nat.add(h, own(t)), s)
