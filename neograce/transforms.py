"""
transforms.py - all the number crunching: formulas, fits and transformations.

Every function here takes numpy arrays and returns NEW arrays. Nothing is
changed in place (the undo system relies on that, see model.py).
"""
import re

import numpy as np


class ExprError(Exception):
    """Raised for user mistakes (bad formula, too few points, ...). The message is shown in a dialog."""
    pass


# ---------------------------------------------------------------------------
# Formula evaluation
#
# A formula like "y = sin(x)^2" is evaluated with Python's eval(), but only with
# the names in this table available (no file access, no imports, nothing else).
# ---------------------------------------------------------------------------
MATH_NAMES = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "arcsin": np.arcsin, "arccos": np.arccos, "arctan": np.arctan, "arctan2": np.arctan2,
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan, "atan2": np.arctan2,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "exp": np.exp, "log": np.log, "ln": np.log, "log10": np.log10, "log2": np.log2,
    "sqrt": np.sqrt, "abs": np.abs, "fabs": np.abs, "floor": np.floor, "ceil": np.ceil,
    "round": np.round, "sign": np.sign, "pow": np.power, "hypot": np.hypot,
    "max": np.maximum, "min": np.minimum, "maximum": np.maximum, "minimum": np.minimum,
    "where": np.where, "heaviside": np.heaviside,
    "pi": np.pi, "e": np.e, "inf": np.inf, "nan": np.nan,
}

# Matches "y = something" (but not "y == something"). Group 1 = target, group 2 = expression.
ASSIGNMENT = re.compile(r"^\s*(x|y|dy)\s*=(?!=)\s*(.+)$", re.IGNORECASE)


def split_assignment(formula):
    """"y = sin(x)^2" -> ("y", "sin(x)**2"). Grace uses ^ for powers, Python uses **."""
    match = ASSIGNMENT.match(formula)
    if match is None:
        raise ExprError("Formula must look like  y = <expression>  (or x = ..., dy = ...)")
    target = match.group(1).lower()
    expression = match.group(2).replace("^", "**")
    return target, expression


def evaluate(formula, x, y, dy=None):
    """Evaluate a formula for every point. Returns (target, new values)."""
    target, expression = split_assignment(formula)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)

    names = dict(MATH_NAMES)
    names["x"] = x
    names["y"] = y
    names["X"] = x
    names["Y"] = y
    names["index"] = np.arange(n, dtype=float)
    names["n"] = n
    names["rand"] = np.random.random(n)               # uniform random numbers 0..1
    names["rnorm"] = np.random.standard_normal(n)     # gaussian random numbers
    if dy is not None:
        names["dy"] = np.asarray(dy, dtype=float)

    try:
        with np.errstate(all="ignore"):
            result = eval(expression, {"__builtins__": {}}, names)
        # A constant like "y = 3" becomes an array of 3s
        values = np.broadcast_to(np.asarray(result, dtype=float), x.shape).copy()
    except Exception as error:
        raise ExprError("Could not evaluate '" + expression + "': " + str(error))
    return target, values


# ---------------------------------------------------------------------------
# Linear regression (polynomial, exponential, power, logarithmic)
# ---------------------------------------------------------------------------
FIT_KINDS = ["Linear", "Quadratic", "Cubic", "Polynomial (degree n)",
             "Exponential  y = A·exp(B·x)", "Power  y = A·x^B", "Logarithmic  y = A + B·ln(x)"]


class FittedFunction:
    """A fitted curve you can evaluate: f(x_array) -> y_array."""

    def __init__(self, kind, coefficients):
        self.kind = kind
        self.c = coefficients

    def __call__(self, t):
        t = np.asarray(t, dtype=float)
        with np.errstate(all="ignore"):
            if self.kind == "poly":
                return np.polyval(self.c, t)
            if self.kind == "exp":
                return self.c[0] * np.exp(self.c[1] * t)
            if self.kind == "power":
                return self.c[0] * np.power(t, self.c[1])
            return self.c[0] + self.c[1] * np.log(t)      # "log"


def regression(x, y, kind, degree=4):
    """Least-squares fit. kind is an index into FIT_KINDS. Returns (FittedFunction, report text)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    lines = []

    if kind <= 3:
        if kind == 0:
            deg = 1
        elif kind == 1:
            deg = 2
        elif kind == 2:
            deg = 3
        else:
            deg = degree
        if good.sum() <= deg:
            raise ExprError("Not enough points for this fit")
        coefficients = np.polyfit(x[good], y[good], deg)      # highest power first
        f = FittedFunction("poly", coefficients)
        lines.append("Polynomial fit, degree " + str(deg) + ":  y = a0 + a1·x + ... + a" + str(deg) + "·x^" + str(deg))
        for power in range(deg + 1):
            lines.append("  a%d = %.8g" % (power, coefficients[deg - power]))
    elif kind == 4:
        good = good & (y > 0)
        b, ln_a = np.polyfit(x[good], np.log(y[good]), 1)     # ln y = ln A + B x
        f = FittedFunction("exp", [np.exp(ln_a), b])
        lines.append("Exponential fit:  y = A·exp(B·x)")
        lines.append("  A = %.8g" % np.exp(ln_a))
        lines.append("  B = %.8g" % b)
    elif kind == 5:
        good = good & (x > 0) & (y > 0)
        b, ln_a = np.polyfit(np.log(x[good]), np.log(y[good]), 1)   # ln y = ln A + B ln x
        f = FittedFunction("power", [np.exp(ln_a), b])
        lines.append("Power fit:  y = A·x^B")
        lines.append("  A = %.8g" % np.exp(ln_a))
        lines.append("  B = %.8g" % b)
    else:
        good = good & (x > 0)
        b, a = np.polyfit(np.log(x[good]), y[good], 1)
        f = FittedFunction("log", [a, b])
        lines.append("Logarithmic fit:  y = A + B·ln(x)")
        lines.append("  A = %.8g" % a)
        lines.append("  B = %.8g" % b)

    residuals = y[good] - f(x[good])
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y[good] - y[good].mean()) ** 2))
    if ss_tot > 0:
        r2 = 1 - ss_res / ss_tot
    else:
        r2 = float("nan")
    count = int(good.sum())
    lines.append("  N = " + str(count))
    lines.append("  R² = %.8g" % r2)
    lines.append("  RMS residual = %.6g" % np.sqrt(ss_res / max(1, count)))
    return f, "\n".join(lines)


# ---------------------------------------------------------------------------
# xmgrace transformations
# ---------------------------------------------------------------------------

def finite_points(x, y):
    """Only the points where both x and y are real numbers."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    return x[good], y[good]


def running(x, y, window, kind="average"):
    """Running average / median / minimum / maximum / std. dev. over `window` points."""
    x, y = finite_points(x, y)
    window = int(window)
    if window < 2 or window > len(y):
        raise ExprError("Window must be between 2 and the number of points (" + str(len(y)) + ")")
    count = len(y) - window + 1
    new_x = np.zeros(count)
    new_y = np.zeros(count)
    for i in range(count):
        chunk = y[i:i + window]
        new_x[i] = x[i:i + window].mean()       # x of the window's centre
        if kind == "average":
            new_y[i] = chunk.mean()
        elif kind == "median":
            new_y[i] = np.median(chunk)
        elif kind == "minimum":
            new_y[i] = chunk.min()
        elif kind == "maximum":
            new_y[i] = chunk.max()
        else:
            new_y[i] = chunk.std()
    return new_x, new_y


def differences(x, y, kind="centered"):
    """Numerical derivative dy/dx."""
    x, y = finite_points(x, y)
    if len(x) < 3:
        raise ExprError("Need at least 3 points")
    with np.errstate(all="ignore"):
        if kind == "forward":
            return x[:-1], np.diff(y) / np.diff(x)
        if kind == "backward":
            return x[1:], np.diff(y) / np.diff(x)
        # centred: (y[i+1] - y[i-1]) / (x[i+1] - x[i-1])
        return x[1:-1], (y[2:] - y[:-2]) / (x[2:] - x[:-2])


def integrate(x, y):
    """Cumulative integral with the trapezoid rule. Returns (x, running integral, total)."""
    x, y = finite_points(x, y)
    if len(x) < 2:
        raise ExprError("Need at least 2 points")
    total = np.zeros(len(x))
    for i in range(1, len(x)):
        total[i] = total[i - 1] + 0.5 * (y[i] + y[i - 1]) * (x[i] - x[i - 1])
    return x, total, float(total[-1])


def natural_spline(x, y, new_x):
    """Natural cubic spline through (x, y), evaluated at new_x. x must be increasing."""
    n = len(x)
    h = np.diff(x)
    if np.any(h <= 0):
        raise ExprError("Spline needs strictly increasing x (sort the set first)")
    # Solve the tridiagonal system for the second-derivative coefficients c
    matrix = np.zeros((n, n))
    rhs = np.zeros(n)
    matrix[0, 0] = 1.0
    matrix[n - 1, n - 1] = 1.0
    for i in range(1, n - 1):
        matrix[i, i - 1] = h[i - 1]
        matrix[i, i] = 2.0 * (h[i - 1] + h[i])
        matrix[i, i + 1] = h[i]
        rhs[i] = 3.0 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
    c = np.linalg.solve(matrix, rhs)
    b = (y[1:] - y[:-1]) / h - h * (2.0 * c[:-1] + c[1:]) / 3.0
    d = (c[1:] - c[:-1]) / (3.0 * h)

    new_x = np.asarray(new_x, dtype=float)
    result = np.zeros(len(new_x))
    for j in range(len(new_x)):
        k = np.searchsorted(x, new_x[j]) - 1      # which interval the point is in
        k = min(max(k, 0), n - 2)
        t = new_x[j] - x[k]
        result[j] = y[k] + b[k] * t + c[k] * t * t + d[k] * t * t * t
    return result


def interpolate(x, y, new_x, method="cubic spline"):
    x, y = finite_points(x, y)
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    if method == "linear":
        return np.interp(new_x, x, y)
    if len(x) > 2000:
        raise ExprError("Cubic spline is limited to 2000 points here; use linear")
    return natural_spline(x, y, new_x)


def fourier(x, y, output="magnitude", window="none", one_sided=True):
    """FFT of evenly spaced data. Returns (frequency, value)."""
    x, y = finite_points(x, y)
    n = len(y)
    if n < 4:
        raise ExprError("Need at least 4 points")
    dx = (x[-1] - x[0]) / (n - 1)

    if window == "hann":
        weights = np.hanning(n)
    elif window == "hamming":
        weights = np.hamming(n)
    elif window == "blackman":
        weights = np.blackman(n)
    elif window == "bartlett":
        weights = np.bartlett(n)
    else:
        weights = np.ones(n)

    if one_sided:
        spectrum = np.fft.rfft(y * weights)
        frequency = np.fft.rfftfreq(n, dx)
    else:
        spectrum = np.fft.fftshift(np.fft.fft(y * weights))
        frequency = np.fft.fftshift(np.fft.fftfreq(n, dx))

    if output == "power":
        value = np.abs(spectrum) ** 2 / n ** 2
    elif output == "phase":
        value = np.angle(spectrum)
    elif output == "real":
        value = spectrum.real / n
    elif output == "imaginary":
        value = spectrum.imag / n
    else:
        value = np.abs(spectrum) / n
    return frequency, value


def histogram(y, bins, lo=None, hi=None, normalize=False, cumulative=False):
    """Returns (bin edges, counts). There is one more edge than counts."""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if lo is None:
        lo = y.min()
    if hi is None:
        hi = y.max()
    counts, edges = np.histogram(y, bins=int(bins), range=(lo, hi))
    counts = counts.astype(float)
    if cumulative:
        counts = np.cumsum(counts)
    if normalize:
        if cumulative:
            counts = counts / counts[-1]
        else:
            counts = counts / (counts.sum() * (edges[1] - edges[0]))
    return edges, counts


def correlation(y1, y2=None, max_lag=None, normalize=True):
    """Autocorrelation (y2 is None) or cross-correlation, versus lag in points."""
    a = np.asarray(y1, dtype=float)
    if y2 is None:
        b = a
    else:
        b = np.asarray(y2, dtype=float)
    n = min(len(a), len(b))
    a = np.nan_to_num(a[:n] - np.nanmean(a[:n]))
    b = np.nan_to_num(b[:n] - np.nanmean(b[:n]))
    if max_lag is None:
        max_lag = n - 1
    max_lag = min(int(max_lag), n - 1)

    lags = np.arange(max_lag + 1, dtype=float)
    values = np.zeros(max_lag + 1)
    for k in range(max_lag + 1):
        values[k] = np.dot(a[:n - k], b[k:]) / (n - k)
    if normalize:
        scale = np.sqrt(np.dot(a, a) / n * np.dot(b, b) / n)
        if scale > 0:
            values = values / scale
    return lags, values


def sort_xy(x, y, dy=None, by="x", descending=False):
    if by == "x":
        key = np.asarray(x, dtype=float)
    else:
        key = np.asarray(y, dtype=float)
    order = np.argsort(key, kind="stable")
    if descending:
        order = order[::-1]
    new_dy = None
    if dy is not None:
        new_dy = np.asarray(dy)[order]
    return np.asarray(x)[order], np.asarray(y)[order], new_dy


def geometric(x, y, angle=0.0, cx=0.0, cy=0.0, sx=1.0, sy=1.0, tx=0.0, ty=0.0):
    """Rotate around (cx, cy), then scale, then translate (same order as Grace)."""
    radians = np.radians(angle)
    dx = np.asarray(x, dtype=float) - cx
    dy = np.asarray(y, dtype=float) - cy
    rotated_x = dx * np.cos(radians) - dy * np.sin(radians)
    rotated_y = dx * np.sin(radians) + dy * np.cos(radians)
    return (rotated_x + cx) * sx + tx, (rotated_y + cy) * sy + ty


def sample(x, y, start=0, step=2):
    """Every `step`-th point, starting at `start`."""
    return np.asarray(x)[start::step].copy(), np.asarray(y)[start::step].copy()


# ---------------------------------------------------------------------------
# Non-linear curve fitting (Levenberg-Marquardt)
# ---------------------------------------------------------------------------
FIT_PRESETS = {
    "Custom": "y = a0 + a1*x",
    "Exponential decay": "y = a0*exp(-x/a1) + a2",
    "Stretched exponential": "y = a0*exp(-(x/a1)^a2)",
    "Double exponential": "y = a0*exp(-x/a1) + a2*exp(-x/a3) + a4",
    "Power law": "y = a0*x^a1",
    "Power law + offset": "y = a0*x^a1 + a2",
    "Gaussian": "y = a0*exp(-(x-a1)^2/(2*a2^2)) + a3",
    "Lorentzian": "y = a0/(1 + ((x-a1)/a2)^2) + a3",
    "Sine": "y = a0*sin(a1*x + a2) + a3",
    "Logistic": "y = a0/(1 + exp(-(x-a1)/a2)) + a3",
    "Ornstein-Zernike": "y = a0/(1 + (a1*x)^2)",
    "Exp. decay x power (correlation)": "y = a0*x^(-a1)*exp(-x/a2)",
}

PARAMETER = re.compile(r"\ba(\d)\b")       # a0 ... a9 as whole words


def fit_params(formula):
    """Which parameters a0..a9 appear in the formula, as a sorted list of numbers."""
    found = []
    for digit in PARAMETER.findall(formula):
        number = int(digit)
        if number not in found:
            found.append(number)
    found.sort()
    return found


class FitModel:
    """A compiled fit formula: model(x, params) -> y, where params maps 0 -> a0 etc."""

    def __init__(self, formula):
        target, expression = split_assignment(formula)
        if target != "y":
            raise ExprError("Fit formula must look like  y = <expression in x and a0..a9>")
        self.code = compile(expression, "<fit>", "eval")

    def __call__(self, x, params):
        names = dict(MATH_NAMES)
        names["x"] = x
        for k in params:
            names["a" + str(k)] = params[k]
        with np.errstate(all="ignore"):
            result = eval(self.code, {"__builtins__": {}}, names)
        return np.broadcast_to(np.asarray(result, dtype=float), x.shape)


class FitResult:
    """The fitted curve: call it like a function, f(x) -> y."""

    def __init__(self, model, params):
        self.model = model
        self.params = params

    def __call__(self, t):
        return self.model(np.asarray(t, dtype=float), self.params)


def clip_to_bounds(params, bounds):
    for k in bounds:
        if k in params:
            lo = bounds[k][0]
            hi = bounds[k][1]
            params[k] = min(max(params[k], lo), hi)
    return params


def nonlinear_fit(formula, x, y, guess, bounds=None, weights=None, max_iter=200, tol=1e-10):
    """Fit `formula` to the points by least squares (Levenberg-Marquardt).

    guess:   {parameter number: starting value}, e.g. {0: 1.0, 1: 5.0}
    bounds:  {parameter number: (lower, upper)}   (optional)
    weights: one weight per point, e.g. 1/dy^2     (optional)
    Returns (params, errors, report text, fitted function).
    """
    model = FitModel(formula)
    keys = sorted(guess)
    if len(keys) == 0:
        raise ExprError("The formula has no parameters a0..a9")
    if bounds is None:
        bounds = {}

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if weights is None:
        w = np.ones_like(y)
    else:
        w = np.asarray(weights, dtype=float)
    good = np.isfinite(x) & np.isfinite(y) & np.isfinite(w) & (w > 0)
    x = x[good]
    y = y[good]
    w = w[good]
    if len(x) <= len(keys):
        raise ExprError("Not enough points for this many parameters")
    sqrt_w = np.sqrt(w)

    params = {}
    for k in keys:
        params[k] = float(guess[k])
    params = clip_to_bounds(params, bounds)

    residual = (model(x, params) - y) * sqrt_w
    if not np.all(np.isfinite(residual)):
        raise ExprError("The model gives NaN/inf at the initial guess; adjust the initial values")
    chi2 = float(np.dot(residual, residual))

    damping = 1e-3
    status = "maximum iterations reached"
    iteration = 0
    jacobian = np.zeros((len(x), len(keys)))
    for iteration in range(1, max_iter + 1):
        # Jacobian by finite differences: how each residual changes with each parameter
        for j in range(len(keys)):
            k = keys[j]
            h = 1e-7 * max(abs(params[k]), 1e-3)
            shifted = dict(params)
            shifted[k] = shifted[k] + h
            jacobian[:, j] = ((model(x, shifted) - y) * sqrt_w - residual) / h
        normal = jacobian.T @ jacobian          # @ is matrix multiplication
        gradient = jacobian.T @ residual

        # Try steps with increasing damping until chi^2 goes down
        improved = False
        relative_change = 0.0
        for attempt in range(30):
            damped = normal + damping * np.diag(np.diag(normal) + 1e-12)
            try:
                step = np.linalg.solve(damped, -gradient)
            except np.linalg.LinAlgError:
                damping = damping * 10
                continue
            trial = {}
            for j in range(len(keys)):
                trial[keys[j]] = params[keys[j]] + step[j]
            trial = clip_to_bounds(trial, bounds)
            trial_residual = (model(x, trial) - y) * sqrt_w
            if np.all(np.isfinite(trial_residual)):
                trial_chi2 = float(np.dot(trial_residual, trial_residual))
            else:
                trial_chi2 = np.inf
            if trial_chi2 < chi2:
                relative_change = (chi2 - trial_chi2) / max(chi2, 1e-300)
                params = trial
                residual = trial_residual
                chi2 = trial_chi2
                damping = max(damping / 10, 1e-12)
                improved = True
                break
            damping = damping * 10

        if not improved:
            status = "converged (no further improvement)"
            break
        if relative_change < tol:
            status = "converged"
            break

    # Parameter errors from the covariance matrix
    dof = max(1, len(x) - len(keys))
    errors = {}
    try:
        covariance = np.linalg.inv(jacobian.T @ jacobian) * (chi2 / dof)
        for j in range(len(keys)):
            errors[keys[j]] = float(np.sqrt(max(covariance[j, j], 0.0)))
    except np.linalg.LinAlgError:
        for k in keys:
            errors[k] = float("nan")

    fitted = model(x, params)
    mean_y = np.average(y, weights=w)
    ss_tot = float(np.sum(w * (y - mean_y) ** 2))
    if ss_tot > 0:
        r2 = 1 - chi2 / ss_tot
    else:
        r2 = float("nan")

    lines = [formula, "  " + status + " after " + str(iteration) + " iterations"]
    for k in keys:
        lines.append("  a%d = %.10g  ± %.4g" % (k, params[k], errors[k]))
    lines.append("  chi² = %.6g   reduced chi² = %.6g   (N = %d, dof = %d)" % (chi2, chi2 / dof, len(x), dof))
    lines.append("  R² = %.8g   RMS residual = %.6g" % (r2, np.sqrt(np.mean((fitted - y) ** 2))))
    return params, errors, "\n".join(lines), FitResult(model, params)
