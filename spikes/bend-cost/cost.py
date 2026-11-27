"""Cluster costs as the twin's Python code computes them (design.md section 5.5).

`items` holds each scope item's own cost in hours, and `shared` is the one setup the cluster
shares, such as blinding and isolating its envelope.
"""


def standalone(shared: int, items: list[int]) -> int:
    """Each item done on its own pays the setup itself."""
    return sum(h + shared for h in items)


def cluster(shared: int, items: list[int]) -> int:
    """Done together, the items pay the setup once. An empty cluster costs nothing."""
    return sum(items) + shared if items else 0
