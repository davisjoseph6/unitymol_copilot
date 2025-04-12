"""
UnityMol Copilot Package

A natural language interface for UnityMol using FastAgent and Ollama.
"""

from .unitymol_zmq import UnityMolZMQ
from .unitymol_copilot import UnityMolCopilot

__version__ = "0.1.0"
__all__ = ["UnityMolZMQ", "UnityMolCopilot"]
__author__ = "Marc Baaden"
__email__ = "baaden@smplinux.de"
