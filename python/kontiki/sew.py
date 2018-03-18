import numpy as np
import scipy.optimize


def bspline_interp_freq_func(w, dt=1.0):
    """Cubic B-spline interpolation frequency function of Mihajlovic1999"""
    sinc = lambda x: 1.0 if x == 0 else np.sin(np.pi*x)/(np.pi*x)
    sinc = np.vectorize(sinc)
    def H(w):
        a = 3 * sinc(w/(2*np.pi))**4
        b = 2 + np.cos(w)
        return a / b
    return dt * H(w * dt)


def spline_interpolation_response(freqs, dt):
    H = bspline_interp_freq_func(2*np.pi*freqs, dt)
    return H / H[0]


def signal_energy(spectrum):
    return np.sum(np.abs(spectrum)**2) / len(spectrum)


def find_max_quality_dt(quality_func, min_q, min_dt, max_dt, verbose=False):
    """Find the largest dt given a quality function

        quality_func : A function that takes a knot spacing and returns a quality measure
        min_q : (float) Minimum quality
        min_dt, max_dt: (float) bounds for dt
    """


    # Endpoint check
    dt = max_dt

    q = quality_func(dt)
    if q >= min_q:
        if verbose:
            print('Found at endpoint')
        return dt

    if verbose:
        print('Endpoint {:.1e} < {:.1e}'.format(q, min_q))

    # Backtrack
    step = max_dt * 0.5
    max_quality = 0
    max_quality_dt = None
    while True:
        dt -= step

        dt = max(dt, min_dt)

        q = quality_func(dt)

        if verbose:
            print('Trying {:.4f}, q={:.3e}'.format(dt, q))

        if q > min_q:

            root_func = lambda dt: quality_func(dt) - min_q
            if verbose:
                print('{:.1e} > {:.1e}: Switching to Brent'.format(q, min_q))
                print(root_func(dt), root_func(max_dt))
            brent_dt = scipy.optimize.brentq(root_func, dt, max_dt)
            if verbose:
                print('Found dt={:.3e}'.format(brent_dt))
            return brent_dt
        else:
            step *= 0.5
            if q > max_quality:
                max_quality = q
                max_quality_dt = dt
    
            if dt <= min_dt:
                if verbose:
                    print('dt too small: No dt satisfies condition. Returning best: {:.1e}'.format(max_quality_dt))
                return max_quality_dt                


def find_uniform_knot_spacing_spectrum(Xhat, times, quality, *, verbose=False, min_dt=None, max_dt=None):
    "Find the uniform knot spacing that keeps quality percent signal energy"
    
    sample_rate = 1 / np.mean(np.diff(times))
    freqs = np.fft.fftfreq(len(times), d=1/sample_rate)
    max_remove = signal_energy(Xhat) * (1 - quality)

    def quality_func(dt):
        H = spline_interpolation_response(freqs, dt)
        removed = signal_energy((1 - H) * Xhat)
        return max_remove / removed

    if min_dt is None:
        min_dt = 1/sample_rate

    if max_dt is None:
        max_dt = (len(times) / 4) / sample_rate

    return find_max_quality_dt(quality_func, 1.0, min_dt, max_dt, verbose=verbose)
    

def find_uniform_knot_spacing(signal, times, quality, *, verbose=False):
    "Find the uniform knot spacing that keeps quality percent signal energy"
    
    Xhat = make_reference_spectrum(signal)
    return find_uniform_knot_spacing_spectrum(Xhat, times, quality, verbose=verbose)


def make_reference_spectrum(signal):
    if signal.ndim == 1:
        signal = np.atleast_2d(signal)
    elif not signal.ndim == 2:
        raise ValueError("Signal must be at most 2D")
        
    d, _ = signal.shape
    S = np.fft.fft(signal, axis=1)
    S[:, 0] = 0 # Remove DC component
    Xhat = np.sqrt(1/d) * np.linalg.norm(S, axis=0)
    return Xhat


def quality_to_variance(signal, q):
    return (1-q) * np.mean(ref**2)


def quality_to_variance_spectrum(spectrum, q):
    N = len(spectrum)
    return (1-q) * np.mean(spectrum**2) / N


def dt_to_variance_spectrum(spectrum, freqs, spline_dt):
    H = spline_interpolation_response(freqs, spline_dt)
    EE = signal_energy((1-H) * spectrum)
    return EE / len(spectrum)
    
    
def knot_spacing_and_variance(signal, times, quality, *, min_dt=None, max_dt=None, verbose=False):
    Xhat = make_reference_spectrum(signal)
    dt = find_uniform_knot_spacing_spectrum(Xhat, times, quality, min_dt=min_dt, max_dt=max_dt, verbose=verbose)
    #variance = quality_to_variance_spectrum(Xhat, quality)
    sample_rate = 1 / np.mean(np.diff(times))
    freqs = np.fft.fftfreq(len(Xhat), d=1/sample_rate)
    variance = dt_to_variance_spectrum(Xhat, freqs, dt)
    return dt, variance


def estimate_variance_of_fit(signal, sample_rate, spline_dt, noise_std, *,
                             spectrum=None, full_output=False):
    Xhat = spectrum if spectrum is not None else np.fft.fft(signal)
    nsample = len(signal)
    freqs = np.fft.fftfreq(nsample, d=1/sample_rate)

    samples_per_knot = sample_rate * spline_dt
    H = spline_interpolation_response(freqs, spline_dt)

    E = (1 - H) * Xhat
    e = np.fft.ifft(E)
    HN = H * np.sqrt(nsample) * noise_std
    hn = np.fft.ifft(HN)
    var_exp = np.std(e)**2 + np.std(hn)**2

    if full_output:
        return var_exp, e
    else:
        return var_exp


def joint_knot_spacing_variance(x_acc, x_gyro, times, q_gyro, *, acc_factor=2.):
    sample_rate = 1 / np.mean(np.diff(times))
    freqs = np.fft.fftfreq(len(times), d=1/sample_rate)
    Xa = make_reference_spectrum(x_acc)
    Xg = make_reference_spectrum(x_gyro)
    dt_gyro, var_gyro = knot_spacing_and_variance(x_gyro, times, q_gyro)

    dt_acc = acc_factor * dt_gyro

    GRAVITY = 9.8065
    EG = var_gyro * len(Xg) * (2 * GRAVITY**2 / 3)
    H = spline_interpolation_response(freqs, dt_acc)
    EA = signal_energy(Xa)
    EHA = signal_energy(H * Xa)
    EHG = signal_energy(np.sqrt(EG) / len(H) * np.ones_like(H) * H)
    EE = EA - EG - EHA + EHG
    var_acc = EE / len(Xa)

    return dt_gyro, var_gyro, dt_acc, var_acc
    
