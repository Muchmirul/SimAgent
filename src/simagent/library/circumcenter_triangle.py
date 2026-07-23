"""'The circumcenter of a triangle lies inside it' — famously false (obtuse
triangles). The simplest full tour of the pipeline: search finds an obtuse
triangle, annealing makes it robust, sympy certifies exact rational
coordinates, and the scene shows the circumcircle with its center outside."""
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
    return simplex_volume(T) > 0.05
'''

SCENE = '''
def build_scene(T):
    c = circumcenter(T)
    w = barycentric(T, c)
    inside = w.min() > 0
    r = float(np.linalg.norm(c - T[0]))
    edges = [(T[0], T[1]), (T[1], T[2]), (T[2], T[0])]
    return [
        scene_polygon(T, color="#4a90d9", opacity=0.45),
        scene_segments(edges, color="#dfe3e8", width=3.0),
        scene_sphere(c, r, color="#f2c14e", opacity=0.10),
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
        theorem="circumcenter_in_triangle_disproof_witness",
        title="Witness triangle whose circumcenter lies outside it "
              "(disproves: the circumcenter lies inside every triangle)",
    )
'''

SPEC = ProblemSpec(
    id="circumcenter-in-triangle",
    title="Circumcenter lies inside every triangle",
    conjecture=(
        "For every (nondegenerate) triangle in the plane, the circumcenter "
        "lies in the interior of the triangle."
    ),
    latex=(
        r"\forall\, A,B,C \in \mathbb{R}^2 \text{ affinely independent},\quad "
        r"O(A,B,C) \in \operatorname{int}\,\triangle ABC"
    ),
    quantifier="forall",
    domain=[VarSpec(name="T", shape=[3, 2], low=-1.2, high=1.2)],
    check_code=CHECK,
    scene_code=SCENE,
    constraint_code=CONSTRAINT,
    certify_code=CERTIFY,
    lean_certificate_code=LEAN_CERT,
    lean_statement=(
        "∀ (s : Affine.Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),\n"
        "    s.circumcenter ∈ interior (convexHull ℝ (Set.range s.points))"
    ),
    notes=(
        "False: any obtuse triangle has its circumcenter outside. The margin "
        "is the minimum barycentric coordinate of the circumcenter."
    ),
)
