# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division


import logging


import numpy as np


from allel.util import asarray_ndim, check_dim0_aligned, ensure_dim1_aligned
from allel.model import GenotypeArray
from allel.stats.window import windowed_statistic
from allel.stats.diversity import mean_pairwise_difference, \
    mean_pairwise_difference_between


logger = logging.getLogger(__name__)
debug = logger.debug


def weir_cockerham_fst(g, subpops, max_allele=None):
    """Compute the variance components from the analyses of variance of
    allele frequencies according to Weir and Cockerham (1984).

    Parameters
    ----------

    g : array_like, int, shape (n_variants, n_samples, ploidy)
        Genotype array.
    subpops : sequence of sequences of ints
        Sample indices for each subpopulation.
    max_allele : int, optional
        The highest allele index to consider.

    Returns
    -------

    a : ndarray, float, shape (n_variants, n_alleles)
        Component of variance between populations.
    b : ndarray, float, shape (n_variants, n_alleles)
        Component of variance between individuals within populations.
    c : ndarray, float, shape (n_variants, n_alleles)
        Component of variance between gametes within individuals.

    Examples
    --------

    Calculate variance components from some genotype data::

        >>> import allel
        >>> g = [[[0, 0], [0, 0], [1, 1], [1, 1]],
        ...      [[0, 1], [0, 1], [0, 1], [0, 1]],
        ...      [[0, 0], [0, 0], [0, 0], [0, 0]],
        ...      [[0, 1], [1, 2], [1, 1], [2, 2]],
        ...      [[0, 0], [1, 1], [0, 1], [-1, -1]]]
        >>> subpops = [[0, 1], [2, 3]]
        >>> a, b, c = allel.stats.weir_cockerham_fst(g, subpops)
        >>> a
        array([[ 0.5  ,  0.5  ,  0.   ],
               [ 0.   ,  0.   ,  0.   ],
               [ 0.   ,  0.   ,  0.   ],
               [ 0.   , -0.125, -0.125],
               [-0.375, -0.375,  0.   ]])
        >>> b
        array([[ 0.        ,  0.        ,  0.        ],
               [-0.25      , -0.25      ,  0.        ],
               [ 0.        ,  0.        ,  0.        ],
               [ 0.        ,  0.125     ,  0.25      ],
               [ 0.41666667,  0.41666667,  0.        ]])
        >>> c
        array([[ 0.        ,  0.        ,  0.        ],
               [ 0.5       ,  0.5       ,  0.        ],
               [ 0.        ,  0.        ,  0.        ],
               [ 0.125     ,  0.25      ,  0.125     ],
               [ 0.16666667,  0.16666667,  0.        ]])

    Estimate the parameter theta (a.k.a., Fst) for each variant
    and each allele individually::

        >>> fst = a / (a + b + c)
        >>> fst
        array([[ 1. ,  1. ,  nan],
               [ 0. ,  0. ,  nan],
               [ nan,  nan,  nan],
               [ 0. , -0.5, -0.5],
               [-1.8, -1.8,  nan]])

    Estimate Fst for each variant individually (averaging over alleles)::

        >>> fst = (np.sum(a, axis=1) /
        ...        (np.sum(a, axis=1) + np.sum(b, axis=1) + np.sum(c, axis=1)))
        >>> fst
        array([ 1. ,  0. ,  nan, -0.4, -1.8])

    Estimate Fst averaging over all variants and alleles::

        >>> fst = np.sum(a) / (np.sum(a) + np.sum(b) + np.sum(c))
        >>> fst
        -4.3680905886891398e-17

    Note that estimated Fst values may be negative.

    """

    # check inputs
    if not hasattr(g, 'shape') or not hasattr(g, 'ndim'):
        g = GenotypeArray(g, copy=False)
    if g.ndim != 3:
        raise ValueError('g must have three dimensions')
    if g.shape[2] != 2:
        raise NotImplementedError('only diploid genotypes are supported')

    # determine highest allele index
    if max_allele is None:
        max_allele = g.max()

    if hasattr(g, 'chunklen'):
        # use a chunk-wise implementation
        blen = g.chunklen
        n_variants = g.shape[0]
        shape = (n_variants, max_allele + 1)
        a = np.zeros(shape, dtype='f8')
        b = np.zeros(shape, dtype='f8')
        c = np.zeros(shape, dtype='f8')
        for i in range(0, n_variants, blen):
            gb = g[i:i+blen]
            ab, bb, cb = _weir_cockerham_fst(gb, subpops, max_allele)
            a[i:i+blen] = ab
            b[i:i+blen] = bb
            c[i:i+blen] = cb

    else:
        a, b, c = _weir_cockerham_fst(g, subpops, max_allele)

    return a, b, c


# noinspection PyPep8Naming
def _weir_cockerham_fst(g, subpops, max_allele):

    # check inputs
    g = GenotypeArray(g, copy=False)
    n_variants, n_samples, ploidy = g.shape
    n_alleles = max_allele + 1

    # number of populations sampled
    r = len(subpops)
    n_populations = r
    debug('r: %r', r)

    # count alleles within each subpopulation
    ac = [g.count_alleles(subpop=s, max_allele=max_allele) for s in subpops]

    # stack allele counts from each sub-population into a single array
    ac = np.dstack(ac)
    assert ac.shape == (n_variants, n_alleles, n_populations)
    debug('ac: %s, %r', ac.shape, ac)

    # count number of alleles called within each population by summing
    # allele counts along the alleles dimension
    an = np.sum(ac, axis=1)
    assert an.shape == (n_variants, n_populations)
    debug('an: %s, %r', an.shape, an)

    # compute number of individuals sampled from each population
    n = an // 2
    assert n.shape == (n_variants, n_populations)
    debug('n: %s, %r', n.shape, n)

    # compute the total number of individuals sampled across all populations
    n_total = np.sum(n, axis=1)
    assert n_total.shape == (n_variants,)
    debug('n_total: %s, %r', n_total.shape, n_total)

    # compute the average sample size across populations
    n_bar = np.mean(n, axis=1)
    assert n_bar.shape == (n_variants,)
    debug('n_bar: %s, %r', n_bar.shape, n_bar)

    # compute the term n sub C incorporating the coefficient of variation in
    # sample sizes
    n_C = (n_total - (np.sum(n**2, axis=1) / n_total)) / (r - 1)
    assert n_C.shape == (n_variants,)
    debug('n_C: %s, %r', n_C.shape, n_C)

    # compute allele frequencies within each population
    p = ac / an[:, np.newaxis, :]
    assert p.shape == (n_variants, n_alleles, n_populations)
    debug('p: %s, %r', p.shape, p)

    # compute the average sample frequency of each allele
    ac_total = np.sum(ac, axis=2)
    an_total = np.sum(an, axis=1)
    p_bar = ac_total / an_total[:, np.newaxis]
    assert p_bar.shape == (n_variants, n_alleles)
    debug('p_bar: %s, %r', p_bar.shape, p_bar)

    # add in some extra dimensions to enable broadcasting
    n_bar = n_bar[:, np.newaxis]
    n_C = n_C[:, np.newaxis]
    n = n[:, np.newaxis, :]
    p_bar = p_bar[:, :, np.newaxis]

    # compute the sample variance of allele frequencies over populations
    s_squared = (
        np.sum(n * ((p - p_bar) ** 2),
               axis=2) /
        (n_bar * (r - 1))
    )
    assert s_squared.shape == (n_variants, n_alleles)
    debug('s_squared: %s, %r', s_squared.shape, s_squared)

    # remove extra dimensions for correct broadcasting
    p_bar = p_bar[:, :, 0]

    # compute the average heterozygosity over all populations
    h_bar = [g.count_het(allele=allele, axis=1) / n_total
             for allele in range(n_alleles)]
    h_bar = np.column_stack(h_bar)
    assert h_bar.shape == (n_variants, n_alleles)
    debug('h_bar: %s, %r', h_bar.shape, h_bar)

    # now comes the tricky bit...

    # component of variance between populations
    a = ((n_bar / n_C) *
         (s_squared -
          ((1 / (n_bar - 1)) *
           ((p_bar * (1 - p_bar)) -
            ((r - 1) * s_squared / r) -
            (h_bar / 4)))))
    assert a.shape == (n_variants, n_alleles)

    # component of variance between individuals within populations
    b = ((n_bar / (n_bar - 1)) *
         ((p_bar * (1 - p_bar)) -
          ((r - 1) * s_squared / r) -
          (((2 * n_bar) - 1) * h_bar / (4 * n_bar))))
    assert b.shape == (n_variants, n_alleles)

    # component of variance between gametes within individuals
    c = h_bar / 2
    assert c.shape == (n_variants, n_alleles)

    return a, b, c


def hudson_fst(ac1, ac2, fill=np.nan):
    """Calculate the numerator and denominator for Fst estimation using the
    method of Hudson (1992) elaborated by Bhatia et al. (2013).

    Parameters
    ----------

    ac1 : array_like, int, shape (n_variants, n_alleles)
        Allele counts array from the first population.
    ac2 : array_like, int, shape (n_variants, n_alleles)
        Allele counts array from the second population.
    fill : float
        Use this value where there are no pairs to compare (e.g.,
        all allele calls are missing).

    Returns
    -------

    num : ndarray, float, shape (n_variants,)
        Divergence between the two populations minus average
        of diversity within each population.
    den : ndarray, float, shape (n_variants,)
        Divergence between the two populations.

    Examples
    --------

    Calculate numerator and denominator for Fst estimation::

        >>> import allel
        >>> g = allel.model.GenotypeArray([[[0, 0], [0, 0], [1, 1], [1, 1]],
        ...                                [[0, 1], [0, 1], [0, 1], [0, 1]],
        ...                                [[0, 0], [0, 0], [0, 0], [0, 0]],
        ...                                [[0, 1], [1, 2], [1, 1], [2, 2]],
        ...                                [[0, 0], [1, 1], [0, 1], [-1, -1]]])
        >>> subpops = [[0, 1], [2, 3]]
        >>> ac1 = g.count_alleles(subpop=subpops[0])
        >>> ac2 = g.count_alleles(subpop=subpops[1])
        >>> num, den = allel.stats.hudson_fst(ac1, ac2)
        >>> num
        array([ 1.        , -0.16666667,  0.        , -0.125     , -0.33333333])
        >>> den
        array([ 1.   ,  0.5  ,  0.   ,  0.625,  0.5  ])

    Estimate Fst for each variant individually::

        >>> fst = num / den
        >>> fst
        array([ 1.        , -0.33333333,         nan, -0.2       , -0.66666667])

    Estimate Fst averaging over variants::

        >>> fst = np.sum(num) / np.sum(den)
        >>> fst
        0.1428571428571429

    """  # flake8: noqa

    # check inputs
    ac1 = asarray_ndim(ac1, 2)
    ac2 = asarray_ndim(ac2, 2)
    check_dim0_aligned(ac1, ac2)
    ac1, ac2 = ensure_dim1_aligned(ac1, ac2)

    # calculate these once only
    an1 = np.sum(ac1, axis=1)
    an2 = np.sum(ac2, axis=1)

    # calculate average diversity (a.k.a. heterozygosity) within each
    # population
    within = (mean_pairwise_difference(ac1, an1, fill=fill) +
              mean_pairwise_difference(ac2, an2, fill=fill)) / 2

    # calculate divergence (a.k.a. heterozygosity) between each population
    between = mean_pairwise_difference_between(ac1, ac2, an1, an2, fill=fill)

    # define numerator and denominator for Fst calculations
    num = between - within
    den = between

    return num, den


def windowed_weir_cockerham_fst(pos, g, subpops, size=None, start=None,
                                stop=None, step=None, windows=None,
                                fill=np.nan, max_allele=None):
    """Estimate average Fst in windows over a single chromosome/contig,
    following the method of Weir and Cockerham (1984).

    Parameters
    ----------

    pos : array_like, int, shape (n_items,)
        Variant positions, using 1-based coordinates, in ascending order.
    g : array_like, int, shape (n_variants, n_samples, ploidy)
        Genotype array.
    subpops : sequence of sequences of ints
        Sample indices for each subpopulation.
    size : int
        The window size (number of bases).
    start : int, optional
        The position at which to start (1-based).
    stop : int, optional
        The position at which to stop (1-based).
    step : int, optional
        The distance between start positions of windows. If not given,
        defaults to the window size, i.e., non-overlapping windows.
    windows : array_like, int, shape (n_windows, 2), optional
        Manually specify the windows to use as a sequence of (window_start,
        window_stop) positions, using 1-based coordinates. Overrides the
        size/start/stop/step parameters.
    fill : object, optional
        The value to use where there are no variants within a window.
    max_allele : int, optional
        The highest allele index to consider.

    Returns
    -------

    fst : ndarray, float, shape (n_windows,)
        Average Fst in each window.
    windows : ndarray, int, shape (n_windows, 2)
        The windows used, as an array of (window_start, window_stop) positions,
        using 1-based coordinates.
    counts : ndarray, int, shape (n_windows,)
        Number of variants in each window.

    """

    # check inputs
    if not hasattr(g, 'shape') or not hasattr(g, 'ndim'):
        g = GenotypeArray(g, copy=False)
    if g.ndim != 3:
        raise ValueError('g must have three dimensions')
    if g.shape[2] != 2:
        raise NotImplementedError('only diploid genotypes are supported')

    # determine highest allele index
    if max_allele is None:
        max_allele = g.max()

    # define the statistic to compute within each window
    def average_fst(wg):
        a, b, c = _weir_cockerham_fst(wg, subpops=subpops,
                                      max_allele=max_allele)
        return np.sum(a) / (np.sum(a) + np.sum(b) + np.sum(c))

    # calculate average Fst in windows
    fst, windows, counts = windowed_statistic(pos, values=g,
                                              statistic=average_fst,
                                              size=size, start=start,
                                              stop=stop, step=step,
                                              windows=windows, fill=fill)

    return fst, windows, counts


def windowed_hudson_fst(pos, ac1, ac2, size=None, start=None, stop=None,
                        step=None, windows=None, fill=np.nan):
    """Estimate average Fst in windows over a single chromosome/contig,
    following the method of Hudson (1992) elaborated by Bhatia et al. (2013).

    Parameters
    ----------

    pos : array_like, int, shape (n_items,)
        Variant positions, using 1-based coordinates, in ascending order.
    ac1 : array_like, int, shape (n_variants, n_alleles)
        Allele counts array from the first population.
    ac2 : array_like, int, shape (n_variants, n_alleles)
        Allele counts array from the second population.
    size : int, optional
        The window size (number of bases).
    start : int, optional
        The position at which to start (1-based).
    stop : int, optional
        The position at which to stop (1-based).
    step : int, optional
        The distance between start positions of windows. If not given,
        defaults to the window size, i.e., non-overlapping windows.
    windows : array_like, int, shape (n_windows, 2), optional
        Manually specify the windows to use as a sequence of (window_start,
        window_stop) positions, using 1-based coordinates. Overrides the
        size/start/stop/step parameters.
    fill : object, optional
        The value to use where there are no variants within a window.

    Returns
    -------

    fst : ndarray, float, shape (n_windows,)
        Average Fst in each window.
    windows : ndarray, int, shape (n_windows, 2)
        The windows used, as an array of (window_start, window_stop) positions,
        using 1-based coordinates.
    counts : ndarray, int, shape (n_windows,)
        Number of variants in each window.

    """

    # check inputs
    ac1 = asarray_ndim(ac1, 2)
    ac2 = asarray_ndim(ac2, 2)
    check_dim0_aligned(ac1, ac2)
    ac1, ac2 = ensure_dim1_aligned(ac1, ac2)

    # define the statistic to compute within each window
    def average_fst(wac1, wac2):
        num, den = hudson_fst(wac1, wac2, fill=fill)
        return np.sum(num) / np.sum(den)

    # calculate average Fst in windows
    fst, windows, counts = windowed_statistic(pos, values=(ac1, ac2),
                                              statistic=average_fst,
                                              size=size, start=start,
                                              stop=stop, step=step,
                                              windows=windows, fill=fill)

    return fst, windows, counts


# TODO moving_weir_cockerham_fst
# TODO moving_hudson_fst
