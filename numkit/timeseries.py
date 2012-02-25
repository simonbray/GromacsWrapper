# numkit --- time series manipulation and analysis
# Copyright (c) 2010 Oliver Beckstein <orbeckst@gmail.com>
# Released under the "Modified BSD Licence" (see COPYING).
"""
:mod:`numkit.timeseries` --- Time series manipulation and analysis
==================================================================

A time series contains of a sequence of time points (typically spaced
equally) and a value for each time point.

.. autofunction:: autocorrelation_fft
.. autofunction:: tcorrel
.. autofunction:: smooth
.. autofunction:: smoothing_window_length
.. autoexception:: LowAccuracyWarning

"""
# doc notes:
# Autocorrelation time (time when ACF becomes 0 for the first time)::
#   R = gromacs.formats.XVG("./md.xvg")
#   acf = mdpow.numkit.autocorrelation_fft(R.array[1])
#   where(acf <= 0)[0][0]
# Alternatively, fit an exponential to the ACF and extract the time constant.


import numpy
import scipy.signal
import scipy.integrate

import warnings
import logging
logger = logging.getLogger("numkit.timeseries")

from numkit import LowAccuracyWarning

def autocorrelation_fft(series, remove_mean=True, paddingcorrection=True,
                        normalize=False, **kwargs):
    """Calculate the auto correlation function.

       autocorrelation_fft(series,remove_mean=False,**kwargs) --> acf

    The time series is correlated with itself across its whole length. Only the
    [0,len(series)[ interval is returned.

    By default, the mean of the series is subtracted and the correlation of the
    fluctuations around the mean are investigated.

    For the default setting remove_mean=True, acf[0] equals the variance of
    the series, acf[0] = Var(series) = <(series - <series>)**2>.

    Optional:

    * The series can be normalized to its 0-th element so that acf[0] == 1.

    * For calculating the acf, 0-padding is used. The ACF should be corrected
      for the 0-padding (the values for larger lags are increased) unless
      mode='valid' is set (see below).

    Note that the series for mode='same'|'full' is inaccurate for long times
    and should probably be truncated at 1/2*len(series)

    :Arguments:
      *series*
        (time) series, a 1D numpy array of length N
      *remove_mean*
        ``False``: use series as is;
        ``True``: subtract mean(series) from series [``True``]
      *paddingcorrection*
        ``False``: corrected for 0-padding; ``True``: return as is it is.
        (the latter is appropriate for periodic signals).
        The correction for element 0=<i<N amounts to a factor N/(N-i). Only
        applied for modes != "valid"       [``True``]
      *normalize*
        ``True`` divides by acf[0] so that the first element is 1;
        ``False`` leaves un-normalized [``False``]
      *mode*
        "full" | "same" | "valid": see :func:`scipy.signal.fftconvolve`
        ["full"]
      *kwargs*
        other keyword arguments for :func:`scipy.signal.fftconvolve`
    """
    kwargs.setdefault('mode','full')

    if len(series.shape) > 2:
        # var/mean below would need proper axis arguments to deal with high dim
        raise TypeError("series must be a 1D array at the moment")

    if remove_mean:
        series = numpy.squeeze(series.astype(float)).copy()   # must copy because de-meaning modifies it
        mean = series.mean()
        series -= mean
    else:
        series = numpy.squeeze(series.astype(float))          # can deal with a view

    ac = scipy.signal.fftconvolve(series,series[::-1,...],**kwargs)

    origin = ac.shape[0]/2        # should work for both odd and even len(series)
    ac = ac[origin:]              # only use second half of the symmetric acf
    assert len(ac) <= len(series), "Oops: len(ac)=%d  len(series)=%d" % (len(ac),len(series))
    if paddingcorrection and  not kwargs['mode'] == 'valid':     # 'valid' was not 0-padded
        # correct for 0 padding
        # XXX: reference? Where did I get this from? (But it makes sense.)
        ac *= len(series)/(len(series) - 1.0*numpy.arange(len(ac)))

    norm = ac[0] or 1.0  # to guard against ACFs of zero arrays
    if not normalize:
        # We use the convention that the ACF is divided by the total time,
        # which makes acf[0] == <series**2> = Var(series) + <series>**2. We do
        # not need to know the time (x) in order to scale the output from the
        # ACF-series accordingly:
        try:
            if remove_mean:
                norm /= numpy.var(series)
            else:
                norm /= numpy.mean(series*series)
        except ZeroDivisionError:
            norm = 1.0
    return ac/norm

def tcorrel(x,y,nstep=100,debug=False):
    """Calculate the correlation time and an estimate of the error of the mean <y>.

    The autocorrelation function f(t) is calculated via FFT on every *nstep* of
    the **fluctuations** of the data around the mean (y-<y>). The normalized
    ACF f(t)/f(0) is assumed to decay exponentially, f(t)/f(0) = exp(-t/tc) and
    the decay constant tc is estimated as the integral of the ACF from the
    start up to its first root.

    See [FrenkelSmit2002]_ `p526`_ for details.

    .. Note:: *nstep* should be set sufficiently large so that there are less
              than ~50,000 entries in the input.

    .. [FrenkelSmit2002] D. Frenkel and B. Smit, Understanding
                         Molecular Simulation. Academic Press, San
                         Diego 2002

    .. _p526: http://books.google.co.uk/books?id=XmyO2oRUg0cC&pg=PA526


    :Arguments:
       *x*
          1D array of abscissa values (typically time)
       *y*
          1D array of the ibservable y(x)
       *nstep*
          only analyze every *nstep* datapoint to speed up calculation
          [100]

    :Returns: dictionary with entries *tc* (decay constant in units of *x*),
              *t0* (value of the first root along x (y(t0) = 0)), *sigma* (error estimate
              for the mean of y, <y>, corrected for correlations in the data).
    """
    if x.shape != y.shape:
        raise TypeError("x and y must be y(x), i.e. same shape")
    _x = x[::nstep]  # do not run acf on all data: takes too long
    _y = y[::nstep]  # and does not improve accuracy
    if len(_y) < 500:  # 500 is a bit arbitrary
        wmsg = "tcorrel(): Only %d datapoints for the chosen nstep=%d; " \
            "ACF will possibly not be accurate." % (len(_y), nstep)
        warnings.warn(wmsg, category=LowAccuracyWarning)
        logger.warn(wmsg)

    acf = autocorrelation_fft(_y, normalize=False)
    try:
        i0 = numpy.where(acf <= 0)[0][0]  # first root of acf
    except IndexError:
        i0 = -1   # use last value as best estimate
    t0 = _x[i0]
    # integral of the _normalized_ acf
    norm = acf[0] or 1.0  # guard against a zero ACF
    tc = scipy.integrate.simps(acf[:i0]/norm, x=_x[:i0])
    # error estimate for the mean [Frenkel & Smit, p526]
    sigma = numpy.sqrt(2*tc*acf[0]/(x[-1] - x[0]))

    result = {'tc':tc, 't0':t0, 'sigma':sigma}
    if debug:
        result['t'] = _x[:i0]
        result['acf'] = acf[:i0]
    return result


def smooth(x, window_len=11, window='flat'):
    """smooth the data using a window with requested size.

    This method is based on the convolution of a scaled window with the signal.
    The signal is prepared by introducing reflected copies of the signal
    (with the window size) in both ends so that transient parts are minimized
    in the begining and end part of the output signal.

    :Arguments:
        *x*
            the input signal, 1D array

        *window_len*
            the dimension of the smoothing window, always converted to
            an integer (using :func:`int`) and must be odd

        *window*
            the type of window from 'flat', 'hanning', 'hamming',
            'bartlett', 'blackman'; flat window will produce a moving
            average smoothing. If *window* is a :class:`numpy.ndarray` then
            this array is directly used as the window (but it still must
            contain an odd number of points) ["flat"]

    :Returns: the smoothed signal as a 1D array

    :Example:

    Apply a simple moving average to a noisy harmonic signal::

       >>> import numpy as np
       >>> t = np.linspace(-2, 2, 201)
       >>> x = np.sin(t) + np.random.randn(len(t))*0.1
       >>> y = smooth(x)

    .. See Also::

       :func:`numpy.hanning`, :func:`numpy.hamming`,
       :func:`numpy.bartlett`, :func:`numpy.blackman`,
       :func:`numpy.convolve`, :func:`scipy.signal.lfilter`

    Source: based on http://www.scipy.org/Cookbook/SignalSmooth
    """
    windows = ['flat', 'hanning', 'hamming', 'bartlett', 'blackman']
    window_len = int(window_len)

    if isinstance(window, numpy.ndarray):
        window_len = len(window)
        w = numpy.asarray(window, dtype=float)
    else:
        if not window in windows:
            raise ValueError("Window %r not supported; must be one of %r" %
                             (window, windows))
        if window == 'flat':
            # moving average
            w = numpy.ones(window_len, dtype=float)
        else:
            w = vars(numpy)[window](window_len)

    if x.ndim != 1:
        raise ValueError("smooth only accepts 1 dimension arrays.")
    if x.size < window_len:
        raise ValueError("Input vector needs to be bigger than window size.")
    if window_len % 2 == 0:
        raise ValueError("window_len should be an odd integer")
    if window_len < 3:
        return x

    s = numpy.r_[x[window_len-1:0:-1], x, x[-1:-window_len:-1]]
    y = numpy.convolve(w/w.sum(), s, mode='valid')
    return y[(window_len-1)/2:-(window_len-1)/2]  # take off repeats on ends

def smoothing_window_length(resolution, t):
    """Compute the length of a smooting window of *resolution* time units.

    :Arguments:

       *resolution*
            length in units of the time in which *t* us supplied
       *t*
            array of time points; if not equidistantly spaced, the
            mean spacing is used to compute the window length

    :Returns: odd integer, the size of a window of approximately *resolution*

    .. SeeAlso:: :func:`smooth`
    """
    dt = numpy.mean(numpy.diff(t))
    N = int(resolution/dt)
    if N % 2 == 0:
        N += 1
    return N
