"""Shared test fixtures for Research OS."""
import pytest


@pytest.fixture
def sample_latex_content():
    """A minimal LaTeX document for testing."""
    return r"""
\documentclass{article}
\title{A Test Paper on Multi-Agent Systems}
\author{John Doe \and Jane Smith}
\begin{document}
\maketitle

\begin{abstract}
This paper presents a novel approach to multi-agent coordination using
reinforcement learning with shared memory pools.
\end{abstract}

\section{Introduction}
Multi-agent systems have become increasingly important in AI research.
We propose a method that enables agents to share long-term memory.

Previous work by \cite{smith2020} showed that memory sharing improves coordination.
The equation $E = mc^2$ is well known.

\subsection{Related Work}
Several approaches exist for multi-agent communication \cite{jones2021}.

\section{Method}
Our approach uses a shared memory pool with attention-based retrieval.

\begin{equation}
\mathbf{h}_t = \text{Attention}(\mathbf{q}_t, \mathbf{K}, \mathbf{V})
\end{equation}

\begin{figure}
\includegraphics{architecture.png}
\caption{System architecture overview}
\label{fig:arch}
\end{figure}

\section{Experiments}
We evaluate on three benchmarks. Results show a 15\% improvement.

\begin{table}
\caption{Comparison of methods}
\label{tab:results}
\begin{tabular}{lcc}
\toprule
Method & Accuracy & F1 \\
\midrule
Baseline & 0.72 & 0.68 \\
Ours & 0.87 & 0.83 \\
\bottomrule
\end{tabular}
\end{table}

\section{Conclusion}
We presented a novel multi-agent coordination method with shared memory.

\bibliography{refs}
\end{document}
"""


@pytest.fixture
def sample_bibtex():
    """Sample BibTeX content."""
    return r"""
@article{smith2020,
    title = {Memory Sharing in Multi-Agent Systems},
    author = {Smith, Alice and Brown, Bob},
    journal = {Journal of AI Research},
    year = {2020},
    volume = {45},
    pages = {123--145},
    doi = {10.1234/jair.2020.001},
}

@inproceedings{jones2021,
    title = {Communication Protocols for Agent Coordination},
    author = {Jones, Charlie and Davis, Diana},
    booktitle = {NeurIPS 2021},
    year = {2021},
    eprint = {2101.12345},
}
"""


@pytest.fixture
def sample_run_data():
    """Sample research run data for testing."""
    from uuid import uuid4
    from datetime import datetime
    return {
        "id": uuid4(),
        "title": "Test Research Run",
        "topic": "Multi-agent coordination with shared memory",
        "status": "queued",
        "goal_type": "survey_plus_innovations",
        "autonomy_mode": "default_autonomous",
        "budget_json": {"max_new_papers": 50, "max_fulltext_reads": 10, "max_estimated_cost_usd": 5.0},
        "policy_json": {"auto_pause_on_budget_hit": True},
        "progress_pct": 0,
        "current_step": None,
        "started_at": None,
        "completed_at": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
