from __future__ import absolute_import, division, print_function

import math

import torch
from six.moves.queue import LifoQueue
from torch.autograd import Variable

from pyro import poutine
from pyro.distributions.util import sum_rightmost
from pyro.poutine.trace import Trace


def _iter_discrete_filter(name, msg):
    return ((msg["type"] == "sample") and
            (not msg["is_observed"]) and
            getattr(msg["fn"], "enumerable", False) and
            (msg["infer"].get("enumerate", "sequential") == "sequential"))


def _iter_discrete_escape(trace, msg):
    return _iter_discrete_filter(msg["name"], msg) and (msg["name"] not in trace)


def iter_discrete_traces(graph_type, max_iarange_nesting, fn, *args, **kwargs):
    """
    Iterate over all discrete choices of a stochastic function.

    When sampling continuous random variables, this behaves like `fn`.
    When sampling discrete random variables, this iterates over all choices.

    This yields `(scale, trace)` pairs, where `scale` is the probability of the
    discrete choices made in the `trace`.

    :param str graph_type: The type of the graph, e.g. "flat" or "dense".
    :param callable fn: A stochastic function.
    :returns: An iterator over (scale, trace) pairs.
    """
    queue = LifoQueue()
    queue.put(Trace())
    q_fn = poutine.queue(fn, queue=queue)
    while not queue.empty():
        q_fn = poutine.queue(fn, queue=queue, escape_fn=_iter_discrete_escape)
        full_trace = poutine.trace(q_fn, graph_type=graph_type).get_trace(*args, **kwargs)

        # Scale trace by probability of discrete choices.
        log_pdf = 0
        full_trace.compute_batch_log_pdf(site_filter=_iter_discrete_filter)
        for name, site in full_trace.nodes.items():
            if _iter_discrete_filter(name, site):
                log_pdf += sum_rightmost(site["batch_log_pdf"], max_iarange_nesting)
        if isinstance(log_pdf, Variable):
            scale = torch.exp(log_pdf.detach())
        else:
            scale = math.exp(log_pdf)

        yield scale, full_trace
