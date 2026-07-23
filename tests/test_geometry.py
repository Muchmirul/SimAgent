import numpy as np

from simagent.sandbox import certify, geometry


def test_circumcenter_right_triangle():
    # Right triangle: circumcenter = hypotenuse midpoint.
    T = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    c = geometry.circumcenter(T)
    assert np.allclose(c, [0.5, 0.5])


def test_circumcenter_equidistance_random():
    rng = np.random.default_rng(1)
    for _ in range(20):
        T = rng.uniform(-1, 1, size=(4, 3))
        if geometry.simplex_volume(T) < 1e-3:
            continue
        c = geometry.circumcenter(T)
        d = np.linalg.norm(T - c, axis=1)
        assert np.allclose(d, d[0])


def test_barycentric_roundtrip():
    rng = np.random.default_rng(2)
    T = rng.uniform(-1, 1, size=(4, 3))
    w = np.array([0.1, 0.2, 0.3, 0.4])
    x = w @ T
    got = geometry.barycentric(T, x)
    assert np.allclose(got, w)


def test_hull_counts_cube():
    corners = np.array(
        [[i, j, k] for i in (0.0, 1.0) for j in (0.0, 1.0) for k in (0.0, 1.0)]
    )
    V, E, F = geometry.hull_counts(corners)
    assert V == 8
    assert F == 12  # triangulated faces
    assert E == 18
    assert V - E + F == 2


def test_exact_circumcenter_matches_numeric():
    import sympy as sp

    T = np.array([[0.0, 0.0], [1.0, 0.0], [0.25, 0.75]])
    exact_T = certify.rationalize_array(T, max_den=16)
    c_exact = certify.exact_circumcenter(exact_T)
    c_num = geometry.circumcenter(T)
    assert np.allclose([float(c_exact[0]), float(c_exact[1])], c_num)
    w = certify.exact_barycentric(exact_T, c_exact)
    assert sp.simplify(sum(w) - 1) == 0
