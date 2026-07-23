"""1 + 3 + 5 + ... + (2n-1) = n² over a finite range — proof by exhaustion.

The domain is deliberately finite (n in 0..200), so the harness can check
every single case and honestly claim the *bounded* statement as proved; the
Lean certificate re-decides all cases in the kernel. The unbounded statement
needs induction (a deductive method) — the spec notes say so. The scene shows
the classic picture proof: each odd number is an L-shaped gnomon completing
the next square."""
from ..spec import ProblemSpec, VarSpec

CHECK = '''
def check(n):
    k = int(n)
    total = sum(2 * i + 1 for i in range(k))
    return {
        "holds": total == k * k,
        "margin": None,
        "data": {"n": k, "sum_of_first_n_odds": total, "n_squared": k * k},
    }
'''

SCENE = '''
def build_scene(n):
    k = max(int(n), 1)
    k = min(k, 14)  # keep the picture readable for large n
    palette = ["#4a90d9", "#f2c14e", "#2ecc71", "#e74c3c", "#9b59b6", "#e67e22", "#1abc9c"]
    prims = []
    s = 2.4 / k
    for layer in range(k):
        pts = []
        for i in range(layer + 1):
            pts.append([i * s, layer * s])
            if i != layer:
                pts.append([layer * s, i * s])
        prims.append(scene_points(pts, color=palette[layer % len(palette)],
                                  radius=min(0.4 * s, 0.06)))
    prims.append(scene_label(
        "n=%d: gnomon layers 1,3,5,... tile the %dx%d square" % (int(n), k, k)))
    return prims
'''

LEAN_CERT = '''
def lean_certificate():
    defs = """
def soddSum : Nat → Nat
  | 0 => 0
  | n + 1 => soddSum n + (2 * n + 1)
"""
    return lean_bounded_nat(
        theorem="sum_of_first_n_odds_eq_square",
        title="For every n <= 200, 1 + 3 + ... + (2n-1) = n^2 (checked case by case)",
        defs=defs,
        statement="∀ n : Nat, n < 201 → soddSum n = n * n",
    )
'''

SPEC = ProblemSpec(
    id="sum-of-odds-square",
    title="Sum of the first n odd numbers equals n² (n ≤ 200)",
    conjecture=(
        "For every integer n with 0 ≤ n ≤ 200, the sum of the first n odd "
        "numbers equals n²."
    ),
    latex=r"\forall\, n \in \{0,\dots,200\}:\quad \sum_{i=1}^{n} (2i-1) = n^2",
    quantifier="forall",
    domain=[VarSpec(name="n", shape=[], low=0, high=200, kind="int")],
    check_code=CHECK,
    scene_code=SCENE,
    constraint_code=None,
    certify_code=None,
    lean_certificate_code=LEAN_CERT,
    lean_statement=(
        "∀ n : Nat, n ≤ 200 → (Finset.range n).sum (fun i => 2 * i + 1) = n ^ 2"
    ),
    notes=(
        "True — and provable for ALL n by induction (a deductive method). The "
        "harness proves only the bounded statement, by exhaustion over every "
        "case in the declared domain."
    ),
)
