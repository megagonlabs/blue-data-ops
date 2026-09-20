"""Exact historical-to-current source bindings for the v2 provenance guard.

One entry per operator whose source has legitimately changed since the frozen baseline,
mapping the digest the baseline pins to the digest the file carries now. The guard
projects each current digest back to its historical value before comparing, so the freeze
goes on measuring everything it measured before while the amended files are allowed to
move.

An entry records that a change was deliberate; it is not a way around the guard. Both
halves of every pair are checked against the tree, so an entry whose historical digest is
not the frozen one, or whose current digest is not what the file actually holds, fails.
"""

from __future__ import annotations

from typing import Final

SOURCE_PROVENANCE_AMENDMENTS: Final[dict[str, tuple[str, str]]] = {
    "data_discover": (
        "36c6e5b4a11d2795ab2de2a4bc57940a3ec9ddc87efb189fba7d0e7b17cb8771",
        "d1649e9a53b50bcdcf8525c82e0c51bc688b95b94c6ce719aaccfed8a6f6d132",
    ),
    "semantic_join": (
        "d0ac8f4392ee9b8c6cf876a5e65f96258a477aed2343ad8d41a1d8a751e3e157",
        "755f1776a1cb3f0658aca7680076844343e7045be9cf49cc7eef3e1f1b773053",
    ),
}
