"""Lifecycle marking and one-per-call warning emission for surfaces removed in 3.0.0.

Only ``BlueDataOpsDeprecationWarning`` is public; it is re-exported from ``blue_data_ops``
and survives the removal it announces. Everything else here is package-internal.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import warnings
from collections.abc import Callable, Generator
from contextvars import ContextVar, Token
from typing import Any, ParamSpec, TypeVar, cast


class BlueDataOpsDeprecationWarning(DeprecationWarning):
    """Category for surfaces deprecated in 2.8.0 and removed in 3.0.0."""


DEPRECATED_OPERATOR_NAMES: frozenset[str] = frozenset(
    {"plan_discover", "query_breakdown", "nl2query_router", "multipart_query"}
)

# Class-body flag on DeclarativeOperator. Read through the MRO, so its subclasses inherit it.
REMOVED_TYPE_MARKER = "__blue_deprecated_type__"
# Instance slot, written only by _VersionBindingMixin.__init__.
BOUND_REMOVED_TARGET = "_blue_removed_target"

HOOKED: tuple[str, ...] = ("apply", "validate", "explain", "refiner", "refine")

_ACTIVE: ContextVar[bool] = ContextVar("blue_data_ops_deprecation_active", default=False)
_PREFIX = "blue-data-ops: "
# A caller who will not import the category filters on this leading literal, so it must
# stay first and unchanged.
_SEAM = {"refine": "RefinableOperator.refine()", "refiner": "Operator.refiner()"}
INJECTED_REFINER_SUBJECT = "Operator(refiner=…) seam"

_MARKER = "__blue_deprecated__"
_OWNERS = "__blue_owners__"

_P = ParamSpec("_P")
_R = TypeVar("_R")

_binding_bases: tuple[type, ...] = ()


def register_version_binding_base(cls: type) -> type:
    """Record the package's own version-binding base.

    Membership in this tuple is the only test for "is this a package version binding", and
    the tuple is written once, from package code. A caller class body cannot join it.
    """
    global _binding_bases
    if cls not in _binding_bases:
        _binding_bases += (cls,)
    return cls


def _binding_removed_target(obj: object) -> bool:
    """Read the closed flag off a package binding's own instance slot."""
    if not _binding_bases or not isinstance(obj, _binding_bases):
        return False
    # vars(), not getattr(): _VersionBindingMixin.__getattr__ delegates a miss to its
    # target, so a getattr could land on a caller target's class attribute.
    return vars(obj).get(BOUND_REMOVED_TARGET, False) is True


def effective_removed_target(target: object) -> bool:
    """The flag a new binding over ``target`` closes over.

    Reading the immediate target only is what lets the disposition survive any number of
    binding layers: layer n inherits what layer n-1 already settled.
    """
    marked = bool(getattr(type(target), REMOVED_TYPE_MARKER, False))
    return marked or _binding_removed_target(target)


def _message(subjects: tuple[str, ...]) -> str:
    verb = "is" if len(subjects) == 1 else "are"
    return (
        f"{_PREFIX}{' and '.join(subjects)} {verb} deprecated in 2.8.0 and will be "
        f"removed in 3.0.0; see COMPATIBILITY.md 'Deprecated in 2.8.0'."
    )


def _subjects(
    receiver: object,
    owners: tuple[type | None, ...],
    method: str | None,
) -> tuple[str, ...]:
    """Classify one call against the closed subject vocabulary.

    ``receiver`` is the instance when the call has one; ``owners`` are the classes the
    package captured at install time, plus the class a classmethod call received. Nothing
    caller-supplied is interpolated.
    """
    name: object = None
    removed = False
    if receiver is not None:
        name = getattr(receiver, "name", None)
        removed = bool(getattr(type(receiver), REMOVED_TYPE_MARKER, False)) or (
            _binding_removed_target(receiver)
        )
    for owner in owners:
        if owner is None:
            continue
        if receiver is None and name is None:
            name = owner.__dict__.get("name", getattr(owner, "name", None))
        removed = removed or bool(getattr(owner, REMOVED_TYPE_MARKER, False))

    subjects: list[str] = []
    if isinstance(name, str) and name in DEPRECATED_OPERATOR_NAMES:
        subjects.append(f"operator {name!r}")
    if removed:
        subjects.append("DeclarativeOperator")
    if method is not None and method in _SEAM:
        subjects.append(_SEAM[method])
    return tuple(subjects)


def _enter(subjects: tuple[str, ...], stacklevel: int = 3) -> Token[bool] | None:
    """Claim the top-level call and warn, or return None when already inside one."""
    if _ACTIVE.get():
        return None
    token = _ACTIVE.set(True)
    try:
        warnings.warn(_message(subjects), BlueDataOpsDeprecationWarning, stacklevel=stacklevel)
    except BaseException:
        # Promoted to an error: release before it reaches the caller.
        _ACTIVE.reset(token)
        raise
    return token


def _exit(token: Token[bool] | None) -> None:
    if token is not None:
        _ACTIVE.reset(token)


def entry(
    method: str | None = None,
    *,
    subject: str | None = None,
    owner: type | tuple[type | None, ...] | None = None,
    receiver: str = "instance",
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Wrap one public entry so a deprecated subject warns once per top-level call.

    Three call forms: a bound method, a module-level ``subject=``, and a receiverless
    descriptor (``receiver="static"`` or ``"class"``). ``owner`` takes a tuple to carry the
    effective owner chain of an inherited-static overlay.
    """
    owners: tuple[type | None, ...] = owner if isinstance(owner, tuple) else (owner,)

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        if getattr(func, _MARKER, False) or getattr(func, "__isabstractmethod__", False):
            return func
        raw = cast("Callable[..., Any]", func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            subjects: tuple[str, ...]
            if subject is not None:
                subjects = (subject,)
            elif receiver == "instance":
                subjects = _subjects(args[0] if args else None, owners, method)
            elif receiver == "class":
                got = args[0] if args and isinstance(args[0], type) else None
                subjects = _subjects(None, (*owners, got), method)
            else:
                subjects = _subjects(None, owners, method)
            if not subjects:
                return raw(*args, **kwargs)
            token = _enter(subjects)
            try:
                return raw(*args, **kwargs)
            finally:
                _exit(token)

        setattr(wrapper, _MARKER, True)
        setattr(wrapper, _OWNERS, tuple(one for one in owners if one is not None))
        return cast("Callable[_P, _R]", wrapper)

    return decorate


def is_wrapped(func: object) -> bool:
    """Whether this callable is already one of our own entry wrappers."""
    return bool(getattr(func, _MARKER, False))


def _rewrap(raw: object, method: str, owner: type) -> object:
    """Wrap one class attribute, preserving its descriptor kind and abstract state."""
    if inspect.isfunction(raw):
        return entry(method, owner=owner, receiver="instance")(cast("Callable[..., Any]", raw))
    if isinstance(raw, staticmethod):
        static = cast("staticmethod[..., Any]", raw)
        plain: Callable[..., Any] = static.__func__
        hooked = entry(method, owner=owner, receiver="static")(plain)
        return static if hooked is plain else staticmethod(hooked)
    if isinstance(raw, classmethod):
        bound = cast("classmethod[Any, ..., Any]", raw)
        underlying: Callable[..., Any] = bound.__func__
        hooked = entry(method, owner=owner, receiver="class")(underlying)
        return bound if hooked is underlying else classmethod(hooked)
    return raw


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Recover the undecorated function from one of our own wrappers."""
    while getattr(func, _MARKER, False) and hasattr(func, "__wrapped__"):
        func = cast("Callable[..., Any]", getattr(func, "__wrapped__"))
    return func


def _inherited(cls: type, name: str) -> tuple[object, type | None]:
    for base in cls.__mro__[1:]:
        if name in base.__dict__:
            return base.__dict__[name], base
    return None, None


def _install_inherited_static_overlays(cls: type) -> None:
    """Give a removed-type subclass its own copy of any inherited concrete staticmethod.

    A staticmethod receives neither an instance nor a class, so it can only carry the owner
    the package captured where it was defined. Plain functions and classmethods already
    receive the dynamic receiver and are never rebound.
    """
    if not getattr(cls, REMOVED_TYPE_MARKER, False):
        return
    for name in HOOKED:
        if name in cls.__dict__:
            continue
        raw, base = _inherited(cls, name)
        if not isinstance(raw, staticmethod):
            continue
        static = cast("staticmethod[..., Any]", raw)
        inner: Callable[..., Any] = static.__func__
        if getattr(static, "__isabstractmethod__", False) or getattr(
            inner, "__isabstractmethod__", False
        ):
            continue
        prior = cast("tuple[type, ...]", getattr(inner, _OWNERS, ()))
        if any(getattr(one, REMOVED_TYPE_MARKER, False) for one in prior):
            continue
        owners: tuple[type | None, ...] = (cls, *(tuple(prior) or (base,)))
        overlay = entry(name, owner=owners, receiver="static")(_unwrap(inner))
        setattr(cls, name, staticmethod(overlay))


def install(cls: type) -> None:
    """Hook the public entries a subclass defines, then overlay inherited static ones."""
    names = HOOKED + (("__init__",) if getattr(cls, REMOVED_TYPE_MARKER, False) else ())
    for name in names:
        raw = cls.__dict__.get(name)
        if raw is None:
            continue
        wrapped = _rewrap(raw, name, cls)
        if wrapped is not raw:
            setattr(cls, name, wrapped)
    _install_inherited_static_overlays(cls)


def warn_injected_refiner() -> None:
    """Emit the injected-seam warning for a non-None ``Operator(refiner=...)``."""
    _exit(_enter((INJECTED_REFINER_SUBJECT,), stacklevel=4))


def propagate(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """Carry the package flag, and only it, into one timeout worker.

    ``contextvars.copy_context()`` would also carry caller-owned variables into package
    worker threads, which is a behavior change this release does not make.
    """
    active = _ACTIVE.get()
    raw = cast("Callable[..., Any]", fn)

    @functools.wraps(fn)
    def worker(*args: Any, **kwargs: Any) -> Any:
        token = _ACTIVE.set(active)
        try:
            return raw(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)

    return cast("Callable[_P, _R]", worker)


@contextlib.contextmanager
def expected() -> Generator[None, None, None]:
    """Suppress the package's own deprecation warnings for this task.

    Per-task rather than process-global, so it is safe under concurrency. It gates only
    this emitter, so a caller-supplied operator's own warnings still escape.
    """
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
