"""Euler's polyhedron formula V - E + F = 2 on random convex hulls — true, so
this exercises the evidence path: the search fails to falsify, and the answer
honestly reports accumulated evidence plus a formalization skeleton."""
from ..spec import ProblemSpec, VarSpec

CHECK = '''
def check(P):
    V, E, F = hull_counts(P)
    chi = V - E + F
    return {
        "holds": chi == 2,
        "margin": None,
        "data": {"V": V, "E": E, "F": F, "chi": chi},
    }
'''

CONSTRAINT = '''
def valid(P):
    try:
        hull_counts(P)
        return True
    except Exception:
        return False
'''

SCENE = '''
def build_scene(P):
    V, E, F = hull_counts(P)
    verts, faces = hull_mesh(P)
    edges = []
    seen = set()
    for f in faces:
        for i in range(3):
            a, b = sorted((f[i], f[(i + 1) % 3]))
            if (a, b) not in seen:
                seen.add((a, b))
                edges.append((verts[a], verts[b]))
    return [
        scene_mesh(verts, faces, color="#4a90d9", opacity=0.25),
        scene_segments(edges, color="#dfe3e8", width=1.5),
        scene_points(P, color="#ffffff", radius=0.04),
        scene_label("V=%d  E=%d  F=%d   V-E+F=%d" % (V, E, F, V - E + F)),
    ]
'''

SPEC = ProblemSpec(
    id="euler-characteristic-hull",
    title="Euler characteristic of convex polyhedra (V - E + F = 2)",
    conjecture=(
        "For the boundary of the convex hull of any finite set of points in "
        "general position in R^3, the vertex, edge and face counts satisfy "
        "V - E + F = 2."
    ),
    latex=(
        r"\forall\, P \subset \mathbb{R}^3 \text{ finite, in general position:}\quad "
        r"V(\mathrm{conv}\,P) - E(\mathrm{conv}\,P) + F(\mathrm{conv}\,P) = 2"
    ),
    quantifier="forall",
    domain=[VarSpec(name="P", shape=[10, 3], low=-1.0, high=1.0)],
    check_code=CHECK,
    scene_code=SCENE,
    constraint_code=CONSTRAINT,
    certify_code=None,
    lean_statement=(
        "-- No off-the-shelf Mathlib statement; Euler's polyhedron formula for\n"
        "-- convex polytopes is itself a formalization target.\n"
        "True"
    ),
    notes=(
        "True (Euler, 1758). Discrete check (no margin): the search can only "
        "accumulate evidence, never a proof — the honest output is "
        "'no counterexample found' plus a proof obligation."
    ),
)
