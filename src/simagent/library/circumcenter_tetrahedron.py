"""3D headline demo: 'the circumcenter of a tetrahedron lies inside it' —
false for sliver-ish tetrahedra. The scene shows the tetrahedron, its
circumsphere, and the circumcenter escaping the solid."""
from ..spec import ProblemSpec, VarSpec

CHECK = '''
def check(T):
    c = circumcenter(T)
    w = barycentric(T, c)
    m = float(w.min())
    return {
        "holds": m > 0,
        "margin": m,
        "data": {"circumcenter": c.tolist(), "barycentric": w.tolist()},
    }
'''

CONSTRAINT = '''
def valid(T):
    return simplex_volume(T) > 0.02
'''

SCENE = '''
def build_scene(T):
    c = circumcenter(T)
    w = barycentric(T, c)
    inside = w.min() > 0
    r = float(np.linalg.norm(c - T[0]))
    faces = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]
    edges = [(T[i], T[j]) for i in range(4) for j in range(i + 1, 4)]
    return [
        scene_mesh(T, faces, color="#4a90d9", opacity=0.35),
        scene_segments(edges, color="#dfe3e8", width=2.5),
        scene_sphere(c, r, color="#f2c14e", opacity=0.08),
        scene_points(T, color="#ffffff", radius=0.05),
        scene_points([c], color="#2ecc71" if inside else "#e74c3c", radius=0.07,
                     name="circumcenter"),
        scene_label("circumcenter %s (min barycentric = %.3f)"
                    % ("inside" if inside else "OUTSIDE", w.min())),
    ]
'''

CERTIFY = '''
def certify(T):
    c = exact_circumcenter(T)
    w = exact_barycentric(T, c)
    return all(x > 0 for x in w)
'''

LEAN_CERT = '''
def lean_certificate(T):
    return lean_simplex_circumcenter(
        T,
        theorem="circumcenter_in_tetrahedron_disproof_witness",
        title="Witness tetrahedron whose circumcenter lies outside it "
              "(disproves: the circumcenter lies inside every tetrahedron)",
    )
'''

SPEC = ProblemSpec(
    id="circumcenter-in-tetrahedron",
    title="Circumcenter lies inside every tetrahedron",
    conjecture=(
        "For every (nondegenerate) tetrahedron in space, the center of its "
        "circumscribed sphere lies in the interior of the tetrahedron."
    ),
    latex=(
        r"\forall\, A,B,C,D \in \mathbb{R}^3 \text{ affinely independent},\quad "
        r"O(A,B,C,D) \in \operatorname{int}\,\mathrm{conv}\{A,B,C,D\}"
    ),
    quantifier="forall",
    domain=[VarSpec(name="T", shape=[4, 3], low=-1.2, high=1.2)],
    check_code=CHECK,
    scene_code=SCENE,
    constraint_code=CONSTRAINT,
    certify_code=CERTIFY,
    lean_certificate_code=LEAN_CERT,
    lean_statement=(
        "∀ (s : Affine.Simplex ℝ (EuclideanSpace ℝ (Fin 3)) 3),\n"
        "    s.circumcenter ∈ interior (convexHull ℝ (Set.range s.points))"
    ),
    notes=(
        "False: flat 'sliver' tetrahedra push the circumcenter far outside. "
        "The margin is the minimum barycentric coordinate of the circumcenter."
    ),
)
